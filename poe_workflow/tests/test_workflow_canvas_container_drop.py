# -*- coding: utf-8 -*-
"""工作流画布 P4-B：模块库拖入容器子区（loop body / branch then|else）。

覆盖：
- 落点换算：loop body 区内索引、空 loop body、branch then/else 区索引、
  两区皆空时名义命中区互不重叠、嵌套容器取最内层
- 顶层路径不回退：容器外落点仍走 paletteDropRequested（索引口径不变）
- handler：新步骤落入容器子列表指定位置、空 else 区自动建表、
  id 重编号与列表卡片同步、未知区/容器缺失/未挂列表的安全处理
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）+ config_manager 夹具。
"""
import pytest

from poe_workflow.ui.tab_workflow import WorkflowTab
from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab, _find_step_by_id
from poe_workflow.ui.workflow_canvas import (
    BRANCH_GAP, CONTAINER_HEADER, CONTAINER_PAD, NODE_H, NODE_W,
    ContainerNode, WorkflowCanvasView,
)
from poe_workflow.ui.workflow_palette import PaletteItemButton
from poe_workflow.workflow_model import validate_workflow, workflow_from_dict


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


def _drop(v, x, y):
    """在**场景坐标** (x, y) 处合成一次模块库拖放（wait_ms）。

    视图未 show 时 mapToScene 非恒等（居中对齐 + 小视口），故用
    mapFromScene 把场景坐标换算成事件坐标，保证与生产路径一致。
    """
    from PyQt5.QtCore import QMimeData, QPointF, Qt
    from PyQt5.QtGui import QDropEvent
    mime = QMimeData()
    mime.setData(PaletteItemButton.MIME_TYPE,
                 b'{"type": "primitive", "payload": "wait_ms"}')
    pos = v.mapFromScene(QPointF(x, y))
    ev = QDropEvent(pos, Qt.CopyAction, mime,
                    Qt.LeftButton, Qt.NoModifier)
    v.dropEvent(ev)


def _view(qapp, steps):
    v = WorkflowCanvasView()
    v.resize(1200, 800)
    v.set_steps(steps)
    v.set_editable(True)
    return v


def _inner_y(container_node):
    """容器子区起始 y（场景坐标）= 框顶 + 标题栏 + 内边距。"""
    return container_node.pos().y() + CONTAINER_HEADER + CONTAINER_PAD


# ── 视图层：落点 → 容器信号 ──────────────────────────────────────────────────

def test_signal_declared(qapp):
    from PyQt5.QtCore import pyqtBoundSignal
    v = WorkflowCanvasView()
    assert isinstance(v.paletteDropInContainer, pyqtBoundSignal)


def test_drop_between_body_children_hits_loop(qapp):
    """loop body 的两个孩子之间落点 → ("2", "body", 1)。"""
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1"), _leaf("2.2")]),
                     _leaf("3")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    v.paletteDropRequested.connect(lambda d, i: got.append(("TOP", "", i)))
    c1, c2 = v._node_by_id["2.1"], v._node_by_id["2.2"]
    x = (c1.pos().x() + NODE_W + c2.pos().x()) / 2.0
    y = _inner_y(v._node_by_id["2"]) + NODE_H / 2.0
    _drop(v, x, y)
    assert got == [("2", "body", 1)], f"落点换算错误：{got}"


def test_drop_into_empty_loop_body(qapp):
    """空 loop body 名义命中区可落 → ("2", "body", 0)。"""
    v = _view(qapp, [_leaf("1"), _loop("2", []), _leaf("3")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    loop = v._node_by_id["2"]
    hit = loop._region_hit["body"]
    _drop(v, (hit[0] + hit[2]) / 2.0, (hit[1] + hit[3]) / 2.0)
    assert got == [("2", "body", 0)], f"空循环体落点错误：{got}"


def test_drop_into_branch_then_and_else(qapp):
    """branch：then 区按孩子算索引；then 非空、else 空时 else 名义区可落。"""
    v = _view(qapp, [_leaf("1"),
                     _branch("2", [_leaf("2.1")]),
                     _leaf("3")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    br = v._node_by_id["2"]
    iy = _inner_y(br)
    then_hit = br._region_hit["then_steps"]
    # then 区（一个孩子）→ 索引 1（落在唯一孩子右缘之内、其左缘之右）
    _drop(v, then_hit[2] - 10.0, (then_hit[1] + then_hit[3]) / 2.0)
    # else 名义区：then 高 NODE_H + BRANCH_GAP 之后
    _drop(v, br.pos().x() + CONTAINER_PAD + 10.0,
          iy + NODE_H + BRANCH_GAP + NODE_H / 2.0)
    assert got == [("2", "then_steps", 1), ("2", "else_steps", 0)], \
        f"分支落点换算错误：{got}"


def test_drop_into_empty_branch_regions_disjoint(qapp):
    """两区皆空：then/else 名义命中区互不重叠，各自可落。"""
    v = _view(qapp, [_leaf("1"), _branch("2", []), _leaf("3")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    br = v._node_by_id["2"]
    iy = _inner_y(br)
    hits = br._region_hit
    assert hits["then_steps"][3] <= hits["else_steps"][1], \
        f"then/else 命中区重叠：{hits}"
    _drop(v, (hits["then_steps"][0] + hits["then_steps"][2]) / 2.0,
          (hits["then_steps"][1] + hits["then_steps"][3]) / 2.0)
    _drop(v, (hits["else_steps"][0] + hits["else_steps"][2]) / 2.0,
          (hits["else_steps"][1] + hits["else_steps"][3]) / 2.0)
    assert got == [("2", "then_steps", 0), ("2", "else_steps", 0)], \
        f"空分支落点换算错误：{got}"


def test_drop_into_nested_container_picks_innermost(qapp):
    """嵌套容器：内层 loop body 内的落点 → 最内层容器（面积最小）。"""
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("3", [_leaf("3.1")])]),
                     _leaf("4")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    inner = v._node_by_id["3"]
    assert isinstance(inner, ContainerNode)
    hit = inner._region_hit["body"]
    _drop(v, (hit[0] + hit[2]) / 2.0, (hit[1] + hit[3]) / 2.0)
    # 区中心落在唯一孩子（占据区左半）右侧 → 索引 1（与顶层口径一致：
    # 落在谁左边插到谁前面）
    assert got == [("3", "body", 1)], f"嵌套容器未取最内层：{got}"


def test_drop_into_outer_container_region_not_inner(qapp):
    """外层 loop body 区内、内层容器子区外的落点 → 外层容器。

    取外层区底部（内层子区高度只到框体中上部），x 取区中心。
    """
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("3", [_leaf("3.1")])]),
                     _leaf("4")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    outer = v._node_by_id["2"]
    hit = outer._region_hit["body"]
    inner_hit = v._node_by_id["3"]._region_hit["body"]
    assert hit[3] > inner_hit[3], "外层区应比内层子区高（下方有余量）"
    _drop(v, (hit[0] + hit[2]) / 2.0, hit[3] - 5.0)
    assert got == [("2", "body", 1)], f"外层容器落点换算错误：{got}"


def test_drop_outside_containers_keeps_top_level_signal(qapp):
    """容器外落点：仍走顶层 paletteDropRequested，不发容器信号。"""
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1")]),
                     _leaf("3")])
    top, got = [], []
    v.paletteDropRequested.connect(lambda d, i: top.append(i))
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    # leaf1 与 loop 之间的缝隙（x 在 loop 区左边缘之左）
    x = (v._node_by_id["1"].pos().x() + NODE_W
         + v._node_by_id["2"].pos().x()) / 2.0
    _drop(v, x, 100.0)
    assert got == [], f"容器外落点误发容器信号：{got}"
    assert top == [1], f"顶层索引错误：{top}"


# ── handler 层：真实数据落位 ─────────────────────────────────────────────────

def _tab(qapp, config_manager):
    """构造**双向挂接**的 列表 + 画布（与 WorkflowDialog 装配一致）。"""
    wf = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(wf)
    wf.attach_canvas_tab(cv)
    wf._on_new()
    cv.refresh_from_workflow()
    return wf, cv


def test_handler_inserts_into_loop_body_at_index(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1"), _leaf("2.2")]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "log"}, "2", "body", 1)
    body = wf._steps_dicts[1]["body"]
    assert len(body) == 3, f"loop body 未插入：{len(body)}"
    assert body[1].get("primitive") == "log", "未落到指定索引"
    # id 按层级位置重编号（A2 链路）
    assert [d["id"] for d in body] == ["2.1", "2.2", "2.3"]
    assert validate_workflow(workflow_from_dict(
        {"steps": wf._steps_dicts})) == [], "插入后方案校验失败"
    # 画布节点数同步（顶层 3 + body 3）
    assert cv._canvas.node_count() == 6


def test_handler_inserts_into_empty_branch_else(qapp, config_manager):
    """else 区为空（键不存在）→ 自动建表并插入，id 连续。"""
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1")])
    del br["else_steps"]
    wf._steps_dicts = [_leaf("1"), br, _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "wait_ms"}, "2", "else_steps", 0)
    assert wf._steps_dicts[1]["else_steps"], "空 else 区未建表"
    assert len(wf._steps_dicts[1]["else_steps"]) == 1
    # 分支两区子步 id 连续编号（then 从 1、else 接其后）——修「分区各自
    # 从 1 起」的跨区撞名（撞名时 validate 拒收、画布 else 子步无法寻址）
    then_ids = [d["id"] for d in wf._steps_dicts[1]["then_steps"]]
    else_ids = [d["id"] for d in wf._steps_dicts[1]["else_steps"]]
    assert then_ids == ["2.1"] and else_ids == ["2.2"]
    assert validate_workflow(workflow_from_dict(
        {"steps": wf._steps_dicts})) == []


def test_handler_syncs_list_cards(qapp, config_manager, monkeypatch):
    """容器插入后必须同步刷新列表卡片（与顶层拖入同一契约）。"""
    from poe_workflow.ui.tab_workflow import StepCard
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1")]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    calls = []
    orig = wf._rebuild_cards

    def _counting(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(wf, "_rebuild_cards", _counting)
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "log"}, "2", "body", 0)
    assert calls, "容器插入后未同步刷新列表卡片"
    cards = []
    for i in range(wf._cards_layout.count()):
        w = wf._cards_layout.itemAt(i).widget()
        if isinstance(w, StepCard):
            cards.append(w)
    assert len(cards) == len(wf._steps_dicts), "卡片数与数据树不一致"


def test_handler_rejects_unknown_region(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"), _loop("2", [_leaf("2.1")])]
    cv.refresh_from_workflow()
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "log"}, "2", "body_x", 0)
    assert "未知容器子区" in cv._status.text()
    assert len(wf._steps_dicts[1]["body"]) == 1, "非法区不得改数据"


def test_handler_missing_container_is_safe(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1")]
    cv.refresh_from_workflow()
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "log"}, "99", "body", 0)
    assert "未找到容器" in cv._status.text()
    assert len(wf._steps_dicts) == 1, "容器缺失不得改数据"


def test_handler_without_list_tab_is_safe(qapp, config_manager):
    cv = WorkflowCanvasTab(config_manager)
    cv._on_canvas_drop_in_container(
        {"type": "primitive", "payload": "log"}, "1", "body", 0)  # 不崩


def test_find_step_by_id_recurses(qapp):
    tree = [_leaf("1"), _loop("2", [_leaf("2.1"),
                                    _branch("2.2", [_leaf("2.2.1")])])]
    assert _find_step_by_id(tree, "2.2.1") is tree[1]["body"][1]["then_steps"][0]
    assert _find_step_by_id(tree, "2") is tree[1]
    assert _find_step_by_id(tree, "nope") is None


# ── 缺容器键的形状（手写 json）不得闪退 ───────────────────────────────────────

def test_step_card_branch_missing_else_key_builds(qapp, config_manager):
    """缺 else_steps 键的 branch 建卡片不得抛 KeyError（槽异常→qFatal 闪退）。"""
    from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab
    tab = WorkflowTab(config_manager)
    d = _branch("1", [_leaf("1.1")])
    del d["else_steps"]
    card = StepCard(d, [d], tab, "1")          # 不得抛
    assert d["else_steps"] == [], "建卡片应补齐 else_steps 键"


def test_step_card_loop_missing_body_key_builds(qapp, config_manager):
    """缺 body 键的 loop 建卡片不得抛 KeyError。"""
    from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab
    tab = WorkflowTab(config_manager)
    d = _loop("1", [])
    del d["body"]
    card = StepCard(d, [d], tab, "1")          # 不得抛
    assert d["body"] == [], "建卡片应补齐 body 键"


def test_normalize_loaded_step_fills_container_keys():
    """加载边界：branch/loop 缺子列表键时补齐（递归嵌套同样覆盖）。"""
    from poe_workflow.ui.tab_workflow import _normalize_loaded_step
    br = {"kind": "branch", "then_steps": [{"kind": "loop"}]}
    _normalize_loaded_step(br)
    assert br["else_steps"] == []
    assert br["then_steps"][0]["body"] == []


def test_branch_children_ids_sequential_across_regions(qapp, config_manager):
    """分支 then/else 两区子步 id 连续不撞名（画布侧 + 列表侧双查）。

    旧实现两区各自从 1 起 → else 子步与 then 子步 id 撞名：
    validate_workflow 拒收「重复 step id」（方案永远无法运行），且画布
    _node_by_id 按 setdefault 注册，撞名的 else 子步无法被选中/删除。
    """
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1"), _leaf("2.2")], [_leaf("2.3")])
    wf._steps_dicts = [_leaf("1"), br, _leaf("3")]
    cv.refresh_from_workflow()
    # 画布侧重编号（assign_step_ids 单一事实源）
    assert [d["id"] for d in br["then_steps"]] == ["2.1", "2.2"]
    assert [d["id"] for d in br["else_steps"]] == ["2.3"]
    # 列表侧重编号（同一 assign_step_ids，经 _rebuild_cards）
    wf._rebuild_cards()
    assert [d["id"] for d in br["then_steps"]] == ["2.1", "2.2"]
    assert [d["id"] for d in br["else_steps"]] == ["2.3"]
    # 全树 id 唯一 → 校验通过（旧实现此处报「重复 step id: 2.1」）
    assert validate_workflow(workflow_from_dict(
        {"steps": wf._steps_dicts})) == []
    # else 子步在画布可寻址（旧实现撞名 → setdefault 丢注册）
    assert "2.3" in cv._canvas._node_by_id


# ── 增量2：子区内拖动改序 ───────────────────────────────────────────────────

def test_drag_body_child_left_emits_region_reorder(qapp):
    """loop body [2.1,2.2,2.3]，拖 2.3 落到首个子节点左侧 → ("2.3","2","body",0)。

    落点 (256, 96) 在 body 命中区内（组框 [254,906] 横向全覆盖，见
    _layout_container 口径）且位于首子节点 2.1 左缘（272）之左 → 索引 0。
    """
    from test_workflow_canvas_edit import (
        _press_node, _drag_to_scene)
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1"), _leaf("2.2"), _leaf("2.3")]),
                     _leaf("4")])
    got = []
    v.stepReorderInRegionRequested.connect(
        lambda sid, c, r, i: got.append((sid, c, r, i)))
    v.stepReorderRequested.connect(
        lambda sid, i: got.append(("TOP", sid, "", i)))
    child = v._node_by_id["2.3"]
    vp = _press_node(v, child)
    _drag_to_scene(v, vp, 256, 96)
    assert got == [("2.3", "2", "body", 0)], f"子区改序换算错误：{got}"


def test_drag_body_child_right_emits_end_index(qapp):
    """拖 2.1 到 2.3 右侧 → 索引 2（= 区尾，remove 后 insert 口径）。"""
    from test_workflow_canvas_edit import (
        _press_node, _drag_to_scene)
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1"), _leaf("2.2"), _leaf("2.3")]),
                     _leaf("4")])
    got = []
    v.stepReorderInRegionRequested.connect(
        lambda sid, c, r, i: got.append((sid, c, r, i)))
    child = v._node_by_id["2.1"]
    vp = _press_node(v, child)
    # 落点 (800, 96)：body 区内、末子节点 2.3 左缘(720)之右 → 索引 2
    _drag_to_scene(v, vp, 800, 96)
    assert got == [("2.1", "2", "body", 2)], f"子区改序换算错误：{got}"


def test_drag_else_child_index_counts_only_else_siblings(qapp):
    """拖 else 子步到区中：索引只数 **else 区**兄弟（then 区不掺入）。

    then=[2.1]、else=[2.2,2.3] 且两区 x 范围重叠——若不过滤 region_key，
    then 子步会混进兄弟集把索引从 1 抬成 2。落点 (400, 192) 在 else 命中
    区内、2.2 左缘(272)之右 → 索引 1。
    """
    from test_workflow_canvas_edit import (
        _press_node, _drag_to_scene)
    v = _view(qapp, [_leaf("1"),
                     _branch("2", [_leaf("2.1")],
                             [_leaf("2.2"), _leaf("2.3")]),
                     _leaf("4")])
    got = []
    v.stepReorderInRegionRequested.connect(
        lambda sid, c, r, i: got.append((sid, c, r, i)))
    child = v._node_by_id["2.3"]
    vp = _press_node(v, child)
    _drag_to_scene(v, vp, 400, 192)
    assert got == [("2.3", "2", "else_steps", 1)], \
        f"else 区索引混入了 then 区兄弟：{got}"


def test_drag_nested_container_reorders_in_outer_region(qapp):
    """嵌套容器自身也是子区兄弟：拖内层 loop 到右侧 → 外层 body 索引 1。

    注意用位置 id（"2.1"）：生产数据经 assign_step_ids/StepCard 重编号后嵌套
    必带点，"." 启发式是 A4 既定契约（_drop_index_for 同款）。落点 (496, 96)
    在外层 body 区内、2.2 左缘(532)之左 → 索引 1。
    """
    from test_workflow_canvas_edit import (
        _press_at_scene, _drag_to_scene)
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("2.1", [_leaf("2.1.1")]),
                                _leaf("2.2")]),
                     _leaf("4")])
    got = []
    v.stepReorderInRegionRequested.connect(
        lambda sid, c, r, i: got.append((sid, c, r, i)))
    inner = v._node_by_id["2.1"]
    # 按标题栏派发按下（中心点会落在子节点 "2.1.1" 上）
    vp = _press_at_scene(v, inner.pos().x() + 20.0, inner.pos().y() + 13.0)
    assert v._drag_node is inner, "应按标题栏命中内层容器本身"
    # 落点 (592, 96)：外层 body 区内、2.2 左缘(532)之右 → 区内索引 1
    _drag_to_scene(v, vp, 592, 96)
    assert got == [("2.1", "2", "body", 1)], f"嵌套容器改序错误：{got}"


def test_region_index_for_missing_tag_returns_none(qapp):
    """子节点缺 _parent_id/_region_key（异常路径）→ 返回 None，调用方放弃。"""
    v = _view(qapp, [_leaf("1"), _loop("2", [_leaf("2.1")])])
    node = v._node_by_id["2.1"]
    node._parent_id = ""
    assert v._region_index_for(node, node.pos().x() + 50.0) is None


def test_drag_nested_without_tag_emits_nothing(qapp):
    """标签缺失时拖嵌套子节点：两个重排信号都不发（不瞎改数据）。"""
    from test_workflow_canvas_edit import (
        _press_node, _move_held_at, _release_at)
    v = _view(qapp, [_leaf("1"), _loop("2", [_leaf("2.1"), _leaf("2.2")])])
    v.set_editable(True)
    top, region = [], []
    v.stepReorderRequested.connect(lambda sid, i: top.append((sid, i)))
    v.stepReorderInRegionRequested.connect(
        lambda *a: region.append(a))
    child = v._node_by_id["2.1"]
    child._parent_id = ""
    vp = _press_node(v, child)
    _move_held_at(v, vp, dx=100)
    _release_at(v, vp)
    assert top == [] and region == [], f"异常路径不应发射：{top} {region}"


def test_handler_reorders_within_loop_body(qapp, config_manager):
    """handler：loop body 内把 2.3 移到首位，顺序/编号/校验全对。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1", "log"),
                                   _leaf("2.2", "wait_ms", ms=50),
                                   _leaf("2.3", "copy")]),
                       _leaf("4")]
    cv.refresh_from_workflow()
    cv._on_canvas_reorder_in_region("2.3", "2", "body", 0)
    body = wf._steps_dicts[1]["body"]
    assert [d["primitive"] for d in body] == ["copy", "log", "wait_ms"], \
        "未按指定索引落位"
    assert [d["id"] for d in body] == ["2.1", "2.2", "2.3"], "id 未重编号"
    assert validate_workflow(workflow_from_dict(
        {"steps": wf._steps_dicts})) == []
    assert cv._canvas.node_count() == 6


def test_handler_reorders_within_branch_else(qapp, config_manager):
    """handler：else 区内把 2.3 移到首位；then 区不动；编号连续。"""
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1", "log")],
                 [_leaf("2.2", "wait_ms", ms=50), _leaf("2.3", "copy")])
    wf._steps_dicts = [_leaf("1"), br, _leaf("4")]
    cv.refresh_from_workflow()
    cv._on_canvas_reorder_in_region("2.3", "2", "else_steps", 0)
    assert [d["primitive"] for d in br["else_steps"]] == ["copy", "wait_ms"]
    assert [d["primitive"] for d in br["then_steps"]] == ["log"], \
        "then 区不应被牵连"
    assert [d["id"] for d in br["then_steps"]] == ["2.1"]
    assert [d["id"] for d in br["else_steps"]] == ["2.2", "2.3"]
    assert validate_workflow(workflow_from_dict(
        {"steps": wf._steps_dicts})) == []


def test_handler_region_reorder_rejects_unknown_region(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"), _loop("2", [_leaf("2.1")])]
    cv.refresh_from_workflow()
    cv._on_canvas_reorder_in_region("2.1", "2", "body_x", 0)
    assert "未知容器子区" in cv._status.text()
    assert len(wf._steps_dicts[1]["body"]) == 1, "非法区不得改数据"


def test_handler_region_reorder_missing_container(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1")]
    cv.refresh_from_workflow()
    cv._on_canvas_reorder_in_region("2.1", "99", "body", 0)
    assert "未找到容器" in cv._status.text()
    assert len(wf._steps_dicts) == 1, "容器缺失不得改数据"


def test_handler_region_reorder_step_not_in_region(qapp, config_manager):
    """声称在 else 的步骤实际在 then → 报错且数据不动（防信号/数据不一致）。"""
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1", "log")], [_leaf("2.2", "wait_ms", ms=50)])
    wf._steps_dicts = [_leaf("1"), br]
    cv.refresh_from_workflow()
    cv._on_canvas_reorder_in_region("2.1", "2", "else_steps", 0)
    assert "未在" in cv._status.text()
    assert [d["primitive"] for d in br["then_steps"]] == ["log"]
    assert [d["primitive"] for d in br["else_steps"]] == ["wait_ms"], \
        "不一致信号不得改数据"


def test_handler_region_reorder_without_list_tab_is_safe(qapp, config_manager):
    cv = WorkflowCanvasTab(config_manager)
    cv._on_canvas_reorder_in_region("2.1", "2", "body", 0)   # 不崩


# ── 增量3：点选/选中联动闭环（id 唯一性修复的收益锁定）──────────────────────

def test_click_nested_else_child_focuses_right_card(qapp, config_manager,
                                                    monkeypatch):
    """点画布 else 子步 → 列表聚焦**该步**的卡片。

    旧实现两区 id 撞名时，_find_step_by_id 首匹配会把 else 子步解析成
    then 子步，高亮/滚动错卡片（da809c1 连续编号修复后的联动闭环）。
    """
    from test_workflow_canvas_edit import _press_node, _release_at
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1", "log")],
                 [_leaf("2.2", "wait_ms", ms=50), _leaf("2.3", "copy")])
    wf._steps_dicts = [_leaf("1"), br]
    cv.refresh_from_workflow()
    else_child = br["else_steps"][1]
    assert else_child["id"] == "2.3", "连续编号前提"
    focused = []
    orig = wf._rebuild_cards

    def _spy(focus_dict=None, *a, **k):
        focused.append(focus_dict)
        return orig(focus_dict, *a, **k)

    monkeypatch.setattr(wf, "_rebuild_cards", _spy)
    node = cv._canvas._node_by_id["2.3"]
    assert node._region_key == "else_steps", "else 子步应带区键"
    vp = _press_node(cv._canvas, node)
    _release_at(cv._canvas, vp)      # 完整 click（press+release）
    assert any(f is else_child for f in focused), \
        "点选联动未聚焦到 else 子步的卡片（错焦/未焦）"


def test_select_step_highlights_nested_else_child(qapp, config_manager):
    """列表→画布：select_step 高亮 else 子步对应节点（撞名时高亮错节点）。"""
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1", "log")], [_leaf("2.2", "copy")])
    wf._steps_dicts = [_leaf("1"), br]
    cv.refresh_from_workflow()
    cv.select_step("2.2")
    assert cv._canvas._node_by_id["2.2"]._selected is True
    assert cv._canvas._node_by_id["2.1"]._selected is False, \
        "不应高亮 then 子步"
