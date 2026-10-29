# -*- coding: utf-8 -*-
# STUB: verbatim copy of poe-mapmaker/modules/affix_parser.py (v3.0.30).
# Self-contained (only stdlib imports); behaviour is byte-identical to the host
# so the engine routing tests in test_workflow_map_eval_module.py keep passing.
import logging
"""
词缀解析模块
- 正则提取剪贴板文本中的 I/Q/怪群规模/地图品质等参数
- 黑白名单词缀匹配（支持精确匹配与正则匹配）
- 腐化状态判定
- 地图稀有度识别
"""
import re
from typing import Dict, List, Optional, Tuple


class AffixParser:
    """POE 地图词缀与参数解析器"""

    PARAM_PATTERNS = {
        "item_quantity": re.compile(r"物品数量:\s*\+(\d+)%"),
        "rarity": re.compile(r"物品稀有度:\s*\+(\d+)%"),
        "pack_size": re.compile(r"怪群规模:\s*\+(\d+)%"),
        "map_quality": re.compile(r"品质:\s*\+(\d+)%"),
    }

    RARITY_KEYWORDS = {
        "普通": "normal",
        "魔法": "magic",
        "稀有": "rare",
        "传奇": "unique",
    }

    def __init__(self, config_getter, config_manager=None):
        self._get = config_getter
        self._cm = config_manager

    # ------------------------------------------------------------------ #
    #                      参数提取                                        #
    # ------------------------------------------------------------------ #
    def extract_params(self, clipboard_text: str) -> Dict[str, Optional[int]]:
        result = {}
        for key, pattern in self.PARAM_PATTERNS.items():
            match = pattern.search(clipboard_text)
            result[key] = int(match.group(1)) if match else None
        return result

    def check_params(self, params: Dict[str, Optional[int]]) -> Tuple[bool, List[str]]:
        failures = []
        checks = [
            ("item_quantity", "item_quantity_enabled", "item_quantity_min"),
            ("rarity", "rarity_enabled", "rarity_min"),
            ("pack_size", "pack_size_enabled", "pack_size_min"),
            ("map_quality", "map_quality_enabled", "map_quality_min"),
        ]
        for param_key, enable_key, min_key in checks:
            enabled = self._get("Parameters", enable_key, "false").lower() == "true"
            if not enabled:
                continue
            try:
                min_val = int(self._get("Parameters", min_key, "0"))
            except (ValueError, TypeError):
                logging.getLogger("AffixParser").warning(f"Invalid min value for {min_key}, using 0")
                min_val = 0
            actual = params.get(param_key)
            if actual is None or actual < min_val:
                failures.append(f"{param_key}: {actual} < {min_val}")
        return len(failures) == 0, failures

    # ------------------------------------------------------------------ #
    #                      稀有度识别                                      #
    # ------------------------------------------------------------------ #
    # 稀有度类别正则：匹配 "稀 有 度: XXX" 字段（POE中文客户端固定格式）
    # LOGIC-005: 用 re.MULTILINE 将 ^ 锚定到行首，只匹配「以 稀有度 开头」的行，
    # 绝不命中行内的 "物品稀有度: +XX%"，避免从词缀行误捕获稀有度。
    _RARITY_LINE_RE = re.compile(r"^\s*稀\s*有\s*度[:：]\s*(\S+)", re.MULTILINE)

    def detect_rarity(self, clipboard_text: str) -> str:
        """从剪贴板文本的 '稀 有 度:' 字段精确提取稀有度类别。
        避免与词缀行 '物品稀有度: +XX%' 中的子串误匹配。"""
        m = self._RARITY_LINE_RE.search(clipboard_text)
        if m:
            cn_value = m.group(1)
            return self.RARITY_KEYWORDS.get(cn_value, "unknown")
        return "unknown"

    # ------------------------------------------------------------------ #
    #                      腐化判定                                        #
    # ------------------------------------------------------------------ #
    def is_corrupted(self, clipboard_text: str) -> bool:
        regex_str = self._get("CorruptionCheck", "corrupted_regex", r"^.*已腐化.*$")
        try:
            return bool(re.search(regex_str, clipboard_text, re.MULTILINE))
        except re.error as e:
            logging.getLogger("AffixParser").warning(
                f"腐化判定正则编译失败 '{regex_str}': {e}，回退到关键词匹配")
            keyword = self._get("CorruptionCheck", "corrupted_keyword", "已腐化")
            return keyword in clipboard_text or "不可改变" in clipboard_text

    def is_unidentified(self, clipboard_text: str) -> bool:
        """检测地图是否为未鉴定状态"""
        return "未鉴定" in clipboard_text

    @staticmethod
    def test_regex(regex_str: str, test_text: str) -> Tuple[bool, str]:
        try:
            match = re.search(regex_str, test_text, re.MULTILINE)
            if match:
                return True, match.group(0)
            return False, "no match"
        except re.error as e:
            return False, f"regex error: {e}"

    # ------------------------------------------------------------------ #
    #                      词缀匹配                                        #
    # ------------------------------------------------------------------ #
    def _build_affix_entries(self, section: str) -> List[Dict]:
        """
        从 ConfigManager 读取纯文本词缀行，构建匹配条目列表。
        每行视为一条独立规则：包含正则特殊字符则作为正则匹配，否则精确匹配。
        """
        if self._cm is None:
            return []
        keywords = self._cm.get_affix_keywords(section)
        entries = []
        regex_special = set(r"\.^$*+?{}[]|()")
        for kw in keywords:
            has_regex = any(c in kw for c in regex_special)
            entries.append({
                "keyword": kw,
                "is_regex": has_regex,
                "tier": "ALL",
            })
        return entries

    def match_affix_list(self, clipboard_text: str, section: str,
                         map_tier: str = "T16") -> Tuple[bool, List[str]]:
        affixes = self._build_affix_entries(section)
        matched = []
        for entry in affixes:
            tier = entry["tier"]
            if tier != "ALL" and tier != map_tier:
                continue
            keyword = entry["keyword"]
            is_regex = entry["is_regex"]
            if is_regex:
                try:
                    if re.search(keyword, clipboard_text):
                        matched.append(keyword)
                except re.error:
                    logging.getLogger("AffixParser").debug(f"Regex compile error in keyword matching: {keyword}", exc_info=True)
            else:
                if keyword in clipboard_text:
                    matched.append(keyword)
        return len(matched) > 0, matched

    def check_blacklist(self, clipboard_text: str,
                        map_tier: str = "T16") -> Tuple[bool, List[str]]:
        enabled = self._get("Strategy", "enable_blacklist", "true").lower() == "true"
        if not enabled:
            return False, []
        return self.match_affix_list(clipboard_text, "AffixBlackList", map_tier)

    def check_whitelist(self, clipboard_text: str,
                        map_tier: str = "T16") -> Tuple[bool, List[str]]:
        # LOGIC-008(i): 无 ConfigManager 时退化为"通过"，避免 self._cm.get_affix_keywords
        # 抛 AttributeError；与 _build_affix_entries 的 None 守卫保持一致。
        if self._cm is None:
            return True, []
        enabled = self._get("Strategy", "enable_whitelist", "true").lower() == "true"
        if not enabled:
            return True, []
        # 空白名单视为不限制（全部通过），避免默认配置拒绝所有地图
        keywords = self._cm.get_affix_keywords("AffixWhiteList")
        if not keywords:
            return True, []
        hit, matched = self.match_affix_list(clipboard_text, "AffixWhiteList", map_tier)
        return hit, matched

    def evaluate_map(self, clipboard_text: str,
                     affix_blacklist: List[Dict],
                     affix_whitelist: List[Dict],
                     map_tier: str = "T16") -> Dict:
        result = {
            "raw_text": clipboard_text,
            "rarity": self.detect_rarity(clipboard_text),
            "is_corrupted": self.is_corrupted(clipboard_text),
            "params": self.extract_params(clipboard_text),
            "params_pass": False,
            "param_failures": [],
            "whitelist_pass": True,
            "whitelist_matched": [],
            "blacklist_hit": False,
            "blacklist_matched": [],
            "final_decision": "reject",
        }

        params_ok, param_fails = self.check_params(result["params"])  # type: ignore[arg-type]
        result["params_pass"] = params_ok
        result["param_failures"] = param_fails
        if not params_ok:
            result["final_decision"] = "reject_param"
            return result

        wl_enabled = self._get("Strategy", "enable_whitelist", "true").lower() == "true"
        if wl_enabled and affix_whitelist:
            wl_hit, wl_matched = self._match_affixes(
                clipboard_text, affix_whitelist, map_tier
            )
            result["whitelist_pass"] = wl_hit
            result["whitelist_matched"] = wl_matched
            if not wl_hit:
                result["final_decision"] = "reject_whitelist"
                return result

        bl_enabled = self._get("Strategy", "enable_blacklist", "true").lower() == "true"
        if bl_enabled:
            bl_hit, bl_matched = self._match_affixes(
                clipboard_text, affix_blacklist, map_tier
            )
            result["blacklist_hit"] = bl_hit
            result["blacklist_matched"] = bl_matched
            if bl_hit:
                result["final_decision"] = "reject_blacklist"
                return result

        result["final_decision"] = "accept"
        return result

    @staticmethod
    def _match_affixes(text: str, affix_list: List[Dict],
                       map_tier: str) -> Tuple[bool, List[str]]:
        matched = []
        for entry in affix_list:
            tier = entry.get("tier", "ALL")
            if tier != "ALL" and tier != map_tier:
                continue
            keyword = entry["keyword"]
            is_regex = entry.get("is_regex", False)
            if is_regex:
                try:
                    if re.search(keyword, text):
                        matched.append(keyword)
                except re.error:
                    logging.getLogger("AffixParser").debug(f"Regex compile error in keyword matching: {keyword}", exc_info=True)
            else:
                if keyword in text:
                    matched.append(keyword)
        return len(matched) > 0, matched
