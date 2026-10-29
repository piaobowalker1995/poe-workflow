# -*- coding: utf-8 -*-
"""Phase B/C 工作流引擎单元测试（无头，免 Qt）。

覆盖 B/C 扩展能力：
- loop（count / until 条件）/ 嵌套 loop
- branch 条件分支（clipboard / ctx / counter / ctx_diff 源）
- counter 条件用于 loop 循环索引（branch 内禁止，引擎固定传 0）
- 每步错误策略 on_error：skip / retry / jump（含重试耗尽）
- abort 贯穿循环体（运行中可中断）
- 护栏：最大迭代次数、最大嵌套深度
- 校验：loop 缺 body / branch 缺 condition / 重复 id / branch 禁用 counter / ctx_diff 需双键
"""
import time

from poe_workflow.workflow_model import WorkflowDef, ActionStep, validate_workflow, workflow_from_dict
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
        self.clicks = []
        self.keys = []
        self.clipboard_text = clipboard
        self.click_failures = 0   # 前 N 次 click 抛错（用于 retry 测试）

    def click(self, x, y):
        if self.click_failures > 0:
            self.click_failures -= 1
            raise RuntimeError("simulated click failure")
        self.clicks.append((x, y))

    def press_key(self, key):
        self.keys.append(key)

    def read_clipboard(self):
        return self.clipboard_text

    def move_mouse(self, x, y):
        # 无头测试：光标移动无需真实设备，仅占位
        pass


def _make():
    coord = FakeCoord({"p": (10, 20)})
    inp = FakeInp()
    eng = WorkflowEngine(coord, inp)
    return eng, coord, inp


# ── loop：count ──────────────────────────────────────────────── #
def test_loop_count_runs_n_times():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop", count=3, body=[
            ActionStep(id="b", primitive="click_anchor", params={"anchor": "p"})
        ])
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert len(coord.calls) == 3


def test_loop_until_counter_stops_when_condition_met():
    # until counter>=3：i=0,1,2 时条件为假（执行 body），i=3 时为真（跳出）
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop",
                   condition={"source": "counter", "op": "ge", "value": "3"},
                   body=[ActionStep(id="b", primitive="click_anchor", params={"anchor": "p"})])
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert len(coord.calls) == 3


def test_validate_loop_requires_count_or_condition():
    # loop 没有 count 也没有 condition 是无终止条件的非法构造，校验应拦截
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop",
                   body=[ActionStep(id="b", primitive="wait_ms", params={"ms": 1})])
    ])
    errs = validate_workflow(wf)
    assert any("count" in e or "condition" in e for e in errs)


# ── loop：嵌套 ──────────────────────────────────────────────── #
def test_nested_loops_multiply():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="O", kind="loop", count=2, body=[
            ActionStep(id="I", kind="loop", count=3, body=[
                ActionStep(id="c", primitive="click_anchor", params={"anchor": "p"})
            ])
        ])
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert len(coord.calls) == 6


# ── branch ──────────────────────────────────────────────────── #
def test_branch_takes_then_when_clipboard_contains():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s0", primitive="read_clipboard", params={}),
        ActionStep(id="Br", kind="branch",
                   condition={"source": "clipboard", "op": "contains", "value": "ITEM"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.keys == ["a"]


def test_branch_takes_else_when_clipboard_missing():
    eng, coord, inp = _make()
    inp.clipboard_text = "NOPE"
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s0", primitive="read_clipboard", params={}),
        ActionStep(id="Br", kind="branch",
                   condition={"source": "clipboard", "op": "contains", "value": "ITEM"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.keys == ["b"]


# ── on_error 错误策略 ──────────────────────────────────────── #
def test_on_error_skip_continues_workflow():
    eng, coord, inp = _make()
    inp.click_failures = 999     # click 永远失败
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="f", primitive="click_anchor", params={"anchor": "p"}, on_error="skip"),
        ActionStep(id="g", primitive="press_key", params={"key": "x"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"      # 跳过后整体仍完成
    assert inp.keys == ["x"]


def test_on_error_retry_then_succeeds():
    eng, coord, inp = _make()
    inp.click_failures = 2     # 前两次失败，第三次成功
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="f", primitive="click_anchor", params={"anchor": "p"},
                  on_error="retry", retry_count=2, retry_delay_ms=0),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert len(inp.clicks) == 1        # 仅 1 次成功点击（共 3 次尝试，前 2 次失败）


def test_on_error_retry_exhausted_aborts():
    eng, coord, inp = _make()
    inp.click_failures = 999
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="f", primitive="click_anchor", params={"anchor": "p"},
                  on_error="retry", retry_count=1),   # 共 2 次尝试全失败
        ActionStep(id="g", primitive="press_key", params={"key": "x"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "error"     # 重试用尽 -> 停止整个 workflow
    assert inp.keys == []                # 后续步骤不执行


# ── abort 贯穿循环体 ───────────────────────────────────────── #
def test_abort_during_loop_body_stops():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop", count=100, body=[
            ActionStep(id="w", primitive="wait_ms", params={"ms": 5000})
        ])
    ])
    eng.load_def(wf)
    eng.start()
    time.sleep(0.2)
    eng.abort()
    time.sleep(0.3)
    assert eng.is_running() is False


# ── 护栏 ───────────────────────────────────────────────────── #
def test_loop_max_iterations_guard():
    eng, coord, inp = _make()
    eng._max_loop_iterations = 5
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop",
                   condition={"source": "counter", "op": "ge", "value": "999"},  # 永不真
                   body=[ActionStep(id="b", primitive="click_anchor", params={"anchor": "p"})])
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"      # 达到上限强制退出
    assert len(coord.calls) == 5


def test_max_depth_guard_triggers():
    eng, coord, inp = _make()
    eng._max_depth = 3
    # 构造 6 层嵌套 loop
    inner = [ActionStep(id="leaf", primitive="wait_ms", params={"ms": 0})]
    for d in range(6):
        inner = [ActionStep(id=f"L{d}", kind="loop", count=1, body=inner)]
    wf = WorkflowDef(name="t", steps=inner)
    eng.load_def(wf)
    assert eng.run_sync() == "error"     # 嵌套过深 -> 停止


# ── 校验 ───────────────────────────────────────────────────── #
def test_validate_loop_requires_body():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop", count=2)
    ])
    errs = validate_workflow(wf)
    assert any("body" in e for e in errs)


def test_validate_branch_requires_condition():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="Br", kind="branch",
                   then_steps=[ActionStep(id="t1", primitive="wait_ms", params={"ms": 1})])
    ])
    errs = validate_workflow(wf)
    assert any("condition" in e for e in errs)


def test_validate_duplicate_id():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="dup", primitive="wait_ms", params={"ms": 1}),
        ActionStep(id="dup", primitive="wait_ms", params={"ms": 1}),
    ])
    errs = validate_workflow(wf)
    assert any("重复" in e for e in errs)


# ── P0-1：branch 禁用 counter 源 ───────────────────────────── #
def test_validate_branch_rejects_counter_source():
    # 引擎 _run_branch 对 counter 固定传 0 —— branch 内 counter 恒为 0 静默失效；校验应拦截
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="Br", kind="branch",
                   condition={"source": "counter", "op": "ge", "value": "3"},
                   then_steps=[ActionStep(id="t1", primitive="wait_ms", params={"ms": 1})]),
    ])
    errs = validate_workflow(wf)
    assert any("counter" in e for e in errs)


def test_validate_loop_allows_counter_source():
    # 对照：loop 的 counter 源合法（用于循环索引）
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="L", kind="loop",
                   condition={"source": "counter", "op": "ge", "value": "3"},
                   body=[ActionStep(id="b", primitive="wait_ms", params={"ms": 1})]),
    ])
    errs = validate_workflow(wf)
    assert not any("counter" in e for e in errs)


# ── P1-1：ctx_diff 比较两上下文变量 ────────────────────────── #
def test_ctx_diff_compares_two_context_vars():
    # before="A" / after=""（规则未命中）→ nequals 为真 -> 走 then
    eng, coord, inp = _make()
    inp.clipboard_text = "A"
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s0", primitive="read_clipboard", params={"store_as": "before"}),
        ActionStep(id="s1", primitive="read_clipboard", params={
            "store_as": "after", "mode": "match",
            "rule": {"pattern": r"X", "kind": "text"}}),
        ActionStep(id="Br", kind="branch",
                   condition={"source": "ctx_diff", "op": "nequals",
                              "key_a": "before", "key_b": "after"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.keys == ["a"]


def test_validate_ctx_diff_requires_both_keys():
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="Br", kind="branch",
                   condition={"source": "ctx_diff", "op": "nequals", "key_a": "a"},
                   then_steps=[ActionStep(id="t1", primitive="wait_ms", params={"ms": 1})]),
    ])
    errs = validate_workflow(wf)
    assert any("key_b" in e for e in errs)


# ── P1-2：ctx 分支取值 / store_as 往返 / 网格 ctx 写入 ──────── #
def test_branch_ctx_source_uses_context_var():
    eng, coord, inp = _make()
    inp.clipboard_text = "5"
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s0", primitive="read_clipboard", params={"store_as": "x"}),
        ActionStep(id="Br", kind="branch",
                   condition={"source": "ctx", "op": "equals", "value": "5", "key": "x"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert inp.keys == ["a"]


def test_store_as_roundtrip_to_context():
    eng, coord, inp = _make()
    inp.clipboard_text = "HELLO"
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="s0", primitive="read_clipboard", params={"store_as": "mine"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("mine") == "HELLO"
    assert eng.context.get("clipboard") == "HELLO"


def test_grid_loop_writes_context_vars():
    eng, coord, inp = _make()
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="G", kind="loop", grid={
            "anchor": "p", "dx": 0, "dy": 0,
            "cols": 2, "rows": 1, "cell_dx": 10, "cell_dy": 10},
            body=[ActionStep(id="c", primitive="click_anchor", params={"anchor": "p"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    # 网格原点解析 1 次 + 每格 click_anchor 各 1 次（cols×rows=2 格）
    assert len(coord.calls) == 3
    assert eng.context.get("__grid_col") == 1   # 最后一格列号
    assert eng.context.get("__loop_index") == 1


# ── P1-5：resolve_rule 拒绝非法正则 ────────────────────────── #
def test_resolve_rule_rejects_bad_regex():
    from poe_workflow.workflow_model import resolve_rule
    assert resolve_rule({"pattern": r"([", "kind": "text"}) is None
    # 合法正则仍通过
    assert resolve_rule({"pattern": r"\d+", "kind": "number"}) is not None


# ── P1-6：默认失败策略 = 重试 ─────────────────────────────── #
def test_default_on_error_is_retry_and_recovers_once():
    # 未显式指定 on_error 的步骤，默认应为「重试」并能消化一次瞬时点击失败
    eng, coord, inp = _make()
    inp.click_failures = 1   # 第一次点击失败，第二次成功
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="f", primitive="click_anchor", params={"anchor": "p"}),
        ActionStep(id="g", primitive="press_key", params={"key": "x"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert len(inp.clicks) == 1        # 仅 1 次成功点击（首次失败被重试消化）
    assert inp.keys == ["x"]


def test_default_on_error_from_dict_is_retry_with_count():
    # 从 dict 加载、未写 on_error 的步骤，默认 retry 且 retry_count 回落为 1、间隔 500ms
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "s", "primitive": "wait_ms", "params": {"ms": 1}},
    ]})
    assert wf.steps[0].on_error == "retry"
    assert wf.steps[0].retry_count == 1
    assert wf.steps[0].retry_delay_ms == 500
