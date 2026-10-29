# -*- coding: utf-8 -*-
"""模块库面板（GUI 升级 阶段1）。

左侧 / 侧边面板：列出 10 个原子原语（按语义分组）+ workflows/ 下的子工作流方案。
点击条目 → 发射 itemActivated 信号，由 WorkflowTab 决定插入位置并生成步骤 dict。

设计约定（见 workflow_gui_upgrade_spec.md §2/§4 + MEMORY ⑥）：
- 面板根控件 objectName="ModulePalette"，子控件由 ui/theme.py 统一着色，不硬编码颜色。
- 拖拽入画布为 阶段3 能力；本阶段仅点击插入。
- 子工作流条目点击后，由接收方通过现有 on_error=jump + jump_target 机制引用（引擎零改动）。
"""
from __future__ import annotations

import os
import json
from typing import Dict, List, Tuple

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QScrollArea,
)
from PyQt5.QtCore import Qt, QMimeData, pyqtSignal
from PyQt5.QtGui import QDrag

from .text_resources import TextResources

# 原语分组（展示名 -> 原语键列表）；顺序即面板展示顺序
PRIMITIVE_GROUPS: List[Tuple[str, List[str]]] = [
    ("移动 / 定位", ["click_anchor", "move_to_anchor", "move_offset"]),
    ("输入操作", ["press_key"]),
    ("剪贴板", ["read_clipboard", "copy"]),
    ("流程控制", ["wait_ms", "recall_cell", "log", "abort"]),
    ("通货 / 会话", ["use_currency", "record_session", "pause"]),
    ("仓库 / 存仓", ["store_to_stash"]),
]


def _subworkflow_display_name(wf_dir: str, payload: str) -> str:
    """子工作流显示名：优先取 json 内 name 字段，失败回退文件名。

    payload 是不含 .json 的文件名（同时是 jump_target / 引擎引用键，
    显示层换名不动数据层）。坏 json 静默回退，面板不得因此崩。
    """
    try:
        path = os.path.join(wf_dir, payload + ".json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                name = str(json.load(f).get("name", "")).strip()
            if name:
                return name
    except Exception:
        pass
    return payload


class PaletteItemButton(QPushButton):
    """可拖拽的模块条目按钮。

    QPushButton 没有 setDragEnabled（那是 QAbstractItemView 的 API），因此这里
    手动实现「按住并移动超过阈值 → 发起 QDrag」的经典模式；点击插入仍照常触发
    clicked（拖动超过阈值时抑制点击，避免「拖完又插一次」）。
    """

    MIME_TYPE = "application/x-workflow-module"
    DRAG_THRESHOLD = 8  # px

    def __init__(self, text: str, typ: str, payload: str, parent=None):
        super().__init__(text, parent)
        self._drag_type = typ
        self._drag_payload = payload
        self._press_pos = None
        self._dragging = False
        self._suppress_click = False   # 本次按下是否已判定为拖拽（抑制 click）

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
            self._dragging = False
            self._suppress_click = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            return
        if (event.pos() - self._press_pos).manhattanLength() < self.DRAG_THRESHOLD:
            return
        self._dragging = True
        self._press_pos = None
        # 一旦越过阈值即判定为「拖拽」：本次按下产生的 click 必须抑制，
        # 否则拖放已插入一步 + click 又插一步 = 重复插入（在真机上会连带
        # 触发画布/卡片重建，把进程带崩）。
        self._suppress_click = True
        self._start_drag()

    def mouseReleaseEvent(self, event):
        was_dragging = self._dragging
        self._press_pos = None
        self._dragging = False
        if was_dragging:
            # 拖拽结束：**不要**调用 super()，否则 clicked 会同步再插一步。
            # event.accept() 吞掉本次释放，纯点击插入不受影响。
            event.accept()
            return
        self._suppress_click = False
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        import json as _json
        descriptor = {"type": self._drag_type, "payload": self._drag_payload}
        mime = QMimeData()
        mime.setData(self.MIME_TYPE,
                     _json.dumps(descriptor, ensure_ascii=False).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec_(Qt.CopyAction)


class ModulePalette(QWidget):
    """模块库面板：原语 + 子工作流，点击发射 itemActivated。"""

    # 描述符：{"type": "primitive"|"subworkflow", "payload": str}
    itemActivated = pyqtSignal(dict)

    def __init__(self, workflows_dir: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ModulePalette")
        self._wf_dir = workflows_dir
        self._buttons: List[QPushButton] = []
        self._inner_layout = None
        self._build()

    # ------------------------------------------------------------------ #
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        title = QLabel("模块库")
        title.setObjectName("PaletteTitle")
        root.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("PaletteScroll")
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self._inner_widget = inner
        self._inner_layout = v
        self._populate(v)

        v.addStretch(1)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _populate(self, v: QVBoxLayout) -> None:
        # 原语分组
        for group_label, prims in PRIMITIVE_GROUPS:
            hl = QLabel(group_label)
            hl.setObjectName("PaletteGroup")
            v.addWidget(hl)
            for p in prims:
                v.addWidget(self._make_item(
                    "primitive", p, TextResources.get_primitive_label(p)))
        # 子工作流
        sw_label = QLabel("子工作流")
        sw_label.setObjectName("PaletteGroup")
        v.addWidget(sw_label)
        names = self._scan_subworkflows()
        if names:
            for n in names:
                v.addWidget(self._make_item(
                    "subworkflow", n, _subworkflow_display_name(self._wf_dir, n)))
        else:
            hint = QLabel("（无）")
            hint.setObjectName("PaletteHint")
            v.addWidget(hint)

    def _make_item(self, typ: str, payload: str, text: str) -> QPushButton:
        btn = PaletteItemButton(text, typ, payload)
        btn.setObjectName("PaletteItem")
        btn.setProperty("palette_type", typ)
        btn.setProperty("palette_payload", payload)
        # 用默认参数绑定，避免闭包共享循环变量
        btn.clicked.connect(
            lambda _checked=False, t=typ, p=payload: self.itemActivated.emit(
                {"type": t, "payload": p}))
        # tooltip 露出数据层键（原语英文键 / 子工作流文件名）：显示名可中文化，
        # 排查「点击插入的是哪一个」时仍能对到序列化与引擎引用的真实键。
        btn.setToolTip(f"{text}（{payload}）")
        self._buttons.append(btn)
        return btn

    def _scan_subworkflows(self) -> List[str]:
        out: List[str] = []
        if self._wf_dir and os.path.isdir(self._wf_dir):
            for fn in sorted(os.listdir(self._wf_dir)):
                if fn.lower().endswith(".json"):
                    out.append(os.path.splitext(fn)[0])
        return out

    def refresh(self) -> None:
        """重新扫描子工作流（方案新增 / 删除后调用）。"""
        self._clear_layout(self._inner_layout)
        self._buttons.clear()
        self._populate(self._inner_layout)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
