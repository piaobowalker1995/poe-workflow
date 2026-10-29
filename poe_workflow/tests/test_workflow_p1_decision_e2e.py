# -*- coding: utf-8 -*-
"""P1(决策大脑) 端到端示例测试：用新积木拼出 FSM 等价的「稀有地图重铸」决策流。

加载 workflows/decision_map_full.json，用 Fake 坐标/输入/解析器跑通：
  copy 取地图文本 → session 分支(限速则 pause 等待继续) → rarity 分支(仅稀有进重铸)
  → until(affix==accept) 重铸循环(use_currency 重铸石 + copy 刷新) → record_session。
证明纯积木形态可完整复刻 FSM 决策大脑，无需任何复合壳。
"""
import os
import re

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import validate_workflow, load_workflow_file

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DECISION_JSON = os.path.join(REPO_ROOT, "workflows", "decision_map_full.json")


class _RerollInp:
    """每次右键取用通货 = 一次重铸；剪贴板文本反映当前重铸次数。"""

    def __init__(self, session_ok=True):
        self.rerolls = 0
        self.record_calls = 0
        self.session_ok = session_ok

    def click(self, x, y, button="left", **kw):
        if button == "right":
            self.rerolls += 1

    def move_mouse(self, x, y):
        pass

    def clear_clipboard(self):
        pass

    def press_key(self, key):
        pass

    def read_clipboard(self):
        # 同时含通货名(过 use_currency 校验)与地图标记(过 rarity/affix 解析)，
        # 重铸次数随右键取用递增 → 驱动 until 循环退出。
        return ("通货：重铸石\n物品类别: 地图\n稀有度: 稀有\n"
                f"重铸次数: {self.rerolls}\n堆叠数量: 99")

    def normal_delay(self):
        pass

    def record_action(self):
        self.record_calls += 1

    def check_session_limit(self):
        return (self.session_ok, "" if self.session_ok else "会话超限")


class _FakeParser:
    def detect_rarity(self, text):
        m = re.search(r'稀有度:\s*(\S+)', text)
        return {"稀有": "rare", "魔法": "magic"}.get(m.group(1) if m else "", "rare")

    def evaluate_map(self, text, blacklist, whitelist):
        n = int(re.search(r'重铸次数:\s*(\d+)', text).group(1))
        if n >= 1:
            return {"final_decision": "accept", "params_pass": True,
                    "whitelist_pass": True, "blacklist_hit": False}
        return {"final_decision": "reject_param", "params_pass": False,
                "whitelist_pass": True, "blacklist_hit": False}


class _FakeCoord:
    def get_absolute_position(self, name):
        return {"map_cell": (100, 100), "重铸石": (20, 20)}.get(name, (0, 0))

    def stash_tab_position(self, tab_index):
        return (10, 10)

    def stash_currency_position(self, currency_name):
        return {"重铸石": (20, 20)}.get(currency_name, (0, 0))


def _engine(inp):
    return WorkflowEngine(_FakeCoord(), inp, parser=_FakeParser(), cm=None)


def test_decision_json_is_valid():
    wf = load_workflow_file(DECISION_JSON)
    assert validate_workflow(wf) == []


def test_decision_rerolls_until_accept_then_records():
    inp = _RerollInp(session_ok=True)
    eng = _engine(inp)
    eng.load(DECISION_JSON)
    reason = eng.run_sync()
    assert reason == "done"
    assert inp.rerolls == 1        # 重铸一次即达标（until 前置判定退出）
    assert inp.record_calls == 1   # 通过后记录一次会话


def test_decision_session_limit_pauses_then_resumes():
    inp = _RerollInp(session_ok=False)
    eng = _engine(inp)
    seen = []
    eng.on_pause = lambda note: (seen.append(note), eng.resume())
    eng.load(DECISION_JSON)
    reason = eng.run_sync()
    assert reason == "done"
    assert seen and "会话" in seen[0]   # 命中限速 → 走 pause 分支
    assert inp.record_calls == 1


def test_decision_non_rare_skips_reroll():
    # 魔法地图：rarity 分支走 else，不重铸、不记录
    inp = _RerollInp(session_ok=True)
    eng = _engine(inp)
    eng._parser = _FakeParser()
    eng._parser.detect_rarity = lambda text: "magic"
    eng.load(DECISION_JSON)
    reason = eng.run_sync()
    assert reason == "done"
    assert inp.rerolls == 0
    assert inp.record_calls == 0
