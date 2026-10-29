# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's ui.main_window.MainWindow.

Minimal QMainWindow that exposes exactly what test_workflow_dialog.py asserts:
  - _tab_order: ordered list of tab labels, deliberately EXCLUDING the
    extracted workflow tabs (TAB_WORKFLOW / TAB_WORKFLOW_CANVAS).
  - open_workflow_dialog(): entry point the test checks for existence.
"""
from PyQt5.QtWidgets import QMainWindow
from modules.text_resources import TextResources


class MainWindow(QMainWindow):
    def __init__(self, cm, inp, coord, parser, fsm):
        super().__init__()
        self.cm = cm
        self.inp = inp
        self.coord = coord
        self.parser = parser
        self.fsm = fsm
        # Navigation tab order — does NOT include the extracted workflow tabs.
        self._tab_order = [
            TextResources.SYS_BTN_GAME_CONFIG,
            "通用",
            "地图",
            "坐标校准",
        ]

    def open_workflow_dialog(self):
        return None
