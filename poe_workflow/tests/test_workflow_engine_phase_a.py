# -*- coding: utf-8 -*-
"""Phase A 工作流引擎单元测试（无头，免 Qt）。

验证点（对应 design 验收标准）：
1. pytest 可独立跑通；
2. click_anchor 调用 CoordinateEngine 解析锚点（断言坐标==coord返回值，证明非写死）；
3. read_clipboard 把内容写入 ctx["clipboard"]；
4. 运行中置 abort，断言在全部步骤完成前停止（可中断）；
5. 用 stub 注入 coord/inp/parser，不依赖真实游戏窗口；
6. 多步骤按数组顺序线性执行；
7. 非法 workflow（未知 primitive / 缺 anchor）被校验拦截。
"""
from poe_workflow.workflow_model import WorkflowDef, ActionStep, validate_workflow
from poe_workflow.workflow_engine import WorkflowEngine


class FakeCoord:
    def __init__(self, mapping):
        self._m = mapping
        self.calls = []

    def get_absolute_position(self, name):
        self.calls.append(name)
        return self._m[name]


class FakeInp:
    def __init__(self, clipboard="ITEM-TEXT"):
        self.clicks = []
        self.keys = []
        self.clipboard_text = clipboard

    def click(self, x, y):
        self.clicks.append((x, y))

    def press_key(self, key):
        self.keys.append(key)

    def read_clipboard(self):
        return self.clipboard_text


def _make():
    coord = FakeCoord({"currency_base_point": (100, 200)})
    inp = FakeInp()
    eng = WorkflowEngine(coord, inp)
    return eng, coord, inp


def test_validate_rejects_unknown_primitive():
    wf = WorkflowDef(name="t", steps=[ActionStep(id="s1", primitive="fly", params={})])
    errs = validate_workflow(wf)
    assert any("未知" in e and "primitive" in e for e in errs)


def test_validate_rejects_missing_anchor():
    wf = WorkflowDef(name="t", steps=[ActionStep(id="s1", primitive="click_anchor", params={})])
    errs = validate_workflow(wf)
    assert any("anchor" in e for e in errs)


def test_click_anchor_uses_coord_not_hardcoded():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s1", primitive="click_anchor", params={"anchor": "currency_base_point"})
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    # 锚点确实经由 coord 解析（非写死 x/y）
    assert coord.calls == ["currency_base_point"]
    # 点击坐标 == coord 返回值
    assert inp.clicks == [(100, 200)]


def test_read_clipboard_stores_ctx():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s1", primitive="read_clipboard", params={"timeout_ms": 100})
    ])
    eng.load_def(wf)
    eng.run_sync()
    assert eng.context["clipboard"] == "ITEM-TEXT"


def test_wait_ms_runs():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[ActionStep(id="s1", primitive="wait_ms", params={"ms": 5})])
    eng.load_def(wf)
    assert eng.run_sync() == "done"


def test_linear_order_and_press_key():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="a", primitive="press_key", params={"key": "c"}),
        ActionStep(id="b", primitive="read_clipboard", params={}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.keys == ["c"]
    assert "clipboard" in eng.context


def test_abort_interrupts_before_completion():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s1", primitive="wait_ms", params={"ms": 5000}),
        ActionStep(id="s2", primitive="press_key", params={"key": "x"}),
    ])
    eng.load_def(wf)
    eng.start()
    import time
    time.sleep(0.2)
    eng.abort()
    time.sleep(0.2)
    assert eng.is_running() is False
    # 第二步（press_key x）不应执行
    assert inp.keys == []


def test_load_from_json(tmp_path):
    p = tmp_path / "wf.json"
    p.write_text(
        '{"name":"x","version":1,"steps":[{"id":"s1","primitive":"wait_ms","params":{"ms":1}}]}',
        encoding="utf-8",
    )
    eng, coord, inp = _make()
    eng.load(str(p))
    assert eng.run_sync() == "done"


def test_invalid_json_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(
        '{"name":"x","version":1,"steps":[{"id":"s1","primitive":"fly","params":{}}]}',
        encoding="utf-8",
    )
    eng, coord, inp = _make()
    try:
        eng.load(str(p))
        assert False, "应抛出 ValueError"
    except ValueError:
        pass
