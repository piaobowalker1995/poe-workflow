# -*- coding: utf-8 -*-
"""对比评估模块（preset_map_eval.json）引擎级测试 + 阈值/词缀库模型测试。

用户提案落地（2026-10-22）：
- 废图由**存仓前评估裁决**定义（条件全过=收入，任一不过=废图）；仓库页只执行去向。
- T 阶 = 阶级阈值判定，下拉只限 1~16；影响效果并入词缀库多选（或匹配）。
- 规则全放工作流侧，FSM 一行不动（路线 B）。

v2（2026-10-23 用户拍板）：
- 腐化门：config 条件源读 [Strategy] enable_corruption——「是否跳过腐化步骤
  即为是否开关腐化步骤」；开关开=优秀/合格图先腐化再复查，关=直接定仓。
- 存仓接线：store_to_stash 按 StashMapping 键名推算页签——「所有图均不指定
  固定页签，按需调整」；优秀→瑕疵仓、合格→成品(腐化开)/半成品(腐化关)、
  废图→废图仓。路由断言看 stash_key（键名），不看页号。
- use_currency 无 target 时回落当前光标（悬停评估场景，见 tests/
  test_workflow_store_and_config_source.py 的积木级测试）。
"""
import json
import os
import re

from poe_workflow.workflow_model import (
    workflow_from_dict, validate_workflow, RULE_PRESETS,
    THRESHOLD_PRESETS, FEATURE_LIBRARY, build_or_pattern, threshold_group,
)
from poe_workflow.workflow_engine import WorkflowEngine
from modules.affix_parser import AffixParser


MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "workflows", "preset_map_eval.json")

SAMPLE = (
    "冰峰峭壁 地图（16阶）\n"
    "稀有度: 稀有\n"
    "物品等级: 83\n"
    "物品数量: +113%\n"
    "物品稀有度: +67%\n"
    "{ 基底属性 }区域被起源者回忆影响\n"
    "{ 基底属性 }地图上有阿尔赫兹敏的要塞\n"
    "{ 基底属性 }该区域被裂界者影响\n"
)

CURRENCY_TEXT = "瓦尔宝珠\n物品类别: 通货\n堆叠数量: 12\n"


class FakeCoord:
    def __init__(self, mapping=None):
        self._m = mapping or {}
        self.calls = []
        self.tab_calls = []

    def get_absolute_position(self, name):
        self.calls.append(name)
        return self._m.get(name, (10, 20))

    def stash_tab_position(self, tab_index):
        self.tab_calls.append(tab_index)
        return (100 + tab_index * 10, 200)

    def stash_currency_position(self, currency_name=None):
        return (0, 0)   # 触发 use_currency 的 get_absolute_position 兜底路径


class FakeInp:
    """输入替身：光标在通货位时 Ctrl+C 读到通货信息，否则读到物品文本
    （模拟 use_currency 取用前验证的真实语义）。"""

    def __init__(self, clipboard=SAMPLE, currency_pos=(10, 20), item_pos=(500, 500)):
        self.moves = []
        self.keys = []
        self.mouse = []
        self.clicks = []
        self.item_text = clipboard
        self.currency_text = CURRENCY_TEXT
        self._currency_pos = tuple(currency_pos)
        self._last_move = tuple(item_pos)
        self.clipboard_text = clipboard
        self.verify_ok = True

    def click(self, x, y, button="left"):
        self.moves.append((x, y))
        self.clicks.append((x, y, button))
        self._last_move = (x, y)

    def move_mouse(self, x, y):
        self.moves.append((x, y))
        self._last_move = (x, y)

    def press_key(self, key):
        self.keys.append(key)
        if key == "ctrl+c":
            self.clipboard_text = (self.currency_text
                                   if self._last_move == self._currency_pos
                                   else self.item_text)

    def press_mouse(self, token):
        self.mouse.append(token)

    def read_clipboard(self):
        return self.clipboard_text

    def clear_clipboard(self):
        self.clipboard_text = ""

    def normal_delay(self):
        pass

    def get_mouse_pos(self):
        return self._last_move

    def clipboard_stash_verify(self):
        return self.verify_ok


class FakeCm:
    """黑白名单（_affix_eval 用）+ 配置读取（config 条件源/存仓页签用）。"""

    def __init__(self, black=None, white=None, config=None):
        self._black = black or []
        self._white = white or []
        self._config = dict(config or {})

    def get_affix_entries(self, section):
        return self._black if section == "AffixBlackList" else self._white

    def get(self, section, key, default=""):
        return self._config.get((section, key), default)


def _getter(sec, key, default=""):
    # 黑名单开启（让 blacklist_hit 可命中）；参数门槛全关（params_pass 恒真）；
    # 白名单开但名单为空 = 全过
    if (sec, key) == ("Strategy", "enable_blacklist"):
        return "true"
    return default


def _config(corruption="true"):
    # 页签索引用测试值（成品2/半成品3/瑕疵4/废图5/通货1），与真实配置解耦：
    # 路由断言只看 stash_key 键名，正是「按需调整不写死」的锁定点
    return {
        ("StashMapping", "currency_stash"): "1",
        ("StashMapping", "finished_map_stash"): "2",
        ("StashMapping", "semi_finished_stash"): "3",
        ("StashMapping", "flawed_map_stash"): "4",
        ("StashMapping", "waste_map_stash"): "5",
        ("Strategy", "enable_corruption"): corruption,
    }


def _run(text, black=None, white=None, corruption="true", coord=None, inp=None):
    inp = inp or FakeInp(clipboard=text)
    # 引擎黑白名单取自 cm（_affix_eval 读 self._cm.get_affix_entries）；
    # parser 的 cm 只被 check_blacklist/check_whitelist 用，evaluate_map 路径不读
    cm = FakeCm(black=black, white=white, config=_config(corruption))
    eng = WorkflowEngine(coord or FakeCoord(), inp,
                         parser=AffixParser(_getter, cm), cm=cm)
    eng.load(MODULE_PATH)
    assert eng.run_sync() == "done"
    return eng, inp


def _stash_key(eng):
    return eng.context["last"]["stash_key"]


# ── 模型层：阈值分组 / 词缀库 ─────────────────────────────────── #

def test_threshold_presets():
    assert THRESHOLD_PRESETS["tier"] == list(range(1, 17))      # 阶级只限 1~16
    assert THRESHOLD_PRESETS["percent"] == [20, 50, 70, 90, 100, 120]


def test_threshold_group():
    assert threshold_group("map_tier") == "tier"
    assert threshold_group("item_quantity") == "percent"
    assert threshold_group({"kind": "number", "pattern": r"(\d+)"}) == "percent"
    assert threshold_group("corrupted") is None      # 布尔无阈值
    assert threshold_group(None) is None             # 原文比较无阈值


def test_feature_library_compiles_and_drift_proof():
    labels = [e["label"] for e in FEATURE_LIBRARY]
    assert labels == ["元素荆棘", "无法再生", "起源者回忆影响",
                      "阿尔赫兹敏的要塞", "裂界者影响"]
    for e in FEATURE_LIBRARY:
        re.compile(e["pattern"])                     # 全部可编译
    # 影响效果类与 RULE_PRESETS 同源（防两处漂移）
    for k in ("influence_originator", "fortress_alhezhim", "influence_breach"):
        assert any(e["pattern"] == RULE_PRESETS[k]["pattern"]
                   for e in FEATURE_LIBRARY), k


def test_build_or_pattern():
    assert build_or_pattern(["元素荆棘", "无法再生"]) == "元素荆棘|无法再生"
    assert build_or_pattern(["  ", ""]) == ""
    assert build_or_pattern([r"被\s*裂界者\s*影响", r"阿尔赫兹敏的要塞"]) == \
        r"被\s*裂界者\s*影响|阿尔赫兹敏的要塞"


def test_library_or_pattern_matches_sample():
    pat = build_or_pattern([e["pattern"] for e in FEATURE_LIBRARY[2:]])
    assert re.search(pat, SAMPLE)                   # 样例三种影响全在
    plain = "冰峰峭壁 地图（16阶）\n稀有度: 魔法\n"
    assert re.search(pat, plain) is None


# ── 模块文件：校验 + 引擎路由 ─────────────────────────────────── #

def test_module_file_validates():
    with open(MODULE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert validate_workflow(workflow_from_dict(data)) == []


def test_sample_passes_evaluation():
    # 全中（IIQ 113 且无词缀瑕疵）→ 合格；腐化开 → 复查后成品仓
    eng, inp = _run(SAMPLE)
    assert _stash_key(eng) == "finished_map_stash"
    assert inp.keys.count("ctrl+c") == 3            # snap + 取通货验证 + 复查
    assert "ctrl+shift+mouse_left" in inp.mouse     # 存仓动作确实执行


def test_low_tier_routes_to_waste():
    eng, _ = _run(SAMPLE.replace("地图（16阶）", "地图（12阶）"))
    assert _stash_key(eng) == "waste_map_stash"


def test_magic_rarity_routes_to_waste():
    eng, _ = _run(SAMPLE.replace("稀有度: 稀有", "稀有度: 魔法"))
    assert _stash_key(eng) == "waste_map_stash"


# ── 三档结论：高参数 + 仅词缀被拒 = 优秀，不一棍子打死 ────────────── #

LOW_IQ = SAMPLE.replace("物品数量: +113%", "物品数量: +70%")
BLACK = [{"keyword": "反射", "is_regex": False, "tier": "ALL"}]
WHITE = [{"keyword": "镀金", "is_regex": False, "tier": "ALL"}]


def test_blacklist_hit_high_quantity_routes_to_flawed():
    # 优秀 + 腐化开 → 腐化复查后仍优秀 → 瑕疵仓
    eng, _ = _run(SAMPLE + "反射诅咒\n", black=BLACK)
    assert _stash_key(eng) == "flawed_map_stash"


def test_blacklist_hit_low_quantity_routes_to_waste():
    eng, _ = _run(LOW_IQ + "反射诅咒\n", black=BLACK)
    assert _stash_key(eng) == "waste_map_stash"


def test_whitelist_miss_high_quantity_routes_to_flawed():
    eng, _ = _run(SAMPLE, white=WHITE)          # 未命中白名单（无「镀金」）
    assert _stash_key(eng) == "flawed_map_stash"


def test_whitelist_miss_low_quantity_routes_to_waste():
    eng, _ = _run(LOW_IQ, white=WHITE)
    assert _stash_key(eng) == "waste_map_stash"


def test_excellent_line_is_configurable():
    # 优秀线默认 100：+90% 不达标 → 黑名单命中也只算废图
    iq90 = SAMPLE.replace("物品数量: +113%", "物品数量: +90%")
    eng, _ = _run(iq90 + "反射诅咒\n", black=BLACK)
    assert _stash_key(eng) == "waste_map_stash"


def test_item_rarity_line_not_misread_as_rarity_class():
    # 「物品稀有度: +67%」不得把稀有度阶级误判成别的（LOGIC-005 行首锚定）
    eng, _ = _run(SAMPLE)
    assert _stash_key(eng) == "finished_map_stash"


# ── 腐化门（用户拍板：接不接腐化复查看开关） ───────────────────── #

def test_corruption_disabled_qualified_goes_semi_finished():
    # 腐化关：合格图不腐化 → 半成品仓（未腐化且符合评估过程的图）
    eng, inp = _run(SAMPLE, corruption="false")
    assert _stash_key(eng) == "semi_finished_stash"
    assert inp.keys.count("ctrl+c") == 1          # 只 snap 一次，未走腐化段
    assert "ctrl+shift+mouse_left" in inp.mouse   # 存仓照常


def test_corruption_disabled_excellent_goes_flawed_directly():
    # 腐化关：优秀图不腐化 → 瑕疵仓
    eng, inp = _run(SAMPLE + "反射诅咒\n", black=BLACK, corruption="false")
    assert _stash_key(eng) == "flawed_map_stash"
    assert inp.keys.count("ctrl+c") == 1


def test_corruption_disabled_waste_never_uses_vaal():
    eng, inp = _run(SAMPLE.replace("地图（16阶）", "地图（12阶）"),
                    corruption="false")
    assert _stash_key(eng) == "waste_map_stash"
    assert inp.keys.count("ctrl+c") == 1


def test_corruption_enabled_excellent_uses_vaal_then_flawed():
    # 腐化开：优秀图吃一次瓦尔 → 复查仍优秀 → 瑕疵仓
    eng, inp = _run(SAMPLE + "反射诅咒\n", black=BLACK)
    assert _stash_key(eng) == "flawed_map_stash"
    assert inp.keys.count("ctrl+c") == 3          # snap + 取通货 + 复查
