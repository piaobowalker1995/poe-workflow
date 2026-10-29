# -*- coding: utf-8 -*-
"""工作流画布 阶段3（可编辑）单元测试。

覆盖：
- 可编辑开关（默认只读保持不变）
- 网格吸附 + 兄弟左边缘对齐吸附 + 参考线生成/清理
- 拖动落点 → 新索引计算（拖动即重排 Q1）
- Delete 删除信号、模块库拖入 → 落点索引
- 画布重排 / 删除 / 拖入后**真实数据顺序**被正确修改（单一事实源）
- A3：子工作流预览节点隔离（不注册 / 点击不联动 / 禁删 / 禁微调）
- A4：拖拽与落点索引的「顶层节点」口径（容器计入、嵌套子节点排除）
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）。
"""
import pytest

from poe_workflow.ui.tab_workflow_canvas import _remove_step_by_id
from poe_workflow.ui.workflow_canvas import (
    ALIGN_TOL, GRID, AlignGuide, CanvasNode, ContainerNode, StepNode,
    SubWorkflowNode, WorkflowCanvasView,
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


def _sub_step(target="preset_mapmaker_full"):
    """子工作流引用步骤（on_error=jump + jump_target）。"""
    return {"id": "1", "kind": "action", "primitive": "log",
            "params": {"message": "call"}, "on_error": "jump",
            "jump_target": target, "retry_count": 0,
            "retry_delay_ms": 0, "delay_ms": 0}


# ── 可编辑开关 ──────────────────────────────────────────────────────────────
def test_default_is_read_only(qapp):
    """默认仍为只读（阶段2 行为不变，向后兼容）。"""
    v = WorkflowCanvasView()
    assert v.is_editable() is False


def test_set_editable_toggles(qapp):
    v = WorkflowCanvasView()
    v.set_editable(True)
    assert v.is_editable() is True
    v.set_editable(False)
    assert v.is_editable() is False


def test_editable_view_declares_signals(qapp):
    """阶段3 需要的三个信号必须存在（供画布页接线）。"""
    from PyQt5.QtCore import pyqtBoundSignal
    v = WorkflowCanvasView()
    assert isinstance(v.stepReorderRequested, pyqtBoundSignal)
    assert isinstance(v.stepDeleteRequested, pyqtBoundSignal)
    assert isinstance(v.paletteDropRequested, pyqtBoundSignal)


# ── 吸附与对齐 ──────────────────────────────────────────────────────────────
def test_snap_to_grid_rounds(qapp):
    v = WorkflowCanvasView()
    assert v._snap_to_grid(0) == 0
    # round(17/16)=1 → 16；round(55/16)=3 → 48（就近吸附，非向上取整）
    assert v._snap_to_grid(GRID + 1) == GRID
    assert v._snap_to_grid(GRID * 3 + 7) == GRID * 3


def test_apply_snap_aligns_to_sibling_left_edge(qapp):
    """与兄弟左边缘在容差内 → 吸附到该边缘并生成对齐参考线。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2"), _leaf("3")])
    sib_x = v._node_by_id["1"].pos().x()
    node = v._node_by_id["3"]
    x, _y = v._apply_snap(node, sib_x + ALIGN_TOL / 2, 100.0)
    assert x == sib_x
    assert v._guide is not None, "对齐时应生成参考线"


def test_apply_snap_grid_when_no_alignment(qapp):
    """无兄弟对齐 → 仅网格吸附。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2")])
    node = v._node_by_id["2"]
    far_x = v._node_by_id["1"].pos().x() + 1000.0
    x, y = v._apply_snap(node, far_x, 100.0)
    assert x == v._snap_to_grid(far_x)
    assert y == v._snap_to_grid(100.0)


def test_clear_guide_removes_item(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2")])
    sib_x = v._node_by_id["1"].pos().x()
    v._apply_snap(v._node_by_id["2"], sib_x, 100.0)
    assert v._guide is not None
    v._clear_guide()
    assert v._guide is None


# ── 落点索引（拖动即重排）────────────────────────────────────────────────────
def test_drop_index_before_first(qapp):
    """落在所有兄弟左边 → 索引 0。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2"), _leaf("3")])
    node = v._node_by_id["2"]
    assert v._drop_index_for(node, -100.0) == 0


def test_drop_index_middle(qapp):
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2"), _leaf("3")])
    node = v._node_by_id["3"]
    x2 = v._node_by_id["2"].pos().x()
    assert v._drop_index_for(node, x2 - 1.0) == 1


def test_drop_index_end(qapp):
    """落在所有兄弟右边 → 索引 = 兄弟数（末尾）。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _leaf("2"), _leaf("3")])
    node = v._node_by_id["1"]
    assert v._drop_index_for(node, 99999.0) == 2


# ── 删除 ────────────────────────────────────────────────────────────────────
def test_remove_step_by_id_top_level(qapp):
    steps = [_leaf("1"), _leaf("2")]
    assert _remove_step_by_id(steps, "1") is True
    assert [s["id"] for s in steps] == ["2"]
    assert _remove_step_by_id(steps, "nope") is False


def test_remove_step_by_id_nested(qapp):
    steps = [_loop("1", [_leaf("1.1"), _leaf("1.2")])]
    assert _remove_step_by_id(steps, "1.2") is True
    assert [s["id"] for s in steps[0]["body"]] == ["1.1"]


# ── 画布页：真实数据被正确修改（单一事实源）───────────────────────────────────
def _tab(qapp, config_manager):
    from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
    from poe_workflow.ui.tab_workflow import WorkflowTab
    wf = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(wf)
    wf._on_new()
    cv.refresh_from_workflow()
    return wf, cv


def _prims(wf):
    """取各步的 primitive 作为稳定标识。

    注意：step 的 id 是**按层级位置推导**的（1 / 1.1 / 1.2 …），任何增删改后
    都会重新编号，故断言顺序必须用 primitive 而非 id。
    """
    return [d.get("primitive") for d in wf._steps_dicts]


def test_reorder_mutates_real_data(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms"),
                       _leaf("3", "copy")]
    cv.refresh_from_workflow()
    assert _prims(wf) == ["log", "wait_ms", "copy"]
    # 把第 3 步（copy）拖到最前
    cv._on_canvas_reorder("3", 0)
    assert _prims(wf) == ["copy", "log", "wait_ms"], f"重排未生效：{_prims(wf)}"


def test_reorder_index_clamped(qapp, config_manager):
    """越界索引应被夹紧到 [0, len]，不抛异常。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms")]
    cv.refresh_from_workflow()
    # 越界大索引 → 落到末尾
    cv._on_canvas_reorder("1", 99)
    assert _prims(wf) == ["wait_ms", "log"]
    # 负索引 → 夹到 0（此时 id "2" 是 primitive=log 那步，移到最前）
    cv._on_canvas_reorder("2", -5)
    assert _prims(wf) == ["log", "wait_ms"]


def test_delete_mutates_real_data(qapp, config_manager):
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms"),
                       _leaf("3", "copy")]
    cv.refresh_from_workflow()
    cv._on_canvas_delete("2")
    assert _prims(wf) == ["log", "copy"], f"删除未生效：{_prims(wf)}"
    # 画布节点数同步减少
    assert cv._canvas.node_count() == 2


def test_drop_inserts_at_index(qapp, config_manager):
    """模块库拖入 → 生成合法步骤并落在指定索引。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = [_leaf("1"), _leaf("2")]
    cv.refresh_from_workflow()
    cv._on_canvas_drop({"type": "primitive", "payload": "wait_ms"}, 0)
    ids = [d.get("id") for d in wf._steps_dicts]
    assert len(ids) == 3
    assert wf._steps_dicts[0]["primitive"] == "wait_ms", f"未落在索引 0：{ids}"
    assert wf._canvas_model.validate() == []


def test_edit_checkbox_toggles_canvas(qapp, config_manager):
    """画布页「可编辑」勾选框应联动画布可编辑状态。"""
    _wf, cv = _tab(qapp, config_manager)
    assert cv._canvas.is_editable() is False
    cv._chk_edit.setChecked(True)
    assert cv._canvas.is_editable() is True
    cv.set_canvas_editable(False)
    assert cv._canvas.is_editable() is False


def test_empty_steps_drop_safe(qapp, config_manager):
    """空方案下拖入不应崩（索引夹紧到 0）。"""
    wf, cv = _tab(qapp, config_manager)
    wf._steps_dicts = []
    cv.refresh_from_workflow()
    cv._on_canvas_drop({"type": "primitive", "payload": "log"}, 5)
    assert len(wf._steps_dicts) == 1


# ── 点击不崩回归（真机「点画布上的模块就闪退」根因修复）───────────────────────
# 根因：stepClicked 是**同步**信号，其槽链路为
#   _on_canvas_clicked → focus_step_by_id → _rebuild_cards
#   → _notify_canvas_changed → refresh_from_workflow → _rebuild → set_steps
#   → scene.clear()
# 会在 emit 返回前同步重建画布、销毁当前 node 图元。mousePressEvent 若在 emit
# 之后继续调用 node.setSelected/pos/setZValue（或让 mouseMoveEvent 持有旧图元），
# 即在已销毁的 C++ 对象上操作 → RuntimeError → PyQt 转 qFatal → 进程 abort
# （真机表现为点击画布节点即闪退）。offscreen 普通用例不复现：画布页单独使用时
# _workflow_tab 为 None 会提前返回，必须两视图挂接（弹窗形态）才触发。
# 修复：所有对 node 的 C++ 调用移到 emit 之前；拖拽图元在重建后按 id 重新解析。


def _press_node(canvas, node):
    """在 node 中心派发一次真实左键按下（直接调用便于断言捕获异常）。"""
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    vp = canvas.mapFromScene(node.scenePos() + node.rect().center())
    ev = QMouseEvent(QEvent.MouseButtonPress, vp, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    canvas.mousePressEvent(ev)
    return vp


def _move_held_at(canvas, vp, dx=0, dy=0):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseMove, QPoint(vp.x() + dx, vp.y() + dy),
                     Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    canvas.mouseMoveEvent(ev)


def _release_at(canvas, vp):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QMouseEvent
    ev = QMouseEvent(QEvent.MouseButtonRelease, vp, Qt.LeftButton,
                     Qt.NoButton, Qt.NoModifier)
    canvas.mouseReleaseEvent(ev)


def _drag_to_scene(canvas, vp, tx, ty):
    """把拖动中的节点落到**场景坐标** (tx, ty) 并释放。

    坐标口径（A4 起所有拖拽测试共用）：mouseMoveEvent 里
    ``raw = _drag_origin + (event.pos() - _drag_origin)``，_drag_origin 在
    加减中抵消 → 节点最终落点 = 释放前的**鼠标视口位置**（视口坐标被当作
    场景坐标用）。因此要让节点落到场景 (tx, ty)，鼠标视口位置就须是
    (tx, ty)——与 mapFromScene 的对齐/滚动偏移无关（offscreen 下偏移可达
    (+6,+189)，只按场景位移量算 dx 会把节点甩出目标区，见
    tests/test_workflow_canvas_cross_move.py 的坐标口径用例）。
    tx/ty 取 16 的整数倍可避开网格吸附偏移；与兄弟左缘保持 >6px 避开对齐吸附。
    """
    _move_held_at(canvas, vp, dx=int(tx - vp.x()), dy=int(ty - vp.y()))
    _release_at(canvas, vp)


def _press_at_scene(canvas, scene_x, scene_y):
    """在场景坐标处派发一次真实左键按下（容器标题栏等非中心点位用）。"""
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent
    vp = canvas.mapFromScene(QPointF(scene_x, scene_y))
    ev = QMouseEvent(QEvent.MouseButtonPress, vp, Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    canvas.mousePressEvent(ev)
    return vp


def _key_event(key, shift=False):
    """构造一个按键事件（offscreen 下直接调用 keyPressEvent 即可）。"""
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtCore import QEvent, Qt
    mods = Qt.ShiftModifier if shift else Qt.NoModifier
    return QKeyEvent(QEvent.KeyPress, key, mods)


def _preview_nodes(view):
    """取场景中全部预览节点（未注册进 _node_by_id，只能从场景捞）。"""
    return [it for it in view._scene.items()
            if isinstance(it, CanvasNode) and getattr(it, "_is_preview", False)]


def _expanded_preview_view(qapp, sub_steps, main_steps=None):
    """构造一个展开了子工作流预览的裸画布（未挂列表，点击不触发重建）。"""
    v = WorkflowCanvasView()
    v.resize(900, 700)      # 保证 itemAt 命中（视口足够大）
    v.set_steps(main_steps if main_steps is not None else [_sub_step()])
    v.set_subworkflow_loader(lambda name: sub_steps)
    assert v.toggle_subworkflow(v._node_by_id["1"]) is True
    v.set_editable(True)
    return v


def test_click_node_with_list_attached_does_not_crash(qapp, config_manager):
    """可编辑态点击节点：联动重建画布后不得在已销毁图元上继续操作。

    注意：必须**双向挂接**（attach_canvas_tab + attach_workflow_tab，与弹窗一致）。
    旧 _tab 助手只挂了单向，wf._canvas_tab 为 None 时 _notify_canvas_changed
    提前返回、画布不重建——该 bug 正是因此逃过整个测试套件的。
    """
    wf, cv = _tab(qapp, config_manager)
    wf.attach_canvas_tab(cv)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms")]
    cv.refresh_from_workflow()
    cv._canvas.set_editable(True)
    old_node = cv._canvas._node_by_id["1"]
    # 完整 click（press + release）：release 路径会读 _drag_node，
    # 只发 press 覆盖不到（9a4c571 首修就漏过 release 路径）。
    vp = _press_node(cv._canvas, old_node)   # 真机在此 qFatal 闪退；不抛异常即通过
    # press 后（release 前）：拖拽起始图元必须已按 id 重新解析到新节点，
    # 不能持有已销毁的旧图元（release 时会读它）
    assert cv._canvas._drag_node is cv._canvas._node_by_id["1"]
    _release_at(cv._canvas, vp)
    # 联动链路确实同步重建了场景（证明本用例覆盖崩溃路径）
    assert cv._canvas._node_by_id["1"] is not old_node
    # release 处理完毕应清空拖拽状态
    assert cv._canvas._drag_node is None
    assert cv._canvas._clicked_id == "1"


def test_click_subworkflow_node_toggles_without_crash(qapp, config_manager,
                                                      monkeypatch):
    """点击子工作流节点：展开/收起预览均不得崩（toggle 同样重建场景）。

    toggle 内部会**再**重建一次场景：若拖拽图元在 toggle 之前解析，
    release 时读到的就是被 toggle 销毁的图元 → RuntimeError → 闪退。
    故必须发完整 click（press + release）才能覆盖。
    """
    monkeypatch.setattr(
        "poe_workflow.ui.tab_workflow_canvas._load_subworkflow_steps",
        lambda name: [_leaf("1", "log")])
    wf, cv = _tab(qapp, config_manager)
    wf.attach_canvas_tab(cv)
    wf._steps_dicts = [{
        "id": "", "kind": "action", "primitive": "log",
        "params": {"message": "调用子工作流: demo"},
        "on_error": "jump", "jump_target": "demo",
        "retry_count": 0, "retry_delay_ms": 0, "delay_ms": 0,
    }]
    cv.refresh_from_workflow()
    cv._canvas.set_editable(True)
    assert isinstance(cv._canvas._node_by_id["1"], SubWorkflowNode)
    vp = _press_node(cv._canvas, cv._canvas._node_by_id["1"])
    _release_at(cv._canvas, vp)
    assert cv._canvas._node_by_id["1"].expanded is True
    vp = _press_node(cv._canvas, cv._canvas._node_by_id["1"])
    _release_at(cv._canvas, vp)
    assert cv._canvas._node_by_id["1"].expanded is False


def test_drag_after_subworkflow_click(qapp, config_manager, monkeypatch):
    """点子工作流（触发 toggle 重建）后紧接着拖动：拖拽图元不得失效。"""
    monkeypatch.setattr(
        "poe_workflow.ui.tab_workflow_canvas._load_subworkflow_steps",
        lambda name: [_leaf("1", "log")])
    wf, cv = _tab(qapp, config_manager)
    wf.attach_canvas_tab(cv)
    wf._steps_dicts = [{
        "id": "", "kind": "action", "primitive": "log",
        "params": {"message": "调用子工作流: demo"},
        "on_error": "jump", "jump_target": "demo",
        "retry_count": 0, "retry_delay_ms": 0, "delay_ms": 0,
    }, _leaf("2", "wait_ms")]
    cv.refresh_from_workflow()
    cv._canvas.set_editable(True)
    got = []
    cv._canvas.stepReorderRequested.connect(
        lambda sid, idx: got.append((sid, idx)))
    # 第一次点击：展开预览（press 内 toggle → 二次重建）
    vp = _press_node(cv._canvas, cv._canvas._node_by_id["1"])
    _release_at(cv._canvas, vp)
    assert cv._canvas._node_by_id["1"].expanded is True
    # 紧接着拖动同一节点：_drag_node 必须是存活图元
    _press_node(cv._canvas, cv._canvas._node_by_id["1"])
    _move_held_at(cv._canvas, vp, dx=-40)
    _release_at(cv._canvas, vp)
    assert got and got[-1][0] == "1", f"拖动未生效：{got}"


def test_press_move_release_drag_chain(qapp, config_manager):
    """点击后立即拖动（press→move→release 全链路）不得崩，重排信号须发出。"""
    wf, cv = _tab(qapp, config_manager)
    wf.attach_canvas_tab(cv)
    wf._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms"),
                       _leaf("3", "copy")]
    cv.refresh_from_workflow()
    cv._canvas.set_editable(True)
    got = []
    cv._canvas.stepReorderRequested.connect(
        lambda sid, idx: got.append((sid, idx)))
    vp = _press_node(cv._canvas, cv._canvas._node_by_id["3"])
    # 拖动中：_drag_node 已是重建后的新图元，setPos 不得崩
    _move_held_at(cv._canvas, vp, dx=-40)
    _release_at(cv._canvas, vp)
    assert got and got[0][0] == "3"


# ── A3：子工作流预览节点隔离（只读，禁误删/误联动）────────────────────────────
# 背景：预览子节点与主流程共用 scene，其 step_id 是子方案的位置 id，与主流程
# 撞名时点击会高亮错误的真实步骤、Delete 会删真实步骤并落盘；语义不撞名时
# 又会污染 _node_by_id（select_step / 落点索引 / node_count）。
# 定案：预览节点打 _is_preview 标记、不注册、点击/删除/微调全部拦截。


def test_preview_nodes_not_registered(qapp):
    """展开预览后：_node_by_id 不含预览节点，node_count 只算主流程。

    子方案用**语义 id**（"3"/"3.1"，不撞名）——旧实现会注册成功、污染注册表。
    """
    v = _expanded_preview_view(
        qapp, [_leaf("1", "log"), _loop("3", [_leaf("3.1")])],
        main_steps=[_sub_step(), _leaf("2")])
    # 主流程 2 个节点（子工作流引用 + leaf2）；预览的 "1"（撞名）/ "3"（容器）
    # / "3.1"（容器内叶子）均不注册
    assert v.node_count() == 2
    assert set(v._node_by_id) == {"1", "2"}
    # 撞名场景：注册表里的 "1" 必须是主流程的 SubWorkflowNode，而非预览叶子
    assert isinstance(v._node_by_id["1"], SubWorkflowNode)
    # 预览节点确实渲染进了场景并打了标记（叶子 + 容器 + 容器内叶子 = 3 个）
    previews = _preview_nodes(v)
    assert len(previews) == 3
    assert any(isinstance(p, ContainerNode) for p in previews)


def test_click_preview_node_emits_no_step_clicked(qapp):
    """对预览节点派发完整 click（press+release）→ stepClicked 未发射。"""
    v = _expanded_preview_view(qapp, [_leaf("1", "log")])
    clicks = []
    v.stepClicked.connect(lambda sid: clicks.append(sid))
    preview = _preview_nodes(v)[0]
    vp = _press_node(v, preview)
    assert preview.isSelected() is True, "预览节点应有点击选中的视觉反馈"
    assert v._clicked_id is None, "点击预览不应留下主流程 clicked id"
    _release_at(v, vp)
    assert clicks == [], f"预览点击不得发射 stepClicked：{clicks}"


def test_delete_key_on_preview_node_emits_no_delete(qapp):
    """选中预览节点后派发 Delete → stepDeleteRequested 未发射（预览区禁删）。"""
    from PyQt5.QtCore import Qt
    v = _expanded_preview_view(qapp, [_leaf("1", "log")])
    deleted = []
    v.stepDeleteRequested.connect(lambda sid: deleted.append(sid))
    preview = _preview_nodes(v)[0]
    _press_node(v, preview)          # 选中预览节点（子方案位置 id "1"）
    v.keyPressEvent(_key_event(Qt.Key_Delete))
    assert deleted == [], f"预览节点不得触发删除：{deleted}"


def test_delete_key_on_main_node_still_emits(qapp):
    """对照：选中主流程节点按 Delete 照常发射（拦截没误伤正常路径）。"""
    from PyQt5.QtCore import Qt
    v = _expanded_preview_view(
        qapp, [_leaf("1", "log")], main_steps=[_sub_step(), _leaf("2")])
    deleted = []
    v.stepDeleteRequested.connect(lambda sid: deleted.append(sid))
    _press_node(v, v._node_by_id["2"])
    v.keyPressEvent(_key_event(Qt.Key_Delete))
    assert deleted == ["2"], f"主流程节点删除被误拦截：{deleted}"


def test_arrow_key_does_not_move_preview_node(qapp):
    """方向键对预览节点禁用（只读预览区不得微调）。"""
    from PyQt5.QtCore import Qt
    v = _expanded_preview_view(qapp, [_leaf("1", "log")])
    preview = _preview_nodes(v)[0]
    _press_node(v, preview)
    x0, y0 = preview.pos().x(), preview.pos().y()
    v.keyPressEvent(_key_event(Qt.Key_Right))
    v.keyPressEvent(_key_event(Qt.Key_Down, shift=True))
    assert preview.pos().x() == x0 and preview.pos().y() == y0, \
        "预览节点不应响应方向键微调"


# ── A4：拖拽/落点索引「顶层节点」口径（容器计入、嵌套子节点排除）──────────────
# 背景：旧 _drop_index_for/docstring 说「容器也参与」却 isinstance 排除容器，
# 且把嵌套子节点（id 形如 "2.1"）混进兄弟集——而消费方只 insert 顶层列表，
# 导致 [A, loop, B] 中把 A 拖到 loop 与 B 之间时 A 被放回队首。
# 定案：顶层兄弟集 = 顶层节点（排除自己 + id 含 "." 的嵌套节点，容器计入）；
# 被拖节点自身是嵌套节点时：落在**所在子区**内走子区重排
# （stepReorderInRegionRequested），落在区外则走跨容器搬运
# （A4 收尾的 stepMoveRequested，见 test_workflow_canvas_cross_move.py）。


def test_drop_index_top_level_siblings(qapp):
    """顶层口径：容器计入兄弟集，嵌套子节点（id 含 "."）不计。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1"), _loop("2", [_leaf("2.1")]), _leaf("3")])
    x1 = v._node_by_id["1"].pos().x()
    x_loop = v._node_by_id["2"].pos().x()
    x_leaf3 = v._node_by_id["3"].pos().x()
    assert x1 < x_loop < x_leaf3
    # 拖 leaf1 到 loop 与 leaf3 之间 → 索引 1（loop 计入；旧实现排除容器会错算 0）
    assert v._drop_index_for(v._node_by_id["1"], x_leaf3 - 1.0) == 1
    # 拖 leaf3 到 leaf1 左侧 → 索引 0（loop 左边缘也是分界，不影响）
    assert v._drop_index_for(v._node_by_id["3"], x1 - 1.0) == 0
    # 拖 loop 自身到 leaf3 右侧 → 索引 2（loop 自己也在兄弟集中）
    assert v._drop_index_for(v._node_by_id["2"], 99999.0) == 2


def test_drag_leaf_between_container_and_leaf(qapp):
    """全链路：[leaf1, loop, leaf3]，把 leaf1 拖到 loop 与 leaf3 之间。

    按 3 个顶层节点算（loop 计入）→ stepReorderRequested 发出 ("1", 1)；
    旧实现只按两枚叶子算，会把 leaf1 放回队首（所见非所得）。
    """
    v = WorkflowCanvasView()
    v.resize(900, 700)
    v.set_steps([_leaf("1", "log"), _loop("2", [_leaf("2.1")]),
                 _leaf("3", "copy")])
    v.set_editable(True)
    got = []
    v.stepReorderRequested.connect(lambda sid, idx: got.append((sid, idx)))
    node = v._node_by_id["1"]
    loop = v._node_by_id["2"]
    leaf3 = v._node_by_id["3"]
    # 目标落点：loop 右边缘与 leaf3 左边缘的中点（避开对齐吸附容差）
    target_x = (loop.pos().x() + loop.rect().width()
                + leaf3.pos().x()) / 2.0
    vp = _press_node(v, node)
    # mouseMoveEvent 的等效场景落点 = vp.x() + dx（_drag_origin 与 vp 同源），
    # 故直接按实际 vp 反算 dx（视图可能有对齐/滚动偏移，不能假设 vp.x()==114）
    _move_held_at(v, vp, dx=int(target_x - vp.x()))
    _release_at(v, vp)
    assert got and got[-1] == ("1", 1), f"容器未计入兄弟集：{got}"


def test_drag_container_itself_counts_in_siblings(qapp):
    """拖容器自身：容器也计入兄弟集，拖到 leaf3 右侧 → index=2。"""
    v = WorkflowCanvasView()
    v.resize(900, 700)
    v.set_steps([_leaf("1"), _loop("2", [_leaf("2.1")]), _leaf("3")])
    v.set_editable(True)
    got = []
    v.stepReorderRequested.connect(lambda sid, idx: got.append((sid, idx)))
    container = v._node_by_id["2"]
    # 按容器标题栏派发按下（中心点会落在子节点 "2.1" 上，itemAt 取不到容器）
    vp = _press_at_scene(v, container.pos().x() + 20.0,
                         container.pos().y() + 13.0)
    assert v._drag_node is container, "应按标题栏命中容器本身"
    _move_held_at(v, vp, dx=400)      # 拖到 leaf3 右侧
    _release_at(v, vp)
    assert got and got[-1] == ("2", 2), f"容器拖拽索引错误：{got}"


def test_drag_nested_child_reorders_within_region(qapp):
    """拖嵌套子节点（id 含 "."）落在**所在子区内** → 子区重排信号。

    P4-B 增量2 起嵌套重排已实现：口径与顶层一致（同区兄弟左边缘分界、
    不含自身），且**不发**顶层 stepReorderRequested。落点在区外则属于
    跨容器搬运（A4 收尾），见 test_workflow_canvas_cross_move.py。
    落点 (600, 96)：body 命中区（组框横向全覆盖）内、2.2 左缘(496)之右
    → 区内索引 1。
    """
    v = WorkflowCanvasView()
    v.resize(900, 700)
    v.set_steps([_leaf("1"), _loop("2", [_leaf("2.1"), _leaf("2.2")])])
    v.set_editable(True)
    top, region = [], []
    v.stepReorderRequested.connect(lambda sid, idx: top.append((sid, idx)))
    v.stepReorderInRegionRequested.connect(
        lambda sid, c, r, i: region.append((sid, c, r, i)))
    child = v._node_by_id["2.1"]
    vp = _press_node(v, child)
    _drag_to_scene(v, vp, 600, 96)
    assert top == [], f"嵌套子节点不应发射顶层重排信号：{top}"
    assert region == [("2.1", "2", "body", 1)], \
        f"子区重排信号错误：{region}"
    # 弹回原位（auto_layout 后位置恢复）
    assert v._node_by_id["2.1"].pos().x() == 272.0


def test_drop_event_index_counts_container(qapp):
    """模块库拖入落点索引同口径：容器计入、嵌套子节点不计。

    loop 与 leaf3 之间落点 → 索引 2（旧实现排除容器会错算 1）。
    """
    from PyQt5.QtCore import QMimeData, QPointF, Qt
    from PyQt5.QtGui import QDropEvent
    from poe_workflow.ui.workflow_palette import PaletteItemButton
    v = WorkflowCanvasView()
    v.resize(900, 700)
    v.set_steps([_leaf("1"), _loop("2", [_leaf("2.1")]), _leaf("3")])
    v.set_editable(True)
    got = []
    v.paletteDropRequested.connect(lambda desc, idx: got.append((desc, idx)))
    mime = QMimeData()
    mime.setData(PaletteItemButton.MIME_TYPE,
                 b'{"type": "primitive", "payload": "wait_ms"}')
    loop = v._node_by_id["2"]
    leaf3 = v._node_by_id["3"]
    drop_x = (loop.pos().x() + loop.rect().width()
              + leaf3.pos().x()) / 2.0
    ev = QDropEvent(QPointF(drop_x, 100.0), Qt.CopyAction, mime,
                    Qt.LeftButton, Qt.NoModifier)
    v.dropEvent(ev)
    assert got and got[-1][1] == 2, f"落点索引错误：{got}"
    assert got[-1][0]["payload"] == "wait_ms"