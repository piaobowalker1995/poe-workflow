# -*- coding: utf-8 -*-
"""工作流编排独立弹窗（用户 2026-10-18 定案）。

把「工作流编排」「工作流画布」及步骤编辑器抽屉从主窗口左侧导航剥离出来，
合并到一个**独立弹窗**里，入口按钮放在「系统设置」页「修改游戏配置」之后。

弹窗内部布局（水平三段）：
    ┌─────────────┬──────────────────────┬──────────────┐
    │ 模块库面板   │  列表视图 / 画布视图   │ 步骤编辑器    │
    │ (ModulePalette)│ (QStackedWidget)  │ (WorkflowEditorPanel) │
    └─────────────┴──────────────────────┴──────────────┘
列表视图与画布视图共享同一份步骤 dict 树（单一事实源），并双向选中联动。

复用要点：本类实现与 MainWindow 同名的 `set_right_drawer_widget` /
`set_right_drawer_visible` 两个 API，`WorkflowTab.showEvent` 通过
`hasattr(self.window(), ...)` 守卫调用，因此 WorkflowTab / WorkflowEditorPanel
**零改动**即可在弹窗内工作（抽屉展开/收起、面板注入全部沿用既有逻辑）。
"""
import logging
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter,
    QStackedWidget, QWidget,
)

from .text_resources import TextResources
from .tab_workflow import WorkflowTab
from .tab_workflow_canvas import WorkflowCanvasTab
from .workflow_palette import ModulePalette

logger = logging.getLogger(__name__)

_WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflows")


class WorkflowDialog(QDialog):
    """工作流编排弹窗：模块库 + 列表/画布双视图 + 步骤编辑器抽屉。"""

    def __init__(self, config_manager, input_simulator=None,
                 coord_engine=None, parser=None, parent=None):
        super().__init__(parent)
        self._cm = config_manager
        self.setWindowTitle("工作流编排")
        self.setObjectName("WorkflowDialog")
        self.resize(1500, 880)
        self.setSizeGripEnabled(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        header = QLabel("工作流编排：左侧模块库拖入/点击插入原语与子工作流，"
                        "中间为步骤列表与流程画布，右侧编辑器编辑选中步骤。")
        header.setWordWrap(True)
        header.setObjectName("StatusHint")
        root.addWidget(header)

        # ── 视图切换按钮行 ──
        view_row = QHBoxLayout()
        self._btn_list = QPushButton("列表视图")
        self._btn_list.setCheckable(True)
        self._btn_canvas = QPushButton("画布视图")
        self._btn_canvas.setCheckable(True)
        self._btn_list.clicked.connect(lambda: self._switch_view(0))
        self._btn_canvas.clicked.connect(lambda: self._switch_view(1))
        view_row.addWidget(self._btn_list)
        view_row.addWidget(self._btn_canvas)
        view_row.addStretch(1)
        self._status = QLabel("就绪")
        self._status.setObjectName("CanvasStatus")
        view_row.addWidget(self._status, stretch=1)
        root.addLayout(view_row)

        # ── 主体：模块库 | 视图栈 | 编辑器抽屉 ──
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setObjectName("WorkflowDialogSplitter")
        self._splitter.setChildrenCollapsible(False)

        # 左：模块库面板（阶段1 已有控件，抽屉里那套搬到这里常驻）
        self._palette = ModulePalette(_WORKFLOWS_DIR)
        self._palette.setMinimumWidth(150)
        self._palette.setMaximumWidth(260)
        self._splitter.addWidget(self._palette)

        # 中：列表视图 + 画布视图
        self._stack = QStackedWidget()
        # 中间视图显式保底下限 360（与 setSizes 公式的 mid 下限一致）：
        # QStackedWidget 的 minimumSizeHint 由页签内固定宽度工具行撑起（实测
        # ~586），窄屏下会把公式里「抽屉 360 / 中间 360」的保底顶掉——1024 宽
        # 实测抽屉被压到 268。显式下限让保底在布局引擎里生效；宽屏下 minimum
        # 不参与约束（请求宽度都大于它），行为不变。
        self._stack.setMinimumWidth(360)
        self._wf_tab = WorkflowTab(config_manager, input_simulator,
                                   coord_engine, parser)
        self._wf_canvas = WorkflowCanvasTab(config_manager, input_simulator,
                                            coord_engine, parser)
        self._stack.addWidget(self._wf_tab)        # 0 列表
        self._stack.addWidget(self._wf_canvas)     # 1 画布
        # 两视图共享数据源 + 双向联动
        self._wf_canvas.attach_workflow_tab(self._wf_tab)
        self._wf_tab.attach_canvas_tab(self._wf_canvas)
        # 弹窗内的模块库条目 → 插入到列表数据源
        self._palette.itemActivated.connect(self._on_palette_activated)
        self._splitter.addWidget(self._stack)

        # 右：步骤编辑器抽屉容器（WorkflowTab.showEvent 会把面板注入这里）
        self._right_drawer = QWidget()
        self._right_drawer.setObjectName("RightDrawer")
        drawer_layout = QVBoxLayout(self._right_drawer)
        drawer_layout.setContentsMargins(0, 0, 0, 0)
        self._right_drawer.setVisible(False)
        self._drawer_shown = False   # 抽屉「期望展开」标记（父窗口未 show 时依赖它）
        self._splitter.addWidget(self._right_drawer)

        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        root.addWidget(self._splitter, stretch=1)

        self._switch_view(0)
        # 画布默认开启可编辑（阶段3：拖动重排 / Delete / 模块库拖入）
        self._wf_canvas.set_canvas_editable(True)
        self._apply_default_sizes()

    def set_canvas_editable(self, on: bool) -> None:
        """透传：设置画布可编辑状态（画布页签的「可编辑」勾选框）。"""
        self._wf_canvas.set_canvas_editable(on)

    # ------------------------------------------------------------------ #
    def _apply_default_sizes(self):
        """初始三段宽度：模块库 ~200 / 主视图 剩余 / 编辑器 ~360。

        抽屉默认收起，中间主视图吃掉剩余宽度；主视图保留下限 360。
        """
        total = self._splitter.width() or max(self.width(), 1200)
        self._splitter.setSizes([200, max(360, total - 560), 360])

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        self._btn_list.setChecked(index == 0)
        self._btn_canvas.setChecked(index == 1)
        if index == 1:
            self._wf_canvas.refresh_from_workflow()

    def _on_palette_activated(self, descriptor):
        """弹窗内模块库点击 → 复用 WorkflowTab 的插入逻辑（生成合法 step）。"""
        try:
            self._wf_tab._on_palette_activated(descriptor)
            self._switch_view(0)   # 插入后切回列表，让用户看到结果
        except Exception as e:
            logger.error(f"模块库插入失败: {e}", exc_info=True)
            self._set_status(f"插入失败：{e}", "error")

    def _set_status(self, msg, level="info"):
        """状态行：颜色走主题（CanvasStatus 的 level 属性），不硬编码。"""
        self._status.setText(msg)
        self._status.setProperty("level", level)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    # ------------------------------------------------------------------ #
    #  与 MainWindow 同名的抽屉 API：WorkflowTab.showEvent 通过 hasattr 守卫调用，
    #  使既有 WorkflowTab / WorkflowEditorPanel 无需任何改动即可在弹窗内工作。
    # ------------------------------------------------------------------ #
    def set_right_drawer_widget(self, widget):
        """把控件注入右侧抽屉容器（先清空旧内容）。

        若 widget 已是抽屉当前控件则跳过，避免重复设置父子关系导致闪烁。
        """
        if self._right_drawer is None or widget is None:
            return
        layout = self._right_drawer.layout()
        if layout.count() == 1 and layout.itemAt(0).widget() is widget:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        layout.addWidget(widget, stretch=1)

    def set_right_drawer_visible(self, visible):
        """展开/收起右侧编辑器抽屉（拉开时主内容自动收窄，不遮挡）。"""
        if self._right_drawer is None:
            return
        if visible:
            if not self._right_drawer.isVisible():
                # 父级未 show 时 isVisible() 恒 False（offscreen / 未显示窗口），
                # 用显式标记记录「期望展开」，否则每次调用都会重设 splitter 比例。
                self._drawer_shown = True
                self._right_drawer.setVisible(True)
                total = self._splitter.width() or self.width()
                dw = max(360, int(total * 0.30))
                dw = min(dw, max(360, total - 560))   # 窄屏保护：左右保底
                left = min(200, self._palette.maximumWidth())  # 永不超 palette 上限
                mid = max(360, total - left - dw)     # 中间拿剩余，不置 0
                self._splitter.setSizes([left, mid, dw])
        else:
            self._drawer_shown = False
            self._right_drawer.setVisible(False)

    # ------------------------------------------------------------------ #
    def showEvent(self, event):
        """弹窗显示时：把编辑器面板注入抽屉并按勾选态展开。

        注意：WorkflowTab.showEvent 也会走同一套 hasattr 逻辑，两者幂等
        （set_right_drawer_widget 对同一控件直接返回），不会重复注入。
        """
        super().showEvent(event)
        try:
            self.set_right_drawer_widget(self._wf_tab._editor_panel)
            self.set_right_drawer_visible(self._wf_tab._btn_editor.isChecked())
        except Exception as e:
            logger.error(f"抽屉初始化失败: {e}", exc_info=True)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        """C1 未保存保护：关闭弹窗前，若方案有未保存修改，弹「保存/丢弃/取消」。

        用户「取消」则忽略关闭事件（event.ignore()），保留弹窗；否则放行。
        """
        wf = getattr(self, "_wf_tab", None)
        if wf is not None and not wf._confirm_discard():
            event.ignore()
            return
        event.accept()
