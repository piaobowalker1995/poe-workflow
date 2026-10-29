# -*- coding: utf-8 -*-
"""条件编辑器下拉 UI 测试（offscreen）：阈值下拉 + 词缀库多选。

2026-10-22 用户定案：
- T 阶 = 阶级阈值判定，比较值下拉只限 1~16（不可手打，越界就近收敛）；
- 百分比门槛（物品数量等）= 常用值下拉（20/50/70/90/100/120，可手打改）；
- 词缀/影响效果同库多选，组成「或」匹配（布尔）。
"""
from PyQt5.QtWidgets import QComboBox, QLineEdit, QListWidget
from PyQt5.QtCore import Qt

from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _new_step_dict, _build_rule_editor


def _branch_card(qapp, config_manager, cond):
    tab = WorkflowTab(config_manager)
    d = _new_step_dict(tab)
    d["kind"] = "branch"
    d["condition"] = cond
    card = StepCard(d, [d], tab, "1")
    return card, d


def test_tier_value_combo_lists_1_to_16(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "rule": "map_tier",
                            "op": "ge", "value": "15"})
    cb = card.findChild(QComboBox, "CondValueCombo")
    assert cb is not None, "数值比较应出现阈值下拉"
    assert [cb.itemText(i) for i in range(cb.count())] == [str(i) for i in range(1, 17)]
    assert cb.currentText() == "15"
    assert not cb.isEditable(), "阶级域只限 1~16，不允许手打"


def test_percent_value_combo_editable(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "rule": "item_quantity",
                            "op": "ge", "value": "70"})
    cb = card.findChild(QComboBox, "CondValueCombo")
    assert cb is not None
    assert [cb.itemText(i) for i in range(cb.count())] == \
        ["20", "50", "70", "90", "100", "120"]
    assert cb.isEditable(), "百分比门槛下拉应可手打改"
    assert cb.currentText() == "70"


def test_tier_out_of_range_clamped(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "rule": "map_tier",
                            "op": "ge", "value": "20"})
    assert d["condition"]["value"] == "16"      # 越界就近收敛并写回
    cb = card.findChild(QComboBox, "CondValueCombo")
    assert cb.currentText() == "16"


def test_text_op_falls_back_to_line_edit(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "op": "equals",
                            "value": "未鉴定"})
    cb = card.findChild(QComboBox, "CondValueCombo")
    le = card.findChild(QLineEdit, "CondValueEdit")
    assert not cb.isVisibleTo(card)
    assert le.isVisibleTo(card)
    assert le.text() == "未鉴定"


def test_op_switch_toggles_value_widgets(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "rule": "item_quantity",
                            "op": "ge", "value": "70"})
    cb = card.findChild(QComboBox, "CondValueCombo")
    le = card.findChild(QLineEdit, "CondValueEdit")
    op_cb = card.findChild(QComboBox, "CondOpCombo")
    assert cb.isVisibleTo(card) and not le.isVisibleTo(card)
    op_cb.setCurrentText("等于")                 # 切文本比较 -> 回落文本框
    assert not cb.isVisibleTo(card)
    assert le.isVisibleTo(card)
    assert d["condition"]["op"] == "equals"


def test_value_combo_writes_cond(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "rule": "item_quantity",
                            "op": "ge", "value": "70"})
    cb = card.findChild(QComboBox, "CondValueCombo")
    cb.setCurrentText("90")
    assert d["condition"]["value"] == "90"


def test_rule_switch_refreshes_combo_items(qapp, config_manager):
    card, d = _branch_card(qapp, config_manager,
                           {"source": "clipboard", "rule": "item_quantity",
                            "op": "ge", "value": "70"})
    cb = card.findChild(QComboBox, "CondValueCombo")
    rule_cb = None
    for w in card.findChildren(QComboBox):
        if w.currentText() == "物品数量":
            rule_cb = w
            break
    assert rule_cb is not None
    rule_cb.setCurrentText("地图阶级")            # 切规则 -> 阶级列表 + 值收敛
    assert [cb.itemText(i) for i in range(cb.count())] == \
        [str(i) for i in range(1, 17)]
    assert d["condition"]["rule"] == "map_tier"
    assert d["condition"]["value"] == "16"       # 70 越界收敛到 16


# ── 词缀库多选 ────────────────────────────────────────────────── #

def _build_rule_editor_capture():
    """以「自定义」当前规则构造（词缀库只在自定义区可见/可用）。"""
    got = []
    cur = {"pattern": "", "kind": "bool", "capture_group": 1}
    w = _build_rule_editor(cur, lambda rule, op: got.append((rule, op)))
    return w, got


def test_feature_library_multi_select_builds_or_pattern(qapp, config_manager):
    w, got = _build_rule_editor_capture()
    lw = w.findChild(QListWidget, "FeatureLibraryList")
    assert lw is not None
    assert lw.count() == 5
    lw.item(0).setCheckState(Qt.Checked)         # 元素荆棘
    lw.item(1).setCheckState(Qt.Checked)         # 无法再生
    rule, op = got[-1]
    assert rule["pattern"] == "元素荆棘|无法再生"
    assert rule["kind"] == "bool"
    assert op is None


def test_feature_library_influence_or_pattern(qapp, config_manager):
    w, got = _build_rule_editor_capture()
    lw = w.findChild(QListWidget, "FeatureLibraryList")
    lw.item(2).setCheckState(Qt.Checked)         # 起源者回忆影响
    lw.item(4).setCheckState(Qt.Checked)         # 裂界者影响
    rule, _ = got[-1]
    assert rule["pattern"] == r"被\s*起源者回忆\s*影响|被\s*裂界者\s*影响"
    assert rule["kind"] == "bool"


def test_feature_library_uncheck_clears_only_library_pattern(qapp, config_manager):
    w, got = _build_rule_editor_capture()
    lw = w.findChild(QListWidget, "FeatureLibraryList")
    lw.item(0).setCheckState(Qt.Checked)
    assert got[-1][0]["pattern"] == "元素荆棘"
    lw.item(0).setCheckState(Qt.Unchecked)       # 取消 -> 清掉库生成的 pattern
    assert got[-1][0]["pattern"] == ""


def test_feature_library_prechecks_existing_pattern(qapp, config_manager):
    got = []
    cur = {"pattern": r"被\s*裂界者\s*影响", "kind": "bool", "capture_group": 1}
    w = _build_rule_editor(cur, lambda rule, op: got.append((rule, op)))
    lw = w.findChild(QListWidget, "FeatureLibraryList")
    assert lw.item(4).checkState() == Qt.Checked          # 裂界者影响 预勾选
    assert lw.item(0).checkState() == Qt.Unchecked
