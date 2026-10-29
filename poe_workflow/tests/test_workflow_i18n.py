# -*- coding: utf-8 -*-
"""工作流编排模块 汉化（显示层中文化，数据层不动）单元测试。

覆盖「工作流编排」i18n 定案：
- 模块库 13 个原语按钮文本 == TextResources.WF_PRIMITIVE_LABELS，
  且 palette_payload 仍为英文键（显示变、数据不变）
- 子工作流按钮文本 == workflows/*.json 的 name 字段（读真实目录）
- 画布叶子节点标题为中文（数据层 primitive 键不变）
- get_primitive_label 未知键回退键本身、空串回退空串
- 模块库按钮 tooltip 露出数据层键（原语英文键 / 子工作流文件名）
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）。
"""
import json
import os

from modules.text_resources import TextResources
from poe_workflow.ui.workflow_canvas import WorkflowCanvasView
from poe_workflow.ui.workflow_palette import ModulePalette

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(REPO_ROOT, "workflows")


def _leaf(sid, prim="move_to_anchor", **params):
    return {"id": sid, "kind": "action", "primitive": prim,
            "params": params or {"anchor": "a"},
            "on_error": "retry", "retry_count": 1,
            "retry_delay_ms": 500, "delay_ms": 0}


def _palette():
    return ModulePalette(WORKFLOWS_DIR)


def _prim_buttons(palette):
    return [b for b in palette._buttons
            if b.property("palette_type") == "primitive"]


def _sub_buttons(palette):
    return [b for b in palette._buttons
            if b.property("palette_type") == "subworkflow"]


# ── 1. 原语按钮：显示中文、数据层英文键 ──────────────────────────────────────
def test_primitive_buttons_show_chinese_labels(qapp):
    """14 个原语按钮文本为中文，palette_payload 保持英文键。"""
    palette = _palette()
    btns = _prim_buttons(palette)
    assert len(btns) == len(TextResources.WF_PRIMITIVE_LABELS) == 14, \
        f"原语按钮数 {len(btns)} 与 WF_PRIMITIVE_LABELS 不一致"
    for btn in btns:
        payload = btn.property("palette_payload")
        assert payload in TextResources.WF_PRIMITIVE_LABELS, \
            f"payload {payload!r} 不是已知原语键"
        assert btn.text() == TextResources.WF_PRIMITIVE_LABELS[payload], \
            f"原语 {payload} 按钮文本应为中文名：{btn.text()!r}"
        # 显示层换名不动数据层：payload 仍是英文键（插入/jump_target 契约）
        assert payload.isascii(), f"数据层键不应中文化：{payload!r}"


# ── 2. 子工作流按钮：显示 json name、数据层文件名 ─────────────────────────────
def test_subworkflow_buttons_show_json_name(qapp):
    """子工作流按钮文本取 workflows/*.json 的 name 字段。"""
    palette = _palette()
    subs = _sub_buttons(palette)
    assert subs, "模块库应至少列出一个子工作流"
    for btn in subs:
        payload = btn.property("palette_payload")   # 不含 .json 的文件名
        path = os.path.join(WORKFLOWS_DIR, payload + ".json")
        with open(path, "r", encoding="utf-8") as f:
            expected = str(json.load(f).get("name", "")).strip()
        assert expected, f"{payload}.json 缺少 name 字段"
        assert btn.text() == expected, \
            f"子工作流 {payload} 显示名应取 json name：{btn.text()!r}"
        # 数据层仍按文件名引用（jump_target / 引擎加载契约不变）
        assert btn.property("palette_payload") == payload


def test_subworkflow_display_name_falls_back_to_filename(qapp, tmp_path):
    """坏 json / 缺 name：静默回退文件名，面板不得因此崩。"""
    from poe_workflow.ui.workflow_palette import _subworkflow_display_name
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "noname.json").write_text('{"steps": []}', encoding="utf-8")
    (tmp_path / "ok.json").write_text(
        '{"name": " 带空格的名字 "}', encoding="utf-8")
    assert _subworkflow_display_name(str(tmp_path), "broken") == "broken"
    assert _subworkflow_display_name(str(tmp_path), "noname") == "noname"
    assert _subworkflow_display_name(str(tmp_path), "missing") == "missing"
    # name 前后空白应被 strip
    assert _subworkflow_display_name(str(tmp_path), "ok") == "带空格的名字"


# ── 3. 画布叶子节点：标题中文、数据层不变 ─────────────────────────────────────
def test_canvas_leaf_title_is_chinese(qapp):
    """画布叶子节点标题为中文；read_clipboard 副标题 mode 也走中文。"""
    v = WorkflowCanvasView()
    v.set_steps([
        _leaf("1"),
        _leaf("2", "read_clipboard", mode="match", store_as="clipboard"),
    ])
    labels = TextResources.WF_PRIMITIVE_LABELS
    assert v._node_by_id["1"]._title == labels["move_to_anchor"]
    assert v._node_by_id["2"]._title == labels["read_clipboard"]
    # mode 中文化：match -> 匹配
    assert v._node_by_id["2"]._subtitle == "匹配 → clipboard", \
        f"read_clipboard 副标题应中文化：{v._node_by_id['2']._subtitle!r}"


def test_canvas_unknown_mode_subtitle_passthrough(qapp):
    """未知 mode 原样透出（防御旧文件/新枚举），不炸不丢信息。"""
    v = WorkflowCanvasView()
    v.set_steps([_leaf("1", "read_clipboard", mode="weird_mode")])
    assert v._node_by_id["1"]._subtitle == "weird_mode → clipboard"


def test_canvas_step_dict_keeps_english_primitive(qapp):
    """画布标题中文化不得回写数据层：step dict 的 primitive 仍是英文键。"""
    v = WorkflowCanvasView()
    step = _leaf("1", "wait_ms", ms=100)
    v.set_steps([step])
    assert v._node_by_id["1"]._title == \
        TextResources.WF_PRIMITIVE_LABELS["wait_ms"]
    assert step["primitive"] == "wait_ms"


# ── 4. get_primitive_label 回退 ──────────────────────────────────────────────
def test_get_primitive_label_fallbacks():
    assert TextResources.get_primitive_label("no_such_key") == "no_such_key"
    assert TextResources.get_primitive_label("") == ""


# ── 5. tooltip 露出数据层键 ──────────────────────────────────────────────────
def test_palette_button_tooltip_reveals_payload(qapp):
    """tooltip 露出英文键/文件名：显示名中文化后仍可对到数据层键。"""
    palette = _palette()
    for btn in _prim_buttons(palette):
        payload = btn.property("palette_payload")
        assert payload in btn.toolTip(), \
            f"原语按钮 tooltip 应露出英文键 {payload}：{btn.toolTip()!r}"
    for btn in _sub_buttons(palette):
        payload = btn.property("palette_payload")
        assert payload in btn.toolTip(), \
            f"子工作流按钮 tooltip 应露出文件名 {payload}：{btn.toolTip()!r}"


# ── 6. 弹窗集成：构造 + 切画布视图 + 原语中文（冒烟）──────────────────────────
def test_dialog_palette_shows_chinese_after_view_switch(qapp, config_manager):
    """offscreen 冒烟：构造弹窗、切到画布视图，原语按钮仍显示中文。"""
    from poe_workflow.ui.dialog_workflow import WorkflowDialog
    dlg = WorkflowDialog(config_manager)
    dlg._switch_view(1)
    assert dlg._stack.currentIndex() == 1
    btns = _prim_buttons(dlg._palette)
    assert len(btns) == 14
    for btn in btns:
        payload = btn.property("palette_payload")
        assert btn.text() == TextResources.WF_PRIMITIVE_LABELS[payload]
    dlg._switch_view(0)
