"""工作流数据模型（Phase A/B/C）。

纯数据 + 校验，无 Qt / 无副作用依赖，便于单测。
对应设计稿：poe_workflow_phaseA_design.md（路线 B：独立并行引擎，不修改 state_machine.py）

Phase B/C 扩展：
- 控制结构 loop / branch（支持嵌套，body / then_steps / else_steps 递归）。
- 条件 condition：clipboard / ctx / counter 源 + contains/equals/gt/lt...
- 每步错误策略 on_error：retry（默认）/ abort / skip / jump（+ retry_count / retry_delay_ms；jump 需 jump_target）。
"""
from __future__ import annotations

import json
import re

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


class WorkflowLoadError(ValueError):
    """工作流文件加载失败（JSON 解析 / schema 非法）。

    携带文件路径与原因，供 UI 侧清晰展示（取代静默跳过导致下拉 / 编辑器 /
    当前文件三处状态不一致）。是 ValueError 子类，便于调用方按异常类型捕获。
    """

# 原子动作原语
# click_anchor / wait_ms 保留用于兼容旧文件；新编排优先 move_to_anchor / 每步 delay_ms
PRIMITIVES = {"click_anchor", "move_to_anchor", "move_offset", "press_key",
              "read_clipboard", "copy", "wait_ms",
              "recall_cell", "log", "abort",
              "use_currency", "record_session", "pause",
              "store_to_stash"}

# 条件支持的源 / 操作符
CONDITION_SOURCES = {"clipboard", "ctx", "counter", "ctx_diff", "rarity", "affix",
                     "session", "config"}
CONDITION_OPS = {"contains", "equals", "nequals", "gt", "lt", "ge", "le"}

# 错误策略
ERROR_POLICIES = {"abort", "skip", "retry", "jump"}

# G8：网格循环维度上限。引擎 _run_grid_loop 到达 _max_loop_iterations 即
# **静默截断**（用户以为跑完、实则半途终止），是正确性陷阱，故 cols×rows
# 上限与引擎迭代护栏同值；单维度上限与 UI 网格编辑器 QSpinBox range 一致
# （cols/rows 1..1000、cell 步进 0..100000、原点偏移 ±100000）。
GRID_MAX_CELLS = 10000
GRID_MAX_DIM = 1000
GRID_MAX_OFFSET = 100000

# 共享规则注册表（批3：③读剪贴板匹配 与 ⑦条件复用 同一套原子规则）
# kind:
#   bool   -> 命中存 "true"/"false"（无捕获组，整段匹配即命中）
#   number -> 捕获组1 为数值，存该数字字符串（item_quantity 默认比较 op=ge）
#   text   -> 存捕获组文本（无捕获组存整段）
# 自定义规则：UI 可填 {pattern, kind, capture_group?(默认1)}
# 地图评估预设（2026-10-22，按用户提供的真实剪贴板样例推导；样例：
# 「地图（16阶）」+「{ 基底属性 }区域被起源者回忆影响 / 地图上有阿尔赫兹敏的要塞 /
#   该区域被裂界者影响」）——内置评估内容放工作流侧，FSM 一行不动（路线 B）
RULE_PRESETS = {
    "unidentified": {"label": "未鉴定", "pattern": r"未鉴定|Unidentified", "kind": "bool"},
    "corrupted":    {"label": "已腐化", "pattern": r"已腐化|Corrupted",     "kind": "bool"},
    "item_quantity":{"label": "物品数量", "pattern": r"物品数量:\s*\+(\d+)%", "kind": "number", "default_op": "ge"},
    # 名字含阶级「地图（16阶）」；容忍全角/半角括号、可选 T 前缀与「阶」后缀
    "map_tier":     {"label": "地图阶级", "pattern": r"地图\s*[（(]\s*[Tt]?\s*(\d+)\s*阶?\s*[）)]", "kind": "number", "default_op": "ge"},
    # 影响效果/地图特征：布尔命中型，每种影响一条；用户补充新影响时按同格式追加即可
    "influence_originator": {"label": "起源者回忆影响", "pattern": r"被\s*起源者回忆\s*影响", "kind": "bool"},
    "fortress_alhezhim":    {"label": "阿尔赫兹敏的要塞", "pattern": r"阿尔赫兹敏的要塞", "kind": "bool"},
    "influence_breach":     {"label": "裂界者影响", "pattern": r"被\s*裂界者\s*影响", "kind": "bool"},
}

# 数值比较阈值下拉（UI 条件编辑器「比较值」data source，2026-10-22 用户定案）：
#   percent —— 物品数量/物品稀有度/品质/怪群规模等百分比门槛（用户举例值，下拉可改）
#   tier    —— 地图阶级专用，只限 1~16（T 阶更接近阈值判定，但阶级域就 1~16）
THRESHOLD_PRESETS = {
    "percent": [20, 50, 70, 90, 100, 120],
    "tier": list(range(1, 17)),
}

# 词缀/特征库（UI 自定义规则区的「词缀库」多选 data source）：
# 点选多条组成 "a|b|c" 或匹配（布尔）。词缀类为纯文本子串；影响效果类与
# RULE_PRESETS 同源（引用预设 pattern，防两处漂移）。用户 2026-10-22：
# 「词缀则是多个词缀的库」「影响效果则类似于词缀库」。
FEATURE_LIBRARY = [
    {"label": "元素荆棘", "pattern": r"元素荆棘"},
    {"label": "无法再生", "pattern": r"无法再生"},
] + [
    {"label": RULE_PRESETS[k]["label"], "pattern": RULE_PRESETS[k]["pattern"]}
    for k in ("influence_originator", "fortress_alhezhim", "influence_breach")
]


def threshold_group(rule):
    """条件 rule -> 数值阈值分组：'tier'（地图阶级 1~16）/ 'percent'（百分比门槛）/ None。

    UI 据此切换「比较值」下拉选项；布尔/文本类规则（含无 rule 的原文比较）
    返回 None，调用方回落纯文本输入。
    """
    if isinstance(rule, str):
        if rule == "map_tier":
            return "tier"
        spec = RULE_PRESETS.get(rule)
        if spec and spec.get("kind") == "number":
            return "percent"
        return None
    if isinstance(rule, dict) and rule.get("kind") == "number":
        return "percent"
    return None


def build_or_pattern(patterns):
    """把多条库内 pattern 组成或匹配正则（逐条转义由库数据保证，这里只做拼接）。

    空串/空白条目跳过；全空返回 ""（调用方按「未选」处理）。
    """
    return "|".join(p for p in (str(x).strip() for x in patterns) if p)

RULE_KINDS = {"bool", "number", "text"}


def resolve_rule(rule):
    """把条件/读剪贴板的 rule 字段解析为统一结构 {pattern, kind, capture_group, default_op}。

    rule 可接受：
    - 预设键（str）：从 RULE_PRESETS 查；
    - 自定义 dict：{pattern, kind, capture_group?}。
    无法解析返回 None。
    """
    if isinstance(rule, str):
        spec = RULE_PRESETS.get(rule)
        if spec is None:
            return None
        return {
            "pattern": spec["pattern"],
            "kind": spec["kind"],
            "capture_group": 1,
            "default_op": spec.get("default_op"),
        }
    if isinstance(rule, dict):
        # ①E 自定义规则（UI 已暴露）：pattern 必须非空，kind 必须属于 RULE_KINDS
        # P1-5：pattern 必须是合法正则，否则无法解析（返回 None 由调用方拦截）
        if not rule.get("pattern") or rule.get("kind") not in RULE_KINDS:
            return None
        try:
            re.compile(rule["pattern"])
        except re.error:
            return None
        return {
            "pattern": rule["pattern"],
            "kind": rule["kind"],
            "capture_group": int(rule.get("capture_group", 1)),
            "default_op": rule.get("default_op"),
        }
    return None


@dataclass
class ActionStep:
    id: str
    kind: str = "action"                       # 'action' | 'loop' | 'branch'
    primitive: str = ""                        # kind=='action' 时填 PRIMITIVES 之一
    params: Dict[str, Any] = field(default_factory=dict)
    next: Optional[str] = None                 # 预留：显式跳转（高级，B/C 主路径未用）
    # 控制结构
    body: List["ActionStep"] = field(default_factory=list)        # loop 主体（嵌套）
    count: Optional[int] = None                 # loop 固定次数；与 condition 二选一
    condition: Optional[Dict[str, Any]] = None  # loop=「until 退出条件」(为真即停)，branch=「if 判定」(为真走 then)
    then_steps: List["ActionStep"] = field(default_factory=list)  # branch 真分支
    else_steps: List["ActionStep"] = field(default_factory=list)  # branch 假分支
    # 错误处理（Phase C）
    on_error: str = "retry"                    # 默认失败策略=重试（'abort' | 'skip' | 'retry' | 'jump'）
    retry_count: int = 1                        # on_error=retry 且未显式指定时的默认重试次数
    retry_delay_ms: int = 500                   # 默认重试间隔（ms）
    delay_ms: int = 0                          # 每步内置延迟（点④：替代独立 wait_ms 步骤，默认 0）
    # ①.2 网格循环（loop 专用）：{anchor, dx, dy, cols, rows, cell_dx, cell_dy}
    grid: Optional[Dict[str, Any]] = None
    # ⑥ 错误跳转目标（on_error=jump 时生效）：步骤 id，或 workflows/ 下的模块方案名（不含 .json）
    jump_target: Optional[str] = None


@dataclass
class WorkflowDef:
    name: str
    version: int = 1
    schema_version: str = "1.0"      # 格式版本（默认 1.0，缺失向后兼容）；破坏性变更才递增
    steps: List[ActionStep] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  JSON <-> 模型
# --------------------------------------------------------------------------- #
def _iter_child_lists(s):
    """产出一个步骤 dict 的三个子列表（body/then_steps/else_steps，缺省跳过）。"""
    for k in ("body", "then_steps", "else_steps"):
        v = s.get(k)
        if isinstance(v, list):
            yield v


def _migrate_step_delay_ms(s):
    """把单步 params 内误写的 delay_ms 提回顶层（见 migrate_delay_ms 注释）。"""
    if not isinstance(s, dict):
        return
    params = s.get("params")
    if not isinstance(params, dict) or "delay_ms" not in params:
        return
    try:
        top = int(s.get("delay_ms", 0) or 0)
    except (TypeError, ValueError):
        top = 0
    v = params.pop("delay_ms")
    if top:
        return          # 顶层已有非 0 值，以顶层为准，丢弃 params 内的
    try:
        s["delay_ms"] = int(v)
    except (TypeError, ValueError):
        s["delay_ms"] = 0


def migrate_delay_ms(steps):
    """递归清洗整棵步骤树中误写入 params 的 delay_ms（历史 UI bug 自愈）。

    旧版「步骤延迟」控件经 _set_param 把值写进 params.delay_ms，而模型与引擎
    （_step_from_dict / _run_one）只读顶层 delay_ms——用户设的延迟静默失效，
    且 params.delay_ms 会被 UI 的 _step_to_dict 整体落盘成为永久垃圾字段。
    规则：params 内有 delay_ms 时，顶层无值（或为 0）则提回顶层，否则丢弃
    params 内的。加载路径（workflow_from_dict 与 UI _load_file）均调用它自愈。
    """
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        _migrate_step_delay_ms(s)
        for lst in _iter_child_lists(s):
            migrate_delay_ms(lst)


def remap_jump_targets(steps, old_to_new):
    """递归把 jump_target 按 old_to_new 映射改写（A2：位置编号重编号后同步）。

    jump_target 也可能是子工作流**方案名**（workflows/<name>.json）而非步骤 id，
    因此只替换命中映射表键的值；映射表由调用方仅收录「真实发生了 id 变化的步骤」。
    old_to_new 为空时直接返回，零改写。
    """
    if not old_to_new:
        return
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        t = s.get("jump_target")
        if isinstance(t, str) and t in old_to_new:
            s["jump_target"] = old_to_new[t]
        for lst in _iter_child_lists(s):
            remap_jump_targets(lst, old_to_new)


def collect_step_ids(steps) -> dict:
    """收集整棵步骤树的 {step id: step dict} 映射（供重编号快照与校验用）。"""
    out = {}

    def _walk(lst):
        for s in lst or []:
            if not isinstance(s, dict):
                continue
            sid = s.get("id")
            if sid:
                out[sid] = s
            for cl in _iter_child_lists(s):
                _walk(cl)

    _walk(steps)
    return out


def build_id_remap(old_ids, new_ids):
    """对比重编号前后的 {id: step_dict} 快照，产出 {旧id: 新id} 映射。

    仅收录「同一个 step dict 对象、id 值发生变化」的项；新增/删除的步骤
    （任一侧无同一对象）不收录，映射为空时调用方零改写。
    传入的两个快照 dict 本身持有 step dict 强引用，保证对象在对比期间存活，
    id() 不会被回收重号误配。
    """
    new_by_obj = {id(d): nid for nid, d in new_ids.items()}
    out = {}
    for oid, d in old_ids.items():
        nid = new_by_obj.get(id(d))
        if nid is not None and nid != oid:
            out[oid] = nid
    return out


def assign_step_ids(steps) -> dict:
    """按层级位置重写整棵步骤树的 id（**唯一事实源**，列表/画布共用）。

    编号规则（与历史上列表 StepCard / 画布 _assign_ids 的行为完全一致，
    P4-B 起两侧同口径，本函数把两份拷贝收敛为一份）：
    - 顶层：1 / 2 / 3 ...（无点号）
    - 子级（loop body / branch then|else）：父路径 + "." + 序号
    - 分支两区**连续**编号：then 从 1 起，else 接 then 数量之后——
      两区各自从 1 起会跨区撞名（validate_workflow 拒收「重复 step id」，
      撞名方案永远无法运行/导出；且画布 _node_by_id 按 setdefault 注册，
      撞名的 else 子步永远无法被选中/删除）。
    - loop body 从 1 起。

    防御：跳过非 dict 条目（与 collect_step_ids / remap_jump_targets 一致；
    裸下标赋值会在 UI 槽里抛 TypeError → qFatal 闪退）。

    返回 {旧id: 新id} 映射（仅收录「同一对象 id 真变化」项，与
    build_id_remap 同口径）——调用方直接喂给 remap_jump_targets 同步
    jump_target；无变化时返回空 dict，remap 零改写。
    幂等：连续调用结果相同（id 只依赖位置，不依赖旧值）。
    """
    before = collect_step_ids(steps)
    _assign_ids_recursive(steps, "")
    return build_id_remap(before, collect_step_ids(steps))


def _assign_ids_recursive(steps, prefix, start=1):
    for i, d in enumerate(steps or []):
        if not isinstance(d, dict):
            continue
        n = start + i
        sid = f"{prefix}{n}" if not prefix else f"{prefix}.{n}"
        d["id"] = sid
        _assign_ids_recursive(d.get("body") or [], sid)
        _assign_ids_recursive(d.get("then_steps") or [], sid)
        _assign_ids_recursive(
            d.get("else_steps") or [], sid,
            1 + len(d.get("then_steps") or []))


def _step_from_dict(s: dict) -> ActionStep:
    # B2：schema 非法（非对象）直接抛清晰异常，不再静默产出畸形模型；
    # 缺 id 不在此处强校验——画布编辑态步骤 id 由 StepCard 按位置派生，
    # 且 validate_workflow 负责语义校验，故空 id 属合法中间态。
    if not isinstance(s, dict):
        raise WorkflowLoadError("<step>", "步骤必须是 JSON 对象")
    # A1 自愈：params 内误写的 delay_ms 提回顶层（历史 UI bug，见 migrate_delay_ms）；
    # 本函数对整棵树递归（body/then_steps/else_steps），每经一步即完成该步清洗。
    _migrate_step_delay_ms(s)
    on_error = s.get("on_error", "retry")
    # 默认失败策略=重试；显式选 retry 但没给次数/间隔时，给能真正重试的合理默认
    retry_count = int(s.get("retry_count", 1 if on_error == "retry" else 0))
    retry_delay_ms = int(s.get("retry_delay_ms", 500 if on_error == "retry" else 0))
    return ActionStep(
        id=s["id"],
        kind=s.get("kind", "action" if s.get("primitive") else "action"),
        primitive=s.get("primitive", ""),
        params=s.get("params", {}) or {},
        next=s.get("next"),
        body=[_step_from_dict(x) for x in s.get("body", [])],
        count=s.get("count"),
        condition=s.get("condition"),
        then_steps=[_step_from_dict(x) for x in s.get("then_steps", [])],
        else_steps=[_step_from_dict(x) for x in s.get("else_steps", [])],
        on_error=on_error,
        retry_count=retry_count,
        retry_delay_ms=retry_delay_ms,
        delay_ms=int(s.get("delay_ms", 0)),
        grid=s.get("grid"),
        jump_target=s.get("jump_target"),
    )


def workflow_from_dict(d: dict) -> WorkflowDef:
    """从 JSON dict 构建 WorkflowDef（递归解析嵌套步骤）。

    schema 非法时抛 WorkflowLoadError（清晰说明原因），不再静默产出畸形模型；
    正常文件行为与此前一致（steps 缺省为空数组、可选字段带默认值）。
    """
    if not isinstance(d, dict):
        raise WorkflowLoadError("<in-memory dict>", "根节点必须是 JSON 对象")
    steps_raw = d.get("steps", [])
    if not isinstance(steps_raw, list):
        raise WorkflowLoadError(
            "<in-memory dict>",
            f"steps 必须是数组，实际为 {type(steps_raw).__name__}")
    steps = [_step_from_dict(s) for s in steps_raw]
    return WorkflowDef(name=d.get("name", "unnamed"), version=d.get("version", 1),
                       schema_version=str(d.get("schema_version", "1.0")), steps=steps)


def load_workflow_file(path):
    """模型层文件读取入口：解析工作流方案文件并返回 WorkflowDef。

    取代 UI 侧散落的 json.load 静默吞错：JSON 解析失败或 schema 非法时抛
    WorkflowLoadError（携带文件名与原因），由 UI 侧统一展示；正常文件行为
    与此前一致。UI 的 _load_file 应改调此函数以复用同一套加载契约。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise WorkflowLoadError(path, f"无法读取或解析 JSON：{e}")
    try:
        return workflow_from_dict(data)
    except WorkflowLoadError as e:
        raise WorkflowLoadError(path, e.reason)


# --------------------------------------------------------------------------- #
#  校验
# --------------------------------------------------------------------------- #
def validate_workflow(wf: WorkflowDef) -> List[str]:
    errors: List[str] = []
    if not wf.steps:
        errors.append("workflow 没有 steps")
        return errors
    _validate_steps(wf.steps, set(), errors)
    return errors


def _validate_steps(steps, seen, errors):
    for s in steps:
        _validate_step(s, seen, errors)


def _validate_step(s: ActionStep, seen: set, errors: List[str]) -> None:
    if s.id in seen:
        errors.append(f"重复 step id: {s.id}")
    seen.add(s.id)

    if s.kind == "action":
        if s.primitive not in PRIMITIVES:
            errors.append(f"step {s.id}: kind=action 但 primitive {s.primitive!r} 未知")
        else:
            if s.primitive == "click_anchor" and "anchor" not in s.params:
                errors.append(f"step {s.id}: click_anchor 需要 params.anchor")
            if s.primitive == "move_to_anchor" and "anchor" not in s.params:
                errors.append(f"step {s.id}: move_to_anchor 需要 params.anchor")
            if s.primitive == "move_offset" and "anchor" not in s.params:
                errors.append(f"step {s.id}: move_offset 需要 params.anchor")
            if s.primitive == "wait_ms" and "ms" not in s.params:
                errors.append(f"step {s.id}: wait_ms 需要 params.ms")
            if s.primitive == "read_clipboard":
                if s.params.get("mode") == "match":
                    if "rule" not in s.params:
                        errors.append(f"step {s.id}: read_clipboard mode=match 需要 params.rule")
                    elif resolve_rule(s.params.get("rule")) is None:
                        errors.append(
                            f"step {s.id}: read_clipboard rule 无法解析"
                            f"（应属 RULE_PRESETS 或合法自定义 dict{{pattern,kind}}）")
            if s.primitive == "use_currency" and "currency" not in s.params:
                errors.append(f"step {s.id}: use_currency 需要 params.currency（通货名，如 '重铸石'）")
            if s.primitive == "store_to_stash":
                # 存仓积木：stash_key 是 [StashMapping] 的键名（页签索引走配置，
                # 不写死页号，用户在仓库管理页按需调整）
                sk = s.params.get("stash_key")
                if not sk or not isinstance(sk, str):
                    errors.append(
                        f"step {s.id}: store_to_stash 需要 params.stash_key"
                        f"（StashMapping 键名，如 waste_map_stash）")
            if s.primitive == "copy":
                # G6：expect_prefix 为可选复制校验前缀；非字符串会让引擎
                # text.startswith(expect) 抛 TypeError，错误信息难以定位
                ep = s.params.get("expect_prefix")
                if ep is not None and not isinstance(ep, str):
                    errors.append(f"step {s.id}: copy 的 params.expect_prefix 必须是字符串")
    elif s.kind == "loop":
        has_count = s.count is not None
        has_cond = s.condition is not None
        has_grid = s.grid is not None
        if sum([has_count, has_cond, has_grid]) != 1:
            errors.append(f"step {s.id}: loop 需要且只能有 count / condition / grid 之一")
        if has_grid:
            g = s.grid or {}
            if not g.get("anchor"):
                errors.append(f"step {s.id}: loop grid 需要 anchor")
            for f in ("cols", "rows", "cell_dx", "cell_dy"):
                if f not in g:
                    errors.append(f"step {s.id}: loop grid 缺少字段 {f}")
                elif isinstance(g[f], bool) or not isinstance(g[f], int) or g[f] < 0:
                    # bool 是 int 子类，须显式拒绝（JSON true 会绕过类型检查）
                    errors.append(f"step {s.id}: loop grid.{f} 必须为非负整数")
            if (g.get("cols", 0) or 0) < 1 or (g.get("rows", 0) or 0) < 1:
                errors.append(f"step {s.id}: loop grid cols/rows 必须 >= 1")
            # G8：单维度上限（越界会把鼠标送出屏幕；UI 侧即此 range）
            for f, lim in (("cols", GRID_MAX_DIM), ("rows", GRID_MAX_DIM),
                           ("cell_dx", GRID_MAX_OFFSET), ("cell_dy", GRID_MAX_OFFSET),
                           ("dx", GRID_MAX_OFFSET), ("dy", GRID_MAX_OFFSET)):
                v = g.get(f)
                if isinstance(v, int) and not isinstance(v, bool) and abs(v) > lim:
                    errors.append(f"step {s.id}: loop grid.{f}={v} 超出上限 ±{lim}")
            # G8：cols×rows 上限。引擎迭代护栏处静默截断 → 方案「看似跑完、
            # 实则半途终止」；在校验层直接拒收，迫使用户显式收窄维度。
            cv, rv = g.get("cols"), g.get("rows")
            if (isinstance(cv, int) and not isinstance(cv, bool)
                    and isinstance(rv, int) and not isinstance(rv, bool)
                    and cv >= 1 and rv >= 1 and cv * rv > GRID_MAX_CELLS):
                errors.append(
                    f"step {s.id}: loop grid cols×rows={cv * rv} 超过上限 "
                    f"{GRID_MAX_CELLS}（引擎迭代护栏处会静默截断，方案看似跑完实则半途终止）")
        if has_count and s.count <= 0:
            errors.append(f"step {s.id}: loop count 必须 > 0")
        if not s.body:
            errors.append(f"step {s.id}: loop 没有 body")
        _validate_steps(s.body, seen, errors)
    elif s.kind == "branch":
        if s.condition is None:
            errors.append(f"step {s.id}: branch 需要 condition")
        _validate_steps(s.then_steps, seen, errors)
        _validate_steps(s.else_steps, seen, errors)
    elif s.kind == "subworkflow":
        # P4-A：子工作流一等公民。模块引用复用 jump_target（与画布预览同源）。
        if not s.jump_target:
            errors.append(
                f"step {s.id}: kind=subworkflow 需要 jump_target（模块方案名，如 preset_mapmaker_full）")
    else:
        errors.append(f"step {s.id}: 未知 kind {s.kind!r}")

    if s.on_error not in ERROR_POLICIES:
        errors.append(f"step {s.id}: on_error 必须是 {sorted(ERROR_POLICIES)}")
    if s.on_error == "jump" and not s.jump_target:
        errors.append(f"step {s.id}: on_error=jump 需要 jump_target（步骤 id 或模块名）")
    if s.condition is not None:
        _validate_condition(s.condition, s.id, errors, kind=s.kind)


def _validate_condition(c: Dict[str, Any], sid: str, errors: List[str], kind: str = "loop") -> None:
    # 组合条件：all(AND) / any(OR)，子条件递归校验；与单源条件互斥
    if "all" in c or "any" in c:
        key = "all" if "all" in c else "any"
        subs = c.get(key)
        if not isinstance(subs, list) or not subs:
            errors.append(f"step {sid}: condition.{key} 必须为非空子条件数组")
        else:
            for i, sub in enumerate(subs):
                if not isinstance(sub, dict):
                    errors.append(f"step {sid}: condition.{key}[{i}] 必须是条件对象")
                else:
                    _validate_condition(sub, sid, errors, kind)
        return
    src = c.get("source")
    op = c.get("op")
    if src not in CONDITION_SOURCES:
        errors.append(f"step {sid}: condition source {src!r} 未知（应属 {sorted(CONDITION_SOURCES)}）")
    if src == "counter" and kind == "branch":
        # 引擎 _run_branch 对 counter 源固定传 0 —— 分支内 counter 恒为 0，条件静默失效；
        # 改用 source=ctx 配合 __grid_col / __loop_index 等上下文键判定「每 N 格」等。
        errors.append(
            f"step {sid}: branch 条件不支持 source=counter（分支内循环索引恒为 0，counter 条件静默失效）；"
            f"请改用 source=ctx 并配合上下文键（如 __grid_col / __loop_index）")
    if op not in CONDITION_OPS:
        errors.append(f"step {sid}: condition op {op!r} 未知（应属 {sorted(CONDITION_OPS)}）")
    if src == "ctx" and "key" not in c:
        errors.append(f"step {sid}: condition source=ctx 需要 key")
    if src == "ctx_diff" and ("key_a" not in c or "key_b" not in c):
        errors.append(f"step {sid}: condition source=ctx_diff 需要 key_a 与 key_b（比较两上下文变量）")
    if src == "config" and ("section" not in c or "key" not in c):
        errors.append(f"step {sid}: condition source=config 需要 section 与 key（读 [section] key 的配置值比较，如 Strategy + enable_corruption）")
    if src == "clipboard" and c.get("rule"):
        if resolve_rule(c["rule"]) is None:
            errors.append(f"step {sid}: condition rule {c['rule']!r} 无法解析（应属 RULE_PRESETS 或合法自定义 dict{{pattern,kind}}）")
