# -*- coding: utf-8 -*-
"""P1 决策大脑 · 条件源单测（G1 affix / G3 rarity / G4 session）。

纯积木形态：只验证三个新条件源 evaluate_map / detect_rarity / check_session_limit
能正确接入 _eval_condition，不依赖真实游戏/UI（用 fake parser/inp）。
"""
import pytest

from poe_workflow.workflow_engine import WorkflowEngine


class _FakeParser:
    def __init__(self, rarity="magic", decision="accept", params_pass=True):
        self._rarity = rarity
        self._decision = decision
        self._params_pass = params_pass
        self.eval_calls = 0

    def detect_rarity(self, text):
        return self._rarity

    def evaluate_map(self, text, blacklist, whitelist, map_tier="T16"):
        self.eval_calls += 1
        return {"_text": text, "final_decision": self._decision,
                "params_pass": self._params_pass,
                "whitelist_pass": True, "blacklist_hit": False}


class _FakeInp:
    def __init__(self, ok=True, reason=""):
        self._ok = ok
        self._reason = reason

    def check_session_limit(self):
        return self._ok, self._reason


def _engine(parser=None, inp=None, cm=None):
    return WorkflowEngine(None, inp or _FakeInp(), parser=parser, cm=cm)


# ── G3 rarity ────────────────────────────────────────────────────────────────
def test_rarity_source_match():
    e = _engine(parser=_FakeParser(rarity="normal"))
    e._ctx["clipboard"] = "稀有度: 普通\n..."
    assert e._eval_condition({"source": "rarity", "op": "equals", "value": "normal"}, 0) is True
    assert e._eval_condition({"source": "rarity", "op": "equals", "value": "magic"}, 0) is False


def test_rarity_source_no_parser_falls_back_unknown():
    e = _engine(parser=None)
    e._ctx["clipboard"] = "anything"
    assert e._eval_condition({"source": "rarity", "op": "equals", "value": "unknown"}, 0) is True


# ── G1 affix ────────────────────────────────────────────────────────────────
def test_affix_source_final_decision():
    e = _engine(parser=_FakeParser(decision="accept"))
    e._ctx["clipboard"] = "affix text"
    assert e._eval_condition(
        {"source": "affix", "key": "final_decision", "op": "equals", "value": "accept"}, 0) is True
    assert e._eval_condition(
        {"source": "affix", "key": "final_decision", "op": "nequals", "value": "accept"}, 0) is False


def test_affix_source_params_pass_bool():
    e = _engine(parser=_FakeParser(params_pass=True))
    e._ctx["clipboard"] = "x"
    assert e._eval_condition(
        {"source": "affix", "key": "params_pass", "op": "equals", "value": "True"}, 0) is True
    assert e._eval_condition(
        {"source": "affix", "key": "params_pass", "op": "equals", "value": "False"}, 0) is False


def test_affix_eval_cached_per_text():
    p = _FakeParser(decision="accept")
    e = _engine(parser=p)
    e._ctx["clipboard"] = "abc"
    e._eval_condition({"source": "affix", "key": "final_decision", "op": "equals", "value": "accept"}, 0)
    e._eval_condition({"source": "affix", "key": "final_decision", "op": "equals", "value": "accept"}, 0)
    # 同文本只算一次（缓存命中）
    assert p.eval_calls == 1
    assert e._ctx["__affix_eval"]["_text"] == "abc"


def test_affix_source_no_parser_degenerate():
    e = _engine(parser=None)
    e._ctx["clipboard"] = "x"
    # 无 parser 退化为 final_decision="unknown"
    assert e._eval_condition(
        {"source": "affix", "key": "final_decision", "op": "equals", "value": "unknown"}, 0) is True


# ── G4 session ──────────────────────────────────────────────────────────────
def test_session_source_ok_false_means_limited():
    e = _engine(inp=_FakeInp(ok=False, reason="hourly limit reached"))
    assert e._eval_condition(
        {"source": "session", "key": "ok", "op": "equals", "value": "False"}, 0) is True
    assert e._eval_condition(
        {"source": "session", "key": "ok", "op": "equals", "value": "True"}, 0) is False


def test_session_source_reason_contains():
    e = _engine(inp=_FakeInp(ok=False, reason="hourly limit reached"))
    assert e._eval_condition(
        {"source": "session", "key": "reason", "op": "contains", "value": "hourly"}, 0) is True


def test_session_source_no_inp_ok_default():
    e = _engine(inp=None)
    # 无 inp 视为未超限（ok=True）
    assert e._eval_condition(
        {"source": "session", "key": "ok", "op": "equals", "value": "True"}, 0) is True


def test_unknown_source_still_false():
    e = _engine()
    assert e._eval_condition({"source": "bogus", "op": "equals", "value": "x"}, 0) is False
