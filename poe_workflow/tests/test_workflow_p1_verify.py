# -*- coding: utf-8 -*-
"""P2-B（纯编排）验证-重试模式测试：不把校验塞进 use_currency，
而是用现有积木拼出「用通货 → 移开移回绕过 PoE 缓存 → 比对前后 → 没生效就重试」。

证明 ctx_diff（前后对比）+ move_offset/move_to_anchor（移开移回）+ loop until
（生效即退出 + __loop_index 护栏）可在编排层完整表达应用后验证。
"""
import os

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import workflow_from_dict, validate_workflow, load_workflow_file

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_JSON = os.path.join(REPO_ROOT, "workflows", "decision_map_verify.json")

TARGET = (100, 100)
CUR = (20, 20)
TAB = (10, 10)


class _VerifyInp:
    """左键点到目标格=一次应用(可开关是否真生效)；右键=取用。
    剪贴板文本反映当前词缀版本号 → 驱动 before/after 对比。"""

    def __init__(self, apply_works=True):
        self.version = 0
        self.rerolls = 0
        self.apply_works = apply_works

    def click(self, x, y, button="left", **kw):
        if button == "right":
            self.rerolls += 1
        elif button == "left" and (x, y) == TARGET and self.apply_works:
            self.version += 1

    def move_mouse(self, x, y):
        pass

    def clear_clipboard(self):
        pass

    def press_key(self, key):
        pass

    def read_clipboard(self):
        return f"通货：重铸石\n物品类别: 地图\n词缀版本: {self.version}"

    def normal_delay(self):
        pass

    def record_action(self):
        pass

    def check_session_limit(self):
        return (True, "")


class _FakeCoord:
    def get_absolute_position(self, name):
        return {"map_cell": TARGET, "重铸石": CUR}.get(name, (0, 0))

    def stash_tab_position(self, tab_index):
        return TAB

    def stash_currency_position(self, currency_name):
        return {"重铸石": CUR}.get(currency_name, (0, 0))


def _engine(inp):
    return WorkflowEngine(_FakeCoord(), inp)


def _verify_workflow(guard):
    """内联构造验证-重试方案（guard=__loop_index 护栏阈值，便于测试控次）。"""
    return {
        "name": "verify", "steps": [
            {"id": "1", "kind": "action", "primitive": "copy",
             "params": {"store_as": "before"}, "on_error": "retry", "delay_ms": 0},
            {"id": "2", "kind": "action", "primitive": "copy",
             "params": {"store_as": "after"}, "on_error": "retry", "delay_ms": 0},
            {"id": "3", "kind": "loop",
             "condition": {"any": [
                 {"source": "ctx_diff", "key_a": "before", "key_b": "after", "op": "nequals"},
                 {"source": "ctx", "key": "__loop_index", "op": "ge", "value": guard},
             ]},
             "body": [
                 {"id": "3.1", "kind": "action", "primitive": "use_currency",
                  "params": {"currency": "重铸石", "target": "map_cell"},
                  "on_error": "retry", "delay_ms": 0},
                 {"id": "3.2", "kind": "action", "primitive": "move_offset",
                  "params": {"anchor": "map_cell", "dx": 40, "dy": 40},
                  "on_error": "retry", "delay_ms": 0},
                 {"id": "3.3", "kind": "action", "primitive": "move_to_anchor",
                  "params": {"anchor": "map_cell"}, "on_error": "retry", "delay_ms": 0},
                 {"id": "3.4", "kind": "action", "primitive": "copy",
                  "params": {"store_as": "after"}, "on_error": "retry", "delay_ms": 0},
             ],
             "on_error": "retry", "delay_ms": 0},
        ],
    }


def test_verify_json_is_valid():
    wf = load_workflow_file(VERIFY_JSON)
    assert validate_workflow(wf) == []


def test_verify_template_exits_once_currency_takes_effect():
    # 加载真实模板：应用一次即生效 → before!=after → 循环第 2 次判定退出，只重铸 1 次
    inp = _VerifyInp(apply_works=True)
    eng = _engine(inp)
    eng.load(VERIFY_JSON)
    reason = eng.run_sync()
    assert reason == "done"
    assert inp.rerolls == 1


def test_verify_bounded_retry_when_never_effective():
    # 应用始终不生效：词缀版本不变 → before==after 恒真 → 靠 __loop_index 护栏有界退出
    inp = _VerifyInp(apply_works=False)
    eng = _engine(inp)
    wf = workflow_from_dict(_verify_workflow(guard=2))  # 最多 3 次(body: i=0,1,2)
    assert validate_workflow(wf) == []
    eng.load_def(wf)
    reason = eng.run_sync()
    assert reason == "done"
    assert inp.rerolls == 3   # 护栏生效，未无限重试
