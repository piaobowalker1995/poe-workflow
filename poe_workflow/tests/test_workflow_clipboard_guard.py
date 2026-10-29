# -*- coding: utf-8 -*-
"""G6 剪贴板防护：None 归一化 + 连续空读熔断 + copy 复制校验前缀。

背景：Ctrl+C 未生效/游戏失焦时剪贴板读取返回空，until 循环可能靠空文本
无限重铸（旧 FSM 已有剪贴板竞争/空值防护，工作流引擎原先零防护）；且
read_clipboard() 返回 None 时会穿透到条件比较。本文件锁定：

1. None 归一化为 ""（_p_read_clipboard / _p_copy 两个读点）；
2. 连续空读计数达阈值（Runtime.clipboard_empty_limit，默认 5）抛
   RuntimeError 熔断，非空读重置；阈值可配置、最小 1；
3. copy 的 expect_prefix：内容不以指定前缀开头即判复制失败（识别
   「剪贴板保留旧内容」这种非空但无效的读取），抛错交 on_error 恢复；
4. 模型层校验 expect_prefix 必须是字符串；UI copy 编辑器可读写该字段。
"""
from PyQt5.QtWidgets import QLineEdit

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import workflow_from_dict, validate_workflow


class _FakeInp:
    def __init__(self, clipboard=""):
        self.clipboard = clipboard
        self.keys = []
        self.copies = 0

    def click(self, x, y, button="left", **kw):
        pass

    def move_mouse(self, x, y):
        pass

    def clear_clipboard(self):
        pass

    def press_key(self, key):
        self.keys.append(key)
        if key == "ctrl+c":
            self.copies += 1

    def read_clipboard(self):
        return self.clipboard

    def normal_delay(self):
        pass

    def record_action(self):
        pass


class _FakeCoord:
    def get_absolute_position(self, name):
        return (100, 100) if name == "map_cell" else (0, 0)


class _FakeCm:
    def __init__(self, values=None):
        self._v = values or {}

    def get(self, section, key, fallback=""):
        return self._v.get((section, key), fallback)


def _engine(inp=None, cm=None):
    return WorkflowEngine(_FakeCoord(), inp or _FakeInp(), cm=cm)


# ── None 归一化 ──────────────────────────────────────────────────────────────

def test_read_clipboard_none_normalized_to_empty():
    """read_clipboard 返回 None（API 失败）时归一化为 ""，不穿透到条件比较。"""
    inp = _FakeInp(clipboard=None)
    eng = _engine(inp)
    r = eng._p_read_clipboard({})
    assert eng._ctx["clipboard"] == ""
    assert r["clipboard"] == ""


def test_read_clipboard_none_with_match_mode_no_crash():
    """None + match 模式：规则抽取不崩，未命中返 ''。"""
    inp = _FakeInp(clipboard=None)
    eng = _engine(inp)
    r = eng._p_read_clipboard({"mode": "match", "rule": "item_quantity"})
    assert r["value"] == ""


def test_copy_none_normalized_to_empty():
    inp = _FakeInp(clipboard=None)
    eng = _engine(inp)
    r = eng._p_copy({"store_as": "after"})
    assert eng._ctx["after"] == ""
    assert r["clipboard"] == ""


# ── 连续空读熔断 ─────────────────────────────────────────────────────────────

def test_consecutive_empty_reads_trip_circuit_breaker():
    """默认阈值 5：前 4 次空读放行，第 5 次抛 RuntimeError 熔断。"""
    inp = _FakeInp(clipboard="")
    eng = _engine(inp)
    for _ in range(4):
        eng._p_copy({})   # 不抛
    assert eng._clipboard_empty_streak == 4
    try:
        eng._p_copy({})
    except RuntimeError as e:
        assert "熔断" in str(e) and "5" in str(e)
    else:
        raise AssertionError("第 5 次连续空读应抛熔断错误")
    assert eng._clipboard_empty_streak == 5


def test_non_empty_read_resets_streak():
    """非空读重置计数：4 次空读 + 1 次非空 + 4 次空读都不熔断。"""
    inp = _FakeInp(clipboard="")
    eng = _engine(inp)
    for _ in range(4):
        eng._p_copy({})
    inp.clipboard = "物品类别: 地图"
    eng._p_copy({})
    assert eng._clipboard_empty_streak == 0
    inp.clipboard = ""
    for _ in range(4):
        eng._p_copy({})   # 重新计到 4，不抛
    assert eng._clipboard_empty_streak == 4


def test_whitespace_only_counts_as_empty():
    """纯空白读视为空（PoE 剪贴板内容不会是有效空白）。"""
    inp = _FakeInp(clipboard="  \n ")
    eng = _engine(inp, cm=_FakeCm({("Runtime", "clipboard_empty_limit"): "2"}))
    eng._p_copy({})
    try:
        eng._p_copy({})
    except RuntimeError:
        pass
    else:
        raise AssertionError("纯空白读应计入空读熔断")


def test_empty_limit_configurable():
    """阈值走 Runtime.clipboard_empty_limit 配置（最小 1）。"""
    inp = _FakeInp(clipboard="")
    eng = _engine(inp, cm=_FakeCm({("Runtime", "clipboard_empty_limit"): "2"}))
    eng._p_copy({})
    try:
        eng._p_copy({})
    except RuntimeError as e:
        assert "2" in str(e)
    else:
        raise AssertionError("阈值=2 时第 2 次空读应熔断")


def test_empty_limit_clamped_to_at_least_one():
    """配置 0/负数收敛到最小 1（不会「永不熔断」）；垃圾值回落默认 5。"""
    inp = _FakeInp(clipboard="")
    eng = _engine(inp, cm=_FakeCm({("Runtime", "clipboard_empty_limit"): "0"}))
    assert eng._clipboard_empty_limit() == 1
    eng = _engine(inp, cm=_FakeCm({("Runtime", "clipboard_empty_limit"): "-3"}))
    assert eng._clipboard_empty_limit() == 1
    eng = _engine(inp, cm=_FakeCm({("Runtime", "clipboard_empty_limit"): "abc"}))
    assert eng._clipboard_empty_limit() == 5


def test_streak_reset_on_new_run():
    """_prepare（run_sync 入口）重置计数：残留 4 + 单次空读 = 1，本步不熔断。

    若忘记重置，上一轮残留 4 次会让本轮第 1 个空读就误触熔断。
    """
    inp = _FakeInp(clipboard="")
    eng = _engine(inp)
    eng._clipboard_empty_streak = 4
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "copy",
         "params": {"store_as": "x"}, "on_error": "retry", "delay_ms": 0}]})
    eng.load_def(wf)
    reason = eng.run_sync()
    assert reason == "done"
    assert eng._clipboard_empty_streak == 1


# ── copy 复制校验前缀 ────────────────────────────────────────────────────────

def test_copy_expect_prefix_mismatch_raises():
    """内容不以 expect_prefix 开头（剪贴板旧内容）→ 抛错交 on_error 恢复。"""
    inp = _FakeInp(clipboard="稀有度: 普通\n旧内容")
    eng = _engine(inp)
    try:
        eng._p_copy({"expect_prefix": "物品类别: 地图"})
    except RuntimeError as e:
        assert "复制校验失败" in str(e)
    else:
        raise AssertionError("前缀不匹配应抛错")


def test_copy_expect_prefix_match_stores():
    inp = _FakeInp(clipboard="物品类别: 地图\n稀有度: 魔法")
    eng = _engine(inp)
    r = eng._p_copy({"expect_prefix": "物品类别: 地图", "store_as": "cur"})
    assert eng._ctx["cur"].startswith("物品类别: 地图")
    assert r["clipboard"].startswith("物品类别: 地图")


def test_copy_expect_prefix_empty_skips_check():
    """空前缀 = 不校验（默认行为不变）。"""
    inp = _FakeInp(clipboard="任意内容")
    eng = _engine(inp)
    eng._p_copy({"expect_prefix": ""})
    assert eng._ctx["clipboard"] == "任意内容"


# ── 端到端：运行中熔断 ───────────────────────────────────────────────────────

def test_run_stops_when_clipboard_never_reads():
    """整案跑起来：5 个连续 copy 全读空 → 第 5 步熔断 → on_error=abort 停止。"""
    inp = _FakeInp(clipboard="")
    eng = _engine(inp)
    errs = []
    eng.on_error = lambda msg: errs.append(msg)
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": str(i), "kind": "action", "primitive": "copy",
         "params": {"store_as": f"v{i}"}, "on_error": "abort", "delay_ms": 0}
        for i in range(1, 7)]})
    eng.load_def(wf)
    reason = eng.run_sync()
    assert reason == "error"
    assert inp.copies == 5, "第 5 步熔断后不应再复制"
    assert errs and "熔断" in errs[0]


# ── 模型校验 ────────────────────────────────────────────────────────────────

def test_validate_rejects_non_string_expect_prefix():
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "copy",
         "params": {"expect_prefix": 123}, "on_error": "retry", "delay_ms": 0}]})
    errs = validate_workflow(wf)
    assert any("expect_prefix" in e for e in errs), errs


def test_validate_accepts_string_expect_prefix():
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "copy",
         "params": {"expect_prefix": "物品类别: 地图"},
         "on_error": "retry", "delay_ms": 0}]})
    assert validate_workflow(wf) == []


# ── UI 编辑器 ───────────────────────────────────────────────────────────────

def _copy_card(qapp, config_manager, params=None):
    from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _new_step_dict
    tab = WorkflowTab(config_manager)
    d = _new_step_dict(tab)
    d["primitive"] = "copy"
    d["params"] = {"store_as": "clipboard"}
    if params:
        d["params"].update(params)
    return StepCard(d, [d], tab, "1"), d


def _expect_edit(card):
    for le in card.findChildren(QLineEdit):
        if le.placeholderText().startswith("如：物品类别"):
            return le
    raise AssertionError("copy 编辑器缺少「内容前缀」输入框")


def test_copy_card_expect_prefix_writes_param(qapp, config_manager):
    card, d = _copy_card(qapp, config_manager)
    le = _expect_edit(card)
    le.setText("物品类别: 地图")
    assert d["params"]["expect_prefix"] == "物品类别: 地图"
    le.setText("")
    assert "expect_prefix" not in d["params"], "清空应移除校验（不留空串垃圾字段）"


def test_copy_card_expect_prefix_loads_existing(qapp, config_manager):
    card, d = _copy_card(qapp, config_manager, {"expect_prefix": "稀有度:"})
    assert _expect_edit(card).text() == "稀有度:"
