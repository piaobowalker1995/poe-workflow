# -*- coding: utf-8 -*-
"""B-001 回归测试：坐标未校准返回 (0,0) 哨兵时，工作流引擎必须阻断点击/移动并中止，
而非拿去点屏幕左上角。

状态机侧已在多处拦截 (0,0)（state_machine.py:418/1005/1113），本文件补齐工作流引擎
原语一侧：_p_click_anchor / _p_move_to_anchor / _p_move_offset / _run_grid_loop 原点。
"""
from poe_workflow.workflow_model import WorkflowDef, ActionStep
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


def _make(mapping):
    coord = FakeCoord(mapping)
    inp = FakeInp()
    eng = WorkflowEngine(coord, inp)
    return eng, coord, inp


def test_click_anchor_uncalibrated_blocks_click_and_aborts():
    eng, coord, inp = _make({"bad": (0, 0)})
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="c", primitive="click_anchor", params={"anchor": "bad"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "aborted"
    assert inp.moves == []   # 没有任何点击落到 (0,0)


def test_move_to_anchor_uncalibrated_blocks_move_and_aborts():
    eng, coord, inp = _make({"bad": (0, 0)})
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="m", primitive="move_to_anchor", params={"anchor": "bad"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "aborted"
    assert inp.moves == []


def test_move_offset_uncalibrated_blocks_move_and_aborts():
    eng, coord, inp = _make({"bad": (0, 0)})
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="o", primitive="move_offset", params={"anchor": "bad", "dx": 5, "dy": 5}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "aborted"
    assert inp.moves == []


def test_grid_loop_origin_uncalibrated_blocks_and_aborts():
    eng, coord, inp = _make({"bad": (0, 0)})
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="g", kind="loop", grid={
            "anchor": "bad", "cols": 2, "rows": 1, "cell_dx": 10, "cell_dy": 10,
        }, body=[
            ActionStep(id="g1", primitive="press_key", params={"key": "x"}),
        ]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "aborted"
    assert inp.moves == []


def test_calibrated_anchor_still_clicks():
    # 反向确认：正常坐标不受 B-001 守卫影响
    eng, coord, inp = _make({"p": (10, 20)})
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="c", primitive="click_anchor", params={"anchor": "p"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.moves == [(10, 20)]
