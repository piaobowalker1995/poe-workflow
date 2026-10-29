# -*- coding: utf-8 -*-
"""工作流画布 A4 收尾：画布跨容器搬运（顶层↔容器、body→then、then→else）。

覆盖：
- 坐标口径：mouseMoveEvent 的落点 = 释放前鼠标**视口**位置
  （raw = _drag_origin + (event.pos() - _drag_origin)，前者被抵消），
  与 mapFromScene 的对齐/滚动偏移无关——所有拖拽落点统一经
  _drag_to_scene 按场景坐标精确合成
- 命中区几何：loop body / branch then|else 的命中区横向覆盖整个组框
  （含左右内边距）——「拖到区首/区尾」几何可达（旧口径把边距排除在
  区外，落在首子节点左缘左侧即出区、被判成拖出容器）
- 视图层：stepMoveRequested 落点换算（body→then、then→else、顶层↔容器、
  嵌套容器取最内层、容器带孩子整体搬）；同区/同层拖动仍走既有重排信号
  （口径不变）；防环双保险（容器拖入自身/后代 → 任何信号都不发）
- handler 层：_on_canvas_move 改真实数据（remove+insert、索引夹紧、
  区域键自动补齐、id 重编号、列表卡片同步）；非法输入安全拒绝不改数据
- 端到端：挂接列表后完整拖拽（press+move+release）真实改数据且校验通过
依赖 tests/conftest.py 的 qapp + config_manager 夹具。
"""
import pytest

from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
from poe_workflow.ui.workflow_canvas import WorkflowCanvasView


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


def _view(qapp, steps):
    v = WorkflowCanvasView()
    v.resize(1200, 800)
    v.set_steps(steps)
    v.set_editable(True)
    return v


def _capture(v):
    """连接全部三个落点信号，返回事件列表（4 元组，首元素为信号名）。"""
    got = []
    v.stepReorderRequested.connect(
        lambda sid, i: got.append(("TOP", sid, "", i)))
    v.stepReorderInRegionRequested.connect(
        lambda sid, c, r, i: got.append(("REGION", sid, c, r, i)))
    v.stepMoveRequested.connect(
        lambda sid, c, r, i: got.append(("MOVE", sid, c, r, i)))
    return got


def _tab(qapp, config_manager):
    """构造**双向挂接**的 列表 + 画布（与 WorkflowDialog 装配一致）。"""
    from poe_workflow.ui.tab_workflow import WorkflowTab
    wf = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(wf)
    wf.attach_canvas_tab(cv)
    wf._on_new()
    cv.refresh_from_workflow()
    return wf, cv


def _top_labels(wf):
    """顶层步骤的稳定标识（叶子取 primitive，容器取 kind）。"""
    return [d.get("primitive") or d.get("kind") for d in wf._steps_dicts]


def _validate(wf):
    from poe_workflow.workflow_model import validate_workflow, workflow_from_dict
    return validate_workflow(workflow_from_dict({"steps": wf._steps_dicts}))


def _live_cards(wf):
    """从**当前布局**取存活卡片（_clear_layout 的 deleteLater 会延迟销毁，
    findChildren 会连陈旧卡片一起捞到——见 P5 聚焦快速路径的教训）。"""
    from poe_workflow.ui.tab_workflow import StepCard
    cards = []
    for i in range(wf._cards_layout.count()):
        w = wf._cards_layout.itemAt(i).widget()
        if isinstance(w, StepCard):
            cards.append(w)
    return cards


# ── 坐标口径 ─────────────────────────────────────────────────────────────────

def test_drag_landing_equals_viewport_pos(qapp):
    """口径锁定：节点最终落点 = 释放前鼠标视口位置（视口坐标当场景坐标用）。

    offscreen 下 mapFromScene 有 (+6,+189) 偏移、视口还被钳制到 638x478
    （虚拟屏限制），只按「场景位移量」算 dx/dy 会把节点甩出目标区——
    既有 4 个区改序测试正是因此只在 x 方向拖拽。本用例把该口径显式锁定，
    所有后续拖拽测试统一走 _drag_to_scene（目标视口位置 = 目标场景坐标）。
    """
    from test_workflow_canvas_edit import (
        _press_node, _move_held_at, _release_at)
    v = _view(qapp, [_leaf("1"), _leaf("2")])
    node = v._node_by_id["1"]
    vp = _press_node(v, node)
    # (192, 288) 均为 16 的整数倍（避开网格吸附）；与兄弟左缘 254 距离 >6
    _move_held_at(v, vp, dx=192 - vp.x(), dy=288 - vp.y())
    assert node.pos().x() == 192.0 and node.pos().y() == 288.0, \
        f"落点口径不是鼠标视口位置：{node.pos()}"
    _release_at(v, vp)      # release 会 auto_layout 重建场景，须最后调用


# ── 命中区几何（组框横向全覆盖）─────────────────────────────────────────────

def test_region_hit_covers_container_frame(qapp):
    """命中区横向覆盖整个组框（含左右内边距）。"""
    v = _view(qapp, [_leaf("1"), _loop("2", [_leaf("2.1")]), _leaf("3")])
    loop = v._node_by_id["2"]
    hit = loop._region_hit["body"]
    assert hit[0] == loop.pos().x(), "区左缘应=组框左缘（左边框内可落=索引0）"
    assert hit[2] == loop.pos().x() + loop.rect().width(), \
        "区右缘应=组框右缘（右边框内可落=追加区尾）"
    # 分支两区同样覆盖组框横向
    v2 = _view(qapp, [_leaf("1"),
                      _branch("2", [_leaf("2.1")], [_leaf("2.2")])])
    br = v2._node_by_id["2"]
    for key in ("then_steps", "else_steps"):
        hit = br._region_hit[key]
        assert hit[0] == br.pos().x(), f"{key} 区左缘应=组框左缘"
        assert hit[2] == br.pos().x() + br.rect().width(), \
            f"{key} 区右缘应=组框右缘"


def test_palette_drop_in_left_pad_lands_in_body(qapp):
    """模块库拖到组框左边框内（首子节点左侧的 18px 边距）→ body 索引 0。

    旧口径区左缘=首子节点左缘，边距在区外 → 误判成顶层拖入。
    """
    from poe_workflow.ui.workflow_palette import PaletteItemButton

    def _drop(v, x, y):
        from PyQt5.QtCore import QMimeData, QPointF, Qt
        from PyQt5.QtGui import QDropEvent
        mime = QMimeData()
        mime.setData(PaletteItemButton.MIME_TYPE,
                     b'{"type": "primitive", "payload": "wait_ms"}')
        pos = v.mapFromScene(QPointF(x, y))
        ev = QDropEvent(pos, Qt.CopyAction, mime,
                        Qt.LeftButton, Qt.NoModifier)
        v.dropEvent(ev)

    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1"), _leaf("2.2")]),
                     _leaf("3")])
    got = []
    v.paletteDropInContainer.connect(
        lambda d, c, r, i: got.append((c, r, i)))
    v.paletteDropRequested.connect(lambda d, i: got.append(("TOP", "", i)))
    loop = v._node_by_id["2"]
    _drop(v, loop.pos().x() + 4.0, 96.0)     # 组框左缘右侧 4px（边距内）
    assert got == [("2", "body", 0)], f"左边框内拖入落点错误：{got}"


# ── 视图层：跨区/跨层/跨容器落点换算 ────────────────────────────────────────

def test_signal_declared(qapp):
    from PyQt5.QtCore import pyqtBoundSignal
    v = WorkflowCanvasView()
    assert isinstance(v.stepMoveRequested, pyqtBoundSignal)


def test_drag_body_child_into_branch_then(qapp):
    """loop body 子步 → branch then 区（跨容器）→ MOVE 信号。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1", "log")]),
                     _branch("3", [_leaf("3.1", "copy")]),
                     _leaf("4")])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["2.1"])
    # 落点 (608, 96)：branch "3" then 命中区 [514,718]x[74,128] 内、
    # then 子步 3.1 左缘(532)之右 → 索引 1
    _drag_to_scene(v, vp, 608, 96)
    assert got == [("MOVE", "2.1", "3", "then_steps", 1)], \
        f"跨容器落点换算错误：{got}"


def test_drag_then_child_into_else(qapp):
    """branch then 子步 → else 区（同容器跨区）→ MOVE 信号。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _branch("2", [_leaf("2.1", "log")],
                             [_leaf("2.2", "copy")]),
                     _leaf("3")])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["2.1"])
    # 落点 (336, 192)：else 命中区 [254,458]x[158,212] 内、2.2 左缘(272)之右 → 1
    _drag_to_scene(v, vp, 336, 192)
    assert got == [("MOVE", "2.1", "2", "else_steps", 1)], \
        f"跨区落点换算错误：{got}"


def test_drag_top_level_into_loop_body(qapp):
    """顶层节点 → loop body 区（跨层）→ MOVE 信号。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1", "log"),
                     _loop("2", [_leaf("2.1", "copy")]),
                     _leaf("3", "wait_ms", ms=50)])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["3"])
    # 落点 (400, 96)：loop "2" body 命中区 [254,458]x[74,128] 内、
    # 2.1 左缘(272)之右 → 索引 1
    _drag_to_scene(v, vp, 400, 96)
    assert got == [("MOVE", "3", "2", "body", 1)], f"跨层落点换算错误：{got}"


def test_drag_body_child_out_to_top_level(qapp):
    """loop body 子步 → 容器外（拖出到顶层）→ MOVE（dst_parent 为空）。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1", "log"),
                     _loop("2", [_leaf("2.1", "copy")]),
                     _leaf("3", "wait_ms", ms=50)])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["2.1"])
    # 落点 (96, 32)：所有容器子区之外；顶层兄弟左缘 30/254/514 → 索引 1
    _drag_to_scene(v, vp, 96, 32)
    assert got == [("MOVE", "2.1", "", "", 1)], f"拖出落点换算错误：{got}"


def test_drag_deeply_nested_child_out_to_top_level(qapp):
    """深层嵌套子步（2.1.1）→ 顶层：索引按顶层兄弟算。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("2.1", [_leaf("2.1.1", "log")])]),
                     _leaf("3")])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["2.1.1"])
    _drag_to_scene(v, vp, 96, 32)
    assert got == [("MOVE", "2.1.1", "", "", 1)], \
        f"深层拖出落点换算错误：{got}"


def test_drag_into_nested_container_picks_innermost(qapp):
    """落点同处内外两层命中区 → 取面积最小的最内层容器。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("2.1", [_leaf("2.1.1", "log")])]),
                     _leaf("3")])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["3"])
    # 落点 (400, 144)：内层 loop "2.1" body 命中区 [272,476]x[118,172] 内
    # （同时落在外层 body 区内，但内层面积更小）
    _drag_to_scene(v, vp, 400, 144)
    assert got == [("MOVE", "3", "2.1", "body", 1)], \
        f"未取最内层容器：{got}"


def test_drag_container_into_other_container(qapp):
    """容器（带孩子）整体搬进另一容器 body → MOVE 信号。"""
    from test_workflow_canvas_edit import _press_at_scene, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1", "log")]),
                     _loop("3", [_leaf("3.1", "copy")]),
                     _leaf("4")])
    got = _capture(v)
    container = v._node_by_id["2"]
    # 按标题栏派发按下（中心点会落在子节点 "2.1" 上）
    vp = _press_at_scene(v, container.pos().x() + 20.0,
                         container.pos().y() + 13.0)
    assert v._drag_node is container, "应按标题栏命中容器本身"
    # 落点 (608, 96)：loop "3" body 命中区 [514,718]x[74,128] 内、
    # 3.1 左缘(532)之右 → 索引 1
    _drag_to_scene(v, vp, 608, 96)
    assert got == [("MOVE", "2", "3", "body", 1)], \
        f"容器搬运落点换算错误：{got}"


# ── 视图层：同区/同层拖动口径不变 ───────────────────────────────────────────

def test_same_region_drag_does_not_emit_move(qapp):
    """同容器同子区内拖动：仍走 REGION 重排，不发 MOVE。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1"), _leaf("2.2")]),
                     _leaf("3")])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["2.1"])
    # 落点 (400, 96)：body 区内、2.2 左缘(496)之左 → 区内索引 0
    # （2.1 是首子步，remove 后 insert 到 2.2 之前即 0）
    _drag_to_scene(v, vp, 400, 96)
    assert got == [("REGION", "2.1", "2", "body", 0)], \
        f"同区拖动走了跨搬运路径：{got}"


def test_top_level_drag_does_not_emit_move(qapp):
    """顶层拖动：仍走 TOP 重排，不发 MOVE（口径不变）。"""
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    v = _view(qapp, [_leaf("1"), _leaf("2"), _leaf("3")])
    got = _capture(v)
    vp = _press_node(v, v._node_by_id["3"])
    _drag_to_scene(v, vp, 100, 30)      # 落到 "1" 左缘(30)右侧 → 索引 1
    assert got == [("TOP", "3", "", 1)], f"顶层拖动走了跨搬运路径：{got}"


# ── 视图层：防环双保险 ──────────────────────────────────────────────────────

def test_is_self_or_descendant_rules(qapp):
    """_is_self_or_descendant：自身/后代/无关/未知 id/_parent_id 链环防御。"""
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("2.1", [_leaf("2.1.1")])]),
                     _loop("3", [_leaf("3.1")])])
    assert v._is_self_or_descendant("2", "2") is True
    assert v._is_self_or_descendant("2", "2.1") is True
    assert v._is_self_or_descendant("2", "2.1.1") is True
    assert v._is_self_or_descendant("2", "3") is False
    assert v._is_self_or_descendant("2", "99") is False
    assert v._is_self_or_descendant("2", "") is False
    # 伪造 _parent_id 链环：不得死循环（seen 防御）
    v._node_by_id["2.1"]._parent_id = "2.1"
    assert v._is_self_or_descendant("2", "2.1") is False


def test_drag_container_into_own_body_blocked(qapp):
    """容器拖进自身 body → 防环拒绝：任何信号都不发（静默弹回）。"""
    from test_workflow_canvas_edit import _press_at_scene, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_leaf("2.1")]),
                     _leaf("3")])
    got = _capture(v)
    container = v._node_by_id["2"]
    vp = _press_at_scene(v, container.pos().x() + 20.0,
                         container.pos().y() + 13.0)
    _drag_to_scene(v, vp, 400, 96)      # 落在自身 body 命中区内
    assert got == [], f"自嵌套未被视图层拦截：{got}"


def test_drag_container_into_descendant_blocked(qapp):
    """容器拖进后代容器 → 防环拒绝：任何信号都不发。"""
    from test_workflow_canvas_edit import _press_at_scene, _drag_to_scene
    v = _view(qapp, [_leaf("1"),
                     _loop("2", [_loop("2.1", [_leaf("2.1.1")])]),
                     _leaf("3")])
    got = _capture(v)
    container = v._node_by_id["2"]
    vp = _press_at_scene(v, container.pos().x() + 20.0,
                         container.pos().y() + 13.0)
    # 落点 (400, 144)：内层 "2.1" body 命中区内
    _drag_to_scene(v, vp, 400, 144)
    assert got == [], f"拖入后代未被视图层拦截：{got}"


# ── handler 层：真实数据落位 ────────────────────────────────────────────────

def test_handler_moves_body_child_into_branch_then(qapp, config_manager):
    """loop body 子步搬进 branch then：数据落位、编号连续、校验通过。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1", "log"),
                                   _leaf("2.2", "wait_ms", ms=50)]),
                       _branch("3", [_leaf("3.1", "copy")]),
                       _leaf("4")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1", "3", "then_steps", 0)
    assert [d["primitive"] for d in wf._steps_dicts[1]["body"]] == \
        ["wait_ms"], "源区未移除被拖步骤"
    then = wf._steps_dicts[2]["then_steps"]
    assert [d["primitive"] for d in then] == ["log", "copy"], "未落到目标索引"
    assert [d["id"] for d in then] == ["3.1", "3.2"], "id 未按新位置重编号"
    assert _validate(wf) == [], "搬运后方案校验失败"
    assert cv._canvas.node_count() == 7, "画布节点数与数据树不一致"


def test_handler_moves_then_into_else(qapp, config_manager):
    """then → else（同容器跨区）：then 不受牵连、else 追加。"""
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1", "log"), _leaf("2.2", "copy")],
                 [_leaf("2.3", "wait_ms", ms=50)])
    wf._steps_dicts = [_leaf("1"), br, _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1", "2", "else_steps", 1)
    assert [d["primitive"] for d in br["then_steps"]] == ["copy"], \
        "then 区不应被牵连"
    assert [d["primitive"] for d in br["else_steps"]] == \
        ["wait_ms", "log"], "未落到 else 指定索引"
    assert [d["id"] for d in br["then_steps"]] == ["2.1"]
    assert [d["id"] for d in br["else_steps"]] == ["2.2", "2.3"], \
        "分支两区 id 未连续编号"
    assert _validate(wf) == []


def test_handler_moves_top_level_into_loop_body(qapp, config_manager):
    """顶层 → loop body：顶层列表缩短、body 落在指定索引。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy")]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    cv._on_canvas_move("3", "2", "body", 0)
    assert _top_labels(wf) == ["log", "loop"], f"顶层未缩短：{_top_labels(wf)}"
    body = wf._steps_dicts[1]["body"]
    assert [d["primitive"] for d in body] == ["wait_ms", "copy"], \
        "未落到 body 首位"
    assert [d["id"] for d in body] == ["2.1", "2.2"], "id 未重编号"
    assert _validate(wf) == []


def test_handler_moves_container_into_other_container(qapp, config_manager):
    """容器整体搬进另一容器：带孩子一起走，结构完整、校验通过。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1", "log")]),
                       _loop("3", [_leaf("3.1", "copy")]),
                       _leaf("4")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2", "3", "body", 0)
    assert _top_labels(wf) == ["move_to_anchor", "loop", "move_to_anchor"], \
        f"顶层结构错误：{_top_labels(wf)}"
    body = wf._steps_dicts[1]["body"]
    assert [d.get("primitive") or d.get("kind") for d in body] == \
        ["loop", "copy"], f"目标 body 结构错误：{[d.get('kind') for d in body]}"
    moved = body[0]
    assert [d["primitive"] for d in moved["body"]] == ["log"], \
        "孩子未随容器一起搬迁"
    assert _validate(wf) == []
    assert cv._canvas.node_count() == 6, "画布节点数与数据树不一致"


def test_handler_moves_child_to_top_level(qapp, config_manager):
    """body 子步 → 顶层指定索引。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy"),
                                   _leaf("2.2", "wait_ms", ms=50)]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1", "", "", 1)
    assert _top_labels(wf) == ["log", "copy", "loop", "move_to_anchor"], \
        f"拖出后顶层结构错误：{_top_labels(wf)}"
    assert [d["primitive"] for d in wf._steps_dicts[2]["body"]] == \
        ["wait_ms"], "源区未移除被拖步骤"
    assert _validate(wf) == []


def test_handler_moves_deep_child_to_top_level(qapp, config_manager):
    """深层嵌套子步（2.1.1）搬到顶层：整棵树编号连续。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_loop("2.1", [_leaf("2.1.1", "copy"),
                                                 _leaf("2.1.2", "wait_ms",
                                                       ms=50)])]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1.1", "", "", 2)
    assert _top_labels(wf) == ["log", "loop", "copy", "wait_ms"], \
        f"深层拖出后顶层结构错误：{_top_labels(wf)}"
    assert [d["primitive"] for d in wf._steps_dicts[1]["body"][0]["body"]] == \
        ["wait_ms"], "内层 body 未保留其余子步"
    assert _validate(wf) == []


def test_handler_rejects_emptying_loop_body(qapp, config_manager):
    """结构护栏：搬走 loop body 唯一子步会留下空 body（validate 拒收）→ 拒绝。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy")]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1", "", "", 0)
    assert "循环体不能为空" in cv._status.text()
    assert _top_labels(wf) == ["log", "loop", "wait_ms"], "拒绝后数据被改"
    assert [d["primitive"] for d in wf._steps_dicts[1]["body"]] == ["copy"]
    assert _validate(wf) == []
    # 同 loop 内的搬移（body→body）不受护栏影响（不会腾空）
    cv._on_canvas_move("2.1", "2", "body", 0)
    assert [d["primitive"] for d in wf._steps_dicts[1]["body"]] == ["copy"]


def test_handler_rejects_region_kind_mismatch(qapp, config_manager):
    """子区键与容器类型不匹配（loop 没有 then_steps）→ 拒绝，不造僵尸子列表。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy")]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    cv._on_canvas_move("3", "2", "then_steps", 0)
    assert "没有 then_steps 子区" in cv._status.text()
    assert "then_steps" not in wf._steps_dicts[1], \
        "不得给 loop 造出布局层从不渲染的僵尸子列表"
    assert _top_labels(wf) == ["log", "loop", "wait_ms"], "拒绝后数据被改"


def test_handler_clamps_out_of_range_index(qapp, config_manager):
    """越界索引夹紧到区尾/顶层首位，不抛异常。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy")]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    cv._on_canvas_move("3", "2", "body", 99)
    assert [d["primitive"] for d in wf._steps_dicts[1]["body"]] == \
        ["copy", "wait_ms"], "越界索引未夹紧到区尾"
    cv._on_canvas_move("2.2", "", "", -5)
    assert _top_labels(wf)[0] == "wait_ms", "负索引未夹紧到顶层首位"
    assert _validate(wf) == []


def test_handler_rejects_container_into_own_body(qapp, config_manager):
    """handler 双保险：容器搬进自己 → 拒绝且数据不动。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_leaf("2.1")]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2", "2", "body", 0)
    assert "不能搬进自己" in cv._status.text()
    assert len(wf._steps_dicts[1]["body"]) == 1, "拒绝后源数据被改"
    assert len(wf._steps_dicts) == 3, "拒绝后顶层被改"


def test_handler_rejects_container_into_descendant(qapp, config_manager):
    """handler 双保险：容器搬进后代 → 拒绝且数据不动。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"),
                       _loop("2", [_loop("2.1", [_leaf("2.1.1")])]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2", "2.1", "body", 0)
    assert "不能搬进自己" in cv._status.text()
    assert [d.get("kind") for d in wf._steps_dicts[1]["body"]] == ["loop"], \
        "拒绝后数据被改"
    assert _validate(wf) == []


def test_handler_rejects_unknown_region(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"), _loop("2", [_leaf("2.1")])]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1", "2", "body_x", 0)
    assert "未知容器子区" in cv._status.text()
    assert len(wf._steps_dicts[1]["body"]) == 1, "非法区不得改数据"


def test_handler_missing_container_is_safe(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("1", "99", "body", 0)
    assert "未找到容器" in cv._status.text()
    assert len(wf._steps_dicts) == 1, "容器缺失不得改数据"


def test_handler_missing_step_is_safe(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("nope", "", "", 0)
    assert "未找到步骤" in cv._status.text()
    assert len(wf._steps_dicts) == 1, "步骤缺失不得改数据"


def test_handler_without_list_tab_is_safe(qapp, config_manager):
    cv = WorkflowCanvasTab(config_manager)
    cv._on_canvas_move("1", "", "", 0)          # 不崩
    cv._on_canvas_move("1", "2", "body", 0)     # 不崩


def test_handler_syncs_list_cards(qapp, config_manager, monkeypatch):
    """搬运后必须同步刷新列表卡片（与其它画布结构操作同一契约）。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy")]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    calls = []
    orig = wf._rebuild_cards

    def _counting(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(wf, "_rebuild_cards", _counting)
    cv._on_canvas_move("3", "2", "body", 0)
    assert calls, "搬运后未同步刷新列表卡片"
    assert len(_live_cards(wf)) == len(wf._steps_dicts), \
        "卡片数与数据树不一致"


def test_handler_into_empty_else_creates_key(qapp, config_manager):
    """缺 else_steps 键的 branch：搬入 else 自动建表（防 StepCard 硬下标闪退）。"""
    wf, cv = _tab(qapp, config_manager)
    br = _branch("2", [_leaf("2.1", "log")])
    del br["else_steps"]
    wf._steps_dicts = [_leaf("1"), br, _leaf("3")]
    cv.refresh_from_workflow()
    cv._on_canvas_move("2.1", "2", "else_steps", 0)
    assert wf._steps_dicts[1]["else_steps"], "空 else 区未建表"
    assert [d["primitive"] for d in wf._steps_dicts[1]["else_steps"]] == \
        ["log"], "未落到 else 区"
    assert [d["id"] for d in wf._steps_dicts[1]["then_steps"]] == []
    assert [d["id"] for d in wf._steps_dicts[1]["else_steps"]] == ["2.1"], \
        "then 腾空后 else 未从 2.1 起连续编号"
    assert _validate(wf) == []


# ── 端到端：挂接列表后完整拖拽 ──────────────────────────────────────────────

def test_end_to_end_drag_top_into_loop_body(qapp, config_manager):
    """端到端：press（触发联动重建）→ move → release 真实改数据。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy")]),
                       _leaf("3", "wait_ms", ms=50)]
    cv.refresh_from_workflow()
    cv._canvas.set_editable(True)
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    vp = _press_node(cv._canvas, cv._canvas._node_by_id["3"])
    # press 内 stepClicked 已同步重建场景；落点按场景坐标换算（与偏移无关）
    _drag_to_scene(cv._canvas, vp, 400, 96)
    assert [d["primitive"] for d in wf._steps_dicts[1]["body"]] == \
        ["copy", "wait_ms"], "端到端拖拽未改真实数据"
    assert _top_labels(wf) == ["log", "loop"], f"顶层未缩短：{_top_labels(wf)}"
    assert _validate(wf) == []
    assert len(_live_cards(wf)) == 2, "列表卡片未同步"


def test_end_to_end_drag_body_child_out(qapp, config_manager):
    """端到端：把 body 子步拖出容器到顶层。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"),
                       _loop("2", [_leaf("2.1", "copy"),
                                   _leaf("2.2", "wait_ms", ms=50)]),
                       _leaf("3")]
    cv.refresh_from_workflow()
    cv._canvas.set_editable(True)
    from test_workflow_canvas_edit import _press_node, _drag_to_scene
    vp = _press_node(cv._canvas, cv._canvas._node_by_id["2.1"])
    _drag_to_scene(cv._canvas, vp, 96, 32)
    assert _top_labels(wf) == ["log", "copy", "loop", "move_to_anchor"], \
        f"端到端拖出未生效：{_top_labels(wf)}"
    assert [d["primitive"] for d in wf._steps_dicts[2]["body"]] == \
        ["wait_ms"], "源区未移除被拖步骤"
    assert _validate(wf) == []
    assert len(_live_cards(wf)) == 4, "列表卡片未同步"
