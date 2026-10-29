# -*- coding: utf-8 -*-
"""工作流画布视图（GUI 升级 阶段2 可视化 + 阶段3 可编辑）。

把现有「步骤 dict 树」（WorkflowTab._steps_dicts，经 CanvasModel 读取）渲染成
PyQt5 QGraphicsView 上的嵌套组框 + 流程箭头。

阶段2：只读可视化（渲染 + 选中高亮 + 自动布局）。
阶段3：可编辑——
  - **拖动即重排（Q1 定案）**：拖动节点改变逻辑顺序（非仅视觉位置）。
  - **网格吸附**：节点位置对齐到 GRID 网格（默认 16px）。
  - **对齐参考线**：拖动时与兄弟节点左/中线对齐则吸附并显示参考线。
  - **Delete 删除**、**模块库拖入/落点插入**。
  - 布局方向仍按 Q4：步骤左→右（横向）、分支/循环上→下（纵向）。

设计要点（见 workflow_gui_upgrade_spec.md §5/§6/§7）：
- 节点类型：StepNode（叶子）/ ContainerNode（loop|branch 组框）/ SubWorkflowNode（jump_target）。
- 连线只表示**既有层级结构的流向**，不是自由 DAG（父子关系由 body/then_steps/else_steps 决定）。
- 配色：QGraphicsItem 不吃 QSS，颜色统一从 ui/theme.py 的 get_canvas_colors() 取，
  跟随浅色/深色主题切换（本项目约定：禁止硬编码颜色）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
)

from .text_resources import TextResources
from .theme import get_canvas_colors
from .workflow_palette import PaletteItemButton

# ── 布局常量（Q4：步骤横向、容器纵向）──
NODE_W = 168.0          # 叶子节点宽
NODE_H = 54.0           # 叶子节点高
H_GAP = 56.0            # 同层兄弟横向间距（留箭头位置）
V_GAP = 26.0            # 纵向间距
CONTAINER_PAD = 18.0    # 组框内边距
CONTAINER_HEADER = 26.0  # 组框标题栏高度
CONTAINER_GAP = 40.0    # 容器之间纵向间距
BRANCH_GAP = 30.0       # branch 的 then / else 两区之间纵向间距

# ── 阶段3 可编辑常量 ──
GRID = 16.0             # 网格吸附粒度（px）
ALIGN_TOL = 6.0         # 对齐参考线吸附容差（px）


class CanvasNode(QGraphicsRectItem):
    """所有节点的基类：矩形 + 标题 + 副标题 + 选中态。"""

    # 子工作流展开区的**预览节点**标记（A3）：预览节点只读——不注册、
    # 不参与点击联动/重排/删除，与主流程 id 空间隔离。
    # 类属性默认 False，预览分支按实例覆盖（比纯实例属性更稳）。
    _is_preview: bool = False

    def __init__(self, step: Dict[str, Any], colors: Dict[str, str],
                 title: str, subtitle: str = "", w: float = NODE_W,
                 h: float = NODE_H):
        super().__init__(0.0, 0.0, w, h)
        self._step = step
        self._colors = colors
        self._title = title
        self._subtitle = subtitle
        self._selected = False
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(False)
        self.setToolTip(self._build_tooltip())

    # ---- 数据 ----
    @property
    def step(self) -> Dict[str, Any]:
        return self._step

    @property
    def step_id(self) -> str:
        return str(self._step.get("id", ""))

    def set_selected(self, on: bool) -> None:
        if self._selected != on:
            self._selected = on
            self.update()

    # ---- 绘制 ----
    def _border_color(self) -> str:
        return self._colors["node_border"]

    def _fill_color(self) -> str:
        return self._colors["node_fill"]

    def _text_color(self) -> str:
        return self._colors["node_text"]

    def paint(self, painter: QPainter, option, widget=None) -> None:
        c = self._colors
        rect = self.rect()
        sel = self._selected or self.isSelected()

        fill = QBrush(QColor(c["selected"] if sel else self._fill_color()))
        border = QColor(self._border_color())
        width = 3.0 if sel else 1.5
        pen = QPen(border)
        pen.setWidthF(width)
        painter.setPen(pen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 5.0, 5.0)

        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(QColor(self._text_color())))
        pad = 8.0
        if self._subtitle:
            painter.drawText(
                QRectF(rect.left() + pad, rect.top() + 5,
                       rect.width() - pad * 2, 18),
                Qt.AlignLeft | Qt.AlignVCenter, self._title)
            f.setBold(False)
            f.setPointSize(8)
            painter.setFont(f)
            painter.setPen(QPen(QColor(c["grid_text"])))
            painter.drawText(
                QRectF(rect.left() + pad, rect.top() + 23,
                       rect.width() - pad * 2, 16),
                Qt.AlignLeft | Qt.AlignVCenter, self._subtitle)
        else:
            painter.drawText(
                QRectF(rect.left() + pad, rect.top(),
                       rect.width() - pad * 2, rect.height()),
                Qt.AlignLeft | Qt.AlignVCenter, self._title)

    def _build_tooltip(self) -> str:
        parts = [f"步骤 {self.step_id or '?'}"]
        for k in ("kind", "primitive", "on_error", "jump_target", "count"):
            v = self._step.get(k)
            if v not in (None, ""):
                parts.append(f"{k}={v}")
        return "\n".join(parts)


class StepNode(CanvasNode):
    """叶子动作节点。"""


class SubWorkflowNode(StepNode):
    """子工作流引用节点（on_error=jump + jump_target），用紫色区分。

    Q3 定案：子工作流节点**只读预览**——点击可展开内部结构，但不可编辑；
    只有「单独加载该子工作流文件」时才可编辑。
    """

    def __init__(self, step: Dict[str, Any], colors: Dict[str, str],
                 title: str, subtitle: str = ""):
        super().__init__(step, colors, title, subtitle)
        self._expanded = False

    def _border_color(self) -> str:
        return self._colors["sub_border"]

    def _fill_color(self) -> str:
        return self._colors["sub_fill"]

    def set_expanded(self, on: bool) -> None:
        self._expanded = bool(on)
        self.update()

    def toggle_expanded(self) -> bool:
        self.set_expanded(not self._expanded)
        return self._expanded

    @property
    def expanded(self) -> bool:
        return self._expanded


class ContainerNode(CanvasNode):
    """容器组框节点（loop / branch），内含子节点区域。

    本节点自身 rect 即组框外框；子节点由布局器另行摆放在框内坐标。
    """

    def __init__(self, step: Dict[str, Any], colors: Dict[str, str],
                 title: str, kind: str):
        super().__init__(step, colors, title, "", w=10.0, h=10.0)
        self._kind = kind

    def _border_color(self) -> str:
        return self._colors["loop_border" if self._kind == "loop"
                           else "branch_border"]

    def _fill_color(self) -> str:
        return self._colors["loop_fill" if self._kind == "loop"
                           else "branch_fill"]

    def paint(self, painter: QPainter, option, widget=None) -> None:
        c = self._colors
        rect = self.rect()
        sel = self._selected or self.isSelected()

        pen = QPen(QColor(self._border_color()))
        pen.setWidthF(3.0 if sel else 1.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(QColor(c["selected"] if sel
                                       else self._fill_color())))
        radius = 7.0
        painter.drawRoundedRect(rect, radius, radius)

        # 标题栏底色 + 标题（loop/branch 组框的辨识标志）
        head = QRectF(rect.left(), rect.top(), rect.width(), CONTAINER_HEADER)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(self._border_color())))
        # 只画标题栏背景：用路径裁出上圆角
        path = self._rounded_top_path(head, radius)
        painter.drawPath(path)
        painter.setBrush(Qt.NoBrush)

        f = QFont()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        # 标题栏文字色跟随主题（浅色主题白字 / 深色主题深字），不硬编码
        painter.setPen(QPen(QColor(c["header_text"])))
        painter.drawText(head.adjusted(8, 0, -8, 0),
                         Qt.AlignLeft | Qt.AlignVCenter, self._title)

    @staticmethod
    def _rounded_top_path(head: QRectF, radius: float):
        from PyQt5.QtGui import QPainterPath
        p = QPainterPath()
        p.moveTo(head.left(), head.bottom())
        p.lineTo(head.left(), head.top() + radius)
        p.quadTo(head.left(), head.top(), head.left() + radius, head.top())
        p.lineTo(head.right() - radius, head.top())
        p.quadTo(head.right(), head.top(), head.right(), head.top() + radius)
        p.lineTo(head.right(), head.bottom())
        p.closeSubpath()
        return p


class ConnectionEdge(QGraphicsRectItem):
    """流程箭头：横向（左→右，步骤流）或纵向（上→下，容器流）。"""

    def __init__(self, x: float, y: float, w: float, h: float,
                 horizontal: bool, colors: Dict[str, str]):
        super().__init__(x, y, w, h)
        self._horizontal = horizontal
        self._colors = colors

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen = QPen(QColor(self._colors["edge"]))
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        r = self.rect()
        cx, cy = r.center().x(), r.center().y()
        if self._horizontal:
            # 从左中 → 右中，中点画箭头
            mid = cx
            painter.drawLine(int(r.left()), int(cy), int(mid - 5), int(cy))
            self._arrow(painter, (mid, cy), 0.0)
        else:
            mid = cy
            painter.drawLine(int(cx), int(r.top()), int(cx), int(mid - 5))
            self._arrow(painter, (cx, mid), 90.0)

    @staticmethod
    def _arrow(painter: QPainter, tip: Tuple[float, float], angle: float) -> None:
        import math
        size = 5.0
        a = math.radians(angle)
        p1 = (tip[0] - size * math.cos(a - 0.42), tip[1] - size * math.sin(a - 0.42))
        p2 = (tip[0] - size * math.cos(a + 0.42), tip[1] - size * math.sin(a + 0.42))
        painter.drawLine(int(tip[0]), int(tip[1]), int(p1[0]), int(p1[1]))
        painter.drawLine(int(tip[0]), int(tip[1]), int(p2[0]), int(p2[1]))


class AlignGuide(QGraphicsRectItem):
    """拖动时显示的对齐参考线（垂直短线，阶段3）。"""

    def __init__(self, x: float, y: float, h: float, colors: Dict[str, str]):
        super().__init__(x, y, 1.5, h)
        self._colors = colors
        self.setZValue(1000)   # 置顶，不被节点遮挡

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pen = QPen(QColor(self._colors["edge"]))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.drawLine(int(self.rect().left()),
                         int(self.rect().top()),
                         int(self.rect().left()),
                         int(self.rect().bottom()))


class WorkflowCanvasView(QGraphicsView):
    """工作流画布（阶段2 只读可视化 + 阶段3 可编辑）。

    对外接口：
    - set_steps(steps)：给定步骤 dict 列表 → 重建整棵可视化。
    - set_theme(key)：切换主题配色并重绘。
    - select_step(step_id)：按 id 高亮节点（供列表→画布联动）。
    - stepClicked(step_id)：用户点击节点时发出（供画布→列表联动）。
    - auto_layout()：按 Q4 方向重新布局。
    阶段3 可编辑：
    - set_editable(bool)：开启后允许拖动重排 / Delete 删除（默认仍为只读）。
    - stepReorderRequested(step_id, new_index)：拖动结束、算出新顺序时发出，
      由外部（WorkflowCanvasTab → CanvasModel）真正改数据。
    - stepReorderInRegionRequested(step_id, container_id, region_key, index)：
      P4-B 增量2 嵌套子节点在**所在子区**内拖动改序时发出。与顶层信号互斥。
    - stepMoveRequested(step_id, dst_parent_id, dst_region_key, dst_index)：
      跨区/跨层/跨容器搬运（A4 收尾）：落点归属与节点当前所在（容器+子区）
      不同即跨搬运——含 loop body→branch then、then→else、顶层↔容器；
      目标容器为被拖容器自身或其后代时视图层直接拒发（防自嵌套环）。
    - stepDeleteRequested(step_id)：按 Delete 时发出。
    - paletteDropRequested(descriptor, target_index)：从模块库拖入落点插入时发出。
    - paletteDropInContainer(descriptor, container_id, region_key, index)：
      P4-B 拖入落点位于容器子区（loop body / branch then_steps、else_steps）
      时发出，由外部把新步骤插进该容器子列表；与顶层信号互斥。
    """

    stepClicked = pyqtSignal(str)
    stepReorderRequested = pyqtSignal(str, int)
    stepReorderInRegionRequested = pyqtSignal(str, str, str, int)
    stepMoveRequested = pyqtSignal(str, str, str, int)
    stepDeleteRequested = pyqtSignal(str)
    paletteDropRequested = pyqtSignal(dict, int)
    paletteDropInContainer = pyqtSignal(dict, str, str, int)

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self._cm = config_manager
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setObjectName("WorkflowCanvas")
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setDragMode(QGraphicsView.NoDrag)      # 默认只读（阶段2 行为）
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAcceptDrops(True)                    # 阶段3：接收模块库拖入

        self._theme_key = "light"
        self._colors = get_canvas_colors(self._theme_key)
        self._node_by_id: Dict[str, CanvasNode] = {}
        self._steps: List[Dict[str, Any]] = []
        self._edges: List[ConnectionEdge] = []

        # ── 阶段3 可编辑状态 ──
        self._editable = False
        self._drag_node: Optional[CanvasNode] = None
        self._drag_origin: QPointF = QPointF()
        self._guide: Optional[AlignGuide] = None
        self._clicked_id = ""      # 最近一次点击/选中的 step id（Delete 用）
        self._sub_loader = None    # 子工作流读取器（阶段4：Q3 只读预览）
        self._preview_owner = None
        # ── 视图导航（缩放/平移）状态 ──
        self._panning = False
        self._pan_last = None  # 平移：记录最近一次鼠标位置(QPoint)，用于 mouseMove 计算位移

        if config_manager is not None:
            self.set_theme(config_manager.get("General", "visual_style",
                                              "light"))

    # ------------------------------------------------------------------ #
    #  阶段3：可编辑开关
    # ------------------------------------------------------------------ #
    def set_editable(self, on: bool) -> None:
        """开启/关闭可编辑。关闭时恢复只读（NoDrag）。"""
        self._editable = bool(on)
        if not self._editable:
            self._drag_node = None
            self._clear_guide()
        # 只读仍用 NoDrag；可编辑时由 mouse 事件自行处理拖动（不用内置 InternalMove，
        # 因为内置拖动只改视觉位置，而 Q1 定案要求「拖动即重排」需自行判定落点）。
        self.setDragMode(QGraphicsView.NoDrag)

    def is_editable(self) -> bool:
        return self._editable

    # ------------------------------------------------------------------ #
    def set_theme(self, key: str) -> None:
        self._theme_key = key if key in ("light", "dark") else "light"
        self._colors = get_canvas_colors(self._theme_key)
        self._scene.setBackgroundBrush(QBrush(QColor(self._colors["canvas_bg"])))
        if self._steps:
            self.set_steps(self._steps)

    def set_subworkflow_loader(self, loader) -> None:
        """注入子工作流读取器：callable(name) -> steps list 或 None。

        用于 Q3：点击子工作流节点展开其内部结构（只读预览）。
        """
        self._sub_loader = loader

    def toggle_subworkflow(self, node: SubWorkflowNode) -> bool:
        """展开/收起子工作流预览；返回展开后的状态。

        注意：展开会触发 set_steps 重建场景，**传入的 node 图元随之被销毁**，
        故调用方不可再用它（内部只按 step dict 身份跟踪）。
        """
        if not isinstance(node, SubWorkflowNode):
            return False
        step = node.step
        was_expanded = node.expanded
        target = step.get("jump_target")
        if not was_expanded:
            # 展开：先取内容，取不到就不展开（静默失败回退）
            steps = self._sub_loader(target) if self._sub_loader else None
            if not steps:
                return False
            # 按 step dict 记忆（重建后图元对象已销毁，身份比对必须用 dict）
            self._preview_owner = (step, steps)
        else:
            self._preview_owner = None
        self.set_steps(self._steps)   # 重建并渲染/收起预览区
        return not was_expanded

    def set_steps(self, steps: List[Dict[str, Any]]) -> None:
        """重建画布（只读渲染）。"""
        self._steps = steps or []
        self._scene.clear()
        self._node_by_id = {}
        self._edges = []
        cursor_x, cursor_y = 30.0, 30.0
        for d in self._steps:
            w, h = self._layout_step(d, cursor_x, cursor_y)
            # 同层兄弟横向排布（Q4：步骤从左到右）
            cursor_x += w + H_GAP
            cursor_y = max(cursor_y, 30.0)
        self._scene.setSceneRect(0, 0, max(cursor_x, 640.0),
                                 max(cursor_y, 420.0))
        self._apply_background()

    def _apply_background(self) -> None:
        self._scene.setBackgroundBrush(QBrush(QColor(self._colors["canvas_bg"])))

    # ------------------------------------------------------------------ #
    def _layout_step(self, d: Dict[str, Any], x: float,
                     y: float, in_preview: bool = False) -> Tuple[float, float]:
        """摆放一个步骤节点（含容器递归），返回其占位 (w, h)。

        in_preview：True 表示这是子工作流展开的**预览节点**（A3：只读、
        不注册、不参与联动），需向容器递归下传。
        """
        kind = d.get("kind", "action")
        if kind == "loop":
            return self._layout_container(d, x, y, "loop", in_preview)
        if kind == "branch":
            return self._layout_container(d, x, y, "branch", in_preview)
        return self._layout_leaf(d, x, y, in_preview)

    # ---- 叶子 ----
    def _layout_leaf(self, d: Dict[str, Any], x: float,
                     y: float, in_preview: bool = False) -> Tuple[float, float]:
        sid = str(d.get("id", ""))
        prim = d.get("primitive", "")
        sub = _subtitle_for(d)
        if d.get("jump_target") and (d.get("on_error") == "jump"
                                     or d.get("kind") == "subworkflow"):
            # on_error=jump：出错恢复用的子工作流；kind=subworkflow：正常路径调用
            # 的子工作流（P4-A 一等公民）。二者都以 SubWorkflowNode 呈现、按
            # jump_target 预览模块内部结构。
            node = SubWorkflowNode(d, self._colors,
                                   f"子工作流：{d.get('jump_target')}", sub)
            # 预览态按 **step dict** 身份比对（重建后图元对象已换新）
            if self._preview_owner is not None and self._preview_owner[0] is d:
                node.set_expanded(True)
        else:
            node = StepNode(d, self._colors,
                            TextResources.get_primitive_label(prim) if prim
                            else "（未设置操作）", sub)
        node.setPos(x, y)
        self._scene.addItem(node)
        if in_preview:
            # A3：预览区节点打标记（_register 据此跳过注册）
            node._is_preview = True
        self._register(node, sid)

        # 展开态：在节点下方渲染子工作流内部结构（只读预览，不参与重排）
        preview_h = 0.0
        if isinstance(node, SubWorkflowNode) and node.expanded:
            preview_steps = (self._preview_owner[1]
                             if self._preview_owner else [])
            py = y + NODE_H + 10.0
            px = x + 14.0
            for sub_d in preview_steps:
                _w, _h = self._layout_step(sub_d, px, py, in_preview=True)
                py += _h + V_GAP
            preview_h = max(0.0, py - (y + NODE_H + 10.0))
            node._preview_height = preview_h
        # 返回高度含预览区，避免后续节点压住展开的子工作流
        return NODE_W, NODE_H + preview_h

    # ---- 容器 ----
    def _layout_container(self, d: Dict[str, Any], x: float, y: float,
                          kind: str,
                          in_preview: bool = False) -> Tuple[float, float]:
        sid = str(d.get("id", ""))
        title = _container_title(d, kind)
        # 先递归摆放子区，量出内容尺寸后再定组框大小
        placeholder = ContainerNode(d, self._colors, title, kind)
        self._scene.addItem(placeholder)
        if in_preview:
            # A3：预览区容器同样打标记、不注册
            placeholder._is_preview = True
        self._register(placeholder, sid)
        # P4-B：子区命中几何（场景坐标），布局时顺手记录，供拖入落点换算
        # 「落在哪个容器哪个区、区内的第几位」。空区给名义高度，保证
        # 空 loop body / 空分支也能落。命中区**横向覆盖整个组框**（含左右
        # 内边距）：落在组框左边框内 = 插到首个子节点之前（索引 0），落在
        # 右边框内 = 追加到区尾。旧口径 right=inner_x+… 把 18px 边距排除在
        # 区外，「拖到区首」在几何上不可能（落在首子节点左缘左侧即出区，
        # 被判成拖出容器）；A4 跨容器搬运上线后该缺陷直接暴露。
        placeholder._region_hit: Dict[str, Tuple[float, float, float, float]] = {}
        placeholder._region_xs: Dict[str, List[float]] = {}

        inner_x = x + CONTAINER_PAD
        inner_y = y + CONTAINER_HEADER + CONTAINER_PAD
        content_w, content_h = 0.0, 0.0

        if kind == "loop":
            # loop body：兄弟横向排布（Q4：步骤从左到右）
            body = d.get("body", []) or []
            cx, row_h = inner_x, 0.0
            body_xs: List[float] = []
            for child in body:
                body_xs.append(cx)
                cw, ch = self._layout_step(child, cx, inner_y, in_preview)
                self._tag_child(child, sid, "body")
                self._h_edge(cx, inner_y, cw, ch)
                cx += cw + H_GAP
                content_w = max(content_w, cx - H_GAP - inner_x)
                row_h = max(row_h, ch)
            content_h = row_h
            # 命中区横向覆盖整个组框（含左右内边距，与 frame_w 同公式）：
            # 左缘 = 组框左缘（落在首个子节点左侧的边距内 → 索引 0），
            # 右缘 = 组框右缘（落在末个子节点右侧的边距内 → 追加到区尾）
            right = x + max(content_w + CONTAINER_PAD * 2, NODE_W)
            placeholder._region_hit["body"] = (
                x, inner_y, right, inner_y + max(row_h, NODE_H))
            placeholder._region_xs["body"] = body_xs
        else:
            # branch：then 区、else 区上下两块（Q4：分支从上而下）
            then_steps = d.get("then_steps", []) or []
            else_steps = d.get("else_steps", []) or []

            def _row(steps, row_y, region_key):
                """横向排布一行，返回 (行高, 子节点左边缘 x 序列)。"""
                nonlocal content_w
                cx, rh = inner_x, 0.0
                xs: List[float] = []
                for child in steps:
                    xs.append(cx)
                    cw, ch = self._layout_step(child, cx, row_y, in_preview)
                    self._tag_child(child, sid, region_key)
                    self._h_edge(cx, row_y, cw, ch)
                    cx += cw + H_GAP
                    content_w = max(content_w, cx - H_GAP - inner_x)
                    rh = max(rh, ch)
                return rh, xs

            then_h, then_xs = (_row(then_steps, inner_y, "then_steps")
                               if then_steps else (0.0, []))
            else_h, else_xs = 0.0, []
            if else_steps:
                else_y = inner_y + then_h + (BRANCH_GAP if then_steps else 0.0)
                else_h, else_xs = _row(else_steps, else_y, "else_steps")
            content_h = then_h + else_h + (BRANCH_GAP if (then_steps and else_steps) else 0.0)

            # P4-B：then/else 命中区必须互不重叠。非空区按实际高度；空区给
            # 名义高度 NODE_H。特例：then 空而 else 非空时，布局上 else 紧贴
            # inner_y，then 无可视空间 → 不设 then 命中区（无从落起）。
            # 命中区横向同样覆盖整个组框（含左右内边距）：落在组框左边框内
            # = 插到该行首个子节点之前，落在右边框内 = 追加到该行区尾
            right = x + max(content_w + CONTAINER_PAD * 2, NODE_W)
            if then_h:
                placeholder._region_hit["then_steps"] = (
                    x, inner_y, right, inner_y + then_h)
                placeholder._region_xs["then_steps"] = then_xs
                else_y0 = inner_y + then_h + BRANCH_GAP
            elif else_h:
                else_y0 = inner_y
            else:
                placeholder._region_hit["then_steps"] = (
                    x, inner_y, right, inner_y + NODE_H)
                placeholder._region_xs["then_steps"] = []
                else_y0 = inner_y + NODE_H + BRANCH_GAP
            placeholder._region_hit["else_steps"] = (
                x, else_y0, right, else_y0 + max(else_h, NODE_H))
            placeholder._region_xs["else_steps"] = else_xs

        frame_w = max(content_w + CONTAINER_PAD * 2, NODE_W)
        frame_h = content_h + CONTAINER_HEADER + CONTAINER_PAD * 2
        placeholder.setRect(0.0, 0.0, frame_w, frame_h)
        placeholder.setPos(x, y)
        placeholder.update()
        return frame_w, frame_h

    # ---- 箭头 ----
    def _h_edge(self, x: float, y: float, node_w: float, node_h: float) -> None:
        """在节点左侧补一条横向「进入」箭头（表达从左到右的流向）。"""
        if x <= 30.0:
            return
        mid_y = y + node_h / 2.0
        e = ConnectionEdge(x - H_GAP + 6.0, mid_y - 1.0,
                           H_GAP - 12.0, 2.0, True, self._colors)
        self._scene.addItem(e)
        self._edges.append(e)

    # ------------------------------------------------------------------ #
    def _tag_child(self, child_dict: Dict[str, Any], parent_id: str,
                   region_key: str) -> None:
        """P4-B：把父容器 id 与子区键记到子节点上（子区内拖动改序用）。

        预览节点不注册（_node_by_id 取不到），天然跳过；id 唯一性由
        分支两区连续编号保证（da809c1），按 id 查节点不会错配。
        """
        node = self._node_by_id.get(str(child_dict.get("id", "")))
        if node is not None:
            node._parent_id = parent_id
            node._region_key = region_key

    def _register(self, node: CanvasNode, sid: str) -> None:
        # A3：预览节点（子工作流展开区）不注册——其 step_id 是子方案的
        # 位置 id，与主流程撞名会污染选中/落点/删除，语义不撞名也会虚增
        # 节点计数（node_count 恢复只算主流程）。
        if sid and not getattr(node, "_is_preview", False):
            self._node_by_id.setdefault(sid, node)

    def select_step(self, step_id: str) -> None:
        """按 step id 高亮节点（列表→画布联动）。"""
        for sid, node in self._node_by_id.items():
            node.set_selected(sid == str(step_id))
        self._scene.update()

    def selected_id(self) -> str:
        items = self._scene.selectedItems()
        return str(items[0].step_id) if items else ""

    def node_count(self) -> int:
        return len(self._node_by_id)

    def auto_layout(self) -> None:
        """按 Q4 方向（步骤横向、容器纵向）重新布局。"""
        self.set_steps(self._steps)

    # ------------------------------------------------------------------ #
    #  吸附与对齐参考线（阶段3）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _snap_to_grid(v: float) -> float:
        return round(v / GRID) * GRID

    def _sibling_left_edges(self, exclude: CanvasNode) -> List[float]:
        """同层兄弟节点的左边缘 x（用于对齐吸附，排除自身与容器）。"""
        out = []
        for node in self._node_by_id.values():
            if node is exclude or isinstance(node, ContainerNode):
                continue
            out.append(node.pos().x())
        return out

    def _apply_snap(self, node: CanvasNode, target_x: float,
                    target_y: float) -> Tuple[float, float]:
        """网格吸附 + 与兄弟左边缘对齐吸附；返回吸附后的 (x, y)。"""
        x = self._snap_to_grid(target_x)
        y = self._snap_to_grid(target_y)
        for ex in self._sibling_left_edges(node):
            if abs(ex - target_x) <= ALIGN_TOL:
                x = ex
                self._show_guide(ex, node.pos().y())
                break
        return x, y

    def _show_guide(self, x: float, y: float) -> None:
        if self._guide is None:
            self._guide = AlignGuide(x, y, NODE_H + 24.0, self._colors)
            self._scene.addItem(self._guide)
        else:
            self._guide.setPos(x, y)
            self._guide.setRect(0.0, 0.0, 1.5, NODE_H + 24.0)
        self._guide.update()

    def _clear_guide(self) -> None:
        if self._guide is not None:
            self._scene.removeItem(self._guide)
            self._guide = None

    # ------------------------------------------------------------------ #
    #  拖动即重排（Q1，阶段3）
    # ------------------------------------------------------------------ #
    def _drop_index_for(self, node: CanvasNode, scene_x: float) -> int:
        """按落点 x 计算该节点在**顶层**兄弟中的新索引（0-based）。

        规则：以各**顶层**兄弟节点左边缘为分界，落在谁左边就插到谁的位置。
        容器节点也参与（整体作为序列的一环）；嵌套子节点（id 含 "."）
        不参与——其归属由所在容器决定，而消费方
        （ui/tab_workflow_canvas.py 的 _on_canvas_reorder）只操作顶层列表。
        """
        sibs = []
        for other in self._node_by_id.values():
            if other is node or "." in other.step_id:
                continue
            sibs.append(other.pos().x())
        sibs.sort()
        for i, ex in enumerate(sibs):
            if scene_x < ex:
                return i
        return len(sibs)

    def _region_at(self, scene_pos: QPointF):
        """落点 → (container_step_id, region_key, index) 或 None（不在容器子区）。

        在所有已注册容器节点（A3 预览节点不注册，天然排除）中找**面积最小**
        的包含落点之子区——嵌套容器取最内层。区内索引按子节点左边缘算：
        落在第几个孩子左边就插到它前面（与顶层 _drop_index_for 同口径）。
        注意：返回纯 Python 数据；调用方 emit 后 handler 会同步重建场景，
        此后不得再碰图元对象。
        """
        best = None
        for node in self._node_by_id.values():
            if not isinstance(node, ContainerNode):
                continue
            hits = getattr(node, "_region_hit", None) or {}
            xs_map = getattr(node, "_region_xs", None) or {}
            for region_key, (x0, y0, x1, y1) in hits.items():
                if not (x0 <= scene_pos.x() <= x1
                        and y0 <= scene_pos.y() <= y1):
                    continue
                xs = sorted(xs_map.get(region_key, []))
                index = sum(1 for x in xs if x <= scene_pos.x())
                area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
                cand = (area, str(node.step_id), region_key, index)
                if best is None or cand[0] < best[0]:
                    best = cand
        if best is None:
            return None
        return best[1], best[2], best[3]

    def _region_index_for(self, node: CanvasNode,
                          scene_x: float) -> Optional[int]:
        """子节点在**所在子区**兄弟中的新索引（0-based，不含自身）。

        与顶层 _drop_index_for 同口径（以同区其他子节点左边缘为分界），
        但兄弟范围按布局时记录的 _parent_id/_region_key 收窄到**同容器
        同子区**——嵌套容器天然只与同层兄弟比，不会串区。父/区信息缺失
        （异常路径）返回 None，由调用方放弃发射。
        """
        parent_id = getattr(node, "_parent_id", "")
        region_key = getattr(node, "_region_key", "")
        if not parent_id or not region_key:
            return None
        sibs = []
        for other in self._node_by_id.values():
            if other is node:
                continue
            if getattr(other, "_parent_id", "") != parent_id:
                continue
            if getattr(other, "_region_key", "") != region_key:
                continue
            sibs.append(other.pos().x())
        sibs.sort()
        for i, ex in enumerate(sibs):
            if scene_x < ex:
                return i
        return len(sibs)

    def _is_self_or_descendant(self, dragged_id: str,
                               target_container_id: str) -> bool:
        """target_container 是否为 dragged 自身或其后代（沿 _parent_id 上溯）。

        跨容器搬运防环：把容器搬进自己 body 或后代容器 → 自嵌套（数据成环、
        编号/遍历皆错）。视图层在此拦截，handler 层还有一道双保险。
        """
        cur = str(target_container_id or "")
        seen = set()
        while cur:
            if cur == dragged_id:
                return True
            if cur in seen:               # 防御：标签链自身成环
                return False
            seen.add(cur)
            node = self._node_by_id.get(cur)
            if node is None:
                return False
            cur = str(getattr(node, "_parent_id", "") or "")
        return False

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        item = self.itemAt(event.pos())
        node = item if isinstance(item, CanvasNode) else None
        if node is None and item is not None:
            parent = item.parentItem()
            node = parent if isinstance(parent, CanvasNode) else None
        for sid, n in self._node_by_id.items():
            n.set_selected(n is node)
        if node is None:
            # 空白处按下：开启平移（左键拖拽），不触发节点选择/拖动
            if event.button() == Qt.LeftButton:
                self._panning = True
                self._pan_last = event.pos()
            return
        # A3：子工作流预览节点（展开区渲染）只读——其 step_id 是子方案的
        # 位置 id，与主流程撞名时 emit 会高亮/删除错误的真实步骤，故在此
        # 提前拦截。该 return 位于 emit/toggle 之前，不触发任何场景重建
        # （符合本函数的时序约束）；预览节点不可拖动，故不设 _drag_node。
        if getattr(node, "_is_preview", False):
            node.setSelected(True)
            self._clicked_id = None
            return
        # step id 是纯 Python 数据：先取出（下面的 emit/toggle 都会同步
        # 重建场景并销毁全部图元）
        step_id = node.step_id
        self._clicked_id = step_id
        # ⚠️ stepClicked 与 toggle_subworkflow 都会**同步**触发场景重建：
        #   stepClicked → focus_step_by_id → _rebuild_cards
        #     → _notify_canvas_changed → refresh_from_workflow → set_steps
        #   toggle_subworkflow → set_steps
        # 两次 scene.clear() 之后，press 时取到的 node 图元早已销毁。
        # 因此本函数**不得在 emit/toggle 之后再碰 press 时的 node 图元**；
        # 拖拽起始图元与原点统一放到函数末尾（所有重建结束后）按 id 取。
        # 画布→列表联动（发射时场景已重建，旧图元全部销毁）
        self.stepClicked.emit(step_id)
        # 阶段4：子工作流节点点击 → 展开/收起只读预览（Q3）。
        # toggle 内部还会再重建一次场景，必须放在最后。
        sub_node = self._node_by_id.get(step_id)
        if isinstance(sub_node, SubWorkflowNode):
            self.toggle_subworkflow(sub_node)
        if self._editable:
            # 所有同步重建均已结束，此时按 id 取到的才是存活的最终图元。
            # 若取不到（异常路径）则放弃本次拖动：mouseMoveEvent 有 None 守卫。
            final = self._node_by_id.get(step_id)
            self._drag_node = final
            if final is not None:
                final.setSelected(True)
                final.setZValue(900)      # 拖动中置顶
                self._drag_origin = final.pos()

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_last is not None:
            # 平移：按滚动条位移跟随光标；纯视图变换，不重建场景、不触发节点拖动
            delta = event.pos() - self._pan_last
            self._pan_last = event.pos()
            h, v = self.horizontalScrollBar(), self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            return
        if not self._editable or self._drag_node is None:
            super().mouseMoveEvent(event)
            return
        delta = event.pos() - self._drag_origin.toPoint()
        raw_x = self._drag_origin.x() + delta.x()
        raw_y = self._drag_origin.y() + delta.y()
        x, y = self._apply_snap(self._drag_node, raw_x, raw_y)
        self._drag_node.setPos(x, y)

    def mouseReleaseEvent(self, event):
        if self._panning:
            self._panning = False
            self._pan_last = None
            event.accept()
            return
        if self._editable and self._drag_node is not None:
            node = self._drag_node
            sid = node.step_id or ""
            # 全部换算必须在 auto_layout（= set_steps 重建，销毁全部图元）
            # **之前**完成，emit 只带纯 Python 数据（同步派发家族纪律）。
            pos = node.pos()                      # QPointF 快照
            nested = "." in sid
            # 落点归属：先试容器子区（_region_at 取面积最小包含区=最内层），
            # 未命中任何子区 → 顶层（索引按顶层兄弟左缘算）。
            hit = self._region_at(pos)
            if hit is not None:
                dst_parent, dst_region, dst_index = str(hit[0]), str(hit[1]), int(hit[2])
            else:
                dst_parent, dst_region = "", ""
                dst_index = self._drop_index_for(node, pos.x())
            cur_parent = str(getattr(node, "_parent_id", "") or "")
            cur_region = str(getattr(node, "_region_key", "") or "")
            same_spot = (dst_parent == cur_parent and dst_region == cur_region)
            # 同容器同区重排索引（既有口径，仅 same_spot 时用）
            if nested:
                region_index = self._region_index_for(node, pos.x())
            else:
                new_index = self._drop_index_for(node, pos.x())
            # 跨搬运防环：容器不能落入自身或后代子区
            cross_blocked = (not same_spot and dst_parent
                             and isinstance(node, ContainerNode)
                             and self._is_self_or_descendant(sid, dst_parent))
            node.setZValue(0)
            self._drag_node = None
            self._clear_guide()
            # 立即恢复自动布局（真实顺序由外部改数据后重建）
            self.auto_layout()
            if not sid:
                event.accept()
                return
            if same_spot:
                # 既有路径：顶层 stepReorderRequested / 同子区
                # stepReorderInRegionRequested，口径不变
                if not nested:
                    self.stepReorderRequested.emit(sid, new_index)
                elif region_index is not None:
                    self.stepReorderInRegionRequested.emit(
                        sid, cur_parent, cur_region, region_index)
            elif not cross_blocked:
                # A4 收尾：跨区/跨层/跨容器搬运（顶层↔容器、body→then、
                # then→else 等），源位置由 handler 按 id 全树定位移除
                self.stepMoveRequested.emit(
                    sid, dst_parent, dst_region, dst_index)
            # cross_blocked：防环拒绝，静默弹回（auto_layout 已恢复位置）
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        """滚轮缩放（光标为中心，限幅 0.2x~5x）。
        __init__ 已设 AnchorUnderMouse，故 scale 以光标为锚点。"""
        cur = self.transform().m11()
        if cur <= 0:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        nxt = cur * factor
        if nxt < 0.2 or nxt > 5.0:
            factor = max(0.2, min(5.0, nxt)) / cur
        self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event):
        """Delete 删除选中步骤；方向键微调选中节点（阶段4 打磨）。"""
        if (self._editable
                and event.key() in (Qt.Key_Delete, Qt.Key_Backspace)):
            # A3：预览节点（子工作流展开区）只读——它未注册进 _node_by_id，
            # 但 selected_id() 取的是场景选中项，其 step_id 是子方案的位置
            # id，与主流程撞名时会经 _on_canvas_delete 误删真实步骤。
            # （_selected_node() 只扫注册表取不到预览节点，故按场景选中判。）
            sel = self._scene.selectedItems()
            if sel and getattr(sel[0], "_is_preview", False):
                event.accept()
                return
            sid = self.selected_id() or self._clicked_id
            if sid:
                self.stepDeleteRequested.emit(sid)
                event.accept()
                return
        # 方向键微调选中节点位置（Shift 加速 4 倍），仅在未拖动时生效
        if self._editable and self._drag_node is None:
            node = self._selected_node()
            # A3：预览节点不参与微调（只读预览区）
            if node is not None and not getattr(node, "_is_preview", False):
                step = GRID if not (event.modifiers() & Qt.ShiftModifier) else GRID * 4
                dx = dy = 0.0
                if event.key() == Qt.Key_Left:
                    dx = -step
                elif event.key() == Qt.Key_Right:
                    dx = step
                elif event.key() == Qt.Key_Up:
                    dy = -step
                elif event.key() == Qt.Key_Down:
                    dy = step
                if dx or dy:
                    node.setPos(node.pos().x() + dx, node.pos().y() + dy)
                    event.accept()
                    return
        super().keyPressEvent(event)

    def _selected_node(self) -> Optional[CanvasNode]:
        for n in self._node_by_id.values():
            if n._selected or n.isSelected():
                return n
        return None

    # ------------------------------------------------------------------ #
    #  模块库拖入落点（阶段3）
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, event):
        if self._editable and event.mimeData().hasFormat(PaletteItemButton.MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._editable and event.mimeData().hasFormat(PaletteItemButton.MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not (self._editable
                and event.mimeData().hasFormat(PaletteItemButton.MIME_TYPE)):
            super().dropEvent(event)
            return
        payload = bytes(event.mimeData().data(PaletteItemButton.MIME_TYPE))
        try:
            import json as _json
            descriptor = _json.loads(payload.decode("utf-8"))
        except Exception:
            event.ignore()
            return
        scene_pos = self.mapToScene(event.pos())
        # P4-B：落点先试容器子区（loop body / branch then|else）。全部换算
        # 在 emit 前完成——信号同步派发，handler 会重建场景销毁全部图元，
        # 因此只把纯 Python 数据（str/int）带出，之后不碰任何图元。
        region = self._region_at(scene_pos)
        if region is not None:
            container_id, region_key, index = region
            self.paletteDropInContainer.emit(descriptor, container_id,
                                             region_key, index)
            event.acceptProposedAction()
            return
        # 落点 → 顶层插入索引（用最近的顶层节点左边缘做参照；
        # 容器计入、嵌套子节点（id 含 "."）不计，与 _drop_index_for 同口径）
        sib_xs = sorted(n.pos().x() for n in self._node_by_id.values()
                        if "." not in n.step_id)
        index = len(sib_xs)
        for i, ex in enumerate(sib_xs):
            if scene_pos.x() < ex:
                index = i
                break
        self.paletteDropRequested.emit(descriptor, index)
        event.acceptProposedAction()


# ── 文本辅助 ────────────────────────────────────────────────────────────────
def _subtitle_for(d: Dict[str, Any]) -> str:
    """叶子节点副标题：取关键参数摘要。"""
    params = d.get("params", {}) or {}
    prim = d.get("primitive", "")
    if not params:
        return ""
    if prim in ("click_anchor", "move_to_anchor", "move_offset"):
        a = params.get("anchor", "")
        if prim == "move_offset":
            return f"{a} ({params.get('dx', 0)},{params.get('dy', 0)})"
        return str(a)
    if prim == "press_key":
        return str(params.get("key", ""))
    if prim == "wait_ms":
        return f"{params.get('ms', '')} ms"
    if prim == "log":
        return str(params.get("message", ""))
    if prim == "copy":
        return f"→ {params.get('store_as', 'clipboard')}"
    if prim == "read_clipboard":
        # mode 走中文（与编辑器下拉用词一致），未知 mode 原样透出
        mode = TextResources.WF_CLIP_MODE_LABELS.get(
            params.get("mode", "read"), params.get("mode", "read"))
        return f"{mode} → {params.get('store_as', 'clipboard')}"
    return ""


def _container_title(d: Dict[str, Any], kind: str) -> str:
    """容器标题：loop 显示次数/网格/条件，branch 显示条件摘要。"""
    sid = str(d.get("id", ""))
    if kind == "loop":
        if d.get("grid"):
            g = d["grid"]
            return f"步骤 {sid} · 网格循环 {g.get('cols', '?')}×{g.get('rows', '?')}"
        if d.get("count") is not None:
            return f"步骤 {sid} · 循环 {d.get('count')} 次"
        if d.get("condition"):
            return f"步骤 {sid} · 循环（条件终止）"
        return f"步骤 {sid} · 循环"
    cond = d.get("condition", {}) or {}
    if "all" in cond or "any" in cond:
        key = "全部满足" if "all" in cond else "任一满足"
        return f"步骤 {sid} · 分支（{key}）"
    src = cond.get("source", "")
    op = cond.get("op", "")
    val = cond.get("value", "")
    return f"步骤 {sid} · 分支（{src} {op} {val}）"