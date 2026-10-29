# -*- coding: utf-8 -*-
"""id 单一事实源：assign_step_ids（modules/workflow_model.py）。

背景：步骤 id 的编号规则曾经有两份形状不同的拷贝——列表侧 StepCard 构造
（index_path 由 _rebuild_cards / _build_child_area 各自拼算）与画布侧
WorkflowCanvasTab._assign_ids 递归静态方法。P4-B 虽把两侧规则对齐（分支
then/else 跨区连续编号），但规则本身仍是双拷贝：漏改一处即静默漂移，且
画布重建后执行会覆盖 dict 里的 id，卡片标题却用列表侧旧值——两边不一致
且无任何报报。本文件锁定收敛后的单一事实源：

- assign_step_ids 编号规则（顶层 / 子级 / 嵌套 / 分支连续 / loop body）；
- 幂等；返回值只收录「同一对象 id 真变化」项（喂给 remap_jump_targets）；
- 非 dict 条目防御跳过（旧实现裸下标赋值会在 UI 槽里抛 TypeError →
  qFatal 闪退家族）；
- 反漂移锁定：同一棵树分别走列表侧与画布侧两条路径，id 结果必须一致，
  且每张卡片标题等于实际 id；
- jump_target 同步改写（A2 链路保持），且 remap 先于建卡——跳转目标
  编辑器立即显示新值（旧顺序「先建卡改 id → 后 remap」有展示滞后）。
"""
import copy

import pytest

from poe_workflow.workflow_model import (
    assign_step_ids, collect_step_ids, remap_jump_targets,
    validate_workflow, workflow_from_dict,
)


def _leaf(sid, prim="move_to_anchor", **params):
    return {"id": sid, "kind": "action", "primitive": prim,
            "params": params or {"anchor": "a"},
            "on_error": "retry", "retry_count": 1,
            "retry_delay_ms": 500, "delay_ms": 0}


def _loop(sid, body):
    return {"id": sid, "kind": "loop", "count": 3, "body": body,
            "condition": None, "on_error": "retry", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


def _branch(sid, then_steps, else_steps=None):
    return {"id": sid, "kind": "branch",
            "condition": {"source": "clipboard", "key": "",
                          "op": "equals", "value": ""},
            "then_steps": then_steps, "else_steps": else_steps or [],
            "on_error": "retry", "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


def _deep_tree():
    """顶层3 + loop 内含 branch，branch then 2 步 / else 含嵌套 loop。"""
    inner = _loop("i", [_leaf("a"), _leaf("b")])
    br = _branch("br", [_leaf("t1"), _leaf("t2")], [_leaf("e1"), inner])
    return [_leaf("x"), _loop("o", [_leaf("c"), br]), _leaf("y")]


# ── 单元：编号规则 ──────────────────────────────────────────────────────────

def test_numbering_top_and_children():
    tree = [_leaf("x1"), _loop("x2", [_leaf("y1"), _leaf("y2")]), _leaf("x3")]
    remap = assign_step_ids(tree)
    assert [d["id"] for d in tree] == ["1", "2", "3"]
    assert [d["id"] for d in tree[1]["body"]] == ["2.1", "2.2"]
    # 返回值收录全部「同对象 id 真变化」项（旧值 → 新值）
    assert remap == {"x1": "1", "x2": "2", "x3": "3",
                     "y1": "2.1", "y2": "2.2"}


def test_branch_regions_continuous():
    """then 从 1 起、else 接 then 数量之后——防跨区 id 撞名（P4-B 规则）。"""
    br = _branch("b", [_leaf("t1"), _leaf("t2")], [_leaf("e1"), _leaf("e2")])
    assign_step_ids([br])
    assert [d["id"] for d in br["then_steps"]] == ["1.1", "1.2"]
    assert [d["id"] for d in br["else_steps"]] == ["1.3", "1.4"]


def test_nested_containers():
    inner = _loop("i", [_leaf("a"), _leaf("b")])
    br = _branch("b", [inner])
    assign_step_ids([_leaf("t"), br])
    assert inner["id"] == "2.1"
    assert [d["id"] for d in inner["body"]] == ["2.1.1", "2.1.2"]


def test_loop_body_starts_at_one():
    lp = _loop("l", [_leaf("a"), _leaf("b"), _leaf("c")])
    assign_step_ids([lp])
    assert [d["id"] for d in lp["body"]] == ["1.1", "1.2", "1.3"]


def test_idempotent_second_run_empty_remap():
    tree = _deep_tree()
    assign_step_ids(tree)
    before = sorted(collect_step_ids(tree))
    remap2 = assign_step_ids(tree)
    assert remap2 == {}, "幂等：第二次调用不应有任何 id 变化"
    assert sorted(collect_step_ids(tree)) == before


def test_remap_only_changed_entries():
    """两步互换：两个对象 id 都变 → 两条映射；按对象身份匹配不按值。"""
    a, b = _leaf("a"), _leaf("b")
    assign_step_ids([a, b])
    remap = assign_step_ids([b, a])
    assert remap == {"1": "2", "2": "1"}


def test_unchanged_and_idless_new_steps_not_in_remap():
    """id 未变的对象与无旧 id 的新步都不进 remap（零改写）。"""
    a = _leaf("a")
    assign_step_ids([a])              # a → "1"
    new = _leaf("")                   # 新步无历史 id（占位空串）
    remap = assign_step_ids([a, new])
    assert remap == {}, "无 id 变化时 remap 必须为空"
    assert [d["id"] for d in (a, new)] == ["1", "2"]


def test_new_step_with_stale_id_gets_remapped():
    """带手写旧 id 的新步也进 remap——指向它的 jump_target 才能被救活。"""
    a = _leaf("a")
    assign_step_ids([a])
    remap = assign_step_ids([a, _leaf("new")])
    assert remap == {"new": "2"}


def test_non_dict_entries_skipped():
    """非 dict 条目跳过不抛（旧实现裸下标赋值 → 槽内 TypeError → 闪退）。"""
    tree = [_leaf("a"), "not-a-dict", None, _leaf("b")]
    remap = assign_step_ids(tree)
    assert [d["id"] for d in tree if isinstance(d, dict)] == ["1", "4"]
    assert remap == {"a": "1", "b": "4"}


def test_empty_and_none_input():
    assert assign_step_ids([]) == {}
    assert assign_step_ids(None) == {}


def test_jump_target_remap_and_scheme_name_untouched():
    """跳转目标按映射改写；模块方案名（非步骤 id）原样保留。"""
    jumper = _leaf("j")
    jumper["on_error"] = "jump"
    jumper["jump_target"] = "t"
    scheme_jumper = _leaf("s")
    scheme_jumper["on_error"] = "jump"
    scheme_jumper["jump_target"] = "preset_mapmaker_full"
    tree = [jumper, scheme_jumper, _leaf("t")]
    remap = assign_step_ids(tree)
    remap_jump_targets(tree, remap)
    assert jumper["jump_target"] == "3"
    assert scheme_jumper["jump_target"] == "preset_mapmaker_full"


# ── 集成：列表侧 vs 画布侧反漂移 ────────────────────────────────────────────

def _tab(qapp, config_manager):
    """构造**双向挂接**的 列表 + 画布（与 WorkflowDialog 装配一致）。"""
    from poe_workflow.ui.tab_workflow import WorkflowTab
    from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
    wf = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(wf)
    wf.attach_canvas_tab(cv)
    wf._on_new()
    cv.refresh_from_workflow()
    return wf, cv


_EXPECTED_DEEP_IDS = [
    "1", "2", "2.1", "2.2", "2.2.1", "2.2.2",
    "2.2.3", "2.2.4", "2.2.4.1", "2.2.4.2", "3",
]


def test_two_paths_agree_on_deep_tree(qapp, config_manager):
    """反漂移锁定：同一棵树走列表侧与画布侧，id 结果必须一致。"""
    wf1, _cv1 = _tab(qapp, config_manager)
    wf1._steps_dicts = _deep_tree()
    wf1._rebuild_cards()          # 列表侧：assign_step_ids + remap + 建卡
    ids_list = sorted(collect_step_ids(wf1._steps_dicts))

    wf2, cv2 = _tab(qapp, config_manager)
    wf2._steps_dicts = _deep_tree()
    cv2.refresh_from_workflow()   # 画布侧：_rebuild → assign_step_ids
    ids_canvas = sorted(collect_step_ids(wf2._steps_dicts))

    assert ids_list == _EXPECTED_DEEP_IDS, f"列表侧编号错误：{ids_list}"
    assert ids_canvas == _EXPECTED_DEEP_IDS, f"画布侧编号错误：{ids_canvas}"
    assert ids_list == ids_canvas, "两侧编号规则漂移"
    # 两条路径的产物都必须通过模型校验（重复 id 会被拒收）
    for wf in (wf1, wf2):
        assert validate_workflow(workflow_from_dict(
            {"steps": wf._steps_dicts})) == [], "编号后方案校验失败"


def test_card_titles_match_assigned_ids(qapp, config_manager):
    """每张卡片标题（index_path）必须等于实际 id——漂移时这里会不一致。"""
    from poe_workflow.ui.tab_workflow import StepCard
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = _deep_tree()
    wf._rebuild_cards()
    # 泵事件让 _clear_layout 的 deleteLater 生效，剔除陈旧卡片后再断言
    qapp.processEvents()
    cards = wf.findChildren(StepCard)
    assert cards, "未找到任何步骤卡片"
    for c in cards:
        assert c._index_path == c._d.get("id"), (
            f"标题 {c._index_path!r} 与实际 id {c._d.get('id')!r} 不一致")


def test_jump_target_editor_shows_remapped_value(qapp, config_manager):
    """remap 先于建卡：重编号后跳转目标编辑器立即显示新值。

    旧顺序「先建卡（构造即改 id）→ 后 remap」会让本次构建的编辑器显示
    旧目标值，要等下一次重建才刷新。
    """
    from PyQt5.QtWidgets import QComboBox
    from poe_workflow.ui.tab_workflow import StepCard
    wf, cv = _tab(qapp, config_manager)
    target = _leaf("t")
    jumper = _leaf("j")
    jumper["on_error"] = "jump"
    jumper["jump_target"] = "t"
    wf._steps_dicts = [jumper, target]
    wf._rebuild_cards()
    # 最前面插入新步 → 原 t(2)→3；jumper.jump_target 应同步为 "3"
    wf._steps_dicts.insert(0, _leaf("new"))
    wf._rebuild_cards()
    assert jumper["jump_target"] == "3"
    # 从当前布局取卡片：_clear_layout 用 deleteLater 延迟销毁旧卡，不泵事件
    # 时 findChildren 会连陈旧卡片一起捞到（offscreen 已知陷阱），会误取
    # 上一次重建构建的旧编辑器。
    cards = [wf._cards_layout.itemAt(i).widget()
             for i in range(wf._cards_layout.count())]
    card = next(c for c in cards if c is not None and c._d is jumper)
    combos = [cb for cb in card.findChildren(QComboBox)
              if any(cb.itemText(i).startswith("步骤: ")
                     for i in range(cb.count()))]
    assert len(combos) == 1, "未定位到跳转目标编辑器"
    assert combos[0].currentData() == "3", "编辑器仍显示旧值（remap 应先于建卡）"


def test_canvas_structural_op_renumbers_via_shared_fn(qapp, config_manager):
    """画布侧结构操作（拖入容器）后的编号仍走同一函数，结果不变。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1"), _leaf("2.2")]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "log"}, "2", "body", 1)
    body = wf._steps_dicts[1]["body"]
    assert [d["id"] for d in body] == ["2.1", "2.2", "2.3"]
    assert sorted(collect_step_ids(wf._steps_dicts)) == [
        "1", "2", "2.1", "2.2", "2.3", "3"]
