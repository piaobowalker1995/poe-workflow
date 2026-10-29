# -*- coding: utf-8 -*-
"""「单击即捕获」按键编辑器单测（V3037-WF 批次）。

覆盖三块：
1. 捕获串 <-> press_key 参数串的双向转换（含鼠标键/滚轮/扩展键/修饰键组合）；
2. InputCaptureHook._held_modifiers 修饰键查询（假 user32 注入，确定性断言）；
3. StepCard press_key 编辑器：单击进入捕获、捕获回调写 params 并回显。
依赖 tests/conftest.py 的 qapp + config_manager 夹具（offscreen）。
"""
import pytest

from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QLineEdit

import modules.key_capture as kc
from modules.key_capture import InputCaptureHook
from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _new_step_dict, \
    _capture_to_presskey, _presskey_to_capture


# ---------------------------------------------------------------- 转换函数
@pytest.mark.parametrize("cap,tok", [
    ("Ctrl+Shift+A", "ctrl+shift+a"),
    ("Ctrl+MButton_Left", "ctrl+mouse_left"),
    ("MButton_Middle", "mouse_middle"),
    ("MWheel_Up", "mouse_wheel_up"),
    ("MWheel_Down", "mouse_wheel_down"),
    ("MButton_X1", "mouse_x1"),
    ("F12", "f12"),
    ("Enter", "enter"),
    ("", ""),
])
def test_capture_to_presskey(cap, tok):
    assert _capture_to_presskey(cap) == tok


@pytest.mark.parametrize("tok,cap", [
    ("ctrl+mouse_left", "Ctrl+MButton_Left"),
    ("mouse_wheel_down", "MWheel_Down"),
    ("mouse_x2", "MButton_X2"),
    ("f12", "F12"),
    ("ctrl+shift+f", "Ctrl+Shift+F"),
    ("", ""),
])
def test_presskey_to_capture(tok, cap):
    assert _presskey_to_capture(tok) == cap


def test_capture_round_trip():
    """捕获 -> 参数 -> 捕获 应回到原串（鼠标组合/滚轮/纯键盘）。"""
    for s in ("Ctrl+MButton_Left", "MWheel_Up", "Ctrl+Shift+A", "MButton_X2"):
        assert _presskey_to_capture(_capture_to_presskey(s)) == s


# ---------------------------------------------------------------- 修饰键查询
class _FakeUser32:
    """按给定虚拟键码集合返回按下状态的假 user32。"""

    def __init__(self, pressed):
        self._pressed = set(pressed)

    def GetAsyncKeyState(self, vk):
        return 0x8000 if vk in self._pressed else 0


@pytest.mark.parametrize("pressed,expect", [
    ({0x11, 0xA2}, ["Ctrl"]),                # 通用 Ctrl 与左 Ctrl 同时按下只算一次
    ({0xA4}, ["Alt"]),
    ({0xA0, 0xA1}, ["Shift"]),
    ({0x11, 0xA0}, ["Ctrl", "Shift"]),
    (set(), []),
])
def test_held_modifiers(pressed, expect, monkeypatch):
    monkeypatch.setattr(kc, "_user32", _FakeUser32(pressed))
    assert InputCaptureHook._held_modifiers(object()) == expect


# ---------------------------------------------------------------- StepCard 编辑器
class _FakeInput:
    """记录 capture_hotkey 回调的假输入模拟器。"""

    def __init__(self):
        self.cb = None

    def capture_hotkey(self, cb):
        self.cb = cb
        return True


def _presskey_card(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    tab._input = _FakeInput()
    d = _new_step_dict(tab)
    d["primitive"] = "press_key"
    d.setdefault("params", {})["key"] = "ctrl+mouse_left"
    card = StepCard(d, [d], tab, "1")
    return card, d


def _capture_box(card):
    boxes = [w for w in card.findChildren(QLineEdit)
             if w.isReadOnly() and w.placeholderText() == "单击后按下按键"]
    assert boxes, "press_key 编辑器应有只读捕获框"
    return boxes[0]


def test_presskey_editor_echo_saved_value(qapp, config_manager):
    """已保存的 ctrl+mouse_left 应回显为 Ctrl+MButton_Left。"""
    card, _ = _presskey_card(qapp, config_manager)
    assert _capture_box(card).text() == "Ctrl+MButton_Left"


def test_presskey_click_enters_capture_and_callback_writes_params(
        qapp, config_manager):
    """单击捕获框进入捕获态；回调送达后写入 params 并回显。"""
    card, d = _presskey_card(qapp, config_manager)
    box = _capture_box(card)
    QTest.mouseClick(box, Qt.LeftButton)
    tab = card._tab
    assert isinstance(tab._input, _FakeInput) and tab._input.cb is not None, \
        "单击后应调用 capture_hotkey 进入捕获态"
    tab._input.cb("Ctrl+MButton_Left")
    assert d["params"]["key"] == "ctrl+mouse_left"
    assert box.text() == "Ctrl+MButton_Left"


def test_presskey_capture_wheel_and_plain_key(qapp, config_manager):
    """滚轮与纯键盘键同样能落参数。"""
    card, d = _presskey_card(qapp, config_manager)
    box = _capture_box(card)
    tab = card._tab
    QTest.mouseClick(box, Qt.LeftButton)
    tab._input.cb("MWheel_Up")
    assert d["params"]["key"] == "mouse_wheel_up"
    assert box.text() == "MWheel_Up"
    QTest.mouseClick(box, Qt.LeftButton)
    tab._input.cb("F9")
    assert d["params"]["key"] == "f9"
    assert box.text() == "F9"


def test_presskey_click_shows_waiting_state(qapp, config_manager):
    """单击进入捕获后应立即清空旧值并显示「等待输入」占位提示，不再保留旧按键。"""
    card, _ = _presskey_card(qapp, config_manager)
    box = _capture_box(card)
    assert box.text() == "Ctrl+MButton_Left", "进入前应回显已存按键"
    QTest.mouseClick(box, Qt.LeftButton)
    assert box.text() == "", "进入捕获态应清空旧按键，避免误以为没在监听"
    assert box.placeholderText() == "请按下按键…（ESC 取消）"


def test_presskey_esc_restores_previous(qapp, config_manager):
    """捕获中按 ESC 应取消并恢复进入前的旧按键，不写入 'esc'。"""
    card, d = _presskey_card(qapp, config_manager)
    box = _capture_box(card)
    QTest.mouseClick(box, Qt.LeftButton)
    card._tab._input.cb("ESC")
    assert d["params"]["key"] == "ctrl+mouse_left", "ESC 不应改变已存按键"
    assert box.text() == "Ctrl+MButton_Left", "ESC 应恢复原回显"
    assert box.placeholderText() == "单击后按下按键"
