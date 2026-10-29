# -*- coding: utf-8 -*-
"""B+C 批 UI 侧回归：B2 坏 json 一致提示 / C1 未保存保护 / C2 运行快捷键绑当前方案。

依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）+ config_manager 夹具。
"""
import json
import os

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QCloseEvent
from PyQt5.QtWidgets import QLineEdit, QMessageBox

from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _canvas_color


def _good_file(name):
    return {
        "name": name,
        "version": 1,
        "steps": [
            {"id": "s1", "kind": "action", "primitive": "log",
             "params": {"message": "hi"}, "on_error": "retry",
             "retry_count": 1, "retry_delay_ms": 500, "delay_ms": 0},
        ],
    }


def _bad_json_bytes():
    # 结构非法：steps 不是数组；模型层 workflow_from_dict 会抛 WorkflowLoadError
    return json.dumps(
        {"name": "bad", "version": 1, "steps": "not-a-list"},
        ensure_ascii=False).encode("utf-8")


# ── B2：坏 json 一致、非崩溃、不残留半载 ────────────────────────────────────
def test_load_bad_json_shows_consistent_error_and_no_half_load(
        qapp, config_manager, tmp_path, monkeypatch):
    """坏 json：捕获模型层异常，下拉项标红 + 状态行报错，且不改动任何已载入状态。"""
    monkeypatch.setattr("poe_workflow.ui.tab_workflow._WORKFLOWS_DIR", str(tmp_path))
    (tmp_path / "bad.json").write_bytes(_bad_json_bytes())
    (tmp_path / "good.json").write_text(
        json.dumps(_good_file("good"), ensure_ascii=False), encoding="utf-8")

    tab = WorkflowTab(config_manager)          # __init__ 扫到空/坏文件不崩溃
    tab._refresh_schemes()                     # 把 bad/good 列进下拉
    before = list(tab._steps_dicts)            # 初始应为空列表（无半载）

    # 触发加载坏文件
    tab._load_file("bad.json")

    # 1) 不崩溃：已到此处即说明无未捕获异常
    # 2) 不残留半载：steps_dicts 未被坏数据覆盖
    assert tab._steps_dicts == before
    # 3) 下拉项标红（三处提示口径之一：下拉项标红）
    idx = tab._combo.findText("bad.json")
    assert idx >= 0
    fg = tab._combo.itemData(idx, Qt.ForegroundRole)
    assert isinstance(fg, QColor)
    # 标红色走主题错误色（error_text），不再写死 Qt.red
    assert fg == QColor(_canvas_color(tab, "error_text"))
    # 4) 状态行报错（三处提示口径之二：状态行报错），且为「方案加载失败」口径
    status = tab._editor_panel.status_label.text()
    assert "方案加载失败" in status


def test_load_good_json_clears_bad_mark(
        qapp, config_manager, tmp_path, monkeypatch):
    """好文件加载成功后：下拉项取消标红，steps 正常载入。"""
    monkeypatch.setattr("poe_workflow.ui.tab_workflow._WORKFLOWS_DIR", str(tmp_path))
    (tmp_path / "good.json").write_text(
        json.dumps(_good_file("good"), ensure_ascii=False), encoding="utf-8")

    tab = WorkflowTab(config_manager)
    tab._refresh_schemes()
    tab._load_file("good.json")

    # 注意：_rebuild_cards 会按位置重排步骤 id（派生为 "1"），故不校验磁盘 id，
    # 改为校验稳定字段与载入条数；下拉项应取消标红；dirty 已清除。
    assert len(tab._steps_dicts) == 1
    assert tab._steps_dicts[0]["params"]["message"] == "hi"
    idx = tab._combo.findText("good.json")
    assert tab._combo.itemData(idx, Qt.ForegroundRole) is None
    # 载入即与磁盘一致 -> dirty 清除
    assert tab._dirty is False


# ── C1：未保存保护 ────────────────────────────────────────────────────────
def test_dirty_flag_toggles(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    assert tab._dirty is False
    tab._mark_dirty()
    assert tab._dirty is True
    tab._clear_dirty()
    assert tab._dirty is False


def test_confirm_discard_clean_when_not_dirty(qapp, config_manager):
    """无改动时直接放行（不弹窗、返回 True）。"""
    tab = WorkflowTab(config_manager)
    assert tab._confirm_discard() is True


class _StubMessageBox(QMessageBox):
    """可控选择（save/discard/cancel）的 QMessageBox 替身，避免真实弹窗阻塞。"""
    _choice = "discard"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._clicked = None
        self._save = self._discard = self._cancel = None

    def addButton(self, text_or_btn, role=None):
        btn = super().addButton(text_or_btn, role)
        if text_or_btn == "保存":
            self._save = btn
        elif text_or_btn == "丢弃修改":
            self._discard = btn
        else:
            self._cancel = btn
        return btn

    def exec_(self):
        self._clicked = {
            "save": self._save, "discard": self._discard,
            "cancel": self._cancel,
        }.get(_StubMessageBox._choice, self._cancel)
        return 1

    def clickedButton(self):
        return self._clicked


def test_confirm_discard_cancel_keeps_dirty(qapp, config_manager, monkeypatch):
    """有改动 + 选「取消」：返回 False 且仍 dirty。"""
    monkeypatch.setattr("poe_workflow.ui.tab_workflow.QMessageBox", _StubMessageBox)
    _StubMessageBox._choice = "cancel"
    tab = WorkflowTab(config_manager)
    tab._mark_dirty()
    assert tab._confirm_discard() is False
    assert tab._dirty is True


def test_confirm_discard_discard_clears_dirty(qapp, config_manager, monkeypatch):
    """有改动 + 选「丢弃」：返回 True 且 dirty 清除。"""
    monkeypatch.setattr("poe_workflow.ui.tab_workflow.QMessageBox", _StubMessageBox)
    _StubMessageBox._choice = "discard"
    tab = WorkflowTab(config_manager)
    tab._mark_dirty()
    assert tab._confirm_discard() is True
    assert tab._dirty is False


def test_on_new_guarded_by_confirm(qapp, config_manager, monkeypatch):
    """_on_new 受未保存保护：取消则不改；放行则新建。"""
    tab = WorkflowTab(config_manager)
    # 构造一个已有内容的脏状态
    tab._steps_dicts = [_good_file("x")["steps"][0]]
    tab._mark_dirty()

    # 取消 -> 不新建
    monkeypatch.setattr(tab, "_confirm_discard", lambda: False)
    tab._on_new()
    assert len(tab._steps_dicts) == 1   # 未变

    # 放行 -> 新建（含一个默认步骤）
    monkeypatch.setattr(tab, "_confirm_discard", lambda: True)
    tab._on_new()
    assert len(tab._steps_dicts) == 1
    assert tab._dirty is True


def test_card_field_edit_marks_dirty(qapp, config_manager):
    """任意字段编辑（如 log 的 message 行）应触发 contentChanged -> dirty。"""
    tab = WorkflowTab(config_manager)
    d = {"id": "1", "kind": "action", "primitive": "log",
         "params": {"message": ""}, "on_error": "retry",
         "retry_count": 1, "retry_delay_ms": 500, "delay_ms": 0}
    card = StepCard(d, [d], tab, "1")
    le = card.findChild(QLineEdit)
    assert le is not None, "log 卡片应有 message QLineEdit"
    le.setText("hello")
    assert tab._dirty is True


def test_dialog_close_event_guarded(qapp, config_manager, monkeypatch):
    """WorkflowDialog 关闭受未保存保护：取消则忽略关闭，放行则接受。"""
    from poe_workflow.ui.dialog_workflow import WorkflowDialog
    dlg = WorkflowDialog(config_manager)
    wf = dlg._wf_tab
    wf._mark_dirty()

    # 取消 -> 关闭被忽略（ignore 后 isAccepted() 为 False）
    monkeypatch.setattr(wf, "_confirm_discard", lambda: False)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert ev.isAccepted() is False

    # 放行 -> 关闭被接受
    monkeypatch.setattr(wf, "_confirm_discard", lambda: True)
    ev2 = QCloseEvent()
    dlg.closeEvent(ev2)
    assert ev2.isAccepted() is True


# ── C2：运行快捷键绑当前方案（非默认 example_click_read.json）────────────────
def test_run_hotkey_binds_current_in_memory_scheme(
        qapp, config_manager, tmp_path, monkeypatch):
    """_on_hotkey -> _on_run 必须基于编辑器内存内容（_to_workflow_dict）构建引擎，
    而不是读默认文件 example_click_read.json。"""
    monkeypatch.setattr("poe_workflow.ui.tab_workflow._WORKFLOWS_DIR", str(tmp_path))
    tab = WorkflowTab(config_manager)
    tab._input = object()
    tab._coord = object()

    # 当前内存方案：一个独有的步骤（id 与默认文件不同），证明走的是内存而非默认文件
    tab._steps_dicts = [{
        "id": "CURRENT-ONLY", "kind": "action", "primitive": "log",
        "params": {"message": "from-editor"}, "on_error": "retry",
        "retry_count": 1, "retry_delay_ms": 500, "delay_ms": 0,
    }]

    captured = {}

    class _CaptureEngine:
        def __init__(self, *a, **k):
            pass

        def is_running(self):
            return False

        def load_def(self, wf):
            captured["wf"] = wf

        def start(self):
            captured["started"] = True

        def abort(self):
            pass

        on_status = on_finished = on_error = None

    monkeypatch.setattr("poe_workflow.ui.tab_workflow.WorkflowEngine", _CaptureEngine)
    tab._on_hotkey()                       # 经快捷键入口

    assert captured.get("started") is True
    assert captured.get("wf") is not None
    # 关键断言：引擎装载的是内存方案（id=CURRENT-ONLY），而非 example_click_read.json
    ids = [s.id for s in captured["wf"].steps]
    assert ids == ["CURRENT-ONLY"]
