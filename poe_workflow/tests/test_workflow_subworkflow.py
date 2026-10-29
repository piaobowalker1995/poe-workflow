# -*- coding: utf-8 -*-
"""P4-A 子工作流一等公民（模型+引擎地基）测试。

kind=subworkflow 在正常路径调用并内联执行模块（workflows/<name>.json），
可嵌套，受 _max_depth 护栏；模块引用复用 jump_target 字段。
"""
from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import workflow_from_dict, validate_workflow


class _FakeInp:
    def __init__(self):
        self.clicks = []

    def click(self, x, y, button="left", **kw):
        self.clicks.append((x, y, button))

    def move_mouse(self, x, y):
        pass

    def clear_clipboard(self):
        pass

    def press_key(self, key):
        pass

    def read_clipboard(self):
        return ""

    def normal_delay(self):
        pass


class _FakeCoord:
    def get_absolute_position(self, name):
        return (100, 100)


def _wf(steps, name="wf"):
    return workflow_from_dict({"name": name, "steps": steps})


def _click_step(sid, anchor="spot"):
    return {"id": sid, "kind": "action", "primitive": "click_anchor",
            "params": {"anchor": anchor}, "on_error": "retry", "delay_ms": 0}


def _sub_step(sid, module):
    return {"id": sid, "kind": "subworkflow", "jump_target": module,
            "on_error": "retry", "delay_ms": 0}


def _engine(inp, scheme_loader, max_depth=16):
    return WorkflowEngine(_FakeCoord(), inp, scheme_loader=scheme_loader,
                          max_depth=max_depth)


def test_subworkflow_runs_on_normal_path():
    main = _wf([_click_step("1"), _sub_step("2", "sub_a"), _click_step("3")], "main")
    sub_a = _wf([_click_step("1", "sub_spot")], "sub_a")
    loader = lambda name: {"sub_a": sub_a}.get(name)
    inp = _FakeInp()
    eng = _engine(inp, loader)
    eng.load_def(main)
    reason = eng.run_sync()
    assert reason == "done"
    # 主方案两步 + 子模块一步，共 3 次点击（子模块确在内联执行）
    assert len(inp.clicks) == 3


def test_subworkflow_nesting():
    # main -> sub_a -> sub_b -> click
    main = _wf([_sub_step("1", "sub_a")], "main")
    sub_a = _wf([_sub_step("1", "sub_b")], "sub_a")
    sub_b = _wf([_click_step("1", "deep_spot")], "sub_b")
    loader = lambda name: {"sub_a": sub_a, "sub_b": sub_b}.get(name)
    inp = _FakeInp()
    eng = _engine(inp, loader)
    eng.load_def(main)
    reason = eng.run_sync()
    assert reason == "done"
    assert inp.clicks == [(100, 100, "left")]


def test_subworkflow_depth_guard():
    # max_depth=1：main->sub_a(depth1) OK，sub_a->sub_b(depth2>1) 触发护栏报错
    main = _wf([_sub_step("1", "sub_a")], "main")
    sub_a = _wf([_sub_step("1", "sub_b")], "sub_a")
    sub_b = _wf([_click_step("1")], "sub_b")
    loader = lambda name: {"sub_a": sub_a, "sub_b": sub_b}.get(name)
    inp = _FakeInp()
    eng = _engine(inp, loader, max_depth=1)
    eng.load_def(main)
    reason = eng.run_sync()
    assert reason == "error"
    assert inp.clicks == []   # 深层未被执行


def test_subworkflow_missing_module_errors():
    main = _wf([_sub_step("1", "nope")], "main")
    inp = _FakeInp()
    eng = _engine(inp, lambda name: None)
    eng.load_def(main)
    reason = eng.run_sync()
    assert reason == "error"


def test_validate_subworkflow_requires_jump_target():
    bad = _wf([{"id": "1", "kind": "subworkflow", "on_error": "retry"}])
    errs = validate_workflow(bad)
    assert any("jump_target" in e for e in errs)


def test_validate_subworkflow_with_target_ok():
    ok = _wf([_sub_step("1", "preset_mapmaker_full")])
    assert validate_workflow(ok) == []
