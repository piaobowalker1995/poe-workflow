# -*- coding: utf-8 -*-
"""地图评估预设规则测试（2026-10-22，用户提案「对比评估模块」落地的第一步）。

背景：用户提议把「剪贴板内容 vs 规则集」的评估收敛成一个对比评估模块——
前置 copy/read_clipboard + 内置评估内容（各自特征分类）+ 开放正则（自由匹配）。
拍板结论：内置规则全部放工作流侧共享规则注册表（RULE_PRESETS），FSM 一行不动。

本文件锁定按用户提供的真实剪贴板样例推导出的四个新预设：
- map_tier            地图阶级（名字「地图（16阶）」，number，默认 ge）
- influence_originator 起源者回忆影响（bool）
- fortress_alhezhim    阿尔赫兹敏的要塞（bool）
- influence_breach     裂界者影响（bool）

样例文本（用户 2026-10-22 提供）：
    地图（16阶）  …  { 基底属性 }区域被起源者回忆影响 /
    { 基底属性 }地图上有阿尔赫兹敏的要塞 /
    { 基底属性 }该区域被裂界者影响
"""
from poe_workflow.workflow_model import (
    WorkflowDef, ActionStep, validate_workflow, resolve_rule, RULE_PRESETS,
)
from poe_workflow.workflow_engine import WorkflowEngine


class FakeCoord:
    def __init__(self, mapping=None):
        self._m = mapping or {}
        self.calls = []

    def get_absolute_position(self, name):
        self.calls.append(name)
        return self._m.get(name, (10, 20))


class FakeInp:
    def __init__(self, clipboard="ITEM"):
        self.moves = []
        self.keys = []
        self.mouse = []
        self.clipboard_text = clipboard

    def click(self, x, y):
        self.moves.append((x, y))

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def press_key(self, key):
        self.keys.append(key)

    def press_mouse(self, token):
        self.mouse.append(token)

    def read_clipboard(self):
        return self.clipboard_text


SAMPLE_MAP_TEXT = (
    "冰峰峭壁 地图（16阶）\n"
    "稀有度: 稀有\n"
    "物品等级: 83\n"
    "物品数量: +113%\n"
    "{ 基底属性 }区域被起源者回忆影响\n"
    "{ 基底属性 }地图上有阿尔赫兹敏的要塞\n"
    "{ 基底属性 }该区域被裂界者影响\n"
)


def _make_with_clipboard(text):
    coord = FakeCoord({"p": (10, 20)})
    inp = FakeInp(clipboard=text)
    eng = WorkflowEngine(coord, inp)
    return eng, coord, inp


# ── 预设注册表结构与 resolve_rule ────────────────────────────── #

def test_map_tier_preset_resolves_to_number_ge():
    spec = resolve_rule("map_tier")
    assert spec is not None
    assert spec["kind"] == "number"
    assert spec["default_op"] == "ge"
    assert spec["capture_group"] == 1


def test_influence_presets_resolve_to_bool():
    for key in ("influence_originator", "fortress_alhezhim", "influence_breach"):
        spec = resolve_rule(key)
        assert spec is not None, key
        assert spec["kind"] == "bool", key
        assert spec["pattern"], key


def test_preset_labels_unique():
    labels = [v["label"] for v in RULE_PRESETS.values()]
    assert len(labels) == len(set(labels))


# ── _apply_rule 抽取（地图阶级） ─────────────────────────────── #

def test_map_tier_extracts_fullwidth_sample():
    spec = resolve_rule("map_tier")
    assert WorkflowEngine._apply_rule(SAMPLE_MAP_TEXT, spec) == "16"


def test_map_tier_tolerates_halfwidth_and_t_prefix():
    spec = resolve_rule("map_tier")
    assert WorkflowEngine._apply_rule("深渊矿井 地图(12阶)", spec) == "12"
    assert WorkflowEngine._apply_rule("深渊矿井 地图（T16）", spec) == "16"
    assert WorkflowEngine._apply_rule("深渊矿井 地图 （ 16 阶 ）", spec) == "16"


def test_map_tier_absent_returns_empty():
    spec = resolve_rule("map_tier")
    # 未命中：number 类返空串（条件比较时按「不通过」处理）
    assert WorkflowEngine._apply_rule("稀有度: 魔法\n物品数量: +58%", spec) == ""


def test_map_tier_no_false_positive_on_category_line():
    spec = resolve_rule("map_tier")
    # 「物品类别: 地图」「更多地图: +35%」等无括号行不得误命中
    assert WorkflowEngine._apply_rule("物品类别: 地图\n更多地图: +35%", spec) == ""


# ── _apply_rule 抽取（影响效果，布尔） ───────────────────────── #

def test_influences_hit_on_sample():
    for key in ("influence_originator", "fortress_alhezhim", "influence_breach"):
        spec = resolve_rule(key)
        assert WorkflowEngine._apply_rule(SAMPLE_MAP_TEXT, spec) == "true", key


def test_influences_miss_on_plain_map():
    plain = "冰峰峭壁 地图（16阶）\n稀有度: 魔法\n物品数量: +58%\n"
    for key in ("influence_originator", "fortress_alhezhim", "influence_breach"):
        spec = resolve_rule(key)
        assert WorkflowEngine._apply_rule(plain, spec) == "false", key


# ── 引擎：read_clipboard match 模式 ──────────────────────────── #

def test_read_clipboard_match_map_tier_stores_number():
    eng, _, _ = _make_with_clipboard(SAMPLE_MAP_TEXT)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "rule": "map_tier", "store_as": "tier"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("tier") == "16"
    # 原始剪贴板始终保留，供 source=clipboard 条件复用
    assert "裂界者影响" in eng.context.get("clipboard", "")


def test_read_clipboard_match_influence_stores_bool():
    eng, _, _ = _make_with_clipboard(SAMPLE_MAP_TEXT)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="r", primitive="read_clipboard",
                   params={"mode": "match", "rule": "influence_breach", "store_as": "br"}),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("br") == "true"


# ── 引擎：条件分支（对比评估组合） ────────────────────────────── #

def test_condition_map_tier_ge_routes_branch():
    # T16 >= 15 -> then；T12 < 15 -> else
    for text, expect in ((SAMPLE_MAP_TEXT, "a"), ("深渊矿井 地图（12阶）", "b")):
        eng, _, _ = _make_with_clipboard(text)
        wf = WorkflowDef(name="t", steps=[
            ActionStep(id="b", kind="branch",
                       condition={"source": "clipboard", "rule": "map_tier",
                                  "op": "ge", "value": "15"},
                       then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                       else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
        ])
        eng.load_def(wf)
        assert eng.run_sync() == "done"
        assert eng.context.get("last", {}).get("key") == expect


def test_condition_influence_bool_equals_true():
    eng, _, _ = _make_with_clipboard(SAMPLE_MAP_TEXT)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="b", kind="branch",
                   condition={"source": "clipboard", "rule": "influence_breach",
                              "op": "equals", "value": "true"},
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("last", {}).get("key") == "a"


def test_branch_all_composes_map_eval():
    # 对比评估组合（all=AND）：T阶≥15 且 裂界者影响 且 物品数量≥100 -> then
    cond = {"all": [
        {"source": "clipboard", "rule": "map_tier", "op": "ge", "value": "15"},
        {"source": "clipboard", "rule": "influence_breach", "op": "equals", "value": "true"},
        {"source": "clipboard", "rule": "item_quantity", "op": "ge", "value": "100"},
    ]}
    # 样例全中 -> then
    eng, _, _ = _make_with_clipboard(SAMPLE_MAP_TEXT)
    wf = WorkflowDef(name="t", steps=[
        ActionStep(id="b", kind="branch", condition=cond,
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    assert validate_workflow(wf) == []
    eng.load_def(wf)
    assert eng.run_sync() == "done"
    assert eng.context.get("last", {}).get("key") == "a"

    # T 阶不足（12 < 15）-> else
    eng2, _, _ = _make_with_clipboard(
        SAMPLE_MAP_TEXT.replace("地图（16阶）", "地图（12阶）"))
    wf2 = WorkflowDef(name="t", steps=[
        ActionStep(id="b", kind="branch", condition=cond,
                   then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                   else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
    ])
    eng2.load_def(wf2)
    assert eng2.run_sync() == "done"
    assert eng2.context.get("last", {}).get("key") == "b"


def test_branch_any_composes_influence_or():
    # any=OR：三种影响沾一条即 then
    cond = {"any": [
        {"source": "clipboard", "rule": "influence_originator", "op": "equals", "value": "true"},
        {"source": "clipboard", "rule": "fortress_alhezhim", "op": "equals", "value": "true"},
        {"source": "clipboard", "rule": "influence_breach", "op": "equals", "value": "true"},
    ]}
    plain = "冰峰峭壁 地图（16阶）\n稀有度: 魔法\n物品数量: +58%\n"
    for text, expect in ((SAMPLE_MAP_TEXT, "a"), (plain, "b")):
        eng, _, _ = _make_with_clipboard(text)
        wf = WorkflowDef(name="t", steps=[
            ActionStep(id="b", kind="branch", condition=cond,
                       then_steps=[ActionStep(id="t1", primitive="press_key", params={"key": "a"})],
                       else_steps=[ActionStep(id="e1", primitive="press_key", params={"key": "b"})]),
        ])
        assert validate_workflow(wf) == []
        eng.load_def(wf)
        assert eng.run_sync() == "done"
        assert eng.context.get("last", {}).get("key") == expect
