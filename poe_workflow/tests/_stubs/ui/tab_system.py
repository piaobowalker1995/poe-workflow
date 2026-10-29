# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's ui.tab_system.SystemTab.

Minimal QWidget rendering the two buttons test_workflow_dialog.py asserts on, in
the required order (游戏配置 before 工作流编排). Button texts come from the stub
TextResources so they match the constants the test compares against.
"""
from PyQt5.QtWidgets import QWidget, QPushButton, QVBoxLayout
from modules.text_resources import TextResources


class SystemTab(QWidget):
    def __init__(self, config_manager, parent=None):
        super().__init__(parent)
        self._cm = config_manager
        layout = QVBoxLayout(self)
        self._btn_game_config = QPushButton(TextResources.SYS_BTN_GAME_CONFIG)
        self._btn_workflow = QPushButton(TextResources.SYS_BTN_WORKFLOW)
        layout.addWidget(self._btn_game_config)
        layout.addWidget(self._btn_workflow)
