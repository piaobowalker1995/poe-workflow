# -*- coding: utf-8 -*-
"""Stub of poe-mapmaker's modules.text_resources.TextResources.

WF_PRIMITIVE_LABELS and get_primitive_label are re-used from poe_workflow's own
UI text resources so they stay byte-identical to what the real poe_workflow
palette/canvas produce (the i18n tests compare against these exact values).

The remaining constants are the poe-mapmaker-specific navigation/tab labels that a
few tests reference. Their *values* only need to be internally consistent with
the stub ui.* classes (see ui/main_window.py and ui/tab_system.py), so any stable
strings work.
"""
from poe_workflow.ui.text_resources import TextResources as _PoeTextResources


class TextResources(_PoeTextResources):
    TAB_WORKFLOW = "工作流"
    TAB_WORKFLOW_CANVAS = "工作流画布"
    SYS_BTN_WORKFLOW = "工作流编排"
    SYS_BTN_GAME_CONFIG = "修改游戏配置"
