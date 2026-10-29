# -*- coding: utf-8 -*-
"""工作流编排数据正确性批（波1-A：A1 延迟字段 + A2 跳转映射）单元测试。

覆盖：
- A1「步骤延迟」控件直写顶层 delay_ms（不再误写 params.delay_ms）；
  存量污染经 migrate_delay_ms 自愈（模型加载 / UI 加载 / 保存往返均干净）
- A2 jump_target 按位置 id 引用：重编号后同步改写（remap_jump_targets /
  collect_step_ids / build_id_remap），运行前校验拦截无效目标，
  合法方案名不被误改写，无 id 变化时零改写
依赖 tests/conftest.py 的 qapp（pytest-qt, offscreen）+ config_manager 夹具。
"""
import json

import pytest
from PyQt5.QtWidgets import QSpinBox

from poe_workflow.workflow_model import (
    migrate_delay_ms, remap_jump_targets, collect_step_ids, build_id_remap,
    workflow_from_dict,
)
from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _new_step_dict


def _leaf(sid, prim="move_to_anchor", **params):
    return {"id": sid, "kind": "action", "primitive": prim,
            "params": params or {"anchor": "a"},
            "on_error": "retry", "retry_count": 1,
            "retry_delay_ms": 500, "delay_ms": 0}


def _delay_row_and_spin(card):
    """构造卡片的「步骤延迟」行，返回 (row, spinbox)。

    必须由调用方持有 row：PyQt5 父控件销毁会级联删除子控件，
    只留 spinbox 引用会在设置值时触发「wrapped C/C++ object deleted」。
    """
    row = card._build_delay_row()
    sb = row.findChild(QSpinBox)
    assert sb is not None, "延迟行应包含 QSpinBox"
    return row, sb


def _assert_no_params_delay_ms(steps):
    def _walk(lst):
        for s in lst:
            assert "delay_ms" not in s.get("params", {}), f"params 被污染: {s}"
            for k in ("body", "then_steps", "else_steps"):
                _walk(s.get(k, []) or [])
    _walk(steps)


# ── A1：步骤延迟字段错位 ────────────────────────────────────────────────────
def test_delay_row_writes_top_level_delay_ms(qapp, config_manager):
    """「步骤延迟」spinbox 必须直写顶层 delay_ms，不能再进 params。"""
    tab = WorkflowTab(config_manager)
    d = _new_step_dict(tab)
    d["delay_ms"] = 0
    card = StepCard(d, [d], tab, "1")
    row, sb = _delay_row_and_spin(card)
    sb.setValue(300)
    assert d["delay_ms"] == 300
    assert "delay_ms" not in d.get("params", {}), "delay_ms 不得再写入 params"


def test_migrate_delay_ms_promotes_from_params():
    """params 内误写的 delay_ms 应被提回顶层（含嵌套 loop/branch 子树）。"""
    steps = [
        {"id": "1", "kind": "action", "primitive": "log",
         "params": {"message": "x", "delay_ms": 50}, "delay_ms": 0},
        {"id": "2", "kind": "loop", "count": 2, "body": [
            {"id": "2.1", "kind": "action", "primitive": "log",
             "params": {"delay_ms": 30}},
            {"id": "2.2", "kind": "branch",
             "condition": {"source": "clipboard", "op": "equals", "value": "1"},
             "then_steps": [{"id": "2.2.1", "kind": "action", "primitive": "log",
                             "params": {"delay_ms": 70}}],
             "else_steps": []},
        ]},
    ]
    migrate_delay_ms(steps)
    assert steps[0]["delay_ms"] == 50
    assert steps[1]["body"][0]["delay_ms"] == 30
    assert steps[1]["body"][1]["then_steps"][0]["delay_ms"] == 70
    _assert_no_params_delay_ms(steps)


def test_migrate_delay_ms_keeps_nonzero_top_level():
    """顶层已有非 0 值时以顶层为准，params 内的被丢弃（不覆盖）。"""
    steps = [{"id": "1", "kind": "action", "primitive": "log",
              "params": {"delay_ms": 50}, "delay_ms": 200}]
    migrate_delay_ms(steps)
    assert steps[0]["delay_ms"] == 200
    assert "delay_ms" not in steps[0]["params"]


def test_workflow_from_dict_self_heals_delay_ms():
    """引擎加载路径（workflow_from_dict）对污染 json 自愈。"""
    wf = workflow_from_dict({"name": "t", "steps": [
        {"id": "1", "kind": "action", "primitive": "log",
         "params": {"message": "x", "delay_ms": 50}},
        {"id": "2", "kind": "action", "primitive": "log",
         "params": {"message": "y"}, "delay_ms": 120},
    ]})
    assert wf.steps[0].delay_ms == 50
    assert wf.steps[1].delay_ms == 120
    assert "delay_ms" not in wf.steps[0].params


def test_load_file_self_heals_delay_ms(qapp, config_manager, tmp_path,
                                       monkeypatch):
    """UI 加载路径：_load_file 对存量污染文件自愈。"""
    tab = WorkflowTab(config_manager)
    dirty = {"name": "dirty", "version": 1, "steps": [
        {"id": "1", "kind": "action", "primitive": "log",
         "params": {"message": "x", "delay_ms": 50}},
    ]}
    (tmp_path / "dirty.json").write_text(
        json.dumps(dirty, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("poe_workflow.ui.tab_workflow._WORKFLOWS_DIR", str(tmp_path))
    tab._load_file("dirty.json")
    assert tab._steps_dicts[0]["delay_ms"] == 50
    assert "delay_ms" not in tab._steps_dicts[0]["params"]


def test_save_roundtrip_has_no_params_delay_ms(qapp, config_manager):
    """保存往返：spinbox 设值后经 _step_to_dict 序列化，params 内无 delay_ms。"""
    tab = WorkflowTab(config_manager)
    tab._on_new()
    d = tab._steps_dicts[0]
    card = StepCard(d, tab._steps_dicts, tab, "1")
    row, sb = _delay_row_and_spin(card)
    sb.setValue(300)
    out = tab._to_workflow_dict()
    assert out["steps"][0]["delay_ms"] == 300
    _assert_no_params_delay_ms(out["steps"])


# ── A2：jump_target 位置编号同步 ────────────────────────────────────────────
def test_remap_jump_targets_rewrites_only_mapped():
    """命中映射表的 jump_target 被改写（含嵌套子树）；方案名保持不动。"""
    steps = [
        {"id": "1", "kind": "action", "primitive": "log", "params": {},
         "on_error": "jump", "jump_target": "3"},
        {"id": "2", "kind": "action", "primitive": "log", "params": {},
         "on_error": "jump", "jump_target": "preset_mapmaker_full"},
        {"id": "3", "kind": "loop", "count": 1, "body": [
            {"id": "3.1", "kind": "action", "primitive": "log", "params": {},
             "on_error": "jump", "jump_target": "1"},
        ]},
    ]
    remap_jump_targets(steps, {"3": "4", "1": "2"})
    assert steps[0]["jump_target"] == "4"                    # 3 -> 4
    assert steps[1]["jump_target"] == "preset_mapmaker_full"  # 方案名不改写
    assert steps[2]["body"][0]["jump_target"] == "2"          # 嵌套子树：1 -> 2


def test_remap_jump_targets_empty_map_is_noop():
    """空映射 → 零改写（序列化内容不变）。"""
    steps = [{"id": "1", "kind": "action", "primitive": "log", "params": {},
              "on_error": "jump", "jump_target": "2"}]
    before = json.dumps(steps, ensure_ascii=False, sort_keys=True)
    remap_jump_targets(steps, {})
    assert json.dumps(steps, ensure_ascii=False, sort_keys=True) == before


def test_collect_step_ids_covers_whole_tree():
    steps = [_leaf("1", "log"),
             {"id": "2", "kind": "loop", "count": 1, "condition": None,
              "body": [_leaf("2.1", "log")]}]
    ids = collect_step_ids(steps)
    assert set(ids) == {"1", "2", "2.1"}
    assert ids["2.1"]["primitive"] == "log"


def test_build_id_remap_only_same_object_changed():
    """仅「同一对象 id 变化」进映射；新增/删除的步骤不进映射。"""
    a, b, c = _leaf("1", "log"), _leaf("2", "log"), _leaf("3", "log")
    old = collect_step_ids([a, b, c])
    for d, nid in ((a, "2"), (b, "3"), (c, "4")):   # 模拟前插一步后的编号
        d["id"] = nid
    assert build_id_remap(old, collect_step_ids([a, b, c])) == \
        {"1": "2", "2": "3", "3": "4"}
    fresh = _leaf("9", "log")
    assert build_id_remap(old, collect_step_ids([fresh])) == {}


def test_rebuild_cards_remaps_jump_after_front_insert(qapp, config_manager):
    """列表侧：前方插入一步 → 重编号 → jump_target 同步改写（不再静默指错）。"""
    tab = WorkflowTab(config_manager)
    tab._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms"),
                        _leaf("3", "copy")]
    tab._steps_dicts[1]["on_error"] = "jump"
    tab._steps_dicts[1]["jump_target"] = "3"
    tab._rebuild_cards()
    assert tab._steps_dicts[1]["jump_target"] == "3"
    # 在最前方插入一步：原 1/2/3 -> 2/3/4
    tab._steps_dicts.insert(0, _new_step_dict(tab))
    tab._rebuild_cards()
    assert tab._steps_dicts[2]["jump_target"] == "4", \
        f"jump_target 未同步改写：{tab._steps_dicts[2]['jump_target']}"


def test_rebuild_cards_zero_rewrite_when_ids_unchanged(qapp, config_manager):
    """无 id 变化的场景（如重复点击聚焦）：序列化内容逐字节不变。"""
    tab = WorkflowTab(config_manager)
    tab._steps_dicts = [
        dict(_leaf("1", "log"), on_error="jump", jump_target="2"),
        _leaf("2", "log"),
    ]
    tab._rebuild_cards()
    before = json.dumps(tab._to_workflow_dict(), ensure_ascii=False,
                        sort_keys=True)
    tab._rebuild_cards()                                   # 模拟再次重建
    tab._rebuild_cards(focus_dict=tab._steps_dicts[0])     # 模拟点击聚焦
    after = json.dumps(tab._to_workflow_dict(), ensure_ascii=False,
                       sort_keys=True)
    assert before == after


def test_run_blocked_on_unresolvable_jump_target(qapp, config_manager,
                                                 monkeypatch):
    """jump_target 既非步骤 id 也非方案文件 → 运行前拦截，引擎不 start。"""
    tab = WorkflowTab(config_manager)
    tab._input = object()
    tab._coord = object()
    started = []

    class FakeEngine:
        def __init__(self, *a, **k):
            self.on_status = self.on_finished = self.on_error = None

        def load_def(self, wf):
            pass

        def start(self):
            started.append(1)

    monkeypatch.setattr("poe_workflow.ui.tab_workflow.WorkflowEngine", FakeEngine)
    d = _new_step_dict(tab)
    d["on_error"] = "jump"
    d["jump_target"] = "99"
    tab._steps_dicts = [d]
    tab._rebuild_cards()
    tab._on_run()
    assert not started, "无效 jump_target 不应启动引擎"
    status = tab._editor_panel.status_label.text()
    assert "跳转目标无效" in status and "99" in status, f"错误提示不明确：{status}"


def test_run_allows_scheme_name_jump_target(qapp, config_manager, monkeypatch):
    """jump_target 是合法方案名（workflows/ 已有文件）→ 校验通过且不被改写。"""
    tab = WorkflowTab(config_manager)
    tab._input = object()
    tab._coord = object()
    started = []

    class FakeEngine:
        def __init__(self, *a, **k):
            self.on_status = self.on_finished = self.on_error = None

        def load_def(self, wf):
            pass

        def start(self):
            started.append(1)

    monkeypatch.setattr("poe_workflow.ui.tab_workflow.WorkflowEngine", FakeEngine)
    d = _new_step_dict(tab)
    d["on_error"] = "jump"
    d["jump_target"] = "preset_mapmaker_full"
    tab._steps_dicts = [d]
    tab._rebuild_cards()
    tab._on_run()
    assert started, "合法方案名 jump_target 不应阻止运行"
    assert tab._steps_dicts[0]["jump_target"] == "preset_mapmaker_full"


def test_canvas_reorder_remaps_jump_target(qapp, config_manager):
    """画布侧重排 → assign_step_ids 重编号 → jump_target 同步改写。"""
    from poe_workflow.ui.tab_workflow_canvas import WorkflowCanvasTab
    tab = WorkflowTab(config_manager)
    cv = WorkflowCanvasTab(config_manager)
    cv.attach_workflow_tab(tab)
    tab.attach_canvas_tab(cv)
    tab._steps_dicts = [_leaf("1", "log"), _leaf("2", "wait_ms"),
                        _leaf("3", "copy")]
    tab._steps_dicts[1]["on_error"] = "jump"
    tab._steps_dicts[1]["jump_target"] = "3"
    cv.refresh_from_workflow()
    # 把第 3 步拖到最前：1/2/3 -> 2/3/1，jump_target "3" 应改指新 "1"
    cv._on_canvas_reorder("3", 0)
    assert tab._steps_dicts[2]["jump_target"] == "1", \
        f"画布侧重排后 jump_target 未同步：{tab._steps_dicts[2]['jump_target']}"
