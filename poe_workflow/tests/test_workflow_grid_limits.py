# -*- coding: utf-8 -*-
"""G8 网格维度上限校验（模型层拒收 + 引擎显式中止 + UI 加载自愈）。

背景：引擎 _run_grid_loop 到达 _max_loop_iterations（10000）即**静默截断**——
cols×rows 超限时方案「看似跑完、实则半途终止」，是正确性陷阱；单维度/步进
越界则会把鼠标送出屏幕。本文件锁定三层防护：

1. 模型层 validate_workflow：bool 拒收、单维度上限（cols/rows<=1000、
   cell_dx/dy/dx/dy<=100000）、cols×rows<=GRID_MAX_CELLS（10000，与引擎
   迭代护栏同值）；
2. 引擎层 _run_grid_loop：超限显式报错 + abort + 返回 "aborted"
   （load/load_def 经 _build 校验拒收后的双保险，防直接注入 _def 的调用方）；
3. UI 加载边界 _normalize_loaded_step：非 dict grid 收敛为默认结构（防
   AttributeError 闪退）、数值字段缺省补齐/越界 clamp、cols×rows 压 rows
   自愈——QSpinBox.setValue 对越界值静默截断且不写回 dict，会留下
   「界面显示正常、保存仍报错」的死角。
"""
import pytest

from poe_workflow.workflow_engine import WorkflowEngine
from poe_workflow.workflow_model import (
    workflow_from_dict, validate_workflow,
    GRID_MAX_CELLS, GRID_MAX_DIM, GRID_MAX_OFFSET,
)


class _FakeInp:
    def __init__(self):
        self.clicks = []
        self.moves = []

    def click(self, x, y, button="left", **kw):
        self.clicks.append((x, y, button))

    def move_mouse(self, x, y):
        self.moves.append((x, y))

    def clear_clipboard(self):
        pass

    def press_key(self, key):
        pass

    def read_clipboard(self):
        return ""

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
        return (0, 0)


def _engine(inp=None):
    return WorkflowEngine(_FakeCoord(), inp or _FakeInp())


def _grid_wf(**over):
    """构造一个 grid 循环方案（默认 2x2 合法），grid 字段可覆盖。"""
    g = {"anchor": "map_cell", "dx": 0, "dy": 0,
         "cols": 2, "rows": 2, "cell_dx": 10, "cell_dy": 10}
    g.update(over)
    return workflow_from_dict({"name": "grid", "steps": [
        {"id": "1", "kind": "loop", "grid": g,
         "body": [{"id": "1.1", "kind": "action", "primitive": "wait_ms",
                   "params": {"ms": 0}, "on_error": "retry", "delay_ms": 0}],
         "on_error": "retry", "delay_ms": 0}]})


# ── 模型层校验 ───────────────────────────────────────────────────────────────

def test_grid_dimensions_at_boundary_pass():
    """边界值全部合法：cols/rows 达单维上限、乘积恰达 GRID_MAX_CELLS。"""
    wf = _grid_wf(cols=1000, rows=GRID_MAX_CELLS // 1000,
                  cell_dx=GRID_MAX_OFFSET, cell_dy=GRID_MAX_OFFSET,
                  dx=-GRID_MAX_OFFSET, dy=GRID_MAX_OFFSET)
    assert validate_workflow(wf) == []


def test_grid_base_case_passes():
    assert validate_workflow(_grid_wf()) == []


def test_grid_cols_over_dim_limit_rejected():
    errs = validate_workflow(_grid_wf(cols=GRID_MAX_DIM + 1))
    assert any("grid.cols" in e and "上限" in e for e in errs), errs


def test_grid_rows_over_dim_limit_rejected():
    errs = validate_workflow(_grid_wf(rows=GRID_MAX_DIM + 1))
    assert any("grid.rows" in e and "上限" in e for e in errs), errs


def test_grid_cell_step_over_offset_limit_rejected():
    errs = validate_workflow(_grid_wf(cell_dx=GRID_MAX_OFFSET + 1))
    assert any("grid.cell_dx" in e for e in errs), errs
    errs = validate_workflow(_grid_wf(cell_dy=GRID_MAX_OFFSET + 1))
    assert any("grid.cell_dy" in e for e in errs), errs


def test_grid_origin_offset_over_limit_rejected():
    """原点偏移可负，上限取绝对值（dx/dy 旧版完全不校验）。"""
    errs = validate_workflow(_grid_wf(dx=GRID_MAX_OFFSET + 1))
    assert any("grid.dx" in e for e in errs), errs
    errs = validate_workflow(_grid_wf(dy=-(GRID_MAX_OFFSET + 1)))
    assert any("grid.dy" in e for e in errs), errs


def test_grid_cells_product_over_limit_rejected():
    """乘积超限：引擎迭代护栏处静默截断，校验层必须拒收。"""
    cols, rows = 101, 100
    assert cols * rows > GRID_MAX_CELLS
    errs = validate_workflow(_grid_wf(cols=cols, rows=rows))
    assert any("cols×rows" in e and str(cols * rows) in e for e in errs), errs


def test_grid_bool_dimension_rejected():
    """bool 是 int 子类，JSON true 会绕过 isinstance(int) 检查，须显式拒绝。"""
    errs = validate_workflow(_grid_wf(cols=True))
    assert any("grid.cols" in e and "非负整数" in e for e in errs), errs
    errs = validate_workflow(_grid_wf(cell_dy=False))
    assert any("grid.cell_dy" in e and "非负整数" in e for e in errs), errs


# ── 引擎层护栏 ───────────────────────────────────────────────────────────────

def test_run_grid_loop_refuses_over_limit_dimensions():
    """引擎直接调用（绕过 load 校验）超限网格：显式中止，一格不走。"""
    inp = _FakeInp()
    eng = _engine(inp)
    wf = _grid_wf(cols=200, rows=100)   # 20000 > 10000
    reason = eng._run_grid_loop(wf.steps[0], 0)
    assert reason == "aborted"
    assert eng._abort.is_set()
    assert inp.moves == [], "超限网格一格都不该走"


def test_run_grid_loop_walks_grid_within_limits():
    """合法网格正常遍历（护栏不误伤）：坐标=锚点+偏移+行列步进。"""
    inp = _FakeInp()
    eng = _engine(inp)
    wf = _grid_wf(dx=5, dy=6, cols=2, rows=2, cell_dx=10, cell_dy=20)
    reason = eng._run_grid_loop(wf.steps[0], 0)
    assert reason == "ok"
    assert inp.moves == [(105, 106), (115, 106), (105, 126), (115, 126)]
    assert eng._ctx["__grid_col"] == 1
    assert eng._ctx["__grid_row"] == 1
    assert eng._ctx["__loop_index"] == 3


def test_engine_load_def_rejects_over_limit_grid():
    """load_def 经 _build 校验：超限网格连加载都进不去。"""
    eng = _engine()
    wf = _grid_wf(cols=101, rows=100)
    with pytest.raises(ValueError, match="cols×rows"):
        eng.load_def(wf)


# ── UI 加载边界自愈 ──────────────────────────────────────────────────────────

def _loaded(grid):
    from poe_workflow.ui.tab_workflow import _normalize_loaded_step
    d = {"id": "1", "kind": "loop", "grid": grid,
         "body": [{"id": "1.1", "kind": "action", "primitive": "wait_ms",
                   "params": {"ms": 0}}]}
    _normalize_loaded_step(d)
    return d


def test_normalize_clamps_out_of_range_grid_values():
    d = _loaded({"anchor": "a", "cols": 99999, "rows": 1,
                 "cell_dx": -5, "cell_dy": GRID_MAX_OFFSET + 1,
                 "dx": 200000, "dy": -200000})
    g = d["grid"]
    assert g["cols"] == GRID_MAX_DIM
    assert g["cell_dx"] == 0            # 负步进收敛到 0
    assert g["cell_dy"] == GRID_MAX_OFFSET
    assert g["dx"] == GRID_MAX_OFFSET
    assert g["dy"] == -GRID_MAX_OFFSET
    # 自愈后可通过校验（anchor/body 已在夹具补齐）
    wf = workflow_from_dict({"name": "t", "steps": [d]})
    assert validate_workflow(wf) == []


def test_normalize_fills_missing_grid_numeric_fields():
    """缺数值字段时补默认值——否则 UI spinbox 显示默认值但不写回 dict，
    保存仍报「缺少字段」，用户无法在界面内修复。"""
    d = _loaded({"anchor": "a", "cols": 3})
    g = d["grid"]
    assert g["rows"] == 1
    assert g["dx"] == 0 and g["dy"] == 0
    assert g["cell_dx"] == 0 and g["cell_dy"] == 0
    wf = workflow_from_dict({"name": "t", "steps": [d]})
    assert validate_workflow(wf) == []


def test_normalize_caps_cells_product():
    """乘积超限压 rows 保 cols（自愈后可运行，不丢用户主维度意图）。"""
    d = _loaded({"anchor": "a", "cols": 1000, "rows": 1000,
                 "cell_dx": 1, "cell_dy": 1})
    assert d["grid"]["cols"] == 1000
    assert d["grid"]["rows"] == GRID_MAX_CELLS // 1000
    wf = workflow_from_dict({"name": "t", "steps": [d]})
    assert validate_workflow(wf) == []


def test_normalize_coerces_non_dict_grid_and_card_builds(qapp, config_manager):
    """非 dict grid（手写 json 的 grid: "abc"）收敛为默认结构，
    且 StepCard 可完整构建——旧实现会在 grid.get(...) 抛 AttributeError
    （槽异常 → qFatal 闪退）。"""
    from poe_workflow.ui.tab_workflow import StepCard, WorkflowTab, _normalize_loaded_step
    d = {"kind": "loop", "grid": "abc", "body": []}
    _normalize_loaded_step(d)
    assert isinstance(d["grid"], dict)
    assert d["grid"]["cols"] == 1 and d["grid"]["cell_dx"] == 0
    tab = WorkflowTab(config_manager)
    card = StepCard(d, [d], tab, "1")
    assert card is not None
