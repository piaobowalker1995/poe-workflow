# -*- coding: utf-8 -*-
"""聚焦点击快速路径：结构未变不重建卡片列表（性能整改）。

背景（实测数据，offscreen）：点画布节点 → focus_step_by_id →
_rebuild_cards 全量重建的链路，N=50 约 205ms、N=100 约 427ms、
N=200 约 1050ms，其中 95% 是列表侧全量建卡（每卡约 4.8ms 的 Qt
控件构造）；画布侧 set_steps 只要 4~14ms。纯聚焦点击并不改变任何
结构，全量重建是浪费。

方案（不做大改增量更新——那是崩溃敏感区，历史三次真机崩溃都出自
重建家族）：_rebuild_cards 入口先算结构签名（递归采集 对象身份 +
id + kind），与上次全量重建后记录的签名相同 → 只定位既有卡片滚动
聚焦，不重建；签名任何差异（增/删/移/改类型/换方案对象）→ 仍走
全量重建，语义与旧版一致。

本文件锁定：
- 聚焦点击复用既有卡片（对象不变 = 未重建）；
- 嵌套子卡也能被快速路径定位；
- 结构变化 / 换方案（同 id 不同对象）/ 改类型 都必须触发全量重建；
- 快速路径的耗时显著低于全量重建（自校准比例断言，防 O(N) 回归）。
"""
import time

from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab


def _leaf(i, prim="move_to_anchor"):
    return {"id": str(i), "kind": "action", "primitive": prim,
            "params": {"anchor": "a"}, "on_error": "retry",
            "retry_count": 1, "retry_delay_ms": 500, "delay_ms": 0}


def _loop(i, body):
    return {"id": str(i), "kind": "loop", "count": 3, "body": body,
            "condition": None, "on_error": "retry", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


def _branch(i, then_steps, else_steps=None):
    return {"id": str(i), "kind": "branch",
            "condition": {"source": "clipboard", "key": "",
                          "op": "equals", "value": ""},
            "then_steps": then_steps, "else_steps": else_steps or [],
            "on_error": "retry", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


def _tab(qapp, config_manager):
    from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
    wf = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(wf)
    wf.attach_canvas_tab(cv)
    wf._on_new()
    cv.refresh_from_workflow()
    return wf, cv


def _top_card_objs(wf):
    """当前布局中的顶层卡片对象列表（身份对比用）。"""
    out = []
    for i in range(wf._cards_layout.count()):
        w = wf._cards_layout.itemAt(i).widget()
        if isinstance(w, StepCard):
            out.append(w)
    return out


def _flat_tree(n):
    return [_leaf(i) for i in range(1, n + 1)]


def _nested_tree():
    return [_leaf("1"),
            _loop("2", [_leaf("2.1"), _leaf("2.2"), _leaf("2.3")]),
            _branch("3", [_leaf("3.1")], [_leaf("3.2"), _leaf("3.3")]),
            _leaf("4")]


def test_focus_click_reuses_cards_no_rebuild(qapp, config_manager):
    """聚焦点击：结构签名未变 → 复用既有卡片，不全量重建。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = _flat_tree(60)
    wf._rebuild_cards()                 # 全量重建，记录签名
    before = _top_card_objs(wf)
    assert len(before) == 60
    sig_before = wf._cards_signature

    wf.focus_step_by_id("30")           # 点画布节点 → 走快速路径
    after = _top_card_objs(wf)
    assert after == before, "聚焦点击不应重建卡片（对象必须复用）"
    assert wf._cards_signature == sig_before

    # 再点另一个节点，依然复用
    wf.focus_step_by_id("7")
    assert _top_card_objs(wf) == before, "连续聚焦点击都应复用卡片"


def test_focus_finds_nested_card(qapp, config_manager):
    """嵌套子卡也能被快速路径定位（顶层卡 + 后代卡两级查找）。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = _nested_tree()
    wf._rebuild_cards()
    before = _top_card_objs(wf)
    nested_target = wf._steps_dicts[1]["body"][2]      # "2.3"
    card = wf._find_live_card(nested_target)
    assert card is not None and card._d is nested_target
    assert card._index_path == "2.3"

    wf.focus_step_by_id("2.3")          # 嵌套聚焦 → 快速路径
    assert _top_card_objs(wf) == before, "嵌套聚焦点击不应重建"
    card2 = wf._find_live_card(nested_target)
    assert card2 is card, "嵌套卡片对象也应复用"


def test_structural_change_forces_full_rebuild(qapp, config_manager):
    """增步骤 → 签名变 → 必须全量重建（新卡出现、旧卡对象更替）。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = _flat_tree(30)
    wf._rebuild_cards()
    before = _top_card_objs(wf)
    wf.focus_step_by_id("5")
    assert _top_card_objs(wf) == before

    new = _leaf(31)
    wf._steps_dicts.append(new)
    wf._rebuild_cards(focus_dict=new)   # 结构变化 → 全量重建
    after = _top_card_objs(wf)
    assert len(after) == 31, "新步骤未建卡"
    assert after != before, "结构变化后必须重建（旧卡对象应被更替）"


def test_reload_same_ids_different_objects_forces_rebuild(qapp, config_manager):
    """换方案但 id/kind 巧合相同 → 对象身份不同 → 必须重建（防陈旧卡片）。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = _flat_tree(10)
    wf._rebuild_cards()
    before = _top_card_objs(wf)
    wf.focus_step_by_id("3")
    assert _top_card_objs(wf) == before

    # 同一文件再加载一遍：全新 dict 对象、id/kind 完全相同
    wf._steps_dicts = _flat_tree(10)
    wf.focus_step_by_id("3")
    after = _top_card_objs(wf)
    assert after != before, "同 id 不同对象的方案切换未被识别（陈旧卡片风险）"
    assert len(after) == 10


def test_kind_change_invalidates_signature(qapp, config_manager):
    """改步骤类型（kind 变）→ 签名变 → 下次聚焦点击必须重建。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"), _leaf("2")]
    wf._rebuild_cards()
    before = _top_card_objs(wf)
    wf.focus_step_by_id("1")
    assert _top_card_objs(wf) == before

    wf._steps_dicts[1]["kind"] = "loop"     # 模拟 _on_kind 的 dict 变异
    wf._steps_dicts[1]["body"] = []
    wf.focus_step_by_id("1")
    assert _top_card_objs(wf) != before, "kind 变化未触发重建"


def test_fast_path_performance_gain(qapp, config_manager):
    """快速路径耗时须显著低于全量重建（自校准比例，防 O(N) 回归）。"""
    wf, cv = _tab(qapp, config_manager)
    n = 100
    wf._steps_dicts = _flat_tree(n)
    wf._rebuild_cards()

    # 全量重建耗时：制造一次结构变化后重建
    t0 = time.perf_counter()
    wf._steps_dicts.append(_leaf(n + 1))
    wf._rebuild_cards(focus_dict=wf._steps_dicts[-1])
    t_full = (time.perf_counter() - t0) * 1000

    # 快速路径耗时：纯聚焦点击
    t0 = time.perf_counter()
    for i in range(1, n + 1, 10):
        wf.focus_step_by_id(str(i))
    t_fast = (time.perf_counter() - t0) * 1000

    assert t_fast < t_full / 4, (
        f"快速路径 {t_fast:.1f}ms 未显著快于全量重建 {t_full:.1f}ms")


def test_fast_path_does_not_skip_renumber_or_notify(qapp, config_manager):
    """快速路径不改变既有契约：不走 notify、不碰 jump_target 数据。"""
    wf, cv = _tab(qapp, config_manager)
    jumper = _leaf("1")
    jumper["on_error"] = "jump"
    jumper["jump_target"] = "3"
    wf._steps_dicts = [jumper, _leaf("2"), _leaf("3")]
    wf._rebuild_cards()
    before_objs = _top_card_objs(wf)
    notified = []
    wf._notify_canvas_changed = lambda: notified.append(1)

    wf.focus_step_by_id("2")              # 快速路径
    assert _top_card_objs(wf) == before_objs
    assert notified == [], "快速路径不应触发画布通知"
    assert jumper["jump_target"] == "3", "快速路径不应改动数据"
