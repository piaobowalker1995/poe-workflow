# -*- coding: utf-8 -*-
"""P1(决策大脑) 新增积木单元测试：use_currency / record_session / pause。

用 FakeCoord / FakeInp 取代真实窗口与坐标系统，验证三个纯积木的：
- use_currency：切页→定位→核对名称/数量→右键取用→左键应用到目标格；
  失败路径（名称不匹配 / 数量告罄 / 缺目标）正确抛错。
- record_session：写入会话限速器一次。
- pause：阻塞至 resume() 解除；abort 期间解除则抛错。
- validate_workflow：接受使用新积木的方案；use_currency 缺 currency 报错。
"""
import threading
import time

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import workflow_from_dict, validate_workflow


class _FakeInp:
    def __init__(self, clipboard_text="通货：重铸石\n堆叠数量: 5\n物品类别: 地图"):
        self.clipboard_text = clipboard_text
        self.clicks = []          # [(x, y, button)]
        self.moves = []
        self.record_calls = 0
        self.cleared = 0

    def click(self, x, y, button="left", **kw):
        self.clicks.append((x, y, button))

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def clear_clipboard(self):
        self.cleared += 1

    def press_key(self, key):
        pass

    def read_clipboard(self):
        return self.clipboard_text

    def normal_delay(self):
        pass

    def record_action(self):
        self.record_calls += 1


class _FakeCoord:
    def __init__(self):
        self._tab = (10, 10)
        self._cur = {"重铸石": (20, 20)}

    def get_absolute_position(self, name):
        if name == "map_cell":
            return (100, 100)
        if name in self._cur:
            return self._cur[name]
        return (0, 0)

    def stash_tab_position(self, tab_index):
        return self._tab

    def stash_currency_position(self, currency_name):
        return self._cur.get(currency_name, (0, 0))


def _engine(inp=None, cm=None):
    return WorkflowEngine(_FakeCoord(), inp or _FakeInp(), cm=cm)


# ── use_currency ────────────────────────────────────────────────────────────
def test_use_currency_applies_to_target_anchor():
    inp = _FakeInp()
    eng = _engine(inp)
    r = eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
    assert r["currency"] == "重铸石"
    assert (r["x"], r["y"]) == (100, 100)
    # 切页（左键点页签）
    assert any(c[0] == 10 and c[1] == 10 for c in inp.clicks)
    # 右键取用通货
    assert any(c[0] == 20 and c[1] == 20 and c[2] == "right" for c in inp.clicks)
    # 左键应用到目标格
    assert any(c[0] == 100 and c[1] == 100 and c[2] == "left" for c in inp.clicks)
    assert inp.cleared >= 1  # 取用前清空剪贴板


def test_use_currency_explicit_xy():
    inp = _FakeInp()
    eng = _engine(inp)
    r = eng._p_use_currency({"currency": "重铸石", "x": 300, "y": 400})
    assert (r["x"], r["y"]) == (300, 400)


def test_use_currency_name_mismatch_raises():
    inp = _FakeInp(clipboard_text="其他物品\n堆叠数量: 3")
    eng = _engine(inp)
    try:
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
        assert False, "应因名称不匹配抛错"
    except RuntimeError as e:
        assert "核对失败" in str(e)


def test_use_currency_qty_zero_raises():
    inp = _FakeInp(clipboard_text="通货：重铸石\n堆叠数量: 0")
    eng = _engine(inp)
    try:
        eng._p_use_currency({"currency": "重铸石", "target": "map_cell"})
        assert False, "应因数量告罄抛错"
    except RuntimeError as e:
        assert "告罄" in str(e)


def test_use_currency_missing_target_raises():
    eng = _engine(_FakeInp())
    try:
        eng._p_use_currency({"currency": "重铸石"})
        assert False, "应因缺少目标抛错"
    except RuntimeError as e:
        assert "缺少目标" in str(e)


def test_use_currency_missing_currency_raises():
    eng = _engine(_FakeInp())
    try:
        eng._p_use_currency({"target": "map_cell"})
        assert False, "应因缺少 currency 抛错"
    except RuntimeError as e:
        assert "currency" in str(e)


# ── record_session ─────────────────────────────────────────────────────────
def test_record_session_records_once():
    inp = _FakeInp()
    eng = _engine(inp)
    r = eng._p_record_session({})
    assert r == {"recorded": True}
    assert inp.record_calls == 1


# ── pause / resume ────────────────────────────────────────────────────────
def test_pause_blocks_until_resume():
    eng = _engine(_FakeInp())
    captured = {}

    def run():
        captured["r"] = eng._p_pause({"note": "x"})

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.15)
    assert eng._paused is True
    eng.resume()
    t.join(timeout=2)
    assert captured["r"] == {"resumed": True, "note": "x"}


def test_pause_abort_raises():
    eng = _engine(_FakeInp())
    err = {}

    def run():
        try:
            eng._p_pause({})
        except RuntimeError as e:
            err["e"] = e

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.15)
    eng.abort()
    t.join(timeout=2)
    assert "中止" in str(err["e"])


def test_pause_fires_on_pause_callback():
    eng = _engine(_FakeInp())
    seen = {}
    eng.on_pause = lambda note: seen.setdefault("note", note)
    captured = {}

    def run():
        captured["r"] = eng._p_pause({"note": "人工介入"})

    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.15)
    assert seen.get("note") == "人工介入"
    eng.resume()
    t.join(timeout=2)
    assert captured["r"]["note"] == "人工介入"


# ── validate_workflow 同步 ─────────────────────────────────────────────────
def test_validate_accepts_new_primitives():
    data = {
        "name": "t", "steps": [
            {"id": "1", "kind": "action", "primitive": "use_currency",
             "params": {"currency": "重铸石", "target": "map_cell"}, "on_error": "retry"},
            {"id": "2", "kind": "action", "primitive": "record_session",
             "params": {}, "on_error": "retry"},
            {"id": "3", "kind": "action", "primitive": "pause",
             "params": {"note": "hi"}, "on_error": "retry"},
        ],
    }
    wf = workflow_from_dict(data)
    assert validate_workflow(wf) == []


def test_validate_use_currency_requires_currency():
    data = {
        "name": "t", "steps": [
            {"id": "1", "kind": "action", "primitive": "use_currency",
             "params": {}, "on_error": "retry"},
        ],
    }
    wf = workflow_from_dict(data)
    errs = validate_workflow(wf)
    assert any("currency" in e for e in errs)
