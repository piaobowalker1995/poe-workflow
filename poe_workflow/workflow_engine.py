"""工作流执行器内核（Phase A/B/C）。

路线 B：独立并行引擎，不修改 state_machine.py。
复用 InputSimulator / CoordinateEngine 的现有原子能力。

Phase A/B/C 范围：
- 原子动作：click_anchor / move_to_anchor / press_key(含鼠标键) / read_clipboard / copy / wait_ms(兼容保留)
- 控制结构：loop（count 或 until 条件）/ branch（条件分支），支持嵌套
- 条件：clipboard / ctx / counter 源 + contains/equals/gt/lt/ge/le
- 每步错误策略：retry（默认）/ abort / skip / jump
- 可中断：_abort 事件贯穿所有层级（含循环体、等待）
- run_sync()：同步模式，供 pytest 免 Qt 验证
- start()/abort()：基于 threading 的可中断异步运行（Phase D 接入 UI 时再包成 QThread）
"""
import json
import re
import threading
import time
import logging
from typing import Optional, Dict, Any, Callable, List

from .workflow_model import (
    WorkflowDef, validate_workflow, workflow_from_dict, resolve_rule,
    GRID_MAX_CELLS,
)
from .protocols import (
    CoordService, InputService, ConfigService, AffixService, SchemeLoader,
)

logger = logging.getLogger(__name__)


class WorkflowEngine:
    def __init__(self, coord: "CoordService", inp: "InputService",
                 parser: "Optional[AffixService]" = None,
                 cm: "Optional[ConfigService]" = None,
                 logger_: "Optional[logging.Logger]" = None,
                 scheme_loader: "Optional[SchemeLoader]" = None,
                 loop_timeout_ms: int = 600000, max_depth: int = 16):
        self._coord = coord          # 锚点解析：需 get_absolute_position(name) -> (x, y)
        self._inp = inp              # 鼠标/键盘/剪贴板：click / press_key / read_clipboard
        self._parser = parser        # AffixParser（后续用，Phase B/C 可选）
        self._cm = cm                # ConfigManager（可选）
        self._log = logger_ or logger
        self._scheme_loader = scheme_loader  # 可选：jump_target 解析模块方案 name->WorkflowDef
        self._abort = threading.Event()
        self._ctx: Dict[str, Any] = {}
        self._def: Optional[WorkflowDef] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # 防无限循环护栏（迭代次数上限）。与模型层 loop grid cols×rows 上限
        # （GRID_MAX_CELLS）同值：网格维度超限时循环会在中途被静默截断，
        # 故两处必须对齐，超限方案在校验层拒收、引擎层显式中止。
        self._max_loop_iterations = GRID_MAX_CELLS
        self._max_depth = max_depth          # 防嵌套过深（可配置，默认 16；预置实测深度 5）
        self._loop_timeout_ms = loop_timeout_ms  # 循环 wall-clock 超时护栏（默认 10 分钟，0/None=禁用）
        # 可选回调（UI 钩子，Phase D 接）
        self.on_status: Optional[Callable[[str, str], None]] = None
        self.on_finished: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self._paused = False
        self._resume_event = threading.Event()
        self.on_pause: Optional[Callable[[str], None]] = None  # 软暂停回调（UI 继续按钮触发）
        # G6：剪贴板连续空读熔断计数（Ctrl+C 未生效/游戏失焦时 read 返回空）
        self._clipboard_empty_streak = 0

    # ── 加载 ──
    @staticmethod
    def _build(data: dict) -> WorkflowDef:
        wf = workflow_from_dict(data)
        errors = validate_workflow(wf)
        if errors:
            raise ValueError("invalid workflow: " + "; ".join(errors))
        return wf

    def load(self, path: str) -> None:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._def = self._build(data)

    def load_def(self, wf: WorkflowDef) -> None:
        errors = validate_workflow(wf)
        if errors:
            raise ValueError("invalid workflow: " + "; ".join(errors))
        self._def = wf

    # ── 原语实现 ──
    def _guard_uncalibrated(self, anchor, x, y):
        # B-001（中危）坐标铁律：取不到坐标时 get_absolute_position 返回 (0,0) 哨兵。
        # 该值一旦拿去点/移鼠标就会误点屏幕左上角，故未校准时阻断动作并中止整个方案，
        # 绝不静默点击。引擎在 _run_action 捕获异常后据 self._abort 立即返回 aborted。
        if (x, y) == (0, 0):
            self._log.error(
                "坐标阻断：锚点 %s 未校准，get_absolute_position 返回 (0,0)，已中止以防误点屏幕左上角",
                anchor)
            self.abort()
            raise RuntimeError(f"锚点 {anchor} 未校准（坐标(0,0)），已阻断点击/移动")

    def _p_click_anchor(self, params):
        anchor = params["anchor"]
        x, y = self._coord.get_absolute_position(anchor)
        self._guard_uncalibrated(anchor, x, y)
        self._inp.click(x, y)
        return {"anchor": anchor, "x": x, "y": y}

    def _p_move_to_anchor(self, params):
        # 点②+补充2：只把光标移到锚点坐标，不点击（点击由后续「按键(鼠标键)」/「复制」完成）
        anchor = params["anchor"]
        x, y = self._coord.get_absolute_position(anchor)
        self._guard_uncalibrated(anchor, x, y)
        self._inp.move_mouse(x, y)
        return {"anchor": anchor, "x": x, "y": y}

    def _p_move_offset(self, params):
        # ①.2 相对移动：锚点 + (dx, dy) 像素偏移后移动光标（不点击）
        anchor = params["anchor"]
        dx = int(params.get("dx", 0))
        dy = int(params.get("dy", 0))
        x, y = self._coord.get_absolute_position(anchor)
        self._guard_uncalibrated(anchor, x, y)
        nx, ny = x + dx, y + dy
        self._inp.move_mouse(nx, ny)
        return {"anchor": anchor, "dx": dx, "dy": dy, "x": nx, "y": ny}

    def _p_press_key(self, params):
        key = params["key"]
        if "mouse_" in key:
            # 鼠标键/滚轮 token（mouse_left / mouse_wheel_up / ctrl+mouse_right …）
            self._inp.press_mouse(key)
        else:
            self._inp.press_key(key)
        return {"key": key}

    def _p_read_clipboard(self, params):
        # 批3 ③：read=整段存；match=按 rule 抽取（bool->true/false，number->捕获组数字，text->文本）
        # G6：None 归一化为 ""（剪贴板 API 失败时防 None 穿透到条件比较）
        text = self._inp.read_clipboard() or ""
        self._register_clipboard_read(text)
        self._ctx["clipboard"] = text   # 始终保留原始剪贴板，供 source=clipboard 条件复用
        mode = params.get("mode", "read")
        store_as = params.get("store_as", "clipboard")
        if mode == "match":
            rule_spec = resolve_rule(params.get("rule"))
            extracted = self._apply_rule(text, rule_spec)
            if store_as != "clipboard":
                self._ctx[store_as] = extracted
            return {"store_as": store_as, "value": extracted}
        # 默认 read：整段存到命名变量（默认 clipboard，已写入）
        self._ctx[store_as] = text
        return {"store_as": store_as, "clipboard": text}

    @staticmethod
    def _apply_rule(text, rule_spec):
        """按规则从文本抽取。bool->'true'/'false'；number/text->捕获组文本（无捕获组取整段）。

        未命中：bool 返 'false'，其余返 ''。rule_spec 为 None（规则无法解析）返 ''。
        P1-5：规则正则非法时兜底返 ''（理论上 resolve_rule 已拦截，此处二次保险）。
        """
        if not rule_spec:
            return ""
        pat = rule_spec["pattern"]
        kind = rule_spec["kind"]
        cg = rule_spec.get("capture_group", 1)
        try:
            m = re.search(pat, text, re.DOTALL)
        except re.error:
            return "false" if kind == "bool" else ""
        if not m:
            return "false" if kind == "bool" else ""
        if kind == "bool":
            return "true"
        if m.groups():
            try:
                return m.group(cg)
            except (IndexError, re.error):
                return m.group(0)
        return m.group(0)

    def _clipboard_empty_limit(self) -> int:
        """连续空读熔断阈值（Runtime.clipboard_empty_limit，默认 5，最小 1）。

        剪贴板连续读空（Ctrl+C 未生效/游戏失焦）时，until 循环可能靠空
        文本无限重铸；达阈值即抛错熔断，交 on_error 策略处理。
        """
        if self._cm is None:
            return 5
        try:
            v = int(self._cm.get("Runtime", "clipboard_empty_limit", "5") or "5")
        except (TypeError, ValueError):
            return 5
        return max(1, v)

    def _tab_recover_retries(self) -> int:
        """切页容错重试次数（Runtime.tab_recover_retries，默认 3，最小 1）。

        与 FSM V3031-TAB-FIX 的 TAB_RECOVER_RETRIES 同值；引擎侧走配置
        便于按机器性能调，FSM 侧暂为硬编码 3（不动其稳定路径）。
        """
        if self._cm is None:
            return 3
        try:
            v = int(self._cm.get("Runtime", "tab_recover_retries", "3") or "3")
        except (TypeError, ValueError):
            return 3
        return max(1, v)

    def _register_clipboard_read(self, text: str) -> None:
        """登记一次剪贴板读取：连续空读达阈值抛 RuntimeError 熔断。

        空 = None（调用方已归一化为 ""）或纯空白。非空读重置计数。
        抛错经 _run_action 的 on_error 通道处理（retry/jump/abort/skip）。
        """
        if text and text.strip():
            self._clipboard_empty_streak = 0
            return
        self._clipboard_empty_streak += 1
        limit = self._clipboard_empty_limit()
        if self._clipboard_empty_streak >= limit:
            self._log.error(
                "剪贴板连续 %d 次读空（阈值 %d），熔断当前步骤",
                self._clipboard_empty_streak, limit)
            raise RuntimeError(
                f"剪贴板连续 {self._clipboard_empty_streak} 次读空（阈值 {limit}），"
                f"已熔断；请检查游戏窗口是否在前台、Ctrl+C 是否生效")

    def _p_copy(self, params):
        # 点④：复制 = 模拟 Ctrl+C 后读取剪贴板，写入命名变量（默认 clipboard）
        store_as = params.get("store_as", "clipboard")
        self._inp.press_key("ctrl+c")
        time.sleep(0.05)  # 50ms 物理下限：等系统完成剪贴板写入
        # G6：None 归一化 + 连续空读熔断登记
        text = self._inp.read_clipboard() or ""
        self._register_clipboard_read(text)
        # G6：可选复制校验。Ctrl+C 未生效/窗口失焦时剪贴板会保留旧内容，
        # 单看「非空」发现不了；配 expect_prefix 后内容不以该前缀开头即视为
        # 复制失败，抛错交 on_error（retry/jump）恢复。空前缀=不校验。
        expect = params.get("expect_prefix")
        if expect and not text.startswith(expect):
            raise RuntimeError(
                f"复制校验失败: 剪贴板内容不以 {expect!r} 开头"
                f"（读到[{text[:40]}]，可能复制未生效/窗口失焦）")
        self._ctx[store_as] = text
        return {"store_as": store_as, "clipboard": text}

    def _p_wait_ms(self, params):
        ms = int(params["ms"])
        self._abort.wait(ms / 1000.0)   # 可被 abort 提前唤醒
        return {"waited_ms": ms}

    def _p_recall_cell(self, params):
        # 全量复刻制图：把光标移回网格循环的当前格。
        # 场景：body 内先移到通货格右键取用，光标已离开背包格，
        # 需回到当前格再左键应用。非网格上下文（无 __grid_cell）报错交 on_error 处理。
        cell = self._ctx.get("__grid_cell")
        if not cell:
            raise RuntimeError("回到当前格失败: 不在网格循环内（__grid_cell 不存在）")
        x, y = int(cell[0]), int(cell[1])
        self._inp.move_mouse(x, y)
        return {"x": x, "y": y}

    def _p_log(self, params):
        # 打印消息到应用主日志（logger.info → 主窗口日志栏），用于调试分支走向
        msg = str(params.get("message", ""))
        self._log.info("[工作流] %s", msg)
        return {"message": msg}

    def _p_abort(self, params):
        # 主动中止整个方案（如取用前验证不通过）：先置 abort 事件再抛异常，
        # _run_action 捕获后因 abort 已置位直接返回 aborted，不走 on_error 策略
        reason = str(params.get("reason", "步骤主动中止"))
        self.abort()
        raise RuntimeError(f"主动中止: {reason}")

    def _p_use_currency(self, params):
        # 纯积木：通货应用核心动作。不耦合 FSM 的「停止转场」——
        # 决策（何时重铸/接受）由编排层用 rarity/affix/session 条件源 + branch/loop 完成，
        # 本原语只负责「把通货用上去」这一动作。
        currency = params.get("currency")
        if not currency:
            raise RuntimeError("use_currency 需要 params.currency（通货名，如 '重铸石'）")

        # 目标格：优先 target 锚点名（与 click_anchor 一致），其次显式 x/y，再次当前网格格
        target = params.get("target")
        if target:
            tx, ty = self._coord.get_absolute_position(target)
            self._guard_uncalibrated(target, tx, ty)
        elif "x" in params and "y" in params:
            tx, ty = int(params["x"]), int(params["y"])
        else:
            cell = self._ctx.get("__grid_cell")
            if cell:
                tx, ty = int(cell[0]), int(cell[1])
            else:
                # 悬停评估场景（地图评估模块 standalone 用法）：无网格循环、
                # 无锚点时，以当前光标位置为目标格——copy/评估都不会移动鼠标，
                # 此刻光标仍在待处理物品上。
                getter = getattr(self._inp, "get_mouse_pos", None)
                pos = getter() if callable(getter) else None
                if not pos or pos == (0, 0):
                    raise RuntimeError(
                        "use_currency 缺少目标: 需 target 锚点名 / x,y / 网格循环内 / "
                        "或光标悬停在目标物品上（读取不到光标位置）")
                tx, ty = int(pos[0]), int(pos[1])

        # Step 1+3: 切页容错循环（移植 FSM V3031-TAB-FIX 方案A）
        # 真机 2026-10-11 07:03 日志证实的竞态：制图存图后游戏停在成品仓页，
        # 取通货前虽点了通货页但页签未真正切过去，Ctrl+C 误读成品仓内容 →
        # 误判「告罄」停止。对策：每次验证都强制重切页签再读，读到非目标
        # 内容/空则重切，最多 Runtime.tab_recover_retries 次仍失败才判负。
        tab_index = 1
        if self._cm is not None:
            tab_index = int(self._cm.get("StashMapping", "currency_stash", "1") or "1")
        tab_pos = self._coord.stash_tab_position(tab_index)
        if tab_pos == (0, 0):
            raise RuntimeError(f"通货页签未校准(tab_index={tab_index})，use_currency 中止")

        # Step 2: 通货坐标（主路径 + 兜底绝对坐标）
        stash_pos = self._coord.stash_currency_position(currency_name=currency)
        if stash_pos == (0, 0):
            stash_pos = self._coord.get_absolute_position(currency)
            if stash_pos == (0, 0):
                raise RuntimeError(f"通货[{currency}]坐标未校准，use_currency 中止")

        retries = self._tab_recover_retries()
        pre_text = ""
        for attempt in range(retries):
            if self._abort.is_set():
                raise RuntimeError("use_currency 中止")
            # 强制切到目标通货页签（覆盖「缓存认为已开但游戏实际未切」的竞态）
            self._inp.click(tab_pos[0], tab_pos[1])
            self._abort.wait(0.3)  # 切页等待（可被 abort 提前唤醒）
            if self._abort.is_set():
                raise RuntimeError("use_currency 切页等待期间被中止")
            self._inp.move_mouse(stash_pos[0], stash_pos[1])
            self._abort.wait(0.1)
            self._inp.clear_clipboard()   # 先清空：消除「读到上一次旧信息」风险
            self._inp.press_key("ctrl+c")
            time.sleep(0.05)
            # 读空时按 0.08*(n+1) 退避重读（同 FSM 取用前验证内层循环）
            pre_text = self._inp.read_clipboard() or ""
            for _read_attempt in range(3):
                if pre_text.strip():
                    break
                if _read_attempt < 2:
                    self._abort.wait(0.08 * (_read_attempt + 1))
                    if self._abort.is_set():
                        raise RuntimeError("use_currency 剪贴板重读期间被中止")
                    pre_text = self._inp.read_clipboard() or ""
            if currency in pre_text:
                break   # 命中目标通货，跳出切页重试
            if attempt < retries - 1:
                self._log.warning(
                    "use_currency: 未在通货页读到[%s]（切页重试 %d/%d），强制重切页签",
                    currency, attempt + 1, retries)
                self._abort.wait(0.1)
        # 外层切页重试结束：判定最终结果（重试耗尽才抛错，交 on_error 处理）
        if not pre_text.strip():
            raise RuntimeError(
                f"取用前验证失败: 无法读取通货[{currency}]信息"
                f"（重切页签 {retries} 次仍读空），通货可能告罄/游戏窗口失焦")
        if currency not in pre_text:
            raise RuntimeError(
                f"通货核对失败: 期望[{currency}]但读到[{pre_text[:40]}]，"
                f"可能坐标错位/页签未切（已重切 {retries} 次）")
        qty_match = re.search(r'堆叠数量:\s*(\d[\d,]*)', pre_text)
        if qty_match:
            qty = int(qty_match.group(1).replace(",", ""))
            if qty <= 0:
                raise RuntimeError(f"通货[{currency}]已告罄(数量=0)")

        # Step 4: 右键取用
        self._inp.click(stash_pos[0], stash_pos[1], button="right")
        self._abort.wait(0.3)

        # Step 5: 左键应用到目标格
        self._inp.click(tx, ty)
        self._inp.normal_delay()
        return {"currency": currency, "target": target, "x": tx, "y": ty}

    def _p_store_to_stash(self, params):
        """存仓积木（2026-10-23 用户拍板：所有去向不写死，走 StashMapping 按需调整）。

        页签索引取自 [StashMapping] <stash_key>（与 FSM _store_to_stash 同口径），
        页签坐标由 coord.stash_tab_position(tab_index) 按 StashTabs 偏移网络推算
        （即「仓库页N」派生锚点）——用户重排仓库页只改配置，不动工作流。
        动作序列与 FSM 存图一致：点页签 → 移回目标格 → ctrl+shift+左键存入。
        """
        stash_key = params.get("stash_key") or "waste_map_stash"
        # 目标格：同 use_currency 口径（target 锚点 > x,y > 网格循环格 > 当前光标）
        target = params.get("target")
        if target:
            tx, ty = self._coord.get_absolute_position(target)
            self._guard_uncalibrated(target, tx, ty)
        elif "x" in params and "y" in params:
            tx, ty = int(params["x"]), int(params["y"])
        else:
            cell = self._ctx.get("__grid_cell")
            if cell:
                tx, ty = int(cell[0]), int(cell[1])
            else:
                # 悬停评估场景（地图评估模块 standalone 用法）：无网格循环、
                # 无锚点时以当前光标位置为目标格——copy/评估都不移动鼠标，
                # 此刻光标仍在待处理物品上。
                getter = getattr(self._inp, "get_mouse_pos", None)
                pos = getter() if callable(getter) else None
                if not pos or pos == (0, 0):
                    raise RuntimeError(
                        "store_to_stash 缺少目标: 需 target 锚点名 / x,y / 网格循环内 / "
                        "或光标悬停在目标物品上（读取不到光标位置）")
                tx, ty = int(pos[0]), int(pos[1])
        # 页签索引走配置：用户按需调整仓库页序，只改 StashMapping 值
        tab_index = 1
        if self._cm is not None:
            try:
                tab_index = int(self._cm.get("StashMapping", stash_key, "1") or "1")
            except (TypeError, ValueError):
                tab_index = 1
        tab_pos = self._coord.stash_tab_position(tab_index)
        if tab_pos == (0, 0):
            raise RuntimeError(
                f"仓库页签未校准(StashMapping.{stash_key}=tab_index {tab_index})，store_to_stash 中止")
        # Step 1: 左键点击页签打开目标仓库页（已打开同页则跳过，与 FSM
        # _current_open_tab_index 同思路；引擎侧记 ctx，本次运行结束即失效）
        if self._ctx.get("__open_tab_index") != tab_index:
            if self._abort.is_set():
                raise RuntimeError("store_to_stash 中止")
            self._inp.click(tab_pos[0], tab_pos[1])
            self._abort.wait(0.3)  # 切页等待（可被 abort 提前唤醒）
            if self._abort.is_set():
                raise RuntimeError("store_to_stash 切页等待期间被中止")
            self._ctx["__open_tab_index"] = tab_index
        # Step 2: 移动鼠标回目标格（物品所在格）
        if self._abort.is_set():
            raise RuntimeError("store_to_stash 中止")
        self._inp.move_mouse(tx, ty)
        self._abort.wait(0.1)
        # Step 3: ctrl+shift+左键存入仓库（PoE：把光标上的物品移入已开的仓库页）
        if self._abort.is_set():
            raise RuntimeError("store_to_stash 中止")
        self._inp.press_mouse("ctrl+shift+mouse_left")
        self._inp.normal_delay()
        # Step 4（可选验证）：存后光标处应为空，与 FSM clipboard_stash_verify 同口径。
        # 输入替身未实现该方法时静默跳过（保持引擎可测）。
        if params.get("verify", True):
            fn = getattr(self._inp, "clipboard_stash_verify", None)
            if callable(fn):
                try:
                    if not fn():
                        self._log.warning(
                            "store_to_stash: 存仓验证未通过（剪贴板仍有内容），物品可能未入库")
                except Exception as e:
                    self._log.warning("store_to_stash: 存仓验证异常: %s", e)
        return {"stash_key": stash_key, "tab_index": tab_index, "x": tx, "y": ty}

    def _p_record_session(self, params):
        # G4：记录一次动作到会话限速器（与 FSM record_action 同源）。
        if self._inp is not None:
            self._inp.record_action()
        return {"recorded": True}

    def _p_pause(self, params):
        # G4：软暂停，等待外部 resume() 调用（如 UI 的「继续」按钮）。
        # 用于会话超限/人工介入：branch 命中后 pause，用户处理后点继续再往下走。
        note = str(params.get("note", ""))
        self._paused = True
        self._resume_event.clear()
        if self.on_pause:
            self.on_pause(note)
        # 可被 resume() 或 abort 唤醒，避免死等
        while self._paused and not self._abort.is_set():
            self._resume_event.wait(0.2)
        self._paused = False
        if self._abort.is_set():
            raise RuntimeError(f"暂停期间被中止（note={note}）")
        return {"resumed": True, "note": note}

    def _dispatch(self, step):
        handlers = {
            "click_anchor": self._p_click_anchor,
            "move_to_anchor": self._p_move_to_anchor,
            "move_offset": self._p_move_offset,
            "press_key": self._p_press_key,
            "read_clipboard": self._p_read_clipboard,
            "copy": self._p_copy,
            "wait_ms": self._p_wait_ms,
            "recall_cell": self._p_recall_cell,
            "log": self._p_log,
            "abort": self._p_abort,
            "use_currency": self._p_use_currency,
            "record_session": self._p_record_session,
            "pause": self._p_pause,
            "store_to_stash": self._p_store_to_stash,
        }
        handler = handlers.get(step.primitive)
        if handler is None:
            raise ValueError(f"未知 primitive: {step.primitive}")
        return handler(step.params)

    # ── 条件评估 ──
    def _eval_condition(self, cond, loop_index):
        if not cond:
            return True
        # 组合条件：all=全部满足(AND) / any=任一满足(OR)，支持嵌套；与单源条件互斥
        if "all" in cond:
            subs = cond["all"]
            if not isinstance(subs, list) or not subs:
                return False
            return all(self._eval_condition(s, loop_index) for s in subs)
        if "any" in cond:
            subs = cond["any"]
            if not isinstance(subs, list) or not subs:
                return False
            return any(self._eval_condition(s, loop_index) for s in subs)
        src = cond.get("source", "clipboard")
        op = cond.get("op", "equals")
        value = cond.get("value")
        if src == "counter":
            return self._cmp(loop_index, op, value, coerce_int=True)
        if src == "clipboard":
            # 优先用 read_clipboard 已缓存的原始剪贴板；否则读一次实时剪贴板（更健壮，条件可独立使用）
            text = self._ctx.get("clipboard")
            if text is None:
                try:
                    text = self._inp.read_clipboard()
                    self._ctx["clipboard"] = text
                except Exception:
                    text = ""
            text = text or ""
            if cond.get("rule"):
                rule_spec = resolve_rule(cond["rule"])
                extracted = self._apply_rule(text, rule_spec)
                return self._cmp(extracted, op, value)
            return self._cmp(text, op, value)
        if src == "ctx_diff":
            # P1-1：比较两上下文变量（如 before / after 严格不等），解锁「前后对比」类条件
            ka = cond.get("key_a")
            kb = cond.get("key_b")
            return self._cmp(self._ctx.get(ka), op, self._ctx.get(kb))
        if src == "ctx":
            key = cond.get("key")
            return self._cmp(self._ctx.get(key), op, value)
        if src == "rarity":
            # G3：稀有度语义（normal/magic/rare/unique/unknown），从剪贴板物品文本解析
            text = self._ctx.get("clipboard") or ""
            rarity = self._parser.detect_rarity(text) if self._parser else "unknown"
            return self._cmp(rarity, op, value)
        if src == "affix":
            # G1：词缀评估（accept/reroll/corrupt 裁决）。条件用 key 取 evaluation 字段
            # （如 key="final_decision" 比 "accept"；key="params_pass" 比 "True"）
            text = self._ctx.get("clipboard") or ""
            ev = self._affix_eval(text)
            field = cond.get("key", "final_decision")
            return self._cmp(ev.get(field), op, value)
        if src == "session":
            # G4：会话限速（防封）。check_session_limit 返回 (ok, reason)；
            # 条件用 key 取字段（如 key="ok" 比 "False" = 已超限）
            ok, reason = self._inp.check_session_limit() if self._inp else (True, "")
            d = {"ok": ok, "reason": reason}
            field = cond.get("key", "ok")
            return self._cmp(d.get(field), op, value)
        if src == "config":
            # 读配置条件源（2026-10-23 用户拍板「腐化后复查按腐化开关走」）：
            # 从 ConfigManager 取 [section] key 的字符串值再比较，让工作流能
            # 按配置开关自动分流（如 Strategy.enable_corruption=true 才走腐化段）。
            # 无 cm 时返回 False（缺配置不放过，交 on_error 处理）。
            if self._cm is None:
                self._log.warning("config 条件源不可用：引擎未传入 ConfigManager")
                return False
            section = cond.get("section", "")
            key = cond.get("key", "")
            if not section or not key:
                self._log.warning("config 条件源缺少 section/key: %s", cond)
                return False
            actual = self._cm.get(section, key, "")
            return self._cmp(str(actual), op, value)
        self._log.warning("未知条件 source: %s", src)
        return False

    def _affix_eval(self, text):
        """缓存式调用 AffixParser.evaluate_map（同一次运行内同文本只算一次）。

        黑白名单取自 ConfigManager（与 FSM _reload_affix_cache 同源）；无 cm/parser
        时退化为「仅参数校验、黑白名单放行」，保证积木在缺配置时也跑得通。
        """
        cache = self._ctx.get("__affix_eval")
        if cache is not None and cache.get("_text") == text:
            return cache
        blacklist = self._cm.get_affix_entries("AffixBlackList") if self._cm else []
        whitelist = self._cm.get_affix_entries("AffixWhiteList") if self._cm else []
        if self._parser is None:
            ev = {"_text": text, "final_decision": "unknown",
                  "params_pass": False, "whitelist_pass": True, "blacklist_hit": False}
        else:
            ev = self._parser.evaluate_map(text, blacklist, whitelist)
            ev["_text"] = text
        self._ctx["__affix_eval"] = ev
        return ev

    @staticmethod
    def _cmp(actual, op, value, coerce_int=False):
        try:
            if op in ("gt", "lt", "ge", "le"):
                a = int(actual)
                b = int(value)
                return {"gt": a > b, "lt": a < b, "ge": a >= b, "le": a <= b}[op]
            if op == "contains":
                return str(value) in str(actual)
            if op == "equals":
                return int(actual) == int(value) if coerce_int else str(actual) == str(value)
            if op == "nequals":
                return int(actual) != int(value) if coerce_int else str(actual) != str(value)
        except Exception:
            return False
        return False

    # ── 递归执行 ──
    def _execute(self) -> str:
        r = self._run_steps(self._def.steps, 0)
        return "done" if r == "ok" else r

    def _run_steps(self, steps: List, depth: int) -> str:
        for step in steps:
            if self._abort.is_set():
                return "aborted"
            if depth > self._max_depth:
                self._log.error(
                    "workflow 嵌套过深（当前层级 %d 超过上限 %d），于步骤 %s 停止。"
                    "建议将深层逻辑拆分为子工作流（用 on_error=jump 指向 workflows/ 下的模块方案）以降低耦合。",
                    depth, self._max_depth, step.id)
                return "error"
            reason = self._run_one(step, depth)
            if reason != "ok":
                return reason
        return "ok"

    def _run_one(self, step, depth, allow_jump=True) -> str:
        if step.kind == "action":
            reason = self._run_action(step, depth, allow_jump)
        elif step.kind == "loop":
            reason = self._run_loop(step, depth)
        elif step.kind == "branch":
            reason = self._run_branch(step, depth)
        elif step.kind == "subworkflow":
            reason = self._run_subworkflow(step, depth)
        else:
            self._log.error("未知 step.kind: %s", step.kind)
            return "error"
        # 点④：每步内置延迟（替代独立 wait_ms 步骤），仅在该步成功执行后才延时
        if reason == "ok" and step.delay_ms:
            if self._abort.is_set():
                return "aborted"
            self._abort.wait(step.delay_ms / 1000.0)
        return reason

    def _run_action(self, step, depth, allow_jump=True) -> str:
        max_attempts = 1 + (step.retry_count if step.on_error == "retry" else 0)
        last_exc = None
        attempt = 0
        while attempt < max_attempts:
            try:
                result = self._dispatch(step)
                if result is not None:
                    self._ctx["last"] = result
                if self.on_status:
                    self.on_status(step.id, "done")
                # 执行后立刻检查中止（如 wait 提前返回）
                if self._abort.is_set():
                    return "aborted"
                return "ok"
            except Exception as e:
                last_exc = e
                attempt += 1
                if self._abort.is_set():
                    return "aborted"
                if attempt < max_attempts and step.retry_delay_ms:
                    self._abort.wait(step.retry_delay_ms / 1000.0)
        # 用尽重试仍失败
        self._log.error("workflow step %s 失败: %s", step.id, last_exc)
        if step.on_error == "jump" and allow_jump:
            # jump 作为「错误恢复动作」：跳转目标成功执行即视为已恢复，
            # 不向 UI 报 on_error（否则会出现「先报错误、再报完成」的误报）。
            # 仅当跳转本身失败（目标不可解析/执行出错）才上报并中止。
            if self._do_jump(step, depth, allow_jump):
                if self.on_status:
                    self.on_status(step.id, "jumped")
                return "ok"
            if self.on_error:
                self.on_error(str(last_exc))
            self._abort.set()
            return "error"
        if self.on_error:
            self.on_error(str(last_exc))
        if step.on_error == "skip":
            if self.on_status:
                self.on_status(step.id, "skipped")
            return "ok"
        # abort / retry 用尽 -> 停止整个 workflow
        self._abort.set()
        return "error"

    # ── 错误跳转（⑥：on_error=jump）──
    def _do_jump(self, step, depth, allow_jump):
        """错误跳转：先按步骤 id 在本树查找，否则按模块方案名（workflows/ 文件）调入执行。

        语义：出错的步骤失败后，运行一次跳转目标（步骤或子程序模块）作为恢复动作，
        随后当前序列从出错步骤的下一个继续。allow_jump=False 时（恢复步骤自身）禁止再跳转，
        避免无限跳转循环。
        """
        target = step.jump_target
        if not target:
            self._log.error("jump 无 jump_target，step %s", step.id)
            return False
        tstep = self._find_step(target)
        if tstep is not None:
            reason = self._run_one(tstep, depth + 1, allow_jump=False)
            return reason in ("ok", None)
        sub = self._resolve_scheme(target)
        if sub is not None:
            reason = self._run_steps(sub.steps, depth + 1)
            return reason in ("ok", None)
        self._log.error("jump_target %r 既非步骤 id 也非可解析模块，step %s", target, step.id)
        return False

    def _find_step(self, target):
        """在整棵 workflow 树中按 id 查找步骤（含嵌套 loop/branch）。"""
        def _walk(steps):
            for s in steps:
                if s.id == target:
                    return s
                if s.kind == "loop":
                    r = _walk(s.body)
                    if r:
                        return r
                elif s.kind == "branch":
                    r = _walk(s.then_steps)
                    if r:
                        return r
                    r = _walk(s.else_steps)
                    if r:
                        return r
            return None
        return _walk(self._def.steps) if self._def else None

    def _resolve_scheme(self, name):
        """把模块名解析为 WorkflowDef（通过注入的 scheme_loader）。未注入或失败返回 None。"""
        if self._scheme_loader is None:
            self._log.warning("jump 到模块 %r 但 scheme_loader 未注入，跳过", name)
            return None
        try:
            return self._scheme_loader(name)
        except Exception as e:
            self._log.error("载入模块 %r 失败: %s", name, e)
            return None

    def _run_subworkflow(self, step, depth) -> str:
        """P4-A：子工作流一等公民——在**正常路径**调用并内联执行（可嵌套，受 _max_depth 护栏）。

        模块引用复用 jump_target 字段（与画布 SubWorkflowNode 预览同源）；
        经 scheme_loader 调入 workflows/<name>.json 的步骤内联运行。
        与 on_error=jump 的区别：那是对出错的「恢复动作」，本类是「正常调用」，
        从而解锁「嵌套子工作流 / 复用编排模组」。depth 由 _run_one 传入，
        嵌套层级受 _run_steps 的 _max_depth 检查约束。
        """
        if self.on_status:
            self.on_status(step.id, "running")
        target = step.jump_target
        if not target:
            self._log.error("子工作流 step %s 缺少 jump_target（模块名），无法调用", step.id)
            return "error"
        sub = self._resolve_scheme(target)
        if sub is None:
            self._log.error(
                "子工作流模块 %r 不可解析（scheme_loader 未注入或载入失败），step %s",
                target, step.id)
            return "error"
        reason = self._run_steps(sub.steps, depth + 1)
        if self.on_status and reason in ("ok", None):
            self.on_status(step.id, "done")
        return reason

    def _run_loop(self, step, depth) -> str:
        # 循环语义（until / count）：
        # - step.condition 非空 → 「until」循环：condition 是「退出条件」，每次进入循环体前先判定；
        #   条件为假时执行循环体，为真时退出（即「反复执行直到条件为真」）。
        #   注意是「前置判定」：若一开始条件即真，循环体一次都不执行。
        # - step.count 非空 → 固定次数循环（i 从 0 计数，i>=count 退出）。
        # - 两者皆无 → 默认执行 1 次。
        # 安全护栏：wall-clock 超时 + 最大迭代次数，避免 until 条件永远不满足时空转。
        if self.on_status:
            self.on_status(step.id, "running")
        if step.grid:
            reason = self._run_grid_loop(step, depth)
            if self.on_status:
                self.on_status(step.id, "done")
            return reason
        i = 0
        loop_start = time.monotonic()
        while True:
            if self._abort.is_set():
                return "aborted"
            # 循环 wall-clock 超时护栏：until 条件卡死时自动退出，避免无限空转
            if self._loop_timeout_ms and (time.monotonic() - loop_start) * 1000 > self._loop_timeout_ms:
                self._log.warning(
                    "loop %s 超过超时上限 %dms（疑似 until 条件永远不满足），强制退出循环",
                    step.id, self._loop_timeout_ms)
                break
            # 结束条件：until 条件满足，或达到 count，或默认 1 次
            if step.condition is not None:
                if self._eval_condition(step.condition, i):
                    break
            elif step.count is not None:
                if i >= step.count:
                    break
            else:
                if i >= 1:
                    break
            self._ctx["__loop_index"] = i
            reason = self._run_steps(step.body, depth + 1)
            if reason not in ("ok", None):
                return reason
            i += 1
            if i >= self._max_loop_iterations:
                self._log.warning("loop %s 达到最大迭代上限 %d，强制退出", step.id, self._max_loop_iterations)
                break
        if self.on_status:
            self.on_status(step.id, "done")
        return "ok"

    def _run_grid_loop(self, step, depth) -> str:
        # ①.2 网格循环：按 (cols × rows) 遍历，每格绝对坐标 = 原点锚点 + 像素偏移 + 行列步进。
        # 每次先把光标移到该格，再执行 body（body 可用「按键(鼠标键)」在光标处点击）。
        g = step.grid or {}
        anchor = g.get("anchor")
        dx0 = int(g.get("dx", 0))
        dy0 = int(g.get("dy", 0))
        cols = int(g.get("cols", 1))
        rows = int(g.get("rows", 1))
        cell_dx = int(g.get("cell_dx", 0))
        cell_dy = int(g.get("cell_dy", 0))
        # G8：维度上限护栏。cols×rows 超过迭代上限时循环会在中途被
        # _max_loop_iterations 静默截断（用户以为跑完实则半途终止）；
        # 此处显式报错并中止，与模型层 validate 的上限对齐（双保险：
        # load/load_def 经 _build 校验拒收，直接注入 _def 的调用方走这里）。
        if cols * rows > self._max_loop_iterations:
            self._log.error(
                "grid loop %s 维度 cols×rows=%d 超过迭代上限 %d，已中止（防止静默截断）",
                step.id, cols * rows, self._max_loop_iterations)
            self.abort()
            return "aborted"
        ox, oy = self._coord.get_absolute_position(anchor)
        if (ox, oy) == (0, 0):
            # B-001：网格原点锚点未校准；loop 路径不经 _run_action 的异常捕获，
            # 故直接中止并返回 reason，而非抛异常（那样会穿透 run_sync）。
            self._log.error(
                "坐标阻断：网格原点锚点 %s 未校准，get_absolute_position 返回 (0,0)，已中止网格循环",
                anchor)
            self.abort()
            return "aborted"
        ox += dx0
        oy += dy0
        idx = 0
        loop_start = time.monotonic()
        for r in range(rows):
            if self._abort.is_set():
                return "aborted"
            # 循环 wall-clock 超时护栏：遍历卡死时自动退出，避免无限空转
            if self._loop_timeout_ms and (time.monotonic() - loop_start) * 1000 > self._loop_timeout_ms:
                self._log.warning(
                    "grid loop %s 超过超时上限 %dms，强制退出网格循环",
                    step.id, self._loop_timeout_ms)
                return "ok"
            for c in range(cols):
                if self._abort.is_set():
                    return "aborted"
                cx = ox + c * cell_dx
                cy = oy + r * cell_dy
                self._inp.move_mouse(cx, cy)
                self._ctx["__grid_cell"] = (cx, cy)
                self._ctx["__grid_row"] = r
                self._ctx["__grid_col"] = c
                self._ctx["__loop_index"] = idx
                reason = self._run_steps(step.body, depth + 1)
                if reason not in ("ok", None):
                    return reason
                idx += 1
                if idx >= self._max_loop_iterations:
                    self._log.warning("grid loop %s 达到最大迭代上限 %d，强制退出", step.id, self._max_loop_iterations)
                    return "ok"
        return "ok"

    def _run_branch(self, step, depth) -> str:
        if self.on_status:
            self.on_status(step.id, "running")
        taken = self._eval_condition(step.condition, 0) if step.condition else True
        branch = step.then_steps if taken else step.else_steps
        reason = self._run_steps(branch, depth + 1)
        if self.on_status:
            self.on_status(step.id, "done")
        return reason

    # ── 准备 / 运行 ──
    def _prepare(self) -> None:
        if self._def is None:
            raise RuntimeError("尚未加载 workflow")
        self._abort.clear()
        self._ctx = {}
        self._running = False
        self._clipboard_empty_streak = 0

    def run_sync(self) -> str:
        self._prepare()
        reason = self._execute()
        if self.on_finished:
            self.on_finished(reason)
        return reason

    def start(self) -> None:
        if self._running:
            return
        self._prepare()
        self._running = True
        self._thread = threading.Thread(target=self._run_thread, daemon=True)
        self._thread.start()

    def _run_thread(self) -> None:
        reason = "error"
        try:
            reason = self._execute()
        except Exception as exc:
            # B1：运行期异常兜底——单步抛异常不应让 UI 卡在「运行中」。
            # 先经 on_error 透出错误信息，再 emit 终态 on_finished 让 UI 可恢复；
            # 正常路径不受影响（异常分支直接 return，后续 on_finished 不再重复发）。
            try:
                if self.on_error:
                    self.on_error(f"{type(exc).__name__}: {exc}")
            finally:
                if self.on_finished:
                    self.on_finished("error")
            return
        finally:
            self._running = False
        if self.on_finished:
            self.on_finished(reason)

    def abort(self) -> None:
        self._abort.set()

    def resume(self) -> None:
        """解除 _p_pause 的软暂停阻塞（由 UI 继续按钮 / 测试调用）。"""
        self._paused = False
        self._resume_event.set()

    def is_running(self) -> bool:
        return self._running

    @property
    def context(self) -> Dict[str, Any]:
        return self._ctx
