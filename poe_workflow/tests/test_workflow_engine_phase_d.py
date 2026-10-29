# -*- coding: utf-8 -*-
"""Phase D 新增原语单元测试（无头，免 Qt）。

覆盖工作流 v2 批2 新增能力：
- move_to_anchor：移动光标到锚点坐标（不点击）
- copy：模拟 Ctrl+C 后读取剪贴板写入 ctx[store_as]
- press_key 鼠标键：mouse_left / mouse_wheel_up 等 token 走 press_mouse
- delay_ms：每步内置延迟（成功后才延时）

覆盖工作流 v2 批3 新增能力：
- read_clipboard mode=match：按 RULE_PRESETS 抽取（物品数量->数字，未鉴定/已腐化->true/false）
- 条件 source=clipboard 复用 rule：抽取后再按 op/value 比较
"""
import os
import time

from poe_workflow.workflow_model import WorkflowDef, ActionStep, validate_workflow
from poe_workflow.workflow_engine import WorkflowEngine


class FakeCoord:
    def __init__(self, mapping=None):
        self._m = mapping or {}
        self.calls = []

    def get_absolute_position(self, name):
        self.calls.append(name)
        return self._m.get(name, (10, 20))


class FakeInp:
    def __init__(self, clipboard="ITEM"):
        self.moves = []
        self.keys = []
        self.mouse = []
        self.clipboard_text = clipboard

    def click(self, x, y):
        self.moves.append((x, y))

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def press_key(self, key):
        self.keys.append(key)

    def press_mouse(self, token):
        self.mouse.append(token)

    def read_clipboard(self):
        return self.clipboard_text


def _make():
    coord = FakeCoord({"p": (10, 20)})
    inp = FakeInp()
    eng = WorkflowEngine(coord, inp)
    return eng, coord, inp


def test_move_to_anchor_moves_without_click():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="m", primitive="move_to_anchor", params={"anchor": "p"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert coord.calls == ["p"]
    assert inp.moves == [(10, 20)]
    assert inp.keys == []   # 不点击


def test_move_to_anchor_then_press_mouse_combo():
    # 补充2：移动至锚点后，由后续「按键(鼠标键)」点击
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="1", primitive="move_to_anchor", params={"anchor": "p"}),
        ActionStep(id="2", primitive="press_key", params={"key": "ctrl+mouse_left"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert coord.calls == ["p"]
    assert inp.moves == [(10, 20)]
    assert inp.mouse == ["ctrl+mouse_left"]


def test_copy_stores_clipboard_into_ctx():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="c", primitive="copy", params={"store_as": "item"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.keys == ["ctrl+c"]
    assert eng.context.get("item") == "ITEM"


def test_copy_default_store_as_clipboard():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="c", primitive="copy", params={}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("clipboard") == "ITEM"


def test_press_key_mouse_token_dispatches_to_press_mouse():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="k", primitive="press_key", params={"key": "mouse_wheel_up"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.mouse == ["mouse_wheel_up"]
    assert inp.keys == []


def test_delay_ms_applied_after_step():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="a", primitive="press_key", params={"key": "x"}, delay_ms=50),
    ])
    eng.load_def(wf)
    t0 = time.time()
    assert eng.run_sync() == "done"
    assert time.time() - t0 >= 0.04   # 至少休眠了 ~50ms


def test_delay_ms_zero_no_sleep():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="a", primitive="press_key", params={"key": "x"}, delay_ms=0),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"


def test_validate_move_to_anchor_requires_anchor():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="m", primitive="move_to_anchor", params={}),
    ])
    errs = validate_workflow(wf)
    assert any("move_to_anchor" in e for e in errs)


def test_copy_no_required_param_validates():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="c", primitive="copy", params={}),
    ])
    assert validate_workflow(wf) == []


def test_primitives_registered():
    from poe_workflow.workflow_model import PRIMITIVES
    assert "move_to_anchor" in PRIMITIVES
    assert "copy" in PRIMITIVES


# ── 批3：读剪贴板匹配（共享 RULE_PRESETS）──

def _make_with_clipboard(text):
    coord = FakeCoord({"p": (10, 20)})
    inp = FakeInp(clipboard=text)
    eng = WorkflowEngine(coord, inp)
    return eng, coord, inp


def test_read_clipboard_match_item_quantity_extracts_number():
    eng, _, _ = _make_with_clipboard("物品数量: +113% (augmented)\n更多地图: +35%")
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "rule": "item_quantity", "store_as": "iq"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("iq") == "113"        # 提取到数字
    assert "物品数量" in eng.context.get("clipboard", "")  # 原始剪贴板仍保留


def test_read_clipboard_match_corrupted_true():
    eng, _, _ = _make_with_clipboard("已腐化\n物品稀有度: +67%")
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "rule": "corrupted", "store_as": "c"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("c") == "true"


def test_read_clipboard_match_unidentified_false():
    eng, _, _ = _make_with_clipboard("物品数量: +58% (augmented)")
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "rule": "unidentified", "store_as": "u"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("u") == "false"


def test_read_clipboard_mode_read_stores_whole():
    eng, _, _ = _make_with_clipboard("abc 123")
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "read", "store_as": "raw"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("raw") == "abc 123"


def test_condition_clipboard_rule_ge_true_and_false():
    # 物品数量 +113% >= 100 -> 走 then
    eng, _, _ = _make_with_clipboard("物品数量: +113% (augmented)")
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="b", kind="branch",
                   condition={"source": "clipboard", "rule": "item_quantity",
                              "op": "ge", "value": "100"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("last", {}).get("key") == "a"

    # 物品数量 +58% < 100 -> 走 else
    eng2, _, _ = _make_with_clipboard("物品数量: +58% (augmented)")
    wf2 = WorkflowDef(name="t", steps=[
        ActionStep(id="b", kind="branch",
                   condition={"source": "clipboard", "rule": "item_quantity",
                              "op": "ge", "value": "100"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng2.load_def(wf2)
    assert eng2.run_sync() == "done"
    assert eng2.context.get("last", {}).get("key") == "b"


def test_validate_read_clipboard_match_requires_rule():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "store_as": "x"}),
    ])
    errs = validate_workflow(wf)
    assert any("read_clipboard" in e and "rule" in e for e in errs)


# ── 批4a：①.2 相对移动原语 + 网格步进循环 ──

def test_move_offset_moves_to_anchor_plus_offset():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="m", primitive="move_offset", params={"anchor": "p", "dx": 30, "dy": 15}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert coord.calls == ["p"]
    assert inp.moves == [(40, 35)]   # (10+30, 20+15)


def test_move_offset_default_zero_offset_equals_anchor():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="m", primitive="move_offset", params={"anchor": "p"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.moves == [(10, 20)]


def test_grid_loop_moves_to_each_cell_and_runs_body():
    # 2 列 × 3 行，cell_dx=10, cell_dy=5，原点锚点 p=(10,20)
    # 期望移动点：r0:(10,20),(20,20); r1:(10,25),(20,25); r2:(10,30),(20,30)
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop", grid={
            "anchor": "p", "dx": 0, "dy": 0, "cols": 2, "rows": 3,
            "cell_dx": 10, "cell_dy": 5,
        }, body=[
            ActionStep(id="c", primitive="press_key", params={"key": "mouse_left"}),
        ]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    expected = [(10, 20), (20, 20), (10, 25), (20, 25), (10, 30), (20, 30)]
    assert inp.moves == expected
    assert inp.mouse == ["mouse_left"] * 6


def test_grid_loop_saves_cell_context():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop", grid={
            "anchor": "p", "cols": 2, "rows": 1, "cell_dx": 7, "cell_dy": 0,
        }, body=[
            ActionStep(id="c", primitive="press_key", params={"key": "x"}),
        ]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("__loop_index") == 1   # 最后一格 idx=1
    assert eng.context.get("__grid_col") == 1
    assert eng.context.get("__grid_row") == 0


def test_validate_move_offset_requires_anchor():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="m", primitive="move_offset", params={}),
    ])
    errs = validate_workflow(wf)
    assert any("move_offset" in e for e in errs)


def test_validate_loop_grid_requires_anchor_and_dims():
    # 缺 anchor：报错；cell_dx/cell_dy=0 是合法非负整数，不报错
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop",
                   grid={"cols": 2, "rows": 1, "cell_dx": 0, "cell_dy": 0},
                   body=[ActionStep(id="c", primitive="press_key", params={"key": "x"})]),
    ])
    errs = validate_workflow(wf)
    assert any("anchor" in e for e in errs)
    assert not any("cell_dx" in e for e in errs)
    assert not any("cell_dy" in e for e in errs)
    # 缺 cell_dx / cell_dy 字段：报错
    wf2 = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop",
                   grid={"anchor": "p", "cols": 2, "rows": 1},
                   body=[ActionStep(id="c", primitive="press_key", params={"key": "x"})]),
    ])
    errs2 = validate_workflow(wf2)
    assert any("cell_dx" in e for e in errs2)
    assert any("cell_dy" in e for e in errs2)


def test_validate_loop_grid_cols_rows_min_1():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop",
                   grid={"anchor": "p", "cols": 0, "rows": 0, "cell_dx": 0, "cell_dy": 0},
                   body=[ActionStep(id="c", primitive="press_key", params={"key": "x"})]),
    ])
    errs = validate_workflow(wf)
    assert any("cols/rows" in e for e in errs)


def test_validate_loop_requires_exactly_one_mode():
    # 同时给 count 与 grid -> 报错
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop", count=2,
                   grid={"anchor": "p", "cols": 1, "rows": 1, "cell_dx": 0, "cell_dy": 0},
                   body=[ActionStep(id="c", primitive="press_key", params={"key": "x"})]),
    ])
    errs = validate_workflow(wf)
    assert any("只能有" in e for e in errs)


def test_primitives_registered_batch4a():
    from poe_workflow.workflow_model import PRIMITIVES
    assert "move_offset" in PRIMITIVES


# ── 批4b：⑥ 错误策略跳转 jump_target（步骤 id 或 模块方案）──

class FailingInp(FakeInp):
    """press_key('boom') 抛异常，用于触发错误策略。"""
    def press_key(self, key):
        if key == "boom":
            raise RuntimeError("boom")
        self.keys.append(key)


def test_on_error_jump_to_step_id_runs_recovery_then_continues():
    coord = FakeCoord({"p": (10, 20)})
    inp = FailingInp()
    eng = WorkflowEngine(coord, inp)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="1", primitive="press_key", params={"key": "boom"},
                   on_error="jump", jump_target="rec"),
        ActionStep(id="rec", primitive="press_key", params={"key": "recovered"}),
        ActionStep(id="2", primitive="press_key", params={"key": "after"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert "recovered" in inp.keys     # 跳转到 rec 并运行
    assert "after" in inp.keys         # 恢复后正常继续
    assert "boom" not in inp.keys      # boom 抛异常，未 append


def test_on_error_jump_to_module_runs_subroutine():
    coord = FakeCoord({"p": (10, 20)})
    inp = FailingInp()
    module = WorkflowDef(name="mod", steps=[
        ActionStep(id="m1", primitive="press_key", params={"key": "mod_ran"}),
    ])
    def loader(name):
        return module if name == "fixer" else None
    eng = WorkflowEngine(coord, inp, scheme_loader=loader)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="1", primitive="press_key", params={"key": "boom"},
                   on_error="jump", jump_target="fixer"),
        ActionStep(id="2", primitive="press_key", params={"key": "after"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert "mod_ran" in inp.keys       # 模块子程序被调入执行
    assert "after" in inp.keys


def test_on_error_jump_unresolvable_aborts():
    coord = FakeCoord({"p": (10, 20)})
    inp = FailingInp()
    eng = WorkflowEngine(coord, inp)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="1", primitive="press_key", params={"key": "boom"},
                   on_error="jump", jump_target="nonexistent"),
        ActionStep(id="2", primitive="press_key", params={"key": "after"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "error"
    assert "after" not in inp.keys     # 中止，后续不执行


def test_jump_recovery_failure_does_not_loop():
    coord = FakeCoord({"p": (10, 20)})
    inp = FailingInp()
    eng = WorkflowEngine(coord, inp)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="1", primitive="press_key", params={"key": "boom"},
                   on_error="jump", jump_target="rec"),
        ActionStep(id="rec", primitive="press_key", params={"key": "boom"},
                   on_error="jump", jump_target="rec"),
    ])
    eng.load_def(wf)
    # rec 自身失败且不允许再跳 -> 中止，无无限循环
    assert eng.run_sync() == "error"


def test_validate_jump_requires_target():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="1", primitive="press_key", params={"key": "x"}, on_error="jump"),
    ])
    errs = validate_workflow(wf)
    assert any("jump_target" in e for e in errs)


def test_error_policies_includes_jump():
    from poe_workflow.workflow_model import ERROR_POLICIES
    assert "jump" in ERROR_POLICIES


# ── ①.1 派生「仓库页N」锚点 ──

def test_derived_stash_page_anchor_resolves_via_stash_tab_position():
    from modules.coord_calculator import CoordCalculator
    calc = CoordCalculator.__new__(CoordCalculator)   # 派生分支不触碰 _engine
    calc.stash_tab_position = lambda n: (100, 200 + n * 30)
    assert calc.get_absolute_position("仓库页1") == (100, 230)
    assert calc.get_absolute_position("仓库页3") == (100, 290)


def test_derived_stash_page_anchor_requires_numeric_suffix():
    from modules.coord_calculator import CoordCalculator
    called = []
    calc = CoordCalculator.__new__(CoordCalculator)
    calc.stash_tab_position = lambda n: called.append(n)
    # 无页号 / 非数字页号 -> 不走派生分支，回落常规读取（此处为 (0,0)），且不调用 stash_tab_position
    assert calc.get_absolute_position("仓库页") == (0, 0)
    assert calc.get_absolute_position("仓库页abc") == (0, 0)
    assert called == []


# ── ①E 自定义规则 + ①D RULE_KINDS 生效 ──

def test_resolve_rule_rejects_unknown_kind_and_empty_pattern():
    from poe_workflow.workflow_model import resolve_rule
    assert resolve_rule({"pattern": "x", "kind": "bogus"}) is None          # kind 不在 RULE_KINDS
    assert resolve_rule({"pattern": "", "kind": "text"}) is None            # pattern 为空
    ok = resolve_rule({"pattern": r"怪物数量:\s*\+(\d+)%", "kind": "number"})
    assert ok is not None and ok["kind"] == "number"


def test_read_clipboard_match_custom_rule_dict():
    eng, _, _ = _make_with_clipboard("怪物数量: +42% 额外")
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match",
                           "rule": {"pattern": r"怪物数量:\s*\+(\d+)%", "kind": "number"},
                           "store_as": "mc"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("mc") == "42"


def test_validate_read_clipboard_custom_rule_unparsable():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "rule": {"pattern": "x", "kind": "bogus"}}),
    ])
    errs = validate_workflow(wf)
    assert any("read_clipboard" in e and "rule" in e for e in errs)



# ── 锚点分类：通货仓 / 背包格（+ 原闪退修复 循环->分支）──

def test_currency_anchor_resolves_by_stripping_prefix():
    """「通货:点金石」-> 剥离前缀后按普通点名解析。"""
    from modules.coord_calculator import CoordCalculator
    calc = CoordCalculator.__new__(CoordCalculator)
    seen = []

    def _plain(name):
        seen.append(name)
        return (11, 22)
    calc._resolve_plain = _plain
    assert calc.get_absolute_position("通货:点金石") == (11, 22)
    assert seen == ["点金石"]


def test_inventory_anchor_resolves_to_cell_position():
    """「背包:R,C」-> inventory_cell_position(row, col)。"""
    from modules.coord_calculator import CoordCalculator
    calc = CoordCalculator.__new__(CoordCalculator)
    seen = []
    calc.inventory_cell_position = lambda r, c: (seen.append((r, c)) or (7, 8))
    assert calc.get_absolute_position("背包:3,5") == (7, 8)
    assert seen == [(3, 5)]
    # 非法格式不进格子计算
    assert calc.get_absolute_position("背包:abc") == (0, 0)
    assert calc.get_absolute_position("背包:3") == (0, 0)
    assert seen == [(3, 5)]


def test_normalize_step_loop_then_branch_keeps_condition_dict():
    """回归：loop 会把 condition 置 None，切 branch 时必须重建为 dict。

    否则 _build_branch 在 cond.setdefault 抛 AttributeError，
    PyQt 槽异常触发 qFatal → 应用闪退。
    """
    from poe_workflow.ui.tab_workflow import _normalize_step
    d = {"id": "1", "kind": "action", "primitive": "move_to_anchor",
         "params": {"anchor": "x"}}
    _normalize_step(d, "loop")
    assert d.get("condition") is None          # loop 侧仍保留 None 语义
    _normalize_step(d, "branch")
    assert isinstance(d["condition"], dict)
    assert d["condition"]["source"] == "clipboard"


def test_anchor_kind_roundtrip():
    """锚点字符串 <-> 分类 反解析（UI 回显用）。"""
    from poe_workflow.ui.tab_workflow import _anchor_kind_of, CURRENCY_ANCHOR_PREFIX, \
        INVENTORY_ANCHOR_PREFIX, DERIVED_STASH_PREFIX
    assert _anchor_kind_of("") == "calib"
    assert _anchor_kind_of("currency_base_point") == "calib"
    assert _anchor_kind_of(f"{CURRENCY_ANCHOR_PREFIX}点金石") == "currency"
    assert _anchor_kind_of(f"{INVENTORY_ANCHOR_PREFIX}2,3") == "inv"
    assert _anchor_kind_of(f"{DERIVED_STASH_PREFIX}7") == "stash"
    assert _anchor_kind_of(f"{DERIVED_STASH_PREFIX}abc") == "calib"


# ── 全量复刻制图：新原语 recall_cell / log / abort + 预置方案 ──

class _FakeInp:
    def __init__(self, clipboard_text=""):
        self.moves = []
        self.clicks = []
        self.keys = []
        self._cb = clipboard_text

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def click(self, x, y):
        self.clicks.append((x, y))

    def press_key(self, k):
        self.keys.append(k)

    def press_mouse(self, k):
        self.keys.append(k)

    def read_clipboard(self):
        return self._cb


class _FakeCoord:
    def get_absolute_position(self, name):
        return (100, 200)


def test_recall_cell_returns_to_grid_cell():
    class _RecallInp(_FakeInp):
        pass
    inp = _RecallInp()
    eng = WorkflowEngine(_FakeCoord(), inp)
    eng.load_def(WorkflowDef(name="t", steps=[ActionStep(id="g", kind="loop", grid={
        "anchor": "a", "dx": 0, "dy": 0, "cols": 2, "rows": 1,
        "cell_dx": 10, "cell_dy": 5}, body=[
            ActionStep(id="r", primitive="recall_cell", params={}),
    ])]))
    assert eng.run_sync() == "done"
    # 每格：先 move 到格 (100+c*10, 200)，再 recall 回同格 -> 坐标成对出现
    assert inp.moves[0] == (100, 200) and inp.moves[1] == (100, 200)
    assert inp.moves[2] == (110, 200) and inp.moves[3] == (110, 200)


def test_recall_cell_outside_grid_raises():
    wf = WorkflowDef(name="t", steps=[ActionStep(id="r", primitive="recall_cell", params={})])
    eng = WorkflowEngine(_FakeCoord(), _FakeInp())
    eng.load_def(wf)
    assert eng.run_sync() == "error"   # on_error 默认 abort -> error


def test_log_primitive_records_message(caplog):
    import logging
    wf = WorkflowDef(name="t", steps=[ActionStep(id="l", primitive="log",
                                                 params={"message": "你好工作流"})])
    eng = WorkflowEngine(_FakeCoord(), _FakeInp())
    eng.load_def(wf)
    with caplog.at_level(logging.INFO, logger="poe_workflow.workflow_engine"):
        assert eng.run_sync() == "done"
    assert any("你好工作流" in r.message for r in caplog.records)


def test_abort_primitive_stops_run():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="a", primitive="abort", params={"reason": "验证失败"}),
        ActionStep(id="b", primitive="wait_ms", params={"ms": 1}),
    ])
    eng = WorkflowEngine(_FakeCoord(), _FakeInp())
    eng.load_def(wf)
    assert eng.run_sync() == "aborted"


def test_preset_mapmaker_full_loads_and_runs():
    """预置·制图流程：合法可加载，Fake 输入下全流程跑通 done。"""
    import json
    from poe_workflow.workflow_model import workflow_from_dict
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "workflows", "preset_mapmaker_full.json")
    with open(path, "r", encoding="utf-8") as f:
        wf = workflow_from_dict(json.load(f))
    assert not validate_workflow(wf)

    class _SeqInp(_FakeInp):
        _n = 0
        seq = ["未鉴定 地图", "稀有度: 普通 地图",
               "稀有度: 稀有 地图", "稀有度: 稀有 已腐化 反射 地图"]
        def read_clipboard(self):
            _SeqInp._n += 1
            return _SeqInp.seq[min(_SeqInp._n - 1, len(_SeqInp.seq) - 1)]

    eng = WorkflowEngine(_FakeCoord(), _SeqInp())
    eng.load_def(wf)
    eng._abort.wait = lambda t: None   # 测试短路 delay_ms 与 wait_ms 真实等待（60格×数十步）
    assert eng.run_sync() == "done"
