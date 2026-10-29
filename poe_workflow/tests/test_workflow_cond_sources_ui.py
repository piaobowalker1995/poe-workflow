# -*- coding: utf-8 -*-
"""until/branch 条件源 UI 补齐：ctx_diff / rarity / affix / session / config。

背景：引擎 _eval_condition 支持 8 个条件源，但条件下拉只暴露
clipboard/ctx/counter 三个——ctx_diff（前后对比）、rarity（稀有度）、
affix（词缀裁决）、session（会话状态）、config（读配置开关，2026-10-23
腐化门）五个引擎支持却无 UI 入口，用户只能手写 json。本文件锁定补齐后的
编辑器行为：

- 源下拉 8 项（loop）；branch 仍禁 counter（P0-1 既定）→ 7 项；
- 字段联动：ctx/affix/session 显示「字段」输入框（占位文案随源切换）、
  ctx_diff 显示双变量输入框且隐藏「比较值」（引擎 _cmp(ctx[key_a], op,
  ctx[key_b]) 不用 value）、config 显示段名/键名输入框且仍比较 value、
  rarity 只留「比较值」、clipboard 显示规则行；
- 写入的 cond dict 可直接通过 validate_workflow（UI 与模型口径一致）。

注意：offscreen 下父窗口未 show 时 isVisible() 恒 False，可见性断言
用 isHidden()（显式 setVisible(False) 才置位）。
"""
import pytest
from PyQt5.QtWidgets import QComboBox, QLineEdit

from poe_workflow.workflow_model import validate_workflow, workflow_from_dict
from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _COND_SRC_LABELS, _new_step_dict


def _card(qapp, config_manager):
    tab = WorkflowTab(config_manager)
    d = _new_step_dict(tab)
    return StepCard(d, [d], tab, "1")


def _editor(card, cond, allow_counter=True):
    return card._build_condition_editor(cond, allow_counter=allow_counter)


def _src_combo(w):
    combos = w.findChildren(QComboBox)
    assert combos, "条件编辑器应含源/比较两个下拉"
    return combos[0]


def _field(w, placeholder):
    for le in w.findChildren(QLineEdit):
        if le.placeholderText() == placeholder:
            return le
    raise AssertionError(f"未找到占位文案为 {placeholder!r} 的输入框")


# ── 源下拉完整性 ────────────────────────────────────────────────────────────

def test_source_combo_lists_all_eight_sources(qapp, config_manager):
    """loop until：8 个源全暴露（与引擎 CONDITION_SOURCES 一致，含 config）。"""
    card = _card(qapp, config_manager)
    w = _editor(card, {"source": "clipboard"})
    labels = [(_src_combo(w).itemText(i)) for i in range(_src_combo(w).count())]
    assert labels == [l for l, _ in _COND_SRC_LABELS]
    assert len(labels) == 8
    values = {v for _, v in _COND_SRC_LABELS}
    assert values == {"clipboard", "ctx", "ctx_diff", "rarity", "affix",
                      "session", "counter", "config"}


def test_branch_condition_excludes_counter(qapp, config_manager):
    """branch：counter 仍禁用（P0-1：分支内循环索引恒 0，条件静默失效）。"""
    card = _card(qapp, config_manager)
    w = _editor(card, {"source": "clipboard"}, allow_counter=False)
    combo = _src_combo(w)
    labels = [combo.itemText(i) for i in range(combo.count())]
    assert "计数器" not in labels
    assert len(labels) == 7
    assert "前后差异" in labels and "稀有度" in labels and "配置开关" in labels


# ── 字段联动 ────────────────────────────────────────────────────────────────

def test_ctx_diff_shows_two_key_fields_hides_value(qapp, config_manager):
    """ctx_diff：显示双变量输入框，隐藏「比较值」（引擎不比 value）。"""
    card = _card(qapp, config_manager)
    cond = {"source": "clipboard"}
    w = _editor(card, cond)
    _src_combo(w).setCurrentText("前后差异")
    assert cond["source"] == "ctx_diff"
    ka = _field(w, "变量 A（如 before）")
    kb = _field(w, "变量 B（如 after）")
    assert not ka.isHidden() and not kb.isHidden()
    assert _field(w, "比较值").isHidden()
    ka.setText("before")
    kb.setText("after")
    assert cond["key_a"] == "before" and cond["key_b"] == "after"
    # 写出的 dict 直接过模型校验（UI 与模型口径一致）。
    # 注意 loop 只能有 count/condition/grid 之一——until 循环用 condition，不带 count。
    step = {"id": "1", "kind": "loop", "condition": cond,
            "body": [{"id": "1.1", "kind": "action", "primitive": "wait_ms",
                      "params": {"ms": 0}, "on_error": "retry", "delay_ms": 0}],
            "on_error": "retry", "delay_ms": 0}
    assert validate_workflow(workflow_from_dict(
        {"name": "t", "steps": [step]})) == []


def test_ctx_diff_initial_visibility_from_loaded_cond(qapp, config_manager):
    """加载即带 ctx_diff 的方案：构建时双变量框可见、内容回填。"""
    card = _card(qapp, config_manager)
    w = _editor(card, {"source": "ctx_diff", "op": "nequals",
                       "key_a": "before", "key_b": "after"})
    assert _src_combo(w).currentText() == "前后差异"
    ka = _field(w, "变量 A（如 before）")
    assert ka.text() == "before" and not ka.isHidden()
    assert _field(w, "变量 B（如 after）").text() == "after"
    assert _field(w, "比较值").isHidden()


def test_affix_shows_key_field_with_decision_placeholder(qapp, config_manager):
    """affix：显示「字段」输入框，占位文案提示裁决字段名。"""
    card = _card(qapp, config_manager)
    cond = {"source": "clipboard"}
    w = _editor(card, cond)
    _src_combo(w).setCurrentText("词缀裁决")
    key_f = _field(w, "裁决字段（如 final_decision）")
    assert not key_f.isHidden()
    assert not _field(w, "比较值").isHidden()
    key_f.setText("final_decision")
    assert cond["key"] == "final_decision"


def test_session_shows_key_field_with_status_placeholder(qapp, config_manager):
    card = _card(qapp, config_manager)
    cond = {"source": "clipboard"}
    w = _editor(card, cond)
    _src_combo(w).setCurrentText("会话状态")
    key_f = _field(w, "状态字段（如 ok）")
    assert not key_f.isHidden()
    key_f.setText("ok")
    assert cond["key"] == "ok"


def test_rarity_hides_key_field(qapp, config_manager):
    """rarity：只留「比较值」（值填稀有度英文），无字段输入框。"""
    card = _card(qapp, config_manager)
    cond = {"source": "clipboard"}
    w = _editor(card, cond)
    _src_combo(w).setCurrentText("稀有度")
    assert cond["source"] == "rarity"
    assert not _field(w, "比较值").isHidden()
    for le in w.findChildren(QLineEdit):
        if le.placeholderText() in ("变量名称（如 count）", "裁决字段（如 final_decision）",
                                    "状态字段（如 ok）", "变量 A（如 before）"):
            assert le.isHidden(), f"rarity 不应显示字段框：{le.placeholderText()}"


def _rule_container(w):
    """定位规则编辑器容器：其下拉末项为「自定义…」。"""
    for cb in w.findChildren(QComboBox):
        if cb.count() and cb.itemText(cb.count() - 1) == "自定义…":
            return cb.parent()
    raise AssertionError("clipboard 源应含规则编辑器")


def test_clipboard_still_shows_rule_row(qapp, config_manager):
    """clipboard：规则行可见性不回退（旧行为保持）。

    规则编辑器是嵌套容器（rule_w），setVisible 藏在父容器上——其内部
    子控件的 isHidden() 不随父容器显隐变化，故断言容器本身。
    """
    card = _card(qapp, config_manager)
    cond = {"source": "clipboard"}
    w = _editor(card, cond)
    rule_w = _rule_container(w)
    assert not rule_w.isHidden()
    # 切到 rarity 后规则行隐藏，切回 clipboard 恢复
    _src_combo(w).setCurrentText("稀有度")
    assert rule_w.isHidden()
    _src_combo(w).setCurrentText("剪贴板内容")
    assert not rule_w.isHidden()


def test_switch_back_and_forth_keeps_fields_consistent(qapp, config_manager):
    """ctx → ctx_diff → ctx 来回切换：字段可见性随之切换，无残留。"""
    card = _card(qapp, config_manager)
    cond = {"source": "ctx"}
    w = _editor(card, cond)
    key_f = _field(w, "变量名称（如 count）")
    assert not key_f.isHidden()
    _src_combo(w).setCurrentText("前后差异")
    assert key_f.isHidden()
    _src_combo(w).setCurrentText("上下文变量")
    assert not key_f.isHidden()
    assert _field(w, "比较值").isHidden() is False


def test_config_source_shows_section_and_key_fields(qapp, config_manager):
    """config（2026-10-23 腐化门）：显示段名/键名输入框，写入 cond 且过校验。"""
    card = _card(qapp, config_manager)
    cond = {"source": "clipboard"}
    w = _editor(card, cond)
    _src_combo(w).setCurrentText("配置开关")
    assert cond["source"] == "config"
    sec_f = _field(w, "段名（如 Strategy）")
    key_f = _field(w, "键名（如 enable_corruption）")
    assert not sec_f.isHidden() and not key_f.isHidden()
    # config 仍比较 value（配置项的值），规则行/其他字段框应隐藏
    assert not _field(w, "比较值").isHidden()
    sec_f.setText("Strategy")
    key_f.setText("enable_corruption")
    assert cond["section"] == "Strategy" and cond["key"] == "enable_corruption"
    step = {"id": "1", "kind": "branch", "condition": cond,
            "on_error": "retry", "delay_ms": 0,
            "then_steps": [], "else_steps": []}
    assert validate_workflow(workflow_from_dict(
        {"name": "t", "steps": [step]})) == []


def test_config_source_initial_visibility_from_loaded_cond(qapp, config_manager):
    """加载即带 config 的方案：构建时段名/键名框即可见（初始显隐同步）。"""
    card = _card(qapp, config_manager)
    cond = {"source": "config", "section": "Strategy",
            "key": "enable_corruption", "op": "equals", "value": "true"}
    w = _editor(card, cond)
    assert _src_combo(w).currentText() == "配置开关"
    assert _field(w, "段名（如 Strategy）").text() == "Strategy"
    assert not _field(w, "键名（如 enable_corruption）").isHidden()
