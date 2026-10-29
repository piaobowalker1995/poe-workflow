# -*- coding: utf-8 -*-
"""POE-MapMaker 视觉风格（浅色 / 深色）主题。

基于 UI demo 的「浅色扁平 / 霓虹赛博」改编，落地到真实应用。
仅保留两套：
  - light (浅色)   —— 改编自 demo 浅色扁平
  - dark  (深色)   —— 改编自 demo 霓虹赛博（名称在 UI 上显示为「深色」）

覆盖真实项目用到的全部控件类型；TabWidget/TabBar 也一并主题化，
否则深色下原生标签页会是白色、与整体割裂。
危险按钮统一用 objectName="DangerBtn" 着色（红）。
"""

# ───────────────────────────────────────────────────────────────────────────
# 浅色（light）—— 浅灰底、深字、蓝色主色
# ───────────────────────────────────────────────────────────────────────────
LIGHT_QSS = """
QWidget { background:#f4f6f8; color:#23272e; font-family:"Microsoft YaHei",sans-serif; font-size:13px; }
QLabel#Title { color:#1565c0; font-size:18px; font-weight:bold; }
QPushButton { background:#1565c0; color:#ffffff; border:none; padding:5px 12px; font-size:12px; border-radius:5px; }
QPushButton:hover { background:#1976d2; }
QPushButton:checked { background:#1565c0; color:#ffffff; }
QPushButton:checked:hover { background:#1976d2; }
QPushButton:disabled { background:#b8c2cc; color:#eef2f6; }
QPushButton#DangerBtn { background:#e53935; color:#ffffff; border:none; }
QPushButton#DangerBtn:hover { background:#c62828; }
QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QComboBox {
    background:#ffffff; border:1px solid #cfd6dd; border-radius:4px; padding:4px; color:#23272e; }
QGroupBox { border:1px solid #d0d6dd; border-radius:6px; margin-top:10px; padding:10px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; color:#1565c0; }
QListWidget::item:selected { background:#d6e4f5; color:#1565c0; }
QListWidget::item:hover { background:#e8f0fa; }
QListWidget#Nav { background:#e9edf2; border:none; border-right:1px solid #d0d6dd; outline:0; }
QListWidget#Nav::item { padding:4px 14px; color:#23272e; border-bottom:1px solid #dce1e7; }
QListWidget#Nav::item:selected { background:#1565c0; color:#ffffff; border-left:3px solid #1565c0; }
QListWidget#Nav::item:hover { background:#e3edf9; }
QCheckBox, QRadioButton { color:#23272e; spacing:6px; }
QCheckBox::indicator { width:14px; height:14px; border-radius:3px; border:1px solid #cfd6dd; background:#ffffff; }
QCheckBox::indicator:checked { background:#1565c0; border:1px solid #1565c0; }
QRadioButton::indicator { width:14px; height:14px; border-radius:7px; }
QRadioButton::indicator:unchecked { background:#cfd6dd; }
QRadioButton::indicator:checked { background:#1565c0; border:2px solid #ffffff; }
QSlider::groove:horizontal { background:#d0d6dd; height:6px; border-radius:3px; }
QSlider::handle:horizontal { background:#1565c0; width:14px; border-radius:7px; margin:-4px 0; }
QProgressBar { background:#e3e8ee; border:1px solid #cfd6dd; border-radius:4px; height:16px; text-align:center; }
QProgressBar::chunk { background:#1565c0; border-radius:3px; }
QStatusBar { background:#e9edf2; color:#555; }
QTextEdit#LogView { background:#eef1f5; color:#23272e; border:1px solid #cfd6dd; border-radius:4px; font-family:"Consolas","Microsoft YaHei",monospace; font-size:12px; }
QLabel#StatusBar { background:#f4f6f8; color:#000000; padding:3px 4px; font-size:12px; }
QWidget#RightDrawer { background:#f4f6f8; border-left:1px solid #cfd6dd; }
#AboutCoordNote { color:#555555; font-size:12px; }
QTabWidget::pane { border:1px solid #d0d6dd; border-radius:4px; }
QTabBar::tab { background:#e9edf2; color:#555; padding:6px 12px; border:1px solid #d0d6dd;
                border-bottom:none; border-top-left-radius:4px; border-top-right-radius:4px; }
QTabBar::tab:selected { background:#ffffff; color:#1565c0; }
QTabBar::tab:hover { background:#e8f0fa; }
QComboBox QAbstractItemView { background:#ffffff; color:#23272e; selection-background-color:#d6e4f5; }
QLabel#StatusHint { color:#6b7683; font-size:12px; }
QLabel#CanvasStatus { font-size:12px; color:#555555; }
QLabel#CanvasStatus[level="ok"] { color:#2e7d32; }
QLabel#CanvasStatus[level="error"] { color:#c62828; }
QLabel#CanvasStatus[level="info"] { color:#1565c0; }
QLabel#CanvasStatus[level="muted"] { color:#8a97a4; }
QWidget#WorkflowDialog { background:#f4f6f8; }
QWidget#WorkflowDialogSplitter::handle { background:#d0d6dd; }
QWidget#WorkflowDialogSplitter::handle:horizontal { width:3px; }
QLabel#PaletteTitle { color:#1565c0; font-size:13px; font-weight:bold; }
QLabel#PaletteGroup { color:#6b7683; font-size:12px; font-weight:bold; padding-top:4px; }
QLabel#PaletteHint { color:#8a97a4; font-size:12px; }
QScrollArea#PaletteScroll { background:#eef1f5; border:1px solid #d0d6dd; border-radius:4px; }
QPushButton#PaletteItem { background:#ffffff; color:#23272e; border:1px solid #cfd6dd;
                          padding:4px 8px; font-size:12px; text-align:left; }
QPushButton#PaletteItem:hover { background:#e8f0fa; border-color:#1565c0; }
QPushButton#PaletteItem:pressed { background:#d6e4f5; }
QPushButton#PaletteItem[palette_type="subworkflow"] { border-color:#6a1b9a; }
QPushButton#PaletteItem[palette_type="subworkflow"]:hover { border-color:#8e24aa; }
QGroupBox#StepCardOuter-action { border:1px solid #1565c0; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardOuter-loop { border:1px solid #2e7d32; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardOuter-branch { border:1px solid #ef6c00; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardOuter-sub { border:1px solid #6a1b9a; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardChildArea { border:1px dashed #7a8a99; margin-top:6px; padding-top:10px; }
QLabel#StepCardTitle { font-weight:bold; }
"""

# ───────────────────────────────────────────────────────────────────────────
# 深色（dark）—— 近黑底、青色霓虹描边
# ───────────────────────────────────────────────────────────────────────────
DARK_QSS = """
QWidget { background:#0a0e1a; color:#cfefff; font-family:"Consolas","Microsoft YaHei",monospace; font-size:13px; }
QLabel#Title { color:#5cffd6; font-size:18px; font-weight:bold; }
QPushButton { background:#0d2236; color:#00e5ff; border:1px solid #00e5ff; padding:5px 12px; font-size:12px; border-radius:4px; }
QPushButton:hover { background:#0a2236; color:#5cffd6; }
QPushButton:checked { background:#0d3a4a; color:#00e5ff; border:1px solid #00e5ff; }
QPushButton:checked:hover { background:#12556b; }
QPushButton:disabled { background:#06121f; color:#2a5a66; border:1px solid #0a3a44; }
QPushButton#DangerBtn { background:#ef4444; color:#ffffff; border:1px solid #ef4444; }
QPushButton#DangerBtn:hover { background:#dc2626; }
QLineEdit, QPlainTextEdit, QTextEdit, QListWidget, QComboBox {
    background:#08101e; color:#cfefff; border:1px solid #0a3a44; border-radius:4px; padding:4px; }
QGroupBox { border:1px solid #0a3a44; border-radius:6px; margin-top:10px; padding:10px; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 4px; color:#00e5ff; }
QListWidget::item:selected { background:#0d2c3a; color:#5cffd6; }
QListWidget::item:hover { background:#0a2236; }
QListWidget#Nav { background:#0d1426; border:none; border-right:1px solid #0a3a44; outline:0; }
QListWidget#Nav::item { padding:4px 14px; color:#cfefff; border-bottom:1px solid #0a2236; }
QListWidget#Nav::item:selected { background:#00e5ff; color:#00210f; border-left:3px solid #00e5ff; }
QListWidget#Nav::item:hover { background:#0a2236; }
QCheckBox, QRadioButton { color:#cfefff; spacing:6px; }
QCheckBox::indicator { width:14px; height:14px; border-radius:3px; border:1px solid #0a3a44; background:#0d1426; }
QCheckBox::indicator:checked { background:#00e5ff; border:1px solid #00e5ff; }
QRadioButton::indicator { width:14px; height:14px; border-radius:7px; }
QRadioButton::indicator:unchecked { background:#08101e; border:1px solid #0a3a44; }
QRadioButton::indicator:checked { background:#00e5ff; border:2px solid #0a0e1a; }
QSlider::groove:horizontal { background:#08101e; height:6px; border-radius:3px; border:1px solid #0a3a44; }
QSlider::handle:horizontal { background:#00e5ff; width:14px; border-radius:7px; margin:-4px 0; }
QProgressBar { background:#08101e; border:1px solid #0a3a44; border-radius:4px; height:16px; text-align:center; }
QProgressBar::chunk { background:#00e5ff; border-radius:3px; }
QStatusBar { background:#05080f; color:#36e0ff; }
QTextEdit#LogView { background:#060a14; color:#cfefff; border:1px solid #0a3a44; border-radius:4px; font-family:"Consolas","Microsoft YaHei",monospace; font-size:12px; }
QLabel#StatusBar { background:#0a0e1a; color:#cfefff; padding:3px 4px; font-size:12px; }
QWidget#RightDrawer { background:#0a0e1a; border-left:1px solid #0a3a44; }
#AboutCoordNote { color:#cfefff; font-size:12px; }
QTabWidget::pane { border:1px solid #0a3a44; border-radius:4px; }
QTabBar::tab { background:#0d1426; color:#36e0ff; padding:6px 12px; border:1px solid #0a3a44;
                border-bottom:none; border-top-left-radius:4px; border-top-right-radius:4px; }
QTabBar::tab:selected { background:#0a2236; color:#5cffd6; border:1px solid #00e5ff; }
QTabBar::tab:hover { background:#0a2236; }
QComboBox QAbstractItemView { background:#08101e; color:#cfefff; selection-background-color:#0d2c3a; }
QLabel#StatusHint { color:#7f95a3; font-size:12px; }
QLabel#CanvasStatus { font-size:12px; color:#9fb6c4; }
QLabel#CanvasStatus[level="ok"] { color:#5cffd6; }
QLabel#CanvasStatus[level="error"] { color:#ff6b6b; }
QLabel#CanvasStatus[level="info"] { color:#00e5ff; }
QLabel#CanvasStatus[level="muted"] { color:#5f7d8c; }
QWidget#WorkflowDialog { background:#0a0e1a; }
QWidget#WorkflowDialogSplitter::handle { background:#0a3a44; }
QWidget#WorkflowDialogSplitter::handle:horizontal { width:3px; }
QLabel#PaletteTitle { color:#5cffd6; font-size:13px; font-weight:bold; }
QLabel#PaletteGroup { color:#7f95a3; font-size:12px; font-weight:bold; padding-top:4px; }
QLabel#PaletteHint { color:#5f7d8c; font-size:12px; }
QScrollArea#PaletteScroll { background:#08101e; border:1px solid #0a3a44; border-radius:4px; }
QPushButton#PaletteItem { background:#0d1426; color:#cfefff; border:1px solid #0a3a44;
                          padding:4px 8px; font-size:12px; text-align:left; }
QPushButton#PaletteItem:hover { background:#0a2236; border-color:#00e5ff; }
QPushButton#PaletteItem:pressed { background:#0d3a4a; }
QPushButton#PaletteItem[palette_type="subworkflow"] { border-color:#ce93d8; }
QPushButton#PaletteItem[palette_type="subworkflow"]:hover { border-color:#e1bee7; }
QGroupBox#StepCardOuter-action { border:1px solid #00e5ff; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardOuter-loop { border:1px solid #5cffd6; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardOuter-branch { border:1px solid #ffb74d; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardOuter-sub { border:1px solid #ce93d8; border-radius:4px; margin-top:6px; padding-top:10px; }
QGroupBox#StepCardChildArea { border:1px dashed #2a5a66; margin-top:6px; padding-top:10px; }
QLabel#StepCardTitle { font-weight:bold; }
"""

DEFAULT_THEME = "light"

# 内部键 -> UI 显示名（用户要求的「浅色 / 深色」）
THEME_DISPLAY = {
    "light": "浅色",
    "dark": "深色",
}

# 内部键 -> QSS
_QSS_MAP = {
    "light": LIGHT_QSS,
    "dark": DARK_QSS,
}


def get_qss(key: str) -> str:
    """返回指定主题的 QSS；非法键回退默认主题。"""
    return _QSS_MAP.get(key, _QSS_MAP[DEFAULT_THEME])


# 内部键 -> 富文本超链接颜色。
# QSS 管不到 QTextEdit/QTextDocument 文档内部的 <a>（那不是控件），
# 富文本里的链接色要用 QTextDocument.setDefaultStyleSheet 单独指定。
LINK_COLOR = {
    "light": "#1565c0",   # 蓝
    "dark": "#4fc3f7",    # 亮蓝（深底上更清楚）
}


def get_link_color(key: str) -> str:
    """返回指定主题的富文本超链接颜色；非法键回退默认主题。"""
    return LINK_COLOR.get(key, LINK_COLOR[DEFAULT_THEME])


# ───────────────────────────────────────────────────────────────────────────
# 画布配色（GUI 升级 阶段2）
# QGraphicsItem 不走 QSS（那是控件样式表，管不到图元），因此画布节点/连线
# 的颜色必须像 LINK_COLOR 一样按主题显式取值，禁止在图元里硬编码颜色。
# ───────────────────────────────────────────────────────────────────────────
CANVAS_COLORS = {
    "light": {
        "canvas_bg":   "#eef1f5",
        "node_fill":   "#ffffff",
        "node_border": "#1565c0",
        "node_text":   "#23272e",
        "grid_text":   "#8a97a4",
        "loop_border": "#2e7d32",
        "loop_fill":   "#f1f8f2",
        "branch_border": "#ef6c00",
        "branch_fill": "#fdf3e7",
        "sub_border":  "#6a1b9a",
        "sub_fill":    "#f6eefb",
        "edge":        "#7a8a99",
        "selected":    "#d6e4f5",
        "error_text":  "#c62828",   # 错误文字（如方案加载失败标红），浅/深底均清晰
        "header_text": "#ffffff",   # 容器组框标题栏文字（标题栏底色=loop/branch_border）
    },
    "dark": {
        "canvas_bg":   "#08101e",
        "node_fill":   "#0d2236",
        "node_border": "#00e5ff",
        "node_text":   "#cfefff",
        "grid_text":   "#5f7d8c",
        "loop_border": "#5cffd6",
        "loop_fill":   "#0a2a22",
        "branch_border": "#ffb74d",
        "branch_fill": "#2a1f0d",
        "sub_border":  "#ce93d8",
        "sub_fill":    "#241233",
        "edge":        "#2a5a66",
        "selected":    "#0d3a4a",
        "error_text":  "#ff6b6b",   # 错误文字（浅亮红，深底上更清楚）
        "header_text": "#08101e",   # 深色主题标题栏底色为浅色（#5cffd6/#ffb74d），文字须深色
    },
}


def get_canvas_colors(key: str) -> dict:
    """返回指定主题的画布配色字典；非法键回退默认主题。"""
    return CANVAS_COLORS.get(key, CANVAS_COLORS[DEFAULT_THEME])


def theme_keys() -> list:
    """可用主题键列表（顺序固定：light, dark）。"""
    return list(_QSS_MAP.keys())
