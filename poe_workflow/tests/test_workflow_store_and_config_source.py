# -*- coding: utf-8 -*-
"""store_to_stash 存仓积木 + config 条件源（2026-10-23 用户拍板）。

拍板要点：
- 「所有图均不指定固定页签，按需调整即可」→ store_to_stash 只存 StashMapping
  键名，页签索引走配置，坐标由 stash_tab_position 按 StashTabs 偏移网络推算；
- 「是否跳过腐化步骤即为是否开关腐化步骤」→ config 条件源读 [section] key
  的字符串值比较，腐化开关一改工作流行为自动跟着变。

锁定行为：
- 动作序列 = 点页签 → 移回目标格 → ctrl+shift+左键存入（FSM 存图同口径）；
- 同页跳过重复点击、异页重新点击；未校准 (0,0) 阻断；
- 目标格解析：target 锚点 > x,y > 网格循环格 > 当前光标；都拿不到则报错；
- config 源：缺 cm / 缺 section/key / 值不匹配均返回 False（不放过）。
"""
from poe_workflow.workflow_model import (
    workflow_from_dict, validate_workflow,
)
from poe_workflow.workflow_engine import WorkflowEngine


class Coord:
    def __init__(self, mapping=None, tab_pos=None):
        self._m = mapping or {}
        self._tab_pos = tab_pos
        self.tab_calls = []
        self.anchor_calls = []

    def get_absolute_position(self, name):
        self.anchor_calls.append(name)
        return self._m.get(name, (10, 20))

    def stash_tab_position(self, tab_index):
        self.tab_calls.append(tab_index)
        if self._tab_pos is not None:
            return self._tab_pos
        return (100 + tab_index * 10, 200)


class Inp:
    def __init__(self, cursor=(500, 500), verify_ok=True):
        self.moves = []
        self.keys = []
        self.mouse = []
        self.clicks = []
        self._cursor = tuple(cursor)
        self.verify_ok = verify_ok
        self.verify_calls = 0

    def click(self, x, y, button="left"):
        self.clicks.append((x, y, button))
        self.moves.append((x, y))

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def press_key(self, key):
        self.keys.append(key)

    def press_mouse(self, token):
        self.mouse.append(token)

    def read_clipboard(self):
        return ""

    def normal_delay(self):
        pass

    def get_mouse_pos(self):
        return self._cursor

    def clipboard_stash_verify(self):
        self.verify_calls += 1
        return self.verify_ok


class NoCursorInp(Inp):
    """读不到光标位置的输入替身（旧替身/异常环境）。"""
    get_mouse_pos = None


class Cm:
    def __init__(self, config=None):
        self._config = dict(config or {})

    def get(self, section, key, default=""):
        return self._config.get((section, key), default)


def _store_step(sid, key, **extra):
    params = {"stash_key": key}
    params.update(extra.pop("params", {}))
    step = {"id": sid, "kind": "action", "primitive": "store_to_stash",
            "params": params, "on_error": "abort", "delay_ms": 0}
    step.update(extra)
    return step


def _run(steps, coord=None, inp=None, cm=None):
    coord = coord or Coord()
    inp = inp if inp is not None else Inp()
    cm = cm if cm is not None else Cm({
        ("StashMapping", "flawed_map_stash"): "4",
        ("StashMapping", "waste_map_stash"): "5",
        ("StashMapping", "finished_map_stash"): "2",
    })
    eng = WorkflowEngine(coord, inp, cm=cm)
    eng.load_def(workflow_from_dict({"name": "t", "steps": steps}))
    result = eng.run_sync()
    return eng, inp, coord, result


# ── store_to_stash：动作序列与页签推算 ─────────────────────────── #

def test_store_sequence_tab_then_item_then_ctrl_shift_click():
    eng, inp, coord, result = _run([_store_step("1", "flawed_map_stash")])
    assert result == "done"
    # 页签坐标按配置键 flawed=4 推算 → (140,200)
    assert coord.tab_calls == [4]
    assert (140, 200, "left") in inp.clicks          # 点了页签
    assert (500, 500) in inp.moves                   # 移回光标所在物品格
    assert inp.mouse == ["ctrl+shift+mouse_left"]    # 存入动作
    assert inp.verify_calls == 1                     # 存后验证走了
    last = eng.context["last"]
    assert last["stash_key"] == "flawed_map_stash" and last["tab_index"] == 4


def test_store_same_tab_skips_second_click():
    steps = [_store_step("1", "flawed_map_stash"),
             _store_step("2", "flawed_map_stash")]
    eng, inp, coord, result = _run(steps)
    assert result == "done"
    assert coord.tab_calls == [4, 4]                 # 两次都推算了坐标
    tab_clicks = [c for c in inp.clicks if c[:2] == (140, 200)]
    assert len(tab_clicks) == 1                      # 但只点了一次（同页跳过）
    assert inp.mouse == ["ctrl+shift+mouse_left"] * 2


def test_store_different_tab_clicks_again():
    steps = [_store_step("1", "flawed_map_stash"),
             _store_step("2", "waste_map_stash")]
    eng, inp, coord, result = _run(steps)
    assert result == "done"
    assert (140, 200, "left") in inp.clicks and (150, 200, "left") in inp.clicks


def test_store_target_anchor_overrides_cursor():
    coord = Coord(mapping={"背包格A": (777, 888)})
    eng, inp, _, result = _run(
        [_store_step("1", "waste_map_stash", params={"target": "背包格A"})],
        coord=coord)
    assert result == "done"
    assert (777, 888) in inp.moves                   # 用锚点坐标而非光标
    assert (500, 500) not in inp.moves


def test_store_explicit_xy_overrides_cursor():
    eng, inp, _, result = _run(
        [_store_step("1", "waste_map_stash", params={"x": 321, "y": 654})])
    assert result == "done"
    assert (321, 654) in inp.moves


def test_store_uncalibrated_tab_blocks_and_aborts():
    # 未校准(0,0)绝不静默点击：步骤失败 → on_error=abort → 引擎置中止位返回 error
    coord = Coord(tab_pos=(0, 0))
    eng, inp, _, result = _run([_store_step("1", "flawed_map_stash")], coord=coord)
    assert result == "error"
    assert eng._abort.is_set()               # 中止位已置（UI 应进入停止态）
    assert inp.clicks == [] and inp.mouse == []


def test_store_missing_target_without_cursor_raises():
    eng, inp, _, result = _run(
        [_store_step("1", "flawed_map_stash")], inp=NoCursorInp())
    assert result == "error"
    assert eng._abort.is_set()
    assert inp.clicks == []


def test_store_verify_failure_only_warns():
    inp = Inp(verify_ok=False)
    eng, _, _, result = _run([_store_step("1", "flawed_map_stash")], inp=inp)
    assert result == "done"                          # 验证失败不中断，仅告警
    assert inp.mouse == ["ctrl+shift+mouse_left"]


def test_store_verify_can_be_disabled():
    inp = Inp()
    eng, _, _, result = _run(
        [_store_step("1", "flawed_map_stash", params={"verify": False})], inp=inp)
    assert result == "done"
    assert inp.verify_calls == 0


# ── config 条件源 ─────────────────────────────────────────────── #

def _gate_step():
    return {
        "id": "gate", "kind": "branch",
        "condition": {"source": "config", "section": "Strategy",
                      "key": "enable_corruption", "op": "equals",
                      "value": "true"},
        "on_error": "abort", "delay_ms": 0,
        "then_steps": [{"id": "yes", "kind": "action", "primitive": "log",
                        "params": {"message": "腐化开"},
                        "on_error": "skip", "delay_ms": 0}],
        "else_steps": [{"id": "no", "kind": "action", "primitive": "log",
                        "params": {"message": "腐化关"},
                        "on_error": "skip", "delay_ms": 0}],
    }


def test_config_source_true_routes_then():
    cm = Cm({("Strategy", "enable_corruption"): "true"})
    eng, _, _, result = _run([_gate_step()], cm=cm)
    assert result == "done"
    assert eng.context["last"]["message"] == "腐化开"


def test_config_source_false_routes_else():
    cm = Cm({("Strategy", "enable_corruption"): "false"})
    eng, _, _, result = _run([_gate_step()], cm=cm)
    assert result == "done"
    assert eng.context["last"]["message"] == "腐化关"


def test_config_source_missing_key_routes_else():
    eng, _, _, result = _run([_gate_step()], cm=Cm())
    assert result == "done"
    assert eng.context["last"]["message"] == "腐化关"


def test_config_source_without_cm_routes_else():
    eng = WorkflowEngine(Coord(), Inp(), cm=None)
    eng.load_def(workflow_from_dict({"name": "t", "steps": [_gate_step()]}))
    assert eng.run_sync() == "done"
    assert eng.context["last"]["message"] == "腐化关"


# ── 模型校验 ──────────────────────────────────────────────────── #

def test_validation_requires_stash_key():
    bad = {"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "store_to_stash",
         "params": {}, "on_error": "abort", "delay_ms": 0}]}
    errs = validate_workflow(workflow_from_dict(bad))
    assert any("stash_key" in e for e in errs)


def test_validation_config_condition_needs_section_and_key():
    cond = {"source": "config", "op": "equals", "value": "true"}
    bad = {"name": "t", "steps": [
        {"id": "1", "kind": "branch", "condition": cond,
         "on_error": "abort", "delay_ms": 0,
         "then_steps": [], "else_steps": []}]}
    errs = validate_workflow(workflow_from_dict(bad))
    assert any("section" in e for e in errs)
    cond["section"], cond["key"] = "Strategy", "enable_corruption"
    assert validate_workflow(workflow_from_dict(bad)) == []


# ── UI 接线：模块库插入 + 编辑器控件 ────────────────────────────── #

def test_palette_insert_store_to_stash_valid(qapp, config_manager):
    """模块库点「存入仓库」→ 生成合法步骤（默认废图仓键名）。"""
    from poe_workflow.ui.tab_workflow import WorkflowTab
    tab = WorkflowTab(config_manager)
    tab._on_new()
    before = len(tab._steps_dicts)
    tab._on_palette_activated({"type": "primitive", "payload": "store_to_stash"})
    assert len(tab._steps_dicts) == before + 1
    assert tab._steps_dicts[-1]["params"]["stash_key"] == "waste_map_stash"
    assert tab._canvas_model.validate() == []


def test_step_card_store_params_editor(qapp, config_manager):
    """store_to_stash 卡片：仓库键下拉 + 目标格选择 + 存后验证勾选。"""
    from PyQt5.QtWidgets import QComboBox, QCheckBox
    from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _new_step_dict
    tab = WorkflowTab(config_manager)
    d = _new_step_dict(tab)
    d["primitive"] = "store_to_stash"
    d["params"] = {"stash_key": "flawed_map_stash", "verify": True}
    card = StepCard(d, [d], tab, "1")
    combo = card.findChild(QComboBox, "StashKeyCombo")
    assert combo is not None and combo.currentText() == "瑕疵仓"
    chk = card.findChild(QCheckBox, "StashVerifyCheck")
    assert chk is not None and chk.isChecked()
    # 切到成品仓 → 写回 params.stash_key（数据层是键名不是中文）
    combo.setCurrentText("成品仓")
    assert d["params"]["stash_key"] == "finished_map_stash"
    # 用户拍板「下拉要做全 + 保留扩展选项应变」：可编辑 + 手输自定义键名直接写回
    assert combo.isEditable() is True
    combo.setCurrentText("my_custom_stash")
    assert d["params"]["stash_key"] == "my_custom_stash"
