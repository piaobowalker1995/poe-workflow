# -*- coding: utf-8 -*-
"""工作流画布 结构操作同步列表卡片（波1-A：A5）单元测试。

覆盖：画布侧重排 / 删除 / 模块库拖入成功后，列表侧 _rebuild_cards 必须被
调用（此前三个 handler 只重建画布，切回列表仍是旧卡片——对已脱离数据树的
僵尸卡片编辑会静默丢失），且卡片数量/顺序与数据树一致；列表刷新异常不得
冒泡穿破坏布 handler。
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）+ config_manager 夹具。
"""
import pytest

from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab
from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab


def _leaf(sid, prim="move_to_anchor", **params):
    return {"id": sid, "kind": "action", "primitive": prim,
            "params": params or {"anchor": "a"},
            "on_error": "retry", "retry_count": 1,
            "retry_delay_ms": 500, "delay_ms": 0}


def _tab(qapp, config_manager):
    """构造**双向挂接**的 列表 + 画布（与 WorkflowDialog 的装配一致）。"""
    wf = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(wf)
    wf.attach_canvas_tab(cv)
    wf._on_new()
    cv.refresh_from_workflow()
    return wf, cv


def _card_dicts(wf):
    """顶层卡片按布局顺序持有的一组 step dict（与 _steps_dicts 应逐一同一对象）。"""
    out = []
    for i in range(wf._cards_layout.count()):
        w = wf._cards_layout.itemAt(i).widget()
        if isinstance(w, StepCard):
            out.append(w._d)
    return out


def _assert_cards_match_data(wf):
    cards = _card_dicts(wf)
    assert len(cards) == len(wf._steps_dicts), \
        f"卡片数与数据树不一致：{len(cards)} vs {len(wf._steps_dicts)}"
    assert all(a is b for a, b in zip(cards, wf._steps_dicts)), \
        "卡片顺序与数据树不一致（存在僵尸卡片）"


@pytest.mark.parametrize("op", ["reorder", "delete", "drop"])
def test_canvas_structure_op_syncs_list_cards(qapp, config_manager, op,
                                              monkeypatch):
    """三个结构 handler 成功后必须刷新列表卡片，且卡片与数据树同源同序。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms"),
                       _leaf("3", "copy")]
    cv.refresh_from_workflow()
    calls = []
    orig = wf._rebuild_cards

    def _counting(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(wf, "_rebuild_cards", _counting)
    if op == "reorder":
        cv._on_canvas_reorder("3", 0)
    elif op == "delete":
        cv._on_canvas_delete("2")
    else:
        cv._on_canvas_drop({"type": "primitive", "payload": "wait_ms"}, 0)
    assert calls, f"{op} 后未同步刷新列表卡片"
    _assert_cards_match_data(wf)


def test_sync_list_failure_does_not_break_handler(qapp, config_manager,
                                                  monkeypatch):
    """列表刷新异常不应冒泡穿破坏布 handler（记日志 + 状态行报错）。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms")]
    cv.refresh_from_workflow()

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(wf, "_rebuild_cards", _boom)
    cv._on_canvas_delete("2")      # 不得抛异常
    assert "同步列表失败" in cv._status.text()
    assert len(wf._steps_dicts) == 1, "数据变更本身应已成功"


def test_handlers_without_list_tab_are_safe(qapp, config_manager):
    """未挂接列表页签时三个 handler 直接返回（不崩）。"""
    cv = WorkflowCanvasTab(config_manager)
    cv._on_canvas_reorder("1", 0)
    cv._on_canvas_delete("1")
    cv._on_canvas_drop({"type": "primitive", "payload": "log"}, 0)
