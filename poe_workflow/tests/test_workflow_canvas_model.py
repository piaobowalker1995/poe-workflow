# -*- coding: utf-8 -*-
"""CanvasModel 非 Qt 单元测试（GUI 升级 阶段1）。

不依赖 PyQt5，纯 Python 即可跑；覆盖增/删/移、校验、set_root、变更监听器、容器子区。
"""
from poe_workflow.ui.workflow_canvas_model import CanvasModel

_PRIMS = ["click_anchor", "move_to_anchor", "move_offset", "press_key",
          "read_clipboard", "copy", "wait_ms", "recall_cell", "log", "abort"]

# 与 poe_workflow.workflow_model._validate_step 的必填参数一致（保证插入即合法）
_PRIM_PARAMS = {
    "click_anchor": {"anchor": "a"},
    "move_to_anchor": {"anchor": "a"},
    "move_offset": {"anchor": "a", "dx": 0, "dy": 0},
    "press_key": {"key": "x"},
    "read_clipboard": {"mode": "read", "store_as": "clipboard"},
    "copy": {"store_as": "clipboard"},
    "wait_ms": {"ms": 100},
    "recall_cell": {},
    "log": {"message": "m"},
    "abort": {},
}

_SEQ = [0]


def _prim(p):
    _SEQ[0] += 1
    return {"id": f"s{_SEQ[0]}", "kind": "action", "primitive": p,
            "params": dict(_PRIM_PARAMS.get(p, {})), "on_error": "retry",
            "retry_count": 1, "retry_delay_ms": 500, "delay_ms": 0}


def test_insert_and_validate():
    m = CanvasModel([])
    m.insert_step(_prim("move_to_anchor"))
    assert len(m.root()) == 1
    assert m.validate() == []


def test_insert_all_ten_primitives_valid():
    m = CanvasModel([])
    for p in _PRIMS:
        m.insert_step(_prim(p))
    errs = m.validate()
    assert errs == [], errs


def test_delete():
    m = CanvasModel([])
    s = _prim("log")
    m.insert_step(s)
    assert len(m.root()) == 1
    assert m.delete_step(s) is True
    assert len(m.root()) == 0
    # 不存在的删除返回 False
    assert m.delete_step(s) is False


def test_move():
    m = CanvasModel([_prim("log"), _prim("wait_ms"), _prim("copy")])
    s = m.root()[0]
    assert m.move_step(s, new_index=2) is True
    assert m.root()[2] is s


def test_set_root_syncs_reference():
    m = CanvasModel([])
    new = [_prim("log")]
    m.set_root(new)
    assert m.root() is new
    assert m.validate() == []


def test_loop_empty_body_invalid():
    m = CanvasModel([])
    m.insert_step({"id": "", "kind": "loop", "count": 3, "body": [],
                   "on_error": "retry", "retry_count": 0,
                   "retry_delay_ms": 0, "delay_ms": 0})
    errs = m.validate()
    assert any("loop" in e for e in errs), errs


def test_subworkflow_jump_target_valid():
    m = CanvasModel([])
    m.insert_step({"id": "", "kind": "action", "primitive": "log",
                   "params": {"message": "x"}, "on_error": "jump",
                   "jump_target": "my_module", "retry_count": 0,
                   "retry_delay_ms": 0, "delay_ms": 0})
    assert m.validate() == [], m.validate()


def test_change_listener_fires():
    fired = []
    m = CanvasModel([], on_change=lambda: fired.append(1))
    m.insert_step(_prim("log"))
    m.delete_step(m.root()[0])
    assert fired == [1, 1]


def test_children_regions():
    loop = {"id": "", "kind": "loop", "count": 2, "body": [_prim("log")],
            "on_error": "retry", "retry_count": 0, "retry_delay_ms": 0, "delay_ms": 0}
    m = CanvasModel([loop])
    regs = m.children_regions(loop)
    assert regs[0][0] == "body"
    # 非容器返回空
    assert m.children_regions(_prim("log")) == []
