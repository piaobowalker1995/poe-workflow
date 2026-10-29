# -*- coding: utf-8 -*-
"""「单击输入框即捕获快捷键」的共用部件。

V3031-QF-002：原先每个 Tab 各自实现「热键输入框 + 捕获按钮」，交互不统一
（按钮文案不一：快捷指令 Tab 叫「捕获」，策略 Tab 叫「录入」）。现统一为
「单击输入框即进入捕获态」，两个 Tab 共用本模块，**不在 Tab 之间互相 import**，
也不在各 Tab 各留一份拷贝。

放在 ui/ 下独立模块而非 tab_hotkeys 的理由：
  1. tab_hotkeys 与 tab_strategy 是平级的选项卡实现，从其中任一个反向 import
     会形成 Tab 间耦合（tab_strategy → tab_hotkeys），后续若把捕获交互挪到第三个
     Tab 就会变成三角依赖；
  2. 本模块只依赖 PyQt5.QtCore/QtWidgets，不依赖任何 Tab、不依赖
     modules.config_manager，可独立单测；
  3. 与既有共享模块 ui/game_config_labels.py 同一组织方式（同为 ui/ 下的
     无状态 UI 辅助模块）。
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit

# 「单击即捕获」输入框的 tooltip 文案（系统热键区与快捷筛选区共用）
CAPTURE_CLICK_HINT = "单击后按下快捷键"


def mark_capture_clickable(line_edit: QLineEdit) -> None:
    """给「单击即捕获」的输入框加视觉提示（点指光标 + tooltip）。

    V3031-QF-002：去掉了独立的「捕获 / 录入」按钮，用户需要靠光标与 tooltip
    才知道输入框可点。
    """
    line_edit.setCursor(Qt.PointingHandCursor)
    line_edit.setToolTip(CAPTURE_CLICK_HINT)


def make_capture_click_handler(line_edit: QLineEdit, start_capture):
    """生成挂到 `line_edit.mousePressEvent` 的单击触发器。

    参数
    ----
    line_edit : QLineEdit
        被挂载的输入框（本函数把捕获逻辑与输入框绑定，故需传入而非从事件反查）。
    start_capture : callable(line_edit) -> None
        由调用方（各 Tab）提供的「开始捕获」入口。本模块**不关心**捕获目标 key
        的具体语义与各自的捕获/落盘/冲突逻辑，只负责把单击事件翻译成一次调用。

    返回
    ----
    一个可赋值给 `line_edit.mousePressEvent` 的函数。它会：
      1. 先给输入框焦点；
      2. 调用 start_capture(line_edit) 触发捕获；
      3. 再交给 QLineEdit 默认实现，保留焦点/光标行为
         （输入框为只读，无实际编辑副作用）。

    注意：各 Tab 自己的「开始捕获」入口需能接受 btn=None（已无独立按钮），
    本函数不传按钮。
    """
    def _on_mouse_press(event):
        line_edit.setFocus()
        start_capture(line_edit)
        QLineEdit.mousePressEvent(line_edit, event)
    return _on_mouse_press