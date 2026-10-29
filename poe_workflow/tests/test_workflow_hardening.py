"""工作流引擎加固回归测试：循环超时护栏 / 嵌套深度可配置 / 组合条件 / schema_version。

对应差距分析 workflow_gap_analysis.md 缺口 ① ② ③ ④。
引擎层纯 Python 测试，无需 Qt。
"""
import time

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import workflow_from_dict, validate_workflow


class _Coord:
    def get_absolute_position(self, name):
        return (100, 100)


class _Inp:
    def click(self, x, y): pass
    def move_mouse(self, x, y): pass
    def press_key(self, k): pass
    def press_mouse(self, k): pass
    def read_clipboard(self): return ""
    def copy(self): pass


def _build_engine(**kw):
    return WorkflowEngine(_Coord(), _Inp(), **kw)


def test_loop_timeout_guard_breaks_hung_until():
    # 缺口①：until 条件永远不满足，应在 loop_timeout_ms 内被切断，不卡死
    wf = workflow_from_dict({
        "name": "t",
        "steps": [{
            "id": "L1", "kind": "loop",
            "condition": {"source": "ctx", "key": "__never", "op": "equals", "value": "x"},
            "body": [{"id": "a", "kind": "action", "primitive": "wait_ms", "params": {"ms": 10}}],
        }],
    })
    eng = _build_engine(loop_timeout_ms=200)
    eng.load_def(wf)
    t0 = time.monotonic()
    r = eng.run_sync()
    dt = time.monotonic() - t0
    assert r == "done"
    assert dt < 3


def test_loop_default_timeout_does_not_break_normal_loop():
    # 默认 10 分钟上限不影响正常短循环
    wf = workflow_from_dict({
        "name": "t2",
        "steps": [{
            "id": "L", "kind": "loop", "count": 3,
            "body": [{"id": "a", "kind": "action", "primitive": "wait_ms", "params": {"ms": 1}}],
        }],
    })
    eng = _build_engine()  # 默认 loop_timeout_ms=600000
    eng.load_def(wf)
    assert eng.run_sync() == "done"


def test_max_depth_configurable_and_message():
    # 缺口②：_max_depth 可配置；超限返回 error 且不崩溃
    wf = workflow_from_dict({
        "name": "deep",
        "steps": [{
            "id": "L0", "kind": "loop", "count": 1,
            "body": [{
                "id": "L1", "kind": "loop", "count": 1,
                "body": [{
                    "id": "L2", "kind": "loop", "count": 1,
                    "body": [{
                        "id": "L3", "kind": "loop", "count": 1,
                        "body": [{
                            "id": "L4", "kind": "loop", "count": 1,
                            "body": [{
                                "id": "L5", "kind": "loop", "count": 1,
                                "body": [{
                                    "id": "L6", "kind": "loop", "count": 1,
                                    "body": [{
                                        "id": "act", "kind": "action",
                                        "primitive": "wait_ms", "params": {"ms": 1},
                                    }],
                                }],
                            }],
                        }],
                    }],
                }],
            }],
        }],
    })
    eng = _build_engine(max_depth=3)
    eng.load_def(wf)
    # 深度 6 超过上限 3 -> error（不崩溃、不无限递归）
    assert eng.run_sync() == "error"


def test_composite_all_and():
    eng = _build_engine()
    eng._ctx = {"x": "1"}
    assert eng._eval_condition({"all": [
        {"source": "ctx", "key": "x", "op": "equals", "value": "1"},
        {"source": "ctx", "key": "x", "op": "nequals", "value": "2"},
    ]}, 0) is True
    assert eng._eval_condition({"all": [
        {"source": "ctx", "key": "x", "op": "equals", "value": "1"},
        {"source": "ctx", "key": "x", "op": "equals", "value": "2"},
    ]}, 0) is False


def test_composite_any_or():
    eng = _build_engine()
    eng._ctx = {"x": "1"}
    assert eng._eval_condition({"any": [
        {"source": "ctx", "key": "x", "op": "equals", "value": "9"},
        {"source": "ctx", "key": "x", "op": "equals", "value": "1"},
    ]}, 0) is True


def test_composite_nested():
    eng = _build_engine()
    eng._ctx = {"x": "1", "clipboard": "hello world"}
    assert eng._eval_condition({"all": [
        {"source": "ctx", "key": "x", "op": "equals", "value": "1"},
        {"any": [
            {"source": "ctx", "key": "x", "op": "nequals", "value": "2"},
            {"source": "clipboard", "op": "contains", "value": "zzz"},
        ]},
    ]}, 0) is True


def test_composite_empty_is_false():
    eng = _build_engine()
    assert eng._eval_condition({"all": []}, 0) is False
    assert eng._eval_condition({"any": []}, 0) is False


def test_composite_validation_ok_and_bad():
    good = workflow_from_dict({"name": "t", "steps": [{
        "id": "L", "kind": "loop",
        "condition": {"all": [{"source": "clipboard", "op": "contains", "value": "A"}]},
        "body": [{"id": "a", "kind": "action", "primitive": "wait_ms", "params": {"ms": 1}}],
    }]})
    assert validate_workflow(good) == []
    bad = workflow_from_dict({"name": "t", "steps": [{
        "id": "L", "kind": "loop",
        "condition": {"all": [{"op": "contains", "value": "A"}]},
        "body": [{"id": "a", "kind": "action", "primitive": "wait_ms", "params": {"ms": 1}}],
    }]})
    errs = validate_workflow(bad)
    assert errs
    assert any("source" in e for e in errs)


def test_schema_version_default_and_explicit():
    # 缺口④
    assert workflow_from_dict({"name": "t", "steps": []}).schema_version == "1.0"
    assert workflow_from_dict({"name": "t", "schema_version": "2.0", "steps": []}).schema_version == "2.0"
