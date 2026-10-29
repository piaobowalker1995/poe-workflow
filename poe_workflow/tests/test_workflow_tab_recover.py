# -*- coding: utf-8 -*-
"""G7 use_currency 切页容错：移植 FSM V3031-TAB-FIX（方案A）重切循环。

背景：真机 2026-10-11 07:03 日志证实的竞态——制图存图后游戏停在成品仓页，
取通货前虽点了通货页但页签未真正切过去，Ctrl+C 误读成品仓内容 → 误判
「告罄」停止。FSM 已修（每次验证强制重切页签再读，≤3 次）；工作流引擎
的 use_currency 原是「点一次页签 + 固定等 0.3s + 读一次」，读到别页内容
直接抛错。本文件锁定移植后的行为：

- 命中：首轮即读到目标通货 → 只点一次页签，行为与旧版一致；
- 未命中：强制重切页签重读，≤ Runtime.tab_recover_retries（默认 3）次；
- 读空：单轮内按 0.08*(n+1) 退避重读 3 次，再失败才进下一轮重切；
- 重试耗尽：抛错交 on_error（retry/jump）处理，错误信息带重试次数；
- 等待/重读期间 abort：立即抛「中止」，不被重试循环吞掉。
"""
import pytest

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import workflow_from_dict


class _FakeInp:
    """剪贴板按 responses 序列供给（耗尽后重复最后一个）；on_click 钩子供 abort 测试。"""

    def __init__(self, responses):
        if isinstance(responses, str):
            responses = [responses]
        self._responses = list(responses)
        self.clicks = []          # [(x, y, button)]
        self.moves = []
        self.cleared = 0
        self.reads = 0
        self.on_click = None

    def click(self, x, y, button="left", **kw):
        self.clicks.append((x, y, button))
        if self.on_click:
            self.on_click()

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def clear_clipboard(self):
        self.cleared += 1

    def press_key(self, key):
        pass

    def read_clipboard(self):
        self.reads += 1
        if not self._responses:
            return ""
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]

    def normal_delay(self):
        pass

    def record_action(self):
        pass


class _FakeCoord:
    def get_absolute_position(self, name):
        return (100, 100) if name == "map_cell" else (0, 0)

    def stash_tab_position(self, tab_index):
        return (10, 10)

    def stash_currency_position(self, currency_name):
        return (20, 20)


class _FakeCm:
    def __init__(self, values=None):
        self._v = values or {}

    def get(self, section, key, fallback=""):
        return self._v.get((section, key), fallback)


CURRENCY_HIT = "通货：重铸石\n堆叠数量: 5\n物品类别: 地图"
OTHER_PAGE = "成品仓页内容\n稀有度: 稀有"


def _engine(responses, cm=None):
    return WorkflowEngine(_FakeCoord(), _FakeInp(responses), cm=cm)


def _tab_clicks(inp):
    return [c for c in inp.clicks if c[:2] == (10, 10)]


# ── 命中路径（行为保持） ─────────────────────────────────────────────────────

def test_first_attempt_hit_clicks_tab_once():
    """首轮即读到目标通货：只点一次页签，后续取用/应用动作不变。"""
    eng = _engine([CURRENCY_HIT])
    r = eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    inp = eng._inp
    assert (r["x"], r["y"]) == (100, 100)
    assert len(_tab_clicks(inp)) == 1
    assert any(c == (20, 20, "right") for c in inp.clicks)   # 右键取用
    assert any(c == (100, 100, "left") for c in inp.clicks)  # 左键应用
    assert inp.cleared >= 1


def test_qty_zero_still_raises():
    """名称命中但堆叠数量为 0 → 判告罄抛错（不重切，数量问题重切无意义）。"""
    eng = _engine(["通货：重铸石\n堆叠数量: 0\n物品类别: 地图"])
    with pytest.raises(RuntimeError, match="告罄"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert len(_tab_clicks(eng._inp)) == 1


# ── 重切容错 ────────────────────────────────────────────────────────────────

def test_retries_until_match():
    """前两轮读到别页内容 → 第 3 轮命中：共点 3 次页签后成功。"""
    eng = _engine([OTHER_PAGE, OTHER_PAGE, CURRENCY_HIT])
    r = eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert (r["x"], r["y"]) == (100, 100)
    assert len(_tab_clicks(eng._inp)) == 3


def test_exhausted_retries_raise_with_count():
    """始终读到别页内容：重切 3 次后抛错，错误信息带重试次数。"""
    eng = _engine([OTHER_PAGE])
    with pytest.raises(RuntimeError, match="已重切 3 次"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert len(_tab_clicks(eng._inp)) == 3


def test_empty_reads_backoff_within_attempt():
    """单轮读空：轮内按 0.08*(n+1) 退避重读 3 次；3 轮共 9 读 + 3 次重切。"""
    eng = _engine([""])
    with pytest.raises(RuntimeError, match="读空"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    inp = eng._inp
    assert inp.reads == 9, f"3 轮 × (首读+2 次退避重读) 应为 9 次读取，实际 {inp.reads}"
    assert len(_tab_clicks(inp)) == 3


def test_empty_then_hit_within_backoff():
    """轮内首读空、退避重读命中：不消耗额外的切页重试。"""
    eng = _engine(["", CURRENCY_HIT])
    r = eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert (r["x"], r["y"]) == (100, 100)
    assert len(_tab_clicks(eng._inp)) == 1
    assert eng._inp.reads == 2


def test_retries_configurable():
    """Runtime.tab_recover_retries 可配置（最小 1）。"""
    eng = _engine([OTHER_PAGE], cm=_FakeCm({("Runtime", "tab_recover_retries"): "1"}))
    with pytest.raises(RuntimeError, match="已重切 1 次"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert len(_tab_clicks(eng._inp)) == 1
    assert _engine([OTHER_PAGE], cm=_FakeCm({("Runtime", "tab_recover_retries"): "0"}))._tab_recover_retries() == 1
    assert _engine([OTHER_PAGE], cm=_FakeCm({("Runtime", "tab_recover_retries"): "abc"}))._tab_recover_retries() == 3


# ── abort 不被重试循环吞掉 ──────────────────────────────────────────────────

def test_abort_during_tab_wait_stops_immediately():
    """切页等待期间 abort：立即抛「中止」，不再进入读取/重试。"""
    eng = _engine([CURRENCY_HIT])

    def _abort_on_click():
        eng._abort.set()

    eng._inp.on_click = _abort_on_click
    with pytest.raises(RuntimeError, match="中止"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert eng._inp.reads == 0, "abort 后不应再读剪贴板"


# ── 未校准坐标（旧行为保持） ────────────────────────────────────────────────

def test_uncalibrated_tab_still_raises_before_any_click():
    eng = _engine([CURRENCY_HIT])

    class _ZeroTabCoord(_FakeCoord):
        def stash_tab_position(self, tab_index):
            return (0, 0)

    eng._coord = _ZeroTabCoord()
    with pytest.raises(RuntimeError, match="页签未校准"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert eng._inp.clicks == []


def test_uncalibrated_currency_still_raises():
    eng = _engine([CURRENCY_HIT])

    class _ZeroCurCoord(_FakeCoord):
        def stash_currency_position(self, currency_name):
            return (0, 0)

        def get_absolute_position(self, name):
            # 仅通货坐标未校准；目标锚点 map_cell 保持可用，
            # 否则会先在 _guard_uncalibrated(map_cell) 处抛另一种错
            return (0, 0) if name == "重铸石" else (100, 100)

    eng._coord = _ZeroCurCoord()
    with pytest.raises(RuntimeError, match="坐标未校准"):
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})


# ── 端到端：编排层视角的恢复 ────────────────────────────────────────────────

def test_tab_recover_recovers_within_single_call():
    """use_currency 首轮读别页内容 → 单次调用内重切即恢复（旧实现此处直接
    失败终止整案）。on_error 重试根本未触发。"""
    inp = _FakeInp([OTHER_PAGE, CURRENCY_HIT])
    eng = WorkflowEngine(_FakeCoord(), inp)
    errs = []
    eng.on_error = errs.append
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "use_currency",
         "params": {"currency": "重铸石", "target": "map_cell"},
         "on_error": "retry", "retry_count": 1, "retry_delay_ms": 0,
         "delay_ms": 0}]})
    eng.load_def(wf)
    reason = eng.run_sync()
    assert reason == "done"
    assert len(_tab_clicks(inp)) == 2   # 第 1 轮未命中重切，第 2 轮命中
    assert not errs, "单次调用内恢复，不应上报步骤级错误"
    assert any(c == (100, 100, "left") for c in inp.clicks)


def test_step_on_error_retry_after_exhausted():
    """重切 3 次仍读到别页内容 → 步骤级失败 → on_error=retry 再跑一次即恢复。
    证明熔断抛错正确接入 _run_action 的重试通道（编排层可自行决定恢复策略）。

    注意：on_error 回调只在步骤重试**耗尽后**才上报；本用例第 2 次尝试
    （_run_action 内部 retry）即成功，故 errs 为空属正确语义。
    """
    inp = _FakeInp([OTHER_PAGE, OTHER_PAGE, OTHER_PAGE, CURRENCY_HIT])
    eng = WorkflowEngine(_FakeCoord(), inp)
    errs = []
    eng.on_error = errs.append
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "use_currency",
         "params": {"currency": "重铸石", "target": "map_cell"},
         "on_error": "retry", "retry_count": 1, "retry_delay_ms": 0,
         "delay_ms": 0}]})
    eng.load_def(wf)
    reason = eng.run_sync()
    assert reason == "done"
    assert len(_tab_clicks(inp)) == 4   # 失败尝试重切 3 次 + 重试尝试 1 次
    assert not errs, "第 2 次尝试成功，on_error 不应上报"
    assert any(c == (100, 100, "left") for c in inp.clicks)
