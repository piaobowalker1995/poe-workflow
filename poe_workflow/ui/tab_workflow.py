# -*- coding: utf-8 -*-
"""选项卡: 工作流编排（Phase D + 待办1 快捷键持久化 + 待办2-① 卡片编辑器）。

路线 B：独立并行引擎，不修改 state_machine.py。

本标签页功能：
- 方案文件选择：下拉列出 workflows/ 下多个「操作步骤方案文件」(.json)，刷新/新建/删除。
- 快捷键持久化（待办1）：在本标签页用 QKeySequenceEdit 捕获组合键，绑定后写入
  poe_config.txt[Workflow]run_hotkey，重启后自动恢复；清除即清空。
- 运行 / 停止：基于 WorkflowEngine.start()/abort()，线程安全回传状态到 UI。
- 卡片编辑器（待办2-①）：用步骤卡片列表替换原 JSON 文本框。每步一张卡
  （id + 类型 + 参数内联 + 上移/下移/删除）；循环/分支以缩进子列表递归呈现。
  底层仍是 WorkflowDef/JSON，引擎零改动；保存 = 序列化回 JSON。

线程安全：引擎回调运行在引擎自己的工作线程，UI 更新统一经 _EngineBridge 的 PyQt 信号。
"""
import os
import json
import tempfile
import logging

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QTextEdit,
    QLabel, QKeySequenceEdit, QShortcut, QFileDialog, QMessageBox,
    QGroupBox, QFrame, QScrollArea, QLineEdit, QSpinBox, QCheckBox,
    QDialog, QListWidget, QListWidgetItem,
)
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QKeySequence, QFont, QColor
from .hotkey_capture_widget import (mark_capture_clickable,
                                      make_capture_click_handler)

from ..workflow_model import (
    workflow_from_dict, validate_workflow, RULE_PRESETS,
    migrate_delay_ms, remap_jump_targets, collect_step_ids,
    assign_step_ids,
    WorkflowLoadError,
    GRID_MAX_CELLS, GRID_MAX_DIM, GRID_MAX_OFFSET,
    THRESHOLD_PRESETS, FEATURE_LIBRARY, build_or_pattern, threshold_group,
)
from ..workflow_engine import WorkflowEngine
from ._constants import SEC_COORD_CUR
from .text_resources import TextResources
from .workflow_canvas_model import CanvasModel
from .theme import DEFAULT_THEME, get_canvas_colors

logger = logging.getLogger(__name__)

# workflows/ 位于仓库根目录（ui/ 的上一级）
_WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflows"
)

# 卡片下拉选项映射（中文标签 <-> 内部值）
_KIND_LABELS = [("动作", "action"), ("循环", "loop"), ("分支", "branch")]
# 操作类型下拉（中文标签 <-> 内部原语）——显示名单一来源：TextResources。
# 点②+补充2：点击锚点拆为「移动至锚点」（悬停/移位不点击）；
#   键盘/鼠标键统一并入「按键」原语（含左/中/右/滚轮/扩展键+修饰键）。
# 点④：等待毫秒不再作为独立步骤，改为每步内置 delay_ms；复制新增为下拉可选原语。
# click_anchor / wait_ms 保留在模型与引擎中用于兼容旧 .json，但不作为新建选项
# （WF_PRIMITIVE_DROPDOWN 不含这两个 legacy 键）。
_PRIM_LABELS = [(TextResources.WF_PRIMITIVE_LABELS[k], k)
                for k in TextResources.WF_PRIMITIVE_DROPDOWN]
_ERR_LABELS = [("中止", "abort"), ("跳过", "skip"), ("重试", "retry"), ("跳转", "jump")]

# 条件编辑器下拉（中文标签 <-> 内部值）。与引擎 _eval_condition 支持的全集一致
# （CONDITION_SOURCES：clipboard/ctx/ctx_diff/rarity/affix/session/counter/config；
# config=读配置开关，2026-10-23 用户拍板腐化复查按 Strategy.enable_corruption 走）；
# 早先下拉只暴露前 3 个，后 4 个引擎支持但 UI 无入口，本次补齐。
_COND_SRC_LABELS = [
    ("剪贴板内容", "clipboard"),
    ("上下文变量", "ctx"),
    ("前后差异", "ctx_diff"),
    ("稀有度", "rarity"),
    ("词缀裁决", "affix"),
    ("会话状态", "session"),
    ("配置开关", "config"),
    ("计数器", "counter"),
]
_COND_OP_LABELS = [
    ("包含", "contains"),
    ("等于", "equals"),
    ("不等于", "nequals"),
    ("大于", "gt"),
    ("小于", "lt"),
    ("大于等于", "ge"),
    ("小于等于", "le"),
]
# 存仓积木仓库键下拉（中文标签 <-> [StashMapping] 键名）；
# 页签索引在「仓库管理」页按需调整，工作流只存键名不写死页号
_STASH_KEY_LABELS = [
    ("成品仓", "finished_map_stash"),
    ("半成品仓", "semi_finished_stash"),
    ("瑕疵仓", "flawed_map_stash"),
    ("废图仓", "waste_map_stash"),
    ("通货仓", "currency_stash"),
]
# 卡片边框色（按类型区分，让用户一眼分清 动作/循环/分支；标题统一为「步骤」）。
# QGroupBox 不吃 QSS 动态属性选择器，只能按 kind 显式取色，禁止硬编码 hex：
def _canvas_color(tab, name):
    """按当前主题取画布配色项（QGroupBox 边框/子区虚线等非图元也要跟随主题）。

    tab 用于读 General/visual_style；读不到或非法值时回退默认主题。
    """
    try:
        key = tab._cm.get("General", "visual_style", DEFAULT_THEME)
        if key not in ("light", "dark"):
            key = DEFAULT_THEME
    except Exception:
        key = DEFAULT_THEME
    return get_canvas_colors(key)[name]




# ①.1 派生的「仓库页N」锚点：不占 Coordinates_Cur 键位，由 CoordCalculator
# 转发到 stash_tab_position(N) 实时派生。N 可编辑——下拉可自由输入任意页号
# （如「仓库页17」），此处只预置常用页号做快捷项。
DERIVED_STASH_PREFIX = "仓库页"
DERIVED_STASH_PAGES = 12


def _derived_stash_anchors():
    return [f"{DERIVED_STASH_PREFIX}{i}" for i in range(1, DERIVED_STASH_PAGES + 1)]


# ── 锚点分类（用户反馈：锚点应按 仓库页签 / 通货仓 / 背包 分类选择）──
# 存储仍是单个锚点字符串，分类只是 UI 侧的编码方式，引擎侧由
# CoordCalculator.get_absolute_position 解析（见 modules/coord_calculator.py）。
CURRENCY_ANCHOR_PREFIX = "通货:"      # 「通货:点金石」→ 通货仓中已注册的通货格
INVENTORY_ANCHOR_PREFIX = "背包:"     # 「背包:R,C」  → 背包第 R 行第 C 列
MAX_STASH_PAGE = 64                   # 仓库页号上限（下拉可指定任意页 N）

_ANCHOR_KINDS = [
    ("已校准锚点", "calib"),
    ("仓库页签", "stash"),
    ("通货仓", "currency"),
    ("背包格", "inv"),
]


def _anchor_kind_of(value):
    """锚点字符串 -> 分类 key（反解析，用于回显）。"""
    v = (value or "").strip()
    if v.startswith(CURRENCY_ANCHOR_PREFIX):
        return "currency"
    if v.startswith(INVENTORY_ANCHOR_PREFIX):
        return "inv"
    if v.startswith(DERIVED_STASH_PREFIX) and v[len(DERIVED_STASH_PREFIX):].isdigit():
        return "stash"
    return "calib"


def _registered_currencies(cm):
    """已注册通货名列表（[Coordinates_Cur] 中 parent == currency_base_point 的点）。

    与「通货管理」页签同一白名单口径（ui/tab_currency.py:_load_currencies），
    刚注册尚未校准坐标的通货也在其中（cur_x/cur_y 为 0）。
    """
    out = []
    if cm is None:
        return out
    try:
        items = cm.items(SEC_COORD_CUR)
    except Exception:
        return out
    parent_map = {}
    for k, v in items:
        if k.endswith("_parent"):
            parent_map[k[:-7]] = str(v)
    for k, _v in items:
        if k.endswith("_cur_x"):
            nm = k[:-6]
            if parent_map.get(nm) == "currency_base_point":
                out.append(nm)
    return sorted(out)


def _anchor_names(cm):
    """枚举锚点名：①.1 派生的「仓库页N」 + 已校准的 [Coordinates_Cur] 锚点。

    用于锚点下拉框（动作锚点 / 网格原点锚点共用）。派生页锚点排在前面便于选页。
    """
    names = set()
    if cm is not None:
        try:
            keys = cm.get_section_keys(SEC_COORD_CUR)
        except Exception:
            keys = []
        for k in keys:
            if k.endswith("_cur_x"):
                names.add(k[:-6])
    derived = _derived_stash_anchors()
    return derived + sorted(n for n in names if n not in set(derived))


# 已知锚点名 -> 中文友好名（仅用于 UI 展示，存储仍为真实锚点名）。
# 锚点是用户校准时起的标识符；此处仅收录应用默认预置的锚点，
# 未收录的用户自定义锚点回退显示原名 + 坐标，不臆造别名。
_ANCHOR_LABELS = {
    "currency_base_point": "通货基准点",
    "inv_origin_offset": "背包原点偏移",
    "inv_first_cell_base_point": "背包首格基准点",
    "inv_last_cell_aux": "背包末格辅助点",
    "primary_tab_aux": "页签基点",
    "secondary_tab": "页签辅点",
}


def _anchor_disp(cm, name):
    """下拉项显示文本：已知锚点显示中文别名，未知显示原名（不显示坐标）。

    ①.1 派生的「仓库页N」不在 _ANCHOR_LABELS 中，直接回退显示原名（本身已是中文）。
    """
    label = _ANCHOR_LABELS.get(name, name)
    return label


def _stash_key_items(cm):
    """仓库键下拉条目 [(中文标签, StashMapping 键名)]：配置全部键 ∪ 已知键。

    2026-10-23 用户拍板「下拉框要做全，保留扩展选项应变」：
    - 全量：枚举 [StashMapping] 配置里的全部键——用户在仓库管理页新增仓库键
      自动进下拉，不用改代码；
    - 兜底：已知键（_STASH_KEY_LABELS）合并去重——_ensure_initialized 对存量
      配置不回写默认键，纯动态枚举会漏键（如新机器缺 flawed_map_stash）；
    - 展示：已知键显示中文名，未知键显示原名（键名即英文，可直接辨认）。
    """
    keys = []
    if cm is not None:
        try:
            for k in (cm.get_section_keys("StashMapping") or []):
                if k and k not in keys:
                    keys.append(k)
        except Exception:
            pass
    for _lab, k in _STASH_KEY_LABELS:
        if k not in keys:
            keys.append(k)
    key_to_label = {k: lab for lab, k in _STASH_KEY_LABELS}
    return [(key_to_label.get(k, k), k) for k in keys]


# press_key 参数 token 串与捕获显示串之间的映射（鼠标键/滚轮沿用捕获器命名）
_MOUSE_TOKEN_TO_CAPTURE = {
    "mouse_left": "MButton_Left",
    "mouse_right": "MButton_Right",
    "mouse_middle": "MButton_Middle",
    "mouse_wheel_up": "MWheel_Up",
    "mouse_wheel_down": "MWheel_Down",
    "mouse_x1": "MButton_X1",
    "mouse_x2": "MButton_X2",
}
_CAPTURE_TO_MOUSE_TOKEN = {v: k for k, v in _MOUSE_TOKEN_TO_CAPTURE.items()}


def _capture_to_presskey(text):
    """捕获串 -> press_key 字符串（token 全小写，+ 连接）。
    例如 'Ctrl+Shift+A' -> 'ctrl+shift+a'，'Ctrl+MButton_Left' -> 'ctrl+mouse_left'，
    'MWheel_Up' -> 'mouse_wheel_up'。"""
    if not text:
        return ""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    out = []
    for p in parts:
        if p in _CAPTURE_TO_MOUSE_TOKEN:
            out.append(_CAPTURE_TO_MOUSE_TOKEN[p])
        else:
            out.append(p.lower())
    return "+".join(out)


def _presskey_to_capture(text):
    """press_key 字符串 -> 捕获显示串（用于回显已保存的按键值）。
    例如 'ctrl+mouse_left' -> 'Ctrl+MButton_Left'，'mouse_wheel_up' -> 'MWheel_Up'，
    'f12' -> 'F12'。"""
    if not text:
        return ""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    out = []
    for p in parts:
        if p in _MOUSE_TOKEN_TO_CAPTURE:
            out.append(_MOUSE_TOKEN_TO_CAPTURE[p])
        else:
            out.append(p.capitalize())
    return "+".join(out)


def _label(labels, value):
    for lab, val in labels:
        if val == value:
            return lab
    return labels[0][0]


def _value(labels, lab):
    for l, val in labels:
        if l == lab:
            return val
    return labels[0][1]


def _clear_layout(layout):
    """递归清空一个 QLayout 并 delete 其 widget（用于重建卡片列表）。"""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


def _new_step_dict(tab):
    """新建一个合法的默认步骤 dict（动作·点击锚点）。"""
    return {
        "id": "",  # 占位；卡片构建时由层级序号（index_path）覆盖为真实 id
        "kind": "action",
        "primitive": "move_to_anchor",
        "params": {"anchor": ""},
        "on_error": "retry",
        "retry_count": 1,
        "retry_delay_ms": 500,
        "delay_ms": 50,  # 用户反馈：新建步骤默认 50ms 物理延迟
    }


def _normalize_step(d, kind):
    """切换步骤类型时，把 dict 规整为该类型的最小合法结构。"""
    d["kind"] = kind
    if kind == "action":
        d.setdefault("primitive", "move_to_anchor")
        d.setdefault("params", {})
        d.pop("body", None)
        d.pop("condition", None)
        d.pop("then_steps", None)
        d.pop("else_steps", None)
    elif kind == "loop":
        d.pop("primitive", None)
        d.pop("params", None)
        d.setdefault("body", [])
        if d.get("grid") is not None:
            d["count"] = None
            d["condition"] = None
        else:
            d.setdefault("count", 1)
            d.setdefault("condition", None)
    elif kind == "branch":
        d.pop("primitive", None)
        d.pop("params", None)
        d.pop("count", None)
        d.pop("body", None)
        # 修复闪退：loop 分支会把 condition 置为 None，此时 setdefault 不生效，
        # _build_branch 拿到 None 会在 cond.setdefault 处抛 AttributeError
        # （PyQt 槽异常 → qFatal → 进程闪退）。非 dict 一律重建。
        if not isinstance(d.get("condition"), dict):
            d["condition"] = {"source": "clipboard", "op": "equals", "value": ""}
        d.setdefault("then_steps", [])
        d.setdefault("else_steps", [])
    d.setdefault("on_error", "retry")
    d.setdefault("retry_count", 1)
    d.setdefault("retry_delay_ms", 500)
    return d


def _find_step_by_id(steps, step_id):
    """在步骤 dict 树（含 body/then_steps/else_steps）中按 id 递归查找步骤。

    id 由卡片构建时的层级序号推导（如 "2" / "2.1"），画布页签用同一套编号。
    """
    if not step_id:
        return None
    for d in steps or []:
        if str(d.get("id", "")) == str(step_id):
            return d
        for key in ("body", "then_steps", "else_steps"):
            found = _find_step_by_id(d.get(key, []), step_id)
            if found is not None:
                return found
    return None


def _iter_jump_targets(steps):
    """遍历整棵步骤树，产出 (step_id, jump_target)（仅非空目标，运行前校验用）。"""
    for d in steps or []:
        if not isinstance(d, dict):
            continue
        t = d.get("jump_target")
        if t:
            yield d.get("id", ""), t
        for k in ("body", "then_steps", "else_steps"):
            v = d.get(k)
            if isinstance(v, list):
                yield from _iter_jump_targets(v)


def _scheme_file_exists(name):
    """跳转目标是否可作为模块方案名解析（workflows/<name>.json 存在性判断，
    与 _on_run 内 _scheme_loader 的解析语义一致）。"""
    base = name if name.lower().endswith(".json") else name + ".json"
    return os.path.isfile(os.path.join(_WORKFLOWS_DIR, base))


def _default_params(prim):
    if prim in ("click_anchor", "move_to_anchor"):
        return {"anchor": ""}
    if prim == "press_key":
        return {"key": ""}
    if prim == "copy":
        return {"store_as": "clipboard"}
    if prim == "read_clipboard":
        return {"mode": "read", "store_as": "clipboard"}
    if prim == "move_offset":
        return {"anchor": "", "dx": 0, "dy": 0}
    if prim == "wait_ms":
        return {"ms": 100}
    if prim == "log":
        return {"message": ""}
    if prim in ("recall_cell", "abort"):
        return {}
    if prim == "use_currency":
        return {"currency": "", "target": ""}
    if prim == "store_to_stash":
        # 存仓积木：stash_key 是 StashMapping 键名（页签索引走配置按需调整）
        return {"stash_key": "waste_map_stash", "verify": True}
    if prim == "record_session":
        return {}
    if prim == "pause":
        return {"note": ""}
    return {}


def _normalize_loaded_step(d):
    """加载旧 .json 时补齐 kind（手写的 loop/branch 可能缺 kind 字段），
    并递归规整嵌套步骤，确保卡片按正确类型渲染。"""
    if not isinstance(d, dict):
        return
    if "kind" not in d:
        if "then_steps" in d or "else_steps" in d:
            d["kind"] = "branch"
        elif "body" in d:
            d["kind"] = "loop"
        else:
            d["kind"] = "action"
    d.setdefault("on_error", "retry")
    d.setdefault("retry_count", 1)
    d.setdefault("retry_delay_ms", 500)
    # P4-B：补齐容器子列表键。手写 json 的 branch 常缺 else_steps（模型层
    # validate 用 .get 默认值放行），缺键会在 StepCard._build_branch 硬下标
    # 处抛 KeyError——槽异常 → qFatal 闪退。在加载边界一次性补齐。
    if d.get("kind") == "loop" and not isinstance(d.get("body"), list):
        d["body"] = []
    elif d.get("kind") == "branch":
        for k in ("then_steps", "else_steps"):
            if not isinstance(d.get(k), list):
                d[k] = []
    # G8：grid 形状自愈。非 dict（手写 json 的 grid: "x"）会让卡片构建处
    # grid.get(...) 抛 AttributeError（槽异常 → qFatal 闪退），收敛为默认结构；
    # 数值字段缺省/越界同样在此收敛——UI 的 QSpinBox.setValue 对越界值静默
    # 截断且不写回 dict（无 valueChanged 信号），会留下「界面显示正常、
    # 保存仍报错」的死角；cols×rows 超引擎迭代上限时压 rows 保 cols。
    if d.get("kind") == "loop" and d.get("grid") is not None:
        if not isinstance(d["grid"], dict):
            d["grid"] = {"anchor": "", "dx": 0, "dy": 0,
                         "cols": 1, "rows": 1, "cell_dx": 0, "cell_dy": 0}
        else:
            g = d["grid"]
            for f in ("cols", "rows"):
                v = g.get(f)
                g[f] = 1 if (isinstance(v, bool) or not isinstance(v, int)) \
                    else max(1, min(GRID_MAX_DIM, v))
            for f, lo in (("dx", -GRID_MAX_OFFSET), ("dy", -GRID_MAX_OFFSET),
                          ("cell_dx", 0), ("cell_dy", 0)):
                v = g.get(f)
                g[f] = 0 if (isinstance(v, bool) or not isinstance(v, int)) \
                    else max(lo, min(GRID_MAX_OFFSET, v))
            if g["cols"] * g["rows"] > GRID_MAX_CELLS:
                g["rows"] = max(1, GRID_MAX_CELLS // g["cols"])
    for k in ("body", "then_steps", "else_steps"):
        if isinstance(d.get(k), list):
            for c in d[k]:
                _normalize_loaded_step(c)


class _EngineBridge(QObject):
    """引擎回调 -> UI 信号桥（保证跨线程更新 UI 安全）。"""
    status = pyqtSignal(str, str)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)


class StepCard(QWidget):
    """单步卡片：编辑一个步骤 dict（动作/循环/分支均可，循环/分支递归嵌套子卡片）。

    self._d        : 本卡片编辑的步骤 dict（直接原地修改，作为唯一真源）
    self._parent_list: 包含 self._d 的列表（用于删除/上下移时操作父列表）
    self._tab      : WorkflowTab 引用（结构变更时触发整树重建）
    """

    # 任意字段编辑（QLineEdit/ComboBox/SpinBox/CheckBox/KeySequence）后发射，
    # 由 WorkflowTab 接为「未保存」标记（C1）。
    contentChanged = pyqtSignal()

    def __init__(self, step_dict, parent_list, tab, index_path=None):
        super().__init__()
        self._d = step_dict
        self._parent_list = parent_list
        self._tab = tab
        self._index_path = index_path  # 层级序号（如 '2' / '2.1'），用于标题展示
        # 内部 id 与层级序号一致（隐藏手动编号框，id 由位置自动推导）。
        # index_path 由调用方从 assign_step_ids 已分配好的 d["id"] 传入，
        # 这里的写回是幂等的（不再自行拼算编号——编号规则唯一事实源在
        # modules/workflow_model.assign_step_ids，列表/画布共用）。
        self._d["id"] = self._index_path or ""

        # StepCard 自身布局：容纳外层 GroupBox（否则卡片渲染为空壳）
        wrapper = QVBoxLayout(self)
        wrapper.setContentsMargins(0, 0, 0, 0)

        self._outer = QGroupBox()
        wrapper.addWidget(self._outer)
        self._refresh_title()
        self._refresh_style()
        main = QVBoxLayout(self._outer)
        main.setSpacing(4)

        # ── 头部：类型 / 移动 / 删除（id 由层级序号自动推导，不手动编辑）──
        hdr = QHBoxLayout()
        kind = QComboBox()
        kind.addItems([l for l, _ in _KIND_LABELS])
        kind.setCurrentText(_label(_KIND_LABELS, self._d.get("kind", "action")))
        kind.currentTextChanged.connect(self._on_kind)
        up = QPushButton("↑")
        up.setMaximumWidth(28)
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("↓")
        down.setMaximumWidth(28)
        down.clicked.connect(lambda: self._move(1))
        delb = QPushButton("✕")
        delb.setMaximumWidth(28)
        delb.clicked.connect(self._delete)
        hdr.addWidget(QLabel("类型"))
        hdr.addWidget(kind)
        hdr.addWidget(up)
        hdr.addWidget(down)
        hdr.addWidget(delb)
        hdr.addStretch(1)
        main.addLayout(hdr)

        # ── 内部参数区（按类型构建）──
        self._inner_w = QWidget()
        self._inner = QVBoxLayout(self._inner_w)
        self._inner.setContentsMargins(0, 0, 0, 0)
        main.addWidget(self._inner_w)
        self._build_inner()
        # C1：所有编辑类控件变化统一经 contentChanged -> WorkflowTab._mark_dirty。
        # _loading 守卫确保构建期（程序化 setText/setCurrentText）不误标 dirty。
        self._loading = True
        self.contentChanged.connect(self._tab._mark_dirty)
        for w in self.findChildren(
                (QLineEdit, QComboBox, QSpinBox, QCheckBox, QKeySequenceEdit)):
            if isinstance(w, QLineEdit):
                w.textChanged.connect(self._emit_changed)
            elif isinstance(w, QSpinBox):
                w.valueChanged.connect(self._emit_changed)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._emit_changed)
            elif isinstance(w, QCheckBox):
                w.stateChanged.connect(self._emit_changed)
            elif isinstance(w, QKeySequenceEdit):
                w.keySequenceChanged.connect(self._emit_changed)
        self._loading = False

    def _emit_changed(self):
        if getattr(self, "_loading", False):
            return
        self.contentChanged.emit()

    # ------------------------------------------------------------------ #
    def iter_descendant_cards(self):
        """产出本卡片的所有后代步骤卡片（子区 GroupBox 内，含嵌套）。

        只走**当前布局**（self._inner 的 widget）——不用
        self.findChildren(StepCard)：重建后 deleteLater 的陈旧卡片仍是
        页签/容器的子对象（offscreen 下不泵事件不销毁），会被误捞。
        供聚焦点击快速路径定位既有卡片，见 WorkflowTab._find_live_card。
        """
        for i in range(self._inner.count()):
            item = self._inner.itemAt(i)
            w = item.widget() if item is not None else None
            if w is None:
                continue          # stretch / spacer
            for c in w.findChildren(StepCard):
                yield c

    def _refresh_title(self):
        # 标题统一为「步骤」+ 层级序号（子步骤带父级序号，如 2.1 / 2.2）
        title = self._index_path if self._index_path else self._d.get("id", "")
        self._outer.setTitle(f"步骤 {title}")

    def _refresh_style(self):
        # 边框按 kind 走主题 QSS（见 ui/theme.py 的 QGroupBox#StepCardOuter-* 规则），
        # 不再内联样式；子区虚线框统一用 objectName=StepCardChildArea 走主题。
        # 切换类型 / 主题后重建会经此刷新：仅改 objectName 并让样式表重算。
        kind = self._d.get("kind", "action")
        name = "action"
        if kind == "loop":
            name = "loop"
        elif kind == "branch":
            name = "branch"
        # kind=subworkflow（P4-A 一等公民）或 action+on_error=jump → 子工作流，用 sub 边框
        if kind == "subworkflow" or (kind == "action" and self._d.get("on_error") == "jump"):
            name = "sub"
        self._outer.setObjectName(f"StepCardOuter-{name}")
        self._outer.style().unpolish(self._outer)
        self._outer.style().polish(self._outer)

    def _safe(self, what, fn):
        """重建类槽的保护壳。

        PyQt5 5.15 中槽抛出的 Python 异常会触发 qFatal 直接终止进程（表现为「闪退」）。
        卡片重建涉及 dict 结构规整 + 控件销毁重建，任一处出错都不该杀掉整个应用：
        这里兜底记录日志并提示到编辑器状态行。
        """
        try:
            fn()
            return True
        except Exception as exc:
            logger.error(f"步骤卡片{what}失败: {exc}", exc_info=True)
            try:
                self._tab._set_editor_status(f"{what}失败：{exc}", "error")
            except Exception:
                pass
            return False

    def _on_kind(self, label):
        def _do():
            _normalize_step(self._d, _value(_KIND_LABELS, label))
            self._refresh_title()
            self._refresh_style()
            self._build_inner()
        self._safe("切换步骤类型", _do)

    def _on_primitive(self, label):
        def _do():
            key = _value(_PRIM_LABELS, label)
            self._d["primitive"] = key
            self._d["params"] = _default_params(key)
            self._build_inner()
        self._safe("切换操作类型", _do)

    def _on_presskey_captured(self, line_edit, key_str):
        """「单击即捕获」回调：捕获串转 press_key 参数写入并回显。"""
        # 捕获态结束：复位占位提示（无论成功/取消都回到常态提示）
        line_edit.setPlaceholderText("单击后按下按键")
        if key_str == "ESC":
            # ESC 取消捕获（key_capture 文档约定），恢复进入捕获前的旧值
            prev = line_edit.property("__prev_key_text")
            if prev:
                line_edit.setText(prev)
            return
        token = _capture_to_presskey(key_str)
        if not token:
            return
        self._set_param("key", token)
        line_edit.setText(_presskey_to_capture(token))

    def _set_param(self, key, val):
        self._d.setdefault("params", {})[key] = val

    def _set_delay(self, v):
        # A1：步骤延迟写**顶层** delay_ms（模型 _step_from_dict / 引擎 _run_one
        # 的唯一口径）；历史版本经 _set_param 误写 params.delay_ms，导致延迟
        # 静默失效并污染落盘 JSON（存量清洗见 workflow_model.migrate_delay_ms）
        self._d["delay_ms"] = int(v)

    def _move(self, delta):
        def _do():
            lst = self._parent_list
            try:
                i = lst.index(self._d)
            except ValueError:
                return
            j = i + delta
            if 0 <= j < len(lst):
                lst[i], lst[j] = lst[j], lst[i]
                self._tab._rebuild_cards()
                self._tab._mark_dirty()
        self._safe("移动步骤", _do)

    def _delete(self):
        def _do():
            if self._d in self._parent_list:
                self._parent_list.remove(self._d)
            self._tab._rebuild_cards()
            self._tab._mark_dirty()
        self._safe("删除步骤", _do)

    # ------------------------------------------------------------------ #
    def _build_inner(self):
        _clear_layout(self._inner)
        kind = self._d.get("kind", "action")
        if kind == "action":
            self._build_action()
        elif kind == "loop":
            self._build_loop()
        elif kind == "branch":
            self._build_branch()
        elif kind == "subworkflow":
            self._build_subworkflow()
        self._build_error_policy()

    def _build_action(self):
        prim = QComboBox()
        prim.addItems([l for l, _ in _PRIM_LABELS])
        prim.setCurrentText(_label(_PRIM_LABELS, self._d.get("primitive", "move_to_anchor")))
        prim.currentTextChanged.connect(self._on_primitive)
        self._inner.addWidget(_labeled("操作类型", prim))
        self._inner.addWidget(self._build_param_editor())
        self._inner.addWidget(self._build_delay_row())

    def _build_subworkflow(self):
        # P4-A：编辑子工作流调用——模块名存 jump_target（复用跳转目标编辑器：
        # 可选 workflows/ 下的模块方案名；本方案步骤 id 亦列出但子工作流仅解析模块）。
        self._inner.addWidget(self._build_jump_target_editor())
        self._inner.addWidget(self._build_delay_row())

    def _build_anchor_picker(self, label, get_val, set_val):
        """分类锚点选择器（点击锚点/移动至锚点/相对移动/网格原点共用）。

        四类：
          已校准锚点 —— 从 [Coordinates_Cur] 已校准点中选择（可手输）
          仓库页签   —— 指定仓库页 N（派生锚点「仓库页N」，引擎实时算页签坐标）
          通货仓     —— 指定已注册的任意通货（含刚注册未校准的），生成「通货:名称」
          背包格     —— 指定背包网格 行/列，生成「背包:R,C」
        存储仍为单个锚点字符串，引擎侧由 CoordCalculator 解析。
        """
        kind = _anchor_kind_of(get_val())
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        kcb = QComboBox()
        kcb.addItems([l for l, _ in _ANCHOR_KINDS])
        kcb.setCurrentText(_label(_ANCHOR_KINDS, kind))
        kcb.setMaximumWidth(120)
        kcb.setToolTip("锚点分类：仓库页签=指定仓库页N；通货仓=指定已注册通货；背包格=指定背包行列")
        row.addWidget(QLabel(label))
        row.addWidget(kcb)
        row.addStretch(1)
        v.addLayout(row)

        args = QWidget()
        av = QVBoxLayout(args)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(2)
        v.addWidget(args)

        def _cur_text():
            return (get_val() or "").strip()

        def _fill(k):
            _clear_layout(av)
            cur = _cur_text()
            if k == "calib":
                cb = QComboBox()
                cb.setEditable(True)
                cb.setMinimumWidth(240)
                cb.setToolTip("从已校准锚点中选择（已知锚点显示中文别名，未知显示原名），也可手动输入锚点名")
                # 派生的「仓库页N」由「仓库页签」分类承担，此处不重复列出
                names = [n for n in _anchor_names(self._tab._cm)
                         if not (n.startswith(DERIVED_STASH_PREFIX)
                                 and n[len(DERIVED_STASH_PREFIX):].isdigit())]
                for nm in names:
                    cb.addItem(_anchor_disp(self._tab._cm, nm), nm)

                def _on_anchor(t):
                    idx = cb.findText(t)
                    data = cb.itemData(idx) if idx >= 0 else None
                    set_val(data if data else t)

                cb.currentTextChanged.connect(_on_anchor)
                if cur and _anchor_kind_of(cur) == "calib":
                    idx = cb.findData(cur)
                    if idx < 0:
                        cb.insertItem(0, cur, cur)
                        idx = 0
                    cb.setCurrentIndex(idx)
                elif cur and names:
                    # 从其它分类切回：同步写回首项，避免下拉显示与存储值不一致
                    cb.setCurrentIndex(0)
                    set_val(names[0])
                elif not names:
                    av.addWidget(QLabel("（尚未校准任何锚点：请到坐标页签校准）"))
                av.addWidget(cb)
            elif k == "stash":
                n = 1
                if cur.startswith(DERIVED_STASH_PREFIX) and cur[len(DERIVED_STASH_PREFIX):].isdigit():
                    n = int(cur[len(DERIVED_STASH_PREFIX):])
                sb = QSpinBox()
                sb.setObjectName("anchor_stash_page")
                sb.setRange(1, MAX_STASH_PAGE)
                sb.setSuffix(" 页")
                sb.setValue(n)
                sb.setToolTip("仓库页号 N：由页签基点 + 页间距实时派生坐标，无需单独校准")
                sb.valueChanged.connect(lambda v: set_val(f"{DERIVED_STASH_PREFIX}{v}"))
                av.addWidget(_labeled("仓库页", sb))
                set_val(f"{DERIVED_STASH_PREFIX}{n}")
            elif k == "currency":
                names = _registered_currencies(self._tab._cm)
                cb = QComboBox()
                cb.setEditable(True)
                cb.setMinimumWidth(240)
                cb.setToolTip("已注册的通货（含刚注册尚未校准坐标的）；也可手输通货名")
                for nm in names:
                    cb.addItem(nm, nm)
                init = cur[len(CURRENCY_ANCHOR_PREFIX):] if cur.startswith(CURRENCY_ANCHOR_PREFIX) else ""
                if init:
                    idx = cb.findData(init)
                    if idx < 0:
                        cb.insertItem(0, init, init)
                        idx = 0
                    cb.setCurrentIndex(idx)
                elif names:
                    cb.setCurrentIndex(0)
                    init = names[0]

                def _on_cur(t):
                    idx = cb.findText(t)
                    data = cb.itemData(idx) if idx >= 0 else None
                    set_val(f"{CURRENCY_ANCHOR_PREFIX}{data if data else t}")

                cb.currentTextChanged.connect(_on_cur)
                av.addWidget(_labeled("通货", cb))
                if init:
                    set_val(f"{CURRENCY_ANCHOR_PREFIX}{init}")
                elif not names:
                    av.addWidget(QLabel("（尚未注册通货：请到「通货管理」页签添加）"))
            else:  # inv
                r, c = 1, 1
                if cur.startswith(INVENTORY_ANCHOR_PREFIX):
                    parts = cur[len(INVENTORY_ANCHOR_PREFIX):].split(",")
                    if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
                        r, c = int(parts[0]), int(parts[1])

                def _emit(_v=None):
                    set_val(f"{INVENTORY_ANCHOR_PREFIX}{rs.value()},{cs.value()}")

                rs = QSpinBox()
                rs.setObjectName("anchor_inv_row")
                rs.setRange(1, 60)
                rs.setSuffix(" 行")
                rs.setValue(r)
                cs = QSpinBox()
                cs.setObjectName("anchor_inv_col")
                cs.setRange(1, 60)
                cs.setSuffix(" 列")
                cs.setValue(c)
                rs.valueChanged.connect(_emit)
                cs.valueChanged.connect(_emit)
                grid = QWidget()
                gh = QHBoxLayout(grid)
                gh.setContentsMargins(0, 0, 0, 0)
                gh.addWidget(rs)
                gh.addWidget(cs)
                gh.addStretch(1)
                av.addWidget(_labeled("背包格", grid))
                set_val(f"{INVENTORY_ANCHOR_PREFIX}{r},{c}")

        def _on_kind(_t):
            self._safe("切换锚点分类",
                       lambda: _fill(_value(_ANCHOR_KINDS, kcb.currentText())))

        kcb.currentTextChanged.connect(_on_kind)
        _fill(kind)
        return holder

    def _build_param_editor(self):
        prim = self._d.get("primitive", "move_to_anchor")
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)

        def _anchor_picker(label="锚点"):
            return self._build_anchor_picker(
                label,
                lambda: self._d.get("params", {}).get("anchor", ""),
                lambda v: self._set_param("anchor", v))

        if prim in ("click_anchor", "move_to_anchor"):
            h.addWidget(_anchor_picker())
        elif prim == "move_offset":
            # ①.2 相对移动：锚点 + (dx, dy) 像素偏移后移动光标
            # 用户反馈：X/Y 偏移与锚点同行太宽 —— 偏移单独占一行
            params = self._d.get("params", {})
            v = QVBoxLayout()
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            v.addWidget(_anchor_picker())
            off = QWidget()
            oh = QHBoxLayout(off)
            oh.setContentsMargins(0, 0, 0, 0)
            dx_sb = QSpinBox()
            dx_sb.setObjectName("offset_dx")
            dx_sb.setRange(-100000, 100000)
            dx_sb.setSuffix(" px")
            dy_sb = QSpinBox()
            dy_sb.setObjectName("offset_dy")
            dy_sb.setRange(-100000, 100000)
            dy_sb.setSuffix(" px")
            dx_sb.setValue(int(params.get("dx", 0) or 0))
            dy_sb.setValue(int(params.get("dy", 0) or 0))
            dx_sb.valueChanged.connect(lambda val: self._set_param("dx", val))
            dy_sb.valueChanged.connect(lambda val: self._set_param("dy", val))
            oh.addWidget(QLabel("X 偏移"))
            oh.addWidget(dx_sb)
            oh.addWidget(QLabel("Y 偏移"))
            oh.addWidget(dy_sb)
            oh.addStretch(1)
            v.addWidget(off)
            holder = QWidget()
            hv = QVBoxLayout(holder)
            hv.setContentsMargins(0, 0, 0, 0)
            hv.addLayout(v)
            h.addWidget(holder, stretch=1)
        elif prim == "press_key":
            # 键盘/鼠标统一为「单击即捕获」输入框（与热键/快捷筛选页签同交互）：
            # 点击框后直接按下真实按键（键盘键/鼠标键/滚轮，可含 Ctrl/Shift/Alt）。
            cur = self._d.get("params", {}).get("key", "")
            cap = QLineEdit(_presskey_to_capture(cur))
            cap.setReadOnly(True)
            cap.setMaximumWidth(180)
            cap.setPlaceholderText("单击后按下按键")
            mark_capture_clickable(cap)

            def _start_presskey_capture(le=None):
                inp = getattr(self._tab, "_input", None)
                if inp is None:
                    self._tab._set_editor_status("输入模拟器不可用，无法捕获按键",
                                                  "error")
                    return
                # 进入捕获态：清空旧值并给出「等待输入」占位提示，避免仍显示旧按键
                # 让人误以为没在监听（用户反馈点记录后无提示、不显眼）。
                if le is not None:
                    le.setProperty("__prev_key_text", le.text())
                    le.clear()
                    le.setPlaceholderText("请按下按键…（ESC 取消）")
                self._tab._set_editor_status("正在捕获按键，请按下组合键（ESC 取消）", "info")
                inp.capture_hotkey(
                    lambda ks, le=le: self._on_presskey_captured(le, ks))

            cap.mousePressEvent = make_capture_click_handler(
                cap, lambda le: _start_presskey_capture(le))
            h.addWidget(QLabel("按键"))
            h.addWidget(cap, stretch=1)

        elif prim == "read_clipboard":
            # 批3 ③：读整段 / 匹配规则（共享 RULE_PRESETS）
            holder = QWidget()
            eh = QVBoxLayout(holder)
            eh.setContentsMargins(0, 0, 0, 0)
            params = self._d.get("params", {})
            mode = QComboBox()
            mode.addItems(["读整段", "匹配规则"])
            mode.setCurrentText("匹配规则" if params.get("mode") == "match" else "读整段")
            store_le = QLineEdit(params.get("store_as", "clipboard"))
            store_le.setPlaceholderText("变量名（默认 clipboard）")
            store_le.setMaximumWidth(160)
            def _on_mode(t):
                if t == "匹配规则":
                    self._set_param("mode", "match")
                    if "rule" not in params:
                        self._set_param("rule", "item_quantity")
                else:
                    self._set_param("mode", "read")
                    self._d["params"].pop("rule", None)
                rule_w.setVisible(t == "匹配规则")

            def _on_rule(rule, _default_op):
                self._set_param("rule", rule)

            rule_w = _build_rule_editor(params.get("rule", "item_quantity"), _on_rule)
            mode.currentTextChanged.connect(_on_mode)
            store_le.textChanged.connect(
                lambda t: self._set_param("store_as", t.strip() or "clipboard"))
            eh.addWidget(_labeled("模式", mode))
            eh.addWidget(_labeled("变量名", store_le))
            eh.addWidget(_labeled("匹配规则", rule_w))
            rule_w.setVisible(params.get("mode") == "match")
            h.addWidget(holder, stretch=1)
        elif prim == "copy":
            # 点④：复制 = 模拟 Ctrl+C 后把剪贴板内容存入命名变量
            le = QLineEdit(self._d.get("params", {}).get("store_as", "clipboard"))
            le.setMaximumWidth(160)
            le.setPlaceholderText("变量名（默认 clipboard）")
            le.setToolTip("复制后剪贴板内容存入此命名变量，供后续条件匹配/读取使用")
            le.textChanged.connect(
                lambda t: self._set_param("store_as", t.strip() or "clipboard"))
            h.addWidget(QLabel("变量名"))
            h.addWidget(le)
            # G6：可选复制校验前缀。留空=不校验；填写后剪贴板内容不以它
            # 开头即判复制失败（Ctrl+C 未生效时会留下旧内容，单看非空发现不了），
            # 抛错交本步 on_error（重试/跳转）恢复。
            ep_le = QLineEdit(str(self._d.get("params", {}).get("expect_prefix", "") or ""))
            ep_le.setMaximumWidth(200)
            ep_le.setPlaceholderText("如：物品类别: 地图（留空=不校验）")
            ep_le.setToolTip("可选：复制后期望内容的开头文本，不匹配则本步报错（交重试/跳转恢复）")

            def _on_expect(t):
                if t:
                    self._set_param("expect_prefix", t)
                else:
                    self._d.setdefault("params", {}).pop("expect_prefix", None)

            ep_le.textChanged.connect(_on_expect)
            h.addWidget(QLabel("内容前缀"))
            h.addWidget(ep_le)
        elif prim == "wait_ms":
            # 兼容旧文件：wait_ms 仍可作为独立步骤渲染（新编排建议改用每步 delay_ms）
            sb = QSpinBox()
            sb.setRange(0, 600000)
            sb.setSuffix(" ms")
            sb.setValue(int(self._d.get("params", {}).get("ms", 100)))
            sb.valueChanged.connect(lambda v: self._set_param("ms", v))
            h.addWidget(QLabel("等待"))
            h.addWidget(sb)
        elif prim == "log":
            # 全量复刻制图：打印消息到主窗口日志栏（调试分支走向用）
            le = QLineEdit(self._d.get("params", {}).get("message", ""))
            le.setPlaceholderText("要打印到日志栏的消息")
            le.setToolTip("运行到该步时把消息写入主窗口底部日志栏（[工作流] 前缀），用于确认分支走向")
            le.textChanged.connect(lambda t: self._set_param("message", t))
            h.addWidget(QLabel("消息"))
            h.addWidget(le, stretch=1)
        elif prim == "recall_cell":
            h.addWidget(QLabel("（把光标移回网格循环的当前格：取通货后回背包格应用时使用）"))
        elif prim == "abort":
            le2 = QLineEdit(self._d.get("params", {}).get("reason", ""))
            le2.setPlaceholderText("中止原因（可选，写入日志）")
            le2.textChanged.connect(lambda t: self._set_param("reason", t))
            h.addWidget(QLabel("原因"))
            h.addWidget(le2, stretch=1)
        elif prim == "use_currency":
            # 纯积木：通货应用。currency=通货名，target=目标格锚点名（与 click_anchor 同体系）
            params = self._d.get("params", {})
            cur_le = QLineEdit(params.get("currency", ""))
            cur_le.setPlaceholderText("通货名（如 重铸石）")
            cur_le.setMaximumWidth(160)
            cur_le.textChanged.connect(
                lambda t: self._set_param("currency", t.strip()))
            target_picker = self._build_anchor_picker(
                "目标格",
                lambda: self._d.get("params", {}).get("target", ""),
                lambda v: self._set_param("target", v))
            h.addWidget(QLabel("通货"))
            h.addWidget(cur_le)
            h.addWidget(target_picker)
            h.addStretch(1)
        elif prim == "store_to_stash":
            # 存仓积木（2026-10-23）：仓库键=StashMapping 键名（页签索引走配置，
            # 在「仓库管理」页按需调整）；目标格同 use_currency 口径，留空=当前光标。
            # 用户拍板「下拉要做全 + 保留扩展选项应变」：动态枚举 [StashMapping]
            # 全部键（仓库页新增键自动进下拉，不用改代码）；setEditable 保留手输
            # 自定义键名以应变（未知键展示即原名，直接当键名写回）。
            params = self._d.get("params", {})
            cm = self._tab._cm if self._tab is not None else None
            _items = _stash_key_items(cm)
            _label_to_key = {l: k for l, k in _items}
            key_cb = QComboBox()
            key_cb.setObjectName("StashKeyCombo")
            key_cb.setEditable(True)
            key_cb.setInsertPolicy(QComboBox.InsertPolicy.InsertAtBottom)
            key_cb.setMinimumWidth(120)
            key_cb.addItems([l for l, _ in _items])
            key_cb.setCurrentText(
                _label(_items, params.get("stash_key", "waste_map_stash")))
            key_cb.setToolTip("存到哪个仓：键名对应 [StashMapping] 页签索引，在「仓库管理」页按需调整；也可手输自定义键名")
            def _on_stash_key_changed(t):
                # 已知键→写键名；未知（手输）→ 文本本身当键名（未知键展示即原名）
                self._set_param("stash_key", _label_to_key.get(t, t))
            key_cb.currentTextChanged.connect(_on_stash_key_changed)
            target_picker = self._build_anchor_picker(
                "目标格",
                lambda: self._d.get("params", {}).get("target", ""),
                lambda v: self._set_param("target", v))
            verify_cb = QCheckBox("存后验证")
            verify_cb.setObjectName("StashVerifyCheck")
            verify_cb.setChecked(bool(params.get("verify", True)))
            verify_cb.setToolTip("存入后校验光标处剪贴板是否已空（物品确实入库）；未通过只记日志不中断")
            verify_cb.toggled.connect(lambda v: self._set_param("verify", bool(v)))
            h.addWidget(QLabel("仓库"))
            h.addWidget(key_cb)
            h.addWidget(target_picker)
            h.addWidget(verify_cb)
            h.addStretch(1)
        elif prim == "pause":
            # G4：软暂停（等待 UI 继续按钮）。note 仅写入日志便于追溯。
            note_le = QLineEdit(self._d.get("params", {}).get("note", ""))
            note_le.setPlaceholderText("暂停备注（可选）")
            note_le.textChanged.connect(lambda t: self._set_param("note", t.strip()))
            h.addWidget(QLabel("备注"))
            h.addWidget(note_le, stretch=1)
        else:
            h.addWidget(QLabel("（无参数）"))
        return w

    def _build_delay_row(self):
        # 点④：每步内置延迟，替代独立「等待毫秒」步骤
        sb = QSpinBox()
        sb.setRange(0, 600000)
        sb.setSuffix(" ms")
        sb.setValue(int(self._d.get("delay_ms", 0) or 0))
        sb.setToolTip("每步执行后的内置延迟（替代独立「等待毫秒」步骤；新建步骤默认 50ms）")
        sb.valueChanged.connect(lambda v: self._set_delay(v))
        return _labeled("步骤延迟", sb)

    def _set_grid(self, key, val):
        self._d.setdefault("grid", {})[key] = val

    def _build_grid_anchor_combo(self):
        """网格循环专用锚点选择：锚点存于 self._d['grid']['anchor']（与 action 的 params.anchor 区分）。

        复用分类选择器（已校准锚点 / 仓库页签 / 通货仓 / 背包格）。
        """
        return self._build_anchor_picker(
            "原点锚点",
            lambda: (self._d.get("grid", {}) or {}).get("anchor", ""),
            lambda v: self._set_grid("anchor", v))

    def _build_loop(self):
        self._d.setdefault("body", [])
        has_count = self._d.get("count") is not None
        has_cond = self._d.get("condition") is not None
        has_grid = self._d.get("grid") is not None
        mode = "count" if has_count else ("condition" if has_cond else "grid")
        mode_combo = QComboBox()
        mode_combo.addItems(["固定次数", "条件终止", "网格"])
        mode_combo.setCurrentText({"count": "固定次数", "condition": "条件终止", "grid": "网格"}[mode])

        def _mode_changed(t):
            def _do():
                # 切换模式时清空另外两种，避免并存触发校验（只能有 count / condition / grid 之一）
                self._d["count"] = None
                self._d["condition"] = None
                self._d["grid"] = None
                if t == "固定次数":
                    self._d["count"] = 1
                elif t == "条件终止":
                    self._d["condition"] = {
                        "source": "clipboard", "op": "equals", "value": ""}
                else:  # 网格
                    self._d["grid"] = {
                        "anchor": "", "dx": 0, "dy": 0, "cols": 1, "rows": 1,
                        "cell_dx": 0, "cell_dy": 0}
                self._build_inner()
            self._safe("切换循环方式", _do)

        mode_combo.currentTextChanged.connect(_mode_changed)
        self._inner.addWidget(_labeled("循环方式", mode_combo))

        if mode == "count":
            sb = QSpinBox()
            sb.setRange(1, 100000)
            sb.setValue(int(self._d.get("count") or 1))
            sb.valueChanged.connect(lambda v: self._d.__setitem__("count", v))
            self._inner.addWidget(_labeled("次数", sb))
        elif mode == "condition":
            # 兜底：condition 非 dict（如旧数据/切模式残留）时重建，避免 None.setdefault 崩溃
            if not isinstance(self._d.get("condition"), dict):
                self._d["condition"] = {"source": "clipboard", "op": "equals", "value": ""}
            self._inner.addWidget(self._build_condition_editor(self._d["condition"]))
        else:  # 网格
            grid = self._d.get("grid", {}) or {}
            gbox = QGroupBox("网格设置")
            gv = QVBoxLayout(gbox)
            gv.setSpacing(4)
            gv.addWidget(self._build_grid_anchor_combo())
            # 原点像素偏移
            off = QWidget()
            oh = QHBoxLayout(off)
            oh.setContentsMargins(0, 0, 0, 0)
            dx_sb = QSpinBox(); dx_sb.setRange(-100000, 100000); dx_sb.setSuffix(" px")
            dy_sb = QSpinBox(); dy_sb.setRange(-100000, 100000); dy_sb.setSuffix(" px")
            dx_sb.setValue(int(grid.get("dx", 0) or 0))
            dy_sb.setValue(int(grid.get("dy", 0) or 0))
            dx_sb.valueChanged.connect(lambda v: self._set_grid("dx", v))
            dy_sb.valueChanged.connect(lambda v: self._set_grid("dy", v))
            oh.addWidget(QLabel("原点 X 偏移")); oh.addWidget(dx_sb)
            oh.addWidget(QLabel("原点 Y 偏移")); oh.addWidget(dy_sb)
            gv.addWidget(off)
            # 行列数
            dim = QWidget()
            dh = QHBoxLayout(dim)
            dh.setContentsMargins(0, 0, 0, 0)
            cols_sb = QSpinBox(); cols_sb.setRange(1, 1000); cols_sb.setSuffix(" 列")
            rows_sb = QSpinBox(); rows_sb.setRange(1, 1000); rows_sb.setSuffix(" 行")
            cols_sb.setValue(int(grid.get("cols", 1) or 1))
            rows_sb.setValue(int(grid.get("rows", 1) or 1))
            cols_sb.valueChanged.connect(lambda v: self._set_grid("cols", v))
            rows_sb.valueChanged.connect(lambda v: self._set_grid("rows", v))
            dh.addWidget(QLabel("列数")); dh.addWidget(cols_sb)
            dh.addWidget(QLabel("行数")); dh.addWidget(rows_sb)
            gv.addWidget(dim)
            # 单元格步进
            cell = QWidget()
            ch = QHBoxLayout(cell)
            ch.setContentsMargins(0, 0, 0, 0)
            cdx_sb = QSpinBox(); cdx_sb.setRange(0, 100000); cdx_sb.setSuffix(" px")
            cdy_sb = QSpinBox(); cdy_sb.setRange(0, 100000); cdy_sb.setSuffix(" px")
            cdx_sb.setValue(int(grid.get("cell_dx", 0) or 0))
            cdy_sb.setValue(int(grid.get("cell_dy", 0) or 0))
            cdx_sb.valueChanged.connect(lambda v: self._set_grid("cell_dx", v))
            cdy_sb.valueChanged.connect(lambda v: self._set_grid("cell_dy", v))
            ch.addWidget(QLabel("列步进")); ch.addWidget(cdx_sb)
            ch.addWidget(QLabel("行步进")); ch.addWidget(cdy_sb)
            gv.addWidget(cell)
            self._inner.addWidget(gbox)

        # 兜底：容器子列表键缺失/非 list 时补齐（手写 json / 外部直接改
        # _steps_dicts 的形状）。缺键硬下标会抛 KeyError → 槽异常 → qFatal
        # 闪退；根因在 _normalize_loaded_step / P4-B handler 边界修，此处防御。
        if not isinstance(self._d.get("body"), list):
            self._d["body"] = []
        self._inner.addWidget(self._build_child_area("循环内容", self._d["body"]))
        self._inner.addWidget(self._build_delay_row())

    def _build_branch(self):
        # 兜底：condition 非 dict 时重建（根因已在 _normalize_step 修，此处防御旧数据）
        if not isinstance(self._d.get("condition"), dict):
            self._d["condition"] = {"source": "clipboard", "op": "equals", "value": ""}
        self._inner.addWidget(self._build_condition_editor(self._d["condition"], allow_counter=False))
        # 兜底：then/else 子列表键补齐（同 _build_loop，防缺键闪退）
        for k in ("then_steps", "else_steps"):
            if not isinstance(self._d.get(k), list):
                self._d[k] = []
        # then/else 连续编号由 assign_step_ids 统一保证（单一事实源），
        # 这里只建区，不再传 start 自行拼号
        self._inner.addWidget(self._build_child_area(
            "条件成立时执行", self._d["then_steps"]))
        self._inner.addWidget(self._build_child_area(
            "条件不成立时执行", self._d["else_steps"]))
        self._inner.addWidget(self._build_delay_row())

    def _build_condition_editor(self, cond, allow_counter=True):
        cond.setdefault("source", "clipboard")
        cond.setdefault("op", "equals")
        cond.setdefault("value", "")
        cond.setdefault("rule", None)
        # P0-1：分支条件不允许 counter 源（引擎 _run_branch 对 counter 固定传 0，恒为 0 静默失效）
        if not allow_counter and cond.get("source") == "counter":
            cond["source"] = "clipboard"
            try:
                self._tab._set_editor_status(
                    "分支条件不支持「计数器」源（分支内循环索引恒为 0），已回退为「剪贴板内容」", "info")
            except Exception:
                pass
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        src = QComboBox()
        src_labels = _COND_SRC_LABELS if allow_counter else [
            (l, v) for (l, v) in _COND_SRC_LABELS if v != "counter"]
        src.addItems([l for l, _ in src_labels])
        src.setCurrentText(_label(_COND_SRC_LABELS, cond["source"]))
        src.setToolTip(
            "条件从哪种来源取值：\n"
            "· 剪贴板内容 —— 上一步「复制」读到游戏物品信息；选规则（如物品数量）先抽取再比较，不选规则比较原文（如包含\"未鉴定\"）\n"
            "· 上下文变量 —— 「读剪贴板」步骤存下的命名变量（填变量名称）\n"
            "· 前后差异 —— 比较两个上下文变量（如重铸前/后的文本），做\"变了没有\"类判断（填两个变量名）\n"
            "· 稀有度 —— 从剪贴板物品文本解析稀有度（normal/magic/rare/unique），值填稀有度英文\n"
            "· 词缀裁决 —— 黑白名单评估结论（字段默认 final_decision，值如 accept/reroll）\n"
            "· 会话状态 —— 会话限速检查结果（字段默认 ok，值如 True/False）\n"
            "· 配置开关 —— 读配置 [段名] 键的字符串值比较（填段名+键名，如 Strategy + enable_corruption）\n"
            "· 计数器 —— 当前循环第几轮（从 0 开始），做\"前 N 轮走 A、之后走 B\"")
        op = QComboBox()
        op.setObjectName("CondOpCombo")
        op.addItems([l for l, _ in _COND_OP_LABELS])
        op.setCurrentText(_label(_COND_OP_LABELS, cond["op"]))
        val = QLineEdit(str(cond["value"]))
        val.setObjectName("CondValueEdit")
        val.setPlaceholderText("比较值")
        # 数值比较阈值下拉（2026-10-22 用户定案）：T 阶=阶级 1~16 专属列表（不可手打），
        # 百分比门槛（物品数量/稀有度数量/品质/怪群规模）= 常用值列表（可手打改）；
        # 布尔/文本比较仍走纯文本输入；ctx_diff 不用比较值。
        val_cb = QComboBox()
        val_cb.setObjectName("CondValueCombo")
        key_f = QLineEdit(cond.get("key", ""))
        key_f.setPlaceholderText("变量名称（如 count）")
        # ctx_diff 专用：比较两个上下文变量（引擎读 key_a/key_b，不用 value）
        key_a_f = QLineEdit(cond.get("key_a", ""))
        key_a_f.setPlaceholderText("变量 A（如 before）")
        key_b_f = QLineEdit(cond.get("key_b", ""))
        key_b_f.setPlaceholderText("变量 B（如 after）")
        # config 源专用：读配置的 段名/键名（引擎取 [section] key 的字符串值比较）
        sec_f = QLineEdit(cond.get("section", ""))
        sec_f.setObjectName("CondSectionEdit")
        sec_f.setPlaceholderText("段名（如 Strategy）")
        cfg_key_f = QLineEdit(cond.get("key", ""))
        cfg_key_f.setObjectName("CondConfigKeyEdit")
        cfg_key_f.setPlaceholderText("键名（如 enable_corruption）")

        def _sync_value_widget():
            """按 源/比较符/规则 切换「比较值」控件：数值阈值走下拉，其余走文本框。"""
            numeric = cond.get("op") in ("gt", "lt", "ge", "le")
            group = (threshold_group(cond.get("rule"))
                     if cond.get("source") == "clipboard" else None)
            use_cb = numeric and group is not None
            if use_cb:
                # 先取原值：clear/addItems 会触发 currentTextChanged 把
                # cond["value"] 冲成首项，事后再按原值恢复/收敛
                v = str(cond.get("value", ""))
                items = [str(t) for t in THRESHOLD_PRESETS[group]]
                if [val_cb.itemText(i) for i in range(val_cb.count())] != items:
                    val_cb.clear()
                    val_cb.addItems(items)
                # 阶级域只限 1~16：下拉不可手打；存量越界值（手改 json 带进来的）
                # 就近收敛并写回，避免显示与实际判定不一致
                val_cb.setEditable(group != "tier")
                if group == "tier":
                    try:
                        n = min(max(int(float(v)), 1), 16)
                    except (TypeError, ValueError):
                        n = 15
                    if v != str(n):
                        cond["value"] = str(n)
                    v = str(n)
                if val_cb.currentText() != v:
                    val_cb.setCurrentText(v)
            val_cb.setVisible(use_cb and cond.get("source") != "ctx_diff")
            val.setVisible(not use_cb and cond.get("source") != "ctx_diff")

        # 批3 ⑦ + ①E：source=clipboard 时可选 rule（预设 或 自定义）复用，抽取后再比较
        def _on_rule(rule, default_op):
            cond["rule"] = rule
            # 预设带 default_op 时跟随设为默认 op（如 物品数量->ge）
            if default_op:
                op.setCurrentText(_label(_COND_OP_LABELS, default_op))
            _sync_value_widget()

        rule_w = _build_rule_editor(cond.get("rule"), _on_rule)

        def _src(t):
            s = _value(_COND_SRC_LABELS, t)
            cond["source"] = s
            # ctx 用 key；affix/session 用 key 取评估字段；ctx_diff 用 key_a/key_b；
            # config 用 section+key 读配置——均不比较 value（ctx_diff/config 除外，
            # config 仍比较 value：配置项的值，如 enable_corruption 比 "true"）
            key_f.setVisible(s in ("ctx", "affix", "session"))
            key_f.setPlaceholderText({
                "ctx": "变量名称（如 count）",
                "affix": "裁决字段（如 final_decision）",
                "session": "状态字段（如 ok）",
            }.get(s, "字段名称"))
            key_a_f.setVisible(s == "ctx_diff")
            key_b_f.setVisible(s == "ctx_diff")
            sec_f.setVisible(s == "config")
            cfg_key_f.setVisible(s == "config")
            rule_w.setVisible(s == "clipboard")
            _sync_value_widget()

        def _on_op(t):
            cond["op"] = _value(_COND_OP_LABELS, t)
            _sync_value_widget()

        src.currentTextChanged.connect(_src)
        op.currentTextChanged.connect(_on_op)
        val.textChanged.connect(lambda t: cond.__setitem__("value", t))
        val_cb.currentTextChanged.connect(lambda t: cond.__setitem__("value", t))
        key_f.textChanged.connect(lambda t: cond.__setitem__("key", t))
        key_a_f.textChanged.connect(lambda t: cond.__setitem__("key_a", t))
        key_b_f.textChanged.connect(lambda t: cond.__setitem__("key_b", t))
        sec_f.textChanged.connect(lambda t: cond.__setitem__("section", t))
        cfg_key_f.textChanged.connect(lambda t: cond.__setitem__("key", t))
        h.addWidget(QLabel("源"))
        h.addWidget(src)
        h.addWidget(QLabel("比较"))
        h.addWidget(op)
        h.addWidget(QLabel("值"))
        h.addWidget(val)
        h.addWidget(val_cb)
        h.addWidget(key_f)
        h.addWidget(key_a_f)
        h.addWidget(key_b_f)
        h.addWidget(sec_f)
        h.addWidget(cfg_key_f)
        h.addWidget(rule_w)
        _sync_value_widget()
        # 初始显隐：connect 之前的 addItems/setCurrentText 信号已丢失，
        # 不补这一刀，加载即带的源（含 config）字段框显隐不对（顺带修旧 latent bug）
        _src(src.currentText())
        return w

    def _build_child_area(self, title, child_list):
        box = QGroupBox(title)
        # 子区虚线边框走主题 QSS（objectName=StepCardChildArea，edge 色），不内联
        box.setObjectName("StepCardChildArea")
        v = QVBoxLayout(box)
        v.setSpacing(4)
        for d in child_list:
            # 分支两区连续编号由 assign_step_ids 统一保证（then 从 1、else
            # 接 then 之后）——旧实现在这里自行拼 child_path，与画布侧
            # _assign_ids 各算一份，规则漂移时标题会与实际 id 不一致；
            # 现在 id 单一事实源，直接取已分配好的 id。
            v.addWidget(StepCard(d, child_list, self._tab, d.get("id") or ""))
        btn = QPushButton("+ 加子步骤")
        btn.clicked.connect(lambda: self._tab._add_child(child_list))
        v.addWidget(btn)
        return box

    def _build_error_policy(self):
        err = QComboBox()
        err.addItems([l for l, _ in _ERR_LABELS])
        err.setCurrentText(_label(_ERR_LABELS, self._d.get("on_error", "retry")))

        def _err_changed(t):
            def _do():
                self._d["on_error"] = _value(_ERR_LABELS, t)
                if self._d["on_error"] == "retry":
                    self._d.setdefault("retry_count", 1)
                    self._d.setdefault("retry_delay_ms", 500)
                elif self._d["on_error"] == "jump":
                    self._d.setdefault("jump_target", "")
                self._build_inner()
            self._safe("切换错误策略", _do)

        err.currentTextChanged.connect(_err_changed)
        self._inner.addWidget(_labeled("错误策略", err))
        if self._d.get("on_error") == "retry":
            rc = QSpinBox()
            rc.setRange(1, 100)
            rc.setValue(int(self._d.get("retry_count", 1)))
            rc.valueChanged.connect(lambda v: self._d.__setitem__("retry_count", v))
            rd = QSpinBox()
            rd.setRange(0, 60000)
            rd.setSuffix(" ms")
            rd.setValue(int(self._d.get("retry_delay_ms", 500)))
            rd.valueChanged.connect(lambda v: self._d.__setitem__("retry_delay_ms", v))
            self._inner.addWidget(_labeled("重试次数", rc))
            self._inner.addWidget(_labeled("重试间隔", rd))
        if self._d.get("on_error") == "jump":
            self._inner.addWidget(self._build_jump_target_editor())

    def _collect_step_ids(self, steps=None):
        if steps is None:
            steps = getattr(self._tab, "_steps_dicts", []) or []
        out = []
        def _walk(lst):
            for d in lst:
                if isinstance(d, dict):
                    sid = d.get("id")
                    if sid:
                        out.append(sid)
                    for k in ("body", "then_steps", "else_steps"):
                        if isinstance(d.get(k), list):
                            _walk(d[k])
        _walk(steps)
        return out

    def _build_jump_target_editor(self):
        jt = QComboBox()
        jt.setEditable(True)
        jt.setMinimumWidth(240)
        jt.setToolTip("跳转目标：本方案内的步骤编号，或 workflows/ 下的模块方案名（不含 .json）")
        step_ids = self._collect_step_ids()
        for sid in step_ids:
            jt.addItem(f"步骤: {sid}", sid)
        schemes = self._tab._scan_schemes() if hasattr(self._tab, "_scan_schemes") else []
        for fn in schemes:
            stem = fn[:-5] if fn.lower().endswith(".json") else fn
            jt.addItem(f"模块: {stem}", stem)
        cur = self._d.get("jump_target", "")
        if cur:
            idx = jt.findData(cur)
            if idx < 0:
                jt.insertItem(0, cur, cur)
                idx = 0
            jt.setCurrentIndex(idx)

        def _on_jt(t):
            idx = jt.findText(t)
            data = jt.itemData(idx) if idx >= 0 else None
            self._d["jump_target"] = data if data else t

        jt.currentTextChanged.connect(_on_jt)
        return _labeled("跳转目标", jt)


def _labeled(text, widget):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(QLabel(text))
    h.addWidget(widget)
    return w


# ①E 自定义规则：下拉除预设外提供「自定义…」，展开 正则 / 类型 / 捕获组 三个输入。
# 模型侧 resolve_rule 早已支持 dict{pattern, kind, capture_group}，此前只是 UI 未暴露。
_CUSTOM_RULE_LABEL = "自定义…"
_RULE_KIND_LABELS = [("布尔", "bool"), ("数值", "number"), ("文本", "text")]


def _rule_combo_text(rule):
    """rule（预设键 str / 自定义 dict）-> 下拉显示文本。"""
    if isinstance(rule, dict):
        return _CUSTOM_RULE_LABEL
    if isinstance(rule, str) and rule in RULE_PRESETS:
        return RULE_PRESETS[rule]["label"]
    return RULE_PRESETS["item_quantity"]["label"]


def _build_rule_editor(current, on_change):
    """规则选择控件（预设 + 自定义 + 词缀库多选）。

    on_change(rule, default_op)：
      rule       = 预设键(str) 或 自定义 dict{pattern, kind, capture_group}
      default_op = 预设自带的默认比较符（如 物品数量->ge），自定义传 None
    返回容器 QWidget；调用方负责 setVisible 控制显隐。
    自定义区含「词缀库」多选：点选多条组成或匹配（布尔），与手写正则等价。
    """
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    rule_keys = list(RULE_PRESETS.keys())
    cb = QComboBox()
    cb.addItems([RULE_PRESETS[k]["label"] for k in rule_keys] + [_CUSTOM_RULE_LABEL])

    custom = QWidget()
    cv = QVBoxLayout(custom)
    cv.setContentsMargins(0, 0, 0, 0)
    cv.setSpacing(2)
    ch = QHBoxLayout()
    ch.setContentsMargins(0, 0, 0, 0)
    pat_le = QLineEdit()
    pat_le.setPlaceholderText("正则表达式，数值/文本类默认取捕获组 1")
    pat_le.setToolTip(r"自定义正则；如 物品数量:\s*\+(\d+)%")
    kind_cb = QComboBox()
    kind_cb.addItems([l for l, _ in _RULE_KIND_LABELS])
    cg_sb = QSpinBox()
    cg_sb.setRange(1, 9)
    cg_sb.setPrefix("组")
    if isinstance(current, dict):
        pat_le.setText(str(current.get("pattern", "")))
        kind_cb.setCurrentText(_label(_RULE_KIND_LABELS, current.get("kind", "text")))
        try:
            cg_sb.setValue(int(current.get("capture_group", 1)))
        except Exception:
            cg_sb.setValue(1)
    ch.addWidget(QLabel("正则"))
    ch.addWidget(pat_le, stretch=1)
    ch.addWidget(kind_cb)
    ch.addWidget(cg_sb)
    cv.addLayout(ch)
    # 词缀/特征库（2026-10-22 用户定案）：常用词缀与影响效果同库多选，
    # 点选多条自动组成「或」匹配（任一命中即真），免得手写正则。
    lib_lw = QListWidget()
    lib_lw.setObjectName("FeatureLibraryList")
    lib_lw.setMaximumHeight(120)
    lib_lw.setToolTip("点选多条组成「或」匹配：任一命中即真。\n"
                      "词缀类=纯文本子串；影响效果类=预设同源正则。")
    cur_pat = str(current.get("pattern", "")) if isinstance(current, dict) else ""
    for entry in FEATURE_LIBRARY:
        it = QListWidgetItem(entry["label"])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if entry["pattern"] in cur_pat else Qt.Unchecked)
        it.setData(Qt.UserRole, entry["pattern"])
        lib_lw.addItem(it)
    cv.addWidget(_labeled("词缀库", lib_lw))
    last_lib_pattern = [""]

    def _on_lib_changed(_item=None):
        pats = [lib_lw.item(i).data(Qt.UserRole)
                for i in range(lib_lw.count())
                if lib_lw.item(i).checkState() == Qt.Checked]
        if pats:
            joined = build_or_pattern(pats)
            last_lib_pattern[0] = joined
            kind_cb.setCurrentText("布尔")   # 触发 kind 信号 -> _emit
            pat_le.setText(joined)           # 触发 text 信号 -> _emit
        elif last_lib_pattern[0] and pat_le.text().strip() == last_lib_pattern[0]:
            pat_le.clear()                   # 仅清掉库生成的 pattern，不动手写的

    lib_lw.itemChanged.connect(_on_lib_changed)
    cb.setCurrentText(_rule_combo_text(current))

    def _emit():
        if cb.currentText() == _CUSTOM_RULE_LABEL:
            on_change({
                "pattern": pat_le.text().strip(),
                "kind": _value(_RULE_KIND_LABELS, kind_cb.currentText()),
                "capture_group": int(cg_sb.value()),
            }, None)
        else:
            idx = cb.findText(cb.currentText())
            key = rule_keys[idx] if 0 <= idx < len(rule_keys) else "item_quantity"
            on_change(key, RULE_PRESETS[key].get("default_op"))

    def _on_cb(_t=None):
        custom.setVisible(cb.currentText() == _CUSTOM_RULE_LABEL)
        _emit()

    cb.currentTextChanged.connect(_on_cb)
    pat_le.textChanged.connect(lambda _t: _emit())
    kind_cb.currentTextChanged.connect(lambda _t: _emit())
    cg_sb.valueChanged.connect(lambda _v: _emit())

    v.addWidget(cb)
    v.addWidget(custom)
    custom.setVisible(cb.currentText() == _CUSTOM_RULE_LABEL)
    return w


class WorkflowEditorPanel(QWidget):
    """步骤编辑器面板（右侧抽屉内容）。

    V3030-drawer：不再是主 UI 之外的独立浮动窗口，而是注入主窗口右侧抽屉容器的
    普通 QWidget。抽屉的展开/收起由 MainWindow.set_right_drawer_visible 控制，
    永远位于主界面最右侧、绝不遮挡任何内容。
    本类只负责编辑器内部布局：标题 + 收起按钮、加一步、卡片列表、保存/校验/预览、状态行。
    """

    def __init__(self, tab):
        super().__init__(tab)
        self._tab = tab
        self.setMinimumWidth(240)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # ── 标题行（收起时仍保留，用于展开）──
        hdr = QHBoxLayout()
        self._title = QLabel("步骤编辑器")
        self._title.setObjectName("StepCardTitle")   # 加粗样式走主题 QSS
        self._btn_collapse = QPushButton("«")
        self._btn_collapse.setMaximumWidth(28)
        self._btn_collapse.setToolTip("收起抽屉（也可取消勾选页签上的「编辑器」）")
        self._btn_collapse.clicked.connect(self._on_collapse)
        hdr.addWidget(self._title, stretch=1)
        hdr.addWidget(self._btn_collapse)
        root.addLayout(hdr)

        # ── 内容区（收起时隐藏）：步骤卡片列表 + 保存校验 ──
        # 注：模块库面板（ModulePalette）已上移到 WorkflowDialog 左侧常驻栏
        # （用户 2026-10-18 定案：工作流相关功能剥离为独立弹窗），此处不再重复一份。
        self._content = QWidget()
        cv = QVBoxLayout(self._content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(6)

        add_row = QHBoxLayout()
        btn_add = QPushButton("+ 加一步")
        btn_add.clicked.connect(self._tab._add_top_step)
        add_row.addWidget(btn_add)
        add_row.addStretch(1)
        cv.addLayout(add_row)

        self.cards_scroll = QScrollArea()
        self.cards_scroll.setWidgetResizable(True)
        self.cards_widget = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setContentsMargins(4, 4, 4, 4)
        self.cards_layout.setSpacing(6)
        self.cards_scroll.setWidget(self.cards_widget)
        cv.addWidget(self.cards_scroll, stretch=1)

        # ── 保存 / 校验 / 预览 ──
        save_row = QHBoxLayout()
        btn_save = QPushButton("保存")
        btn_saveas = QPushButton("另存为")
        btn_validate = QPushButton("校验")
        btn_preview = QPushButton("预览")
        btn_save.clicked.connect(self._tab._on_save)
        btn_saveas.clicked.connect(self._tab._on_save_as)
        btn_validate.clicked.connect(self._tab._on_validate)
        btn_preview.clicked.connect(self._tab._on_preview)
        save_row.addWidget(btn_save)
        save_row.addWidget(btn_saveas)
        save_row.addWidget(btn_validate)
        save_row.addWidget(btn_preview)
        cv.addLayout(save_row)

        # 编辑状态行（校验/保存/另存/预览）——配色走主题 QSS：
        # objectName=CanvasStatus，level 属性区分 ok/error/info，不硬编码
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("CanvasStatus")
        self.status_label.setWordWrap(True)
        cv.addWidget(self.status_label)

        root.addWidget(self._content, stretch=1)

    # ------------------------------------------------------------------ #
    def set_status(self, msg, level="info"):
        """状态行：颜色走主题（CanvasStatus 的 level 属性），不硬编码。"""
        self.status_label.setText(msg)
        self.status_label.setProperty("level", level)
        # level 变化后需重跑 QSS：重设属性会触发 unpolish
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    # ------------------------------------------------------------------ #
    def _on_collapse(self):
        """收起抽屉：隐藏主窗口右侧抽屉，并取消页签「编辑器」勾选。"""
        try:
            mw = self._tab.window()
            if hasattr(mw, "set_right_drawer_visible"):
                mw.set_right_drawer_visible(False)
            if hasattr(self._tab, "_btn_editor"):
                self._tab._btn_editor.setChecked(False)
        except Exception:
            pass


class WorkflowTab(QWidget):
    def __init__(self, config_manager, input_simulator=None,
                 coord_engine=None, parser=None):
        super().__init__()
        self._cm = config_manager
        self._input = input_simulator
        self._coord = coord_engine
        self._parser = parser
        self._current_path = None          # 当前编辑器对应的磁盘文件
        self._engine = None                # 运行中的引擎实例
        self._bridge = _EngineBridge()
        # 工作流真源：步骤 dict 列表 + 名称/版本
        self._steps_dicts = []
        # 画布数据适配层（GUI 升级 阶段1）：持有同一根列表引用，作为单一事实源
        self._canvas_model = CanvasModel(self._steps_dicts)
        self._canvas_tab = None      # 「工作流画布」页签（阶段2 双向联动，可为 None）
        self._wf_name = "新方案"
        self._wf_version = 1
        self._editor_panel = None         # 右侧抽屉内的编辑器面板（_build 中创建）
        self._dirty = False               # 未保存保护：当前编辑器内容相对磁盘是否有改动
        # 卡片列表结构签名（_rebuild_cards 全量重建后记录）：聚焦点击快速路径
        # 用它判断「结构没变就不要全量重建」，见 _rebuild_cards。
        self._cards_signature = None
        self._card_index = {}      # {id(step dict): 卡片}，随全量重建重建
        self._build()

    def showEvent(self, event):
        """切到本页签时：把编辑器面板注入主窗口右侧抽屉，并按「编辑器」勾选态展开/收起。"""
        super().showEvent(event)
        mw = self.window()
        if hasattr(mw, "set_right_drawer_widget") and hasattr(mw, "set_right_drawer_visible"):
            mw.set_right_drawer_widget(self._editor_panel)
            mw.set_right_drawer_visible(self._btn_editor.isChecked())

    def _on_editor_toggled(self, checked):
        """「编辑器」按钮勾选态变化 → 展开/收起主窗口右侧抽屉。"""
        mw = self.window()
        if hasattr(mw, "set_right_drawer_visible"):
            mw.set_right_drawer_visible(checked)

    # ------------------------------------------------------------------ #
    def _build(self):
        # 编辑器改为注入主窗口右侧抽屉（WorkflowEditorPanel，由 MainWindow 的
        # 右侧抽屉容器承载）：拉开时主内容区自动收窄，绝不遮挡内容。
        # 页签内只保留运行控制（运行/停止/编辑器开关/运行状态）。
        # 状态分工：编辑类状态 → 抽屉内编辑器状态行；方案级 → 应用主日志（logger.info）。
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QLabel("工作流编排：把一串操作（移动至锚点 / 相对移动 / 按键 / 读剪贴板 / 复制）"
                        "编排成可重复执行的方案，支持循环（含网格步进）与条件分支，绑定快捷键一键运行。")
        header.setWordWrap(True)
        # 说明文字色走主题 QSS（objectName=PaletteHint），不硬编码
        header.setObjectName("PaletteHint")
        layout.addWidget(header)

        # ── 方案文件选择 ──
        file_group = QGroupBox("方案文件")
        file_row = QHBoxLayout(file_group)
        self._combo = QComboBox()
        self._combo.setMinimumWidth(240)
        self._combo.currentTextChanged.connect(self._on_combo_changed)
        file_row.addWidget(self._combo, stretch=1)
        btn_refresh = QPushButton("刷新")
        btn_new = QPushButton("新建")
        btn_del = QPushButton("删除")
        btn_refresh.clicked.connect(self._refresh_schemes)
        btn_new.clicked.connect(self._on_new)
        btn_del.clicked.connect(self._on_delete)
        file_row.addWidget(btn_refresh)
        file_row.addWidget(btn_new)
        file_row.addWidget(btn_del)
        layout.addWidget(file_group)

        # ── 快捷键绑定（待办1：持久化）──
        hk_group = QGroupBox("运行快捷键（持久化到配置文件）")
        hk_row = QHBoxLayout(hk_group)
        self._ks_edit = QKeySequenceEdit()
        btn_set_hk = QPushButton("设为运行快捷键")
        btn_clr_hk = QPushButton("清除")
        btn_set_hk.clicked.connect(self._on_set_hotkey)
        btn_clr_hk.clicked.connect(self._on_clear_hotkey)
        hk_row.addWidget(QLabel("按键:"))
        hk_row.addWidget(self._ks_edit, stretch=1)
        hk_row.addWidget(btn_set_hk)
        hk_row.addWidget(btn_clr_hk)
        self._hk_label = QLabel("（未绑定）")
        # 说明文字色走主题 QSS（objectName=PaletteHint），不硬编码
        self._hk_label.setObjectName("PaletteHint")
        hk_row.addWidget(self._hk_label)
        layout.addWidget(hk_group)

        # 应用级快捷键（持久化后重启仍有效）
        self._shortcut = QShortcut(QKeySequence(), self)
        self._shortcut.setContext(Qt.ApplicationShortcut)
        self._shortcut.activated.connect(self._on_hotkey)

        # ── 运行控制 + 编辑器开关 + 运行状态 ──
        run_row = QHBoxLayout()
        self._btn_run = QPushButton("运行")
        self._btn_stop = QPushButton("停止")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setEnabled(False)
        run_row.addWidget(self._btn_run)
        run_row.addWidget(self._btn_stop)
        self._btn_editor = QPushButton("编辑器")
        self._btn_editor.setCheckable(True)
        self._btn_editor.setChecked(True)
        self._btn_editor.setToolTip("显示/隐藏右侧步骤编辑器抽屉")
        run_row.addWidget(self._btn_editor)
        run_row.addStretch(1)
        # 运行状态标签：配色走主题（objectName=CanvasStatus + level 属性），
        # 不硬编码（红→error、橙→info，见 _set_run_status）
        self._status_label = QLabel("空闲")
        self._status_label.setObjectName("CanvasStatus")
        self._status_label.setProperty("level", "info")
        run_row.addWidget(self._status_label, stretch=1)
        layout.addLayout(run_row)
        layout.addStretch(1)

        # ── 编辑器：注入主窗口右侧抽屉（见 WorkflowEditorPanel）──
        self._editor_panel = WorkflowEditorPanel(self)
        self._cards_scroll = self._editor_panel.cards_scroll
        self._cards_widget = self._editor_panel.cards_widget
        self._cards_layout = self._editor_panel.cards_layout
        self._btn_editor.toggled.connect(self._on_editor_toggled)

        # 信号桥 -> UI 槽
        self._bridge.status.connect(self._on_engine_status)
        self._bridge.finished.connect(self._on_engine_finished)
        self._bridge.error.connect(self._on_engine_error)

        # 待办1：启动后恢复已持久化的快捷键
        self._restore_hotkey()

        self._refresh_schemes()
        self._rebuild_cards()

    # ------------------------------------------------------------------ #
    #  方案文件管理
    # ------------------------------------------------------------------ #
    def _scan_schemes(self):
        items = []
        if os.path.isdir(_WORKFLOWS_DIR):
            for fn in sorted(os.listdir(_WORKFLOWS_DIR)):
                if fn.lower().endswith(".json"):
                    items.append(fn)
        return items

    def _refresh_schemes(self):
        schemes = self._scan_schemes()
        prev = self._combo.currentText()
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItems(schemes)
        if prev and prev in schemes:
            self._combo.setCurrentText(prev)
        self._combo.blockSignals(False)
        if schemes and not self._current_path:
            self._load_file(schemes[0])

    def _on_combo_changed(self, name):
        if not name:
            return
        # C1 未保存保护：切换方案前先确认（保存/丢弃/取消）；取消则回退下拉
        if not self._confirm_discard():
            if self._current_path:
                self._combo.blockSignals(True)
                self._combo.setCurrentText(os.path.basename(self._current_path))
                self._combo.blockSignals(False)
            return
        self._load_file(name)

    def _mark_scheme_bad(self, name):
        """下拉项标红：提示该方案文件无法加载（坏 json / 非法结构）。"""
        idx = self._combo.findText(name)
        if idx >= 0:
            # 阻塞信号：setItemData 作用于「当前项」时会由 Qt 重发 currentTextChanged，
            # 否则会递归触发 _on_combo_changed → _load_file → … 死循环。
            self._combo.blockSignals(True)
            # 标红走主题错误色（error_text），不写死 Qt.red
            self._combo.setItemData(idx, QColor(_canvas_color(self, "error_text")), Qt.ForegroundRole)
            self._combo.blockSignals(False)

    def _mark_scheme_ok(self, name):
        """清除下拉项标红。"""
        idx = self._combo.findText(name)
        if idx >= 0:
            self._combo.blockSignals(True)
            self._combo.setItemData(idx, None, Qt.ForegroundRole)
            self._combo.blockSignals(False)

    # ------------------------------------------------------------------ #
    #  C1 未保存保护：dirty 标记 + 保存/丢弃/取消确认
    # ------------------------------------------------------------------ #
    def _mark_dirty(self):
        """标记当前编辑器内容相对磁盘已改动（任何结构或字段编辑后调用）。"""
        if not self._dirty:
            self._dirty = True
            self._update_dirty_status()

    def _clear_dirty(self):
        """标记当前内容与磁盘一致（载入/保存成功后调用）。"""
        if self._dirty:
            self._dirty = False
            self._update_dirty_status()

    def _update_dirty_status(self):
        """在编辑器状态行反映未保存态（仅提示，不阻塞）。"""
        if self._dirty:
            self._set_editor_status("● 有未保存的修改（关闭/新建/切换前请先保存）", "error")
        else:
            self._set_editor_status("就绪")

    def _confirm_discard(self):
        """未保存保护：若有改动，弹「保存 / 丢弃 / 取消」。

        返回 True 表示可继续（已保存或已丢弃）；False 表示用户取消（中止当前操作）。
        """
        if not self._dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("未保存的修改")
        name = os.path.basename(self._current_path) if self._current_path else "未命名方案"
        box.setText(f"方案「{name}」有未保存的修改，是否保存后再继续？")
        btn_save = box.addButton("保存", QMessageBox.AcceptRole)
        btn_discard = box.addButton("丢弃修改", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == btn_save:
            self._on_save()
            # 保存对话框被取消时仍 dirty → 视为中止
            return not self._dirty
        elif clicked == btn_discard:
            self._clear_dirty()
            return True
        return False

    def _load_file(self, name):
        path = os.path.join(_WORKFLOWS_DIR, name)
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # B2：复用模型层 schema 校验契约（坏 json / 非法结构统一抛 WorkflowLoadError，
            # 属 ValueError 子类），由下方统一捕获并给出一致、非崩溃的提示。
            workflow_from_dict(data)
            self._wf_name = data.get("name", "新方案")
            self._wf_version = data.get("version", 1)
            self._steps_dicts = data.get("steps", []) or []
            # A1 自愈：清洗存量文件里误写入 params 的 delay_ms（提回顶层）
            migrate_delay_ms(self._steps_dicts)
            for s in self._steps_dicts:
                _normalize_loaded_step(s)
            self._canvas_model.set_root(self._steps_dicts)
            self._current_path = path
            self._rebuild_cards()
            self._mark_scheme_ok(name)
            self._clear_dirty()            # 载入即与磁盘一致
            self._log(f"[文件] 已载入: {name}")
        except (ValueError, OSError) as e:
            # 模型层/解析层异常：坏 json 或 schema 非法——不残留半载状态（上方未改动任何成员变量）、不静默、不崩溃
            self._mark_scheme_bad(name)
            msg = f"方案加载失败（{name}）：{e}"
            self._log(f"[错误] {msg}")
            self._set_editor_status(msg, "error")
        except Exception as e:
            # 其他意外（自愈/规整/渲染）：同样不残留半载、记录但不崩溃
            self._mark_scheme_bad(name)
            msg = f"方案加载出错（{name}）：{e}"
            self._log(f"[错误] {msg}")
            self._set_editor_status(msg, "error")

    def _on_new(self):
        # C1 未保存保护：新建前先确认
        if not self._confirm_discard():
            return
        self._current_path = None
        self._wf_name = "新方案"
        self._wf_version = 1
        self._steps_dicts = [_new_step_dict(self)]
        self._canvas_model.set_root(self._steps_dicts)
        self._rebuild_cards()
        self._mark_dirty()                # 新方案尚未落盘
        self._log("[文件] 新建空白方案（含一个默认步骤，未保存）")

    def _on_delete(self):
        if not self._current_path:
            QMessageBox.information(self, "提示", "当前方案尚未保存到磁盘，无法删除。")
            return
        name = os.path.basename(self._current_path)
        ok = QMessageBox.question(
            self, "确认删除", f"确定删除方案文件 {name}？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ok != QMessageBox.Yes:
            return
        try:
            os.remove(self._current_path)
            self._log(f"[文件] 已删除: {name}")
            self._current_path = None
            self._clear_dirty()           # 文件已删，无未保存态
            self._refresh_schemes()
        except Exception as e:
            self._log(f"[错误] 删除失败: {e}")

    # ------------------------------------------------------------------ #
    #  卡片列表管理（待办2-①）
    # ------------------------------------------------------------------ #
    def _rebuild_cards(self, focus_dict=None):
        # 聚焦点击快速路径（性能，实测 N=100 全量重建约 430ms / N=200 约 1s，
        # 其中 95% 是列表侧全量建卡）：结构签名未变时（对象身份 + id + kind
        # 逐一相同，见 _tree_signature）说明这次调用只是「点画布节点聚焦」，
        # 卡片内容都是活的，直接定位既有卡片滚动聚焦即可，不重建。
        # 结构任何变化（增/删/移/改类型/换方案）都会改签名 → 仍走全量重建。
        sig = self._tree_signature()
        if focus_dict is not None and sig == self._cards_signature:
            card = self._card_index.get(id(focus_dict))
            if card is not None:
                self._cards_scroll.ensureWidgetVisible(card)
                card.setFocus()
                return
        # id 单一事实源：先由 modules/workflow_model.assign_step_ids 按层级
        # 位置统一重编号（与画布侧同一函数），并同步改写 jump_target，再建卡。
        # 顺序很关键——旧实现「先建卡（StepCard 构造即改 id）→ 后 remap」
        # 会让已构建的 jump_target 编辑器显示旧值，要等下次重建才刷新。
        remap_jump_targets(
            self._steps_dicts, assign_step_ids(self._steps_dicts))
        _clear_layout(self._cards_layout)
        focus_card = None
        for i, d in enumerate(self._steps_dicts):
            # index_path 直接取刚分配好的 id（构造器内幂等写回），不再自行拼算
            card = StepCard(d, self._steps_dicts, self, d.get("id") or "")
            self._cards_layout.addWidget(card)
            if focus_dict is not None and d is focus_dict:
                focus_card = card
        self._cards_layout.addStretch(1)
        if focus_card is not None:
            self._cards_scroll.ensureWidgetVisible(focus_card)
            focus_card.setFocus()
        # 结构变化后把新结构推给画布页签（阶段2 联动，保持两视图同源）
        self._notify_canvas_changed()
        # 签名在 assign 之后采集：id 为规范值，与下次进入时的入口签名可比
        # （结构未变时 assign 幂等，入口签名 id 已是规范值）。
        self._cards_signature = self._tree_signature()
        self._reindex_cards()

    def _iter_live_cards(self):
        """遍历当前布局中的存活步骤卡片（顶层 + 嵌套子卡）。

        只走布局，不用 self.findChildren：重建后 deleteLater 的陈旧卡片
        仍是页签子对象（offscreen 下不泵事件不销毁），会被误捞。
        """
        for i in range(self._cards_layout.count()):
            w = self._cards_layout.itemAt(i).widget()
            if not isinstance(w, StepCard):
                continue
            yield w
            yield from w.iter_descendant_cards()

    def _reindex_cards(self):
        """全量重建后建立 {id(step dict): 卡片} 索引（快速路径 O(1) 定位）。

        索引持卡片强引用，随下次全量重建整体替换，有界。
        """
        self._card_index = {id(c._d): c for c in self._iter_live_cards()}

    def _find_live_card(self, target):
        """在当前布局里找 target dict 对应的既有卡片（含嵌套子卡）。

        找不到返回 None（调用方回落全量重建）。
        """
        for c in self._iter_live_cards():
            if c._d is target:
                return c
        return None

    def _tree_signature(self):
        """步骤树结构签名：递归采集 (对象身份, id, kind)。

        对象身份保证「换了方案文件但 id/kind 巧合相同」也判不同（防陈旧
        卡片）；id 序列保证增/删/移被测到；kind 保证改类型被测到。
        纯聚焦点击三者全同 → 走快速路径。采集只读 dict，不碰控件。
        """
        sig = []

        def _walk(lst):
            for d in lst or []:
                if not isinstance(d, dict):
                    sig.append(("raw", id(d)))
                    continue
                sig.append((id(d), d.get("id"), d.get("kind")))
                for k in ("body", "then_steps", "else_steps"):
                    _walk(d.get(k))

        _walk(self._steps_dicts)
        return tuple(sig)

    def _find_live_card(self, target):
        """在当前布局里找 target dict 对应的既有卡片（含嵌套子卡）。

        只遍历布局中的存活卡片；陈旧卡片（deleteLater 待销毁）不在布局
        里，天然被排除。找不到返回 None（调用方回落全量重建）。
        """
        for i in range(self._cards_layout.count()):
            w = self._cards_layout.itemAt(i).widget()
            if not isinstance(w, StepCard):
                continue
            if w._d is target:
                return w
            for c in w.iter_descendant_cards():
                if c._d is target:
                    return c
        return None

    def _notify_canvas_changed(self):
        """通知画布页签重建（列表增删改后调用）。"""
        if self._canvas_tab is None:
            return
        try:
            self._canvas_tab.refresh_from_workflow()
        except Exception as e:
            logger.error(f"同步画布失败: {e}", exc_info=True)

    def _add_top_step(self):
        new = _new_step_dict(self)
        self._steps_dicts.append(new)
        self._rebuild_cards(focus_dict=new)
        self._mark_dirty()

    def _add_child(self, target_list):
        new = _new_step_dict(self)
        target_list.append(new)
        self._rebuild_cards(focus_dict=new)
        self._mark_dirty()

    # ------------------------------------------------------------------ #
    #  GUI 升级 阶段1：模块库面板点击插入
    # ------------------------------------------------------------------ #
    def _on_palette_activated(self, descriptor):
        """模块库条目被点击/激活 → 生成合法步骤并插入（当前：追加到顶层末尾）。

        阶段1 仅做点击插入（拖拽入容器 / 插入到选中步骤之后 属 阶段3 画布能力）。
        子工作流为一等公民（P4-A）：插入 kind=subworkflow 步骤，正常路径内联执行
        模块；模块名存 jump_target（与画布 SubWorkflowNode 预览/编辑器同源）。
        on_error=jump 仍保留作为「出错恢复跳转」的独立机制。
        """
        try:
            t = descriptor.get("type")
            payload = descriptor.get("payload", "")
            if t == "primitive":
                step = _new_step_dict(self)
                step["kind"] = "action"
                step["primitive"] = payload
                step["params"] = _default_params(payload)
                self._canvas_model.insert_step(step, parent_list=self._steps_dicts)
                self._rebuild_cards(focus_dict=step)
                self._mark_dirty()
                self._set_editor_status(
                    f"已插入步骤：{TextResources.get_primitive_label(payload)}", "ok")
            elif t == "subworkflow":
                # P4-A：一等公民——插入 kind=subworkflow（正常路径内联执行模块），
                # 模块名存 jump_target（与画布预览/编辑器同源）。
                step = {
                    "id": "",
                    "kind": "subworkflow",
                    "jump_target": payload,
                    "on_error": "retry",
                    "retry_count": 0,
                    "retry_delay_ms": 0,
                    "delay_ms": 0,
                }
                self._canvas_model.insert_step(step, parent_list=self._steps_dicts)
                self._rebuild_cards(focus_dict=step)
                self._mark_dirty()
                self._set_editor_status(
                    f"已插入子工作流调用：{payload}（正常路径内联执行）", "ok")
            else:
                self._set_editor_status(f"未知模块类型：{t}", "error")
        except Exception as e:
            logger.error(f"模块库插入失败: {e}", exc_info=True)
            self._set_editor_status(f"插入失败：{e}", "error")

    # ------------------------------------------------------------------ #
    #  GUI 升级 阶段2：与「工作流画布」页签的双向选中联动
    # ------------------------------------------------------------------ #
    def attach_canvas_tab(self, canvas_tab) -> None:
        """绑定画布页签（列表→画布高亮）。"""
        self._canvas_tab = canvas_tab

    def focus_step_by_id(self, step_id: str):
        """画布→列表：按层级 id 定位并滚动到对应步骤卡片。"""
        if not step_id:
            return
        target = _find_step_by_id(self._steps_dicts, step_id)
        if target is None:
            return
        self._rebuild_cards(focus_dict=target)

    def _sync_canvas_selection(self, step_id: str):
        """步骤卡片被操作后，把选中态同步到画布。"""
        if self._canvas_tab is not None:
            try:
                self._canvas_tab.select_step(step_id)
            except Exception as e:
                logger.error(f"列表→画布联动失败: {e}", exc_info=True)

    # P1-4：序列化白名单（与 workflow_model._step_from_dict 读取的字段保持一致），
    # 写回时只保留已知字段，避免卡片临时/脏字段污染导出 JSON，保证往返对称。
    _WF_STEP_FIELDS = (
        "id", "kind", "primitive", "params", "next",
        "body", "count", "condition", "then_steps", "else_steps",
        "on_error", "retry_count", "retry_delay_ms", "delay_ms",
        "grid", "jump_target",
    )

    def _step_to_dict(self, d):
        out = {}
        for k in self._WF_STEP_FIELDS:
            if k not in d:
                continue
            v = d[k]
            if k in ("body", "then_steps", "else_steps"):
                out[k] = [self._step_to_dict(x) for x in v] if isinstance(v, list) else v
            else:
                out[k] = v
        return out

    def _to_workflow_dict(self):
        return {
            "name": self._wf_name,
            "version": self._wf_version,
            "steps": [self._step_to_dict(d) for d in self._steps_dicts],
        }

    def _validate_model(self):
        """把卡片 dict 构建成 WorkflowDef 并校验，返回错误列表（空=通过）。"""
        try:
            wf = workflow_from_dict(self._to_workflow_dict())
            return validate_workflow(wf)
        except Exception as e:
            return [f"模型构建失败: {e}"]

    # ------------------------------------------------------------------ #
    #  快捷键（待办1：持久化）
    # ------------------------------------------------------------------ #
    def _on_set_hotkey(self):
        seq = self._ks_edit.keySequence()
        if seq.isEmpty():
            self._log("[快捷键] 请先按下要绑定的组合键")
            return
        self._shortcut.setKey(seq)
        self._hk_label.setText(f"已绑定: {seq.toString()}")
        self._persist_hotkey(seq.toString())
        self._log(f"[快捷键] 已绑定并持久化: {seq.toString()}")

    def _on_clear_hotkey(self):
        self._shortcut.setKey(QKeySequence())
        self._ks_edit.setKeySequence(QKeySequence())
        self._hk_label.setText("（未绑定）")
        self._persist_hotkey("")
        self._log("[快捷键] 已清除（配置已同步）")

    def _persist_hotkey(self, value: str):
        """待办1：把运行快捷键写回 poe_config.txt[Workflow]run_hotkey（空串=清除）。

        显式 flush() 保证落盘：ConfigManager.set 有 100ms 节流，紧接着的写入只标
        pending 不立即写盘；若不 flush，用户设完快捷键立刻退出可能丢失本次写入。
        """
        if self._cm is None:
            return
        try:
            self._cm.set("Workflow", "run_hotkey", value)
            self._cm.flush()
        except Exception as e:
            self._log(f"[快捷键] 持久化失败: {e}")

    def _restore_hotkey(self):
        """待办1：启动时从配置恢复已保存的快捷键。"""
        if self._cm is None:
            return
        try:
            saved = self._cm.get("Workflow", "run_hotkey", "")
        except Exception:
            return
        if not saved:
            return
        seq = QKeySequence(saved)
        if seq.isEmpty():
            return
        self._shortcut.setKey(seq)
        self._ks_edit.setKeySequence(seq)
        self._hk_label.setText(f"已绑定: {seq.toString()}")
        self._log(f"[快捷键] 已从配置恢复: {seq.toString()}")

    def _on_hotkey(self):
        if self._engine is not None and self._engine.is_running():
            self._log("[快捷键] 已有方案运行中，忽略本次触发")
            return
        self._log("[快捷键] 触发运行")
        self._on_run()

    # ------------------------------------------------------------------ #
    #  校验 / 保存 / 预览 / 运行 / 停止
    # ------------------------------------------------------------------ #
    def _on_validate(self):
        errs = self._validate_model()
        if errs:
            shown = "; ".join(errs[:3]) + ("…" if len(errs) > 3 else "")
            self._set_editor_status("校验未通过: " + shown, "error")
        else:
            self._set_editor_status("校验通过 ✓", "ok")

    def _on_preview(self):
        try:
            text = json.dumps(self._to_workflow_dict(), ensure_ascii=False, indent=2)
        except Exception as e:
            self._set_editor_status(f"预览失败: {e}", "error")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("预览 JSON")
        v = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setFontFamily("Consolas")
        # 预览框配色交给主题 QSS（QTextEdit 全局规则），不硬编码深色
        te.setPlainText(text)
        v.addWidget(te)
        btn = QPushButton("关闭")
        btn.clicked.connect(dlg.accept)
        v.addWidget(btn)
        dlg.resize(560, 520)
        dlg.exec_()
        self._set_editor_status("JSON 已预览")

    def _on_save(self):
        if not self._current_path:
            self._on_save_as()
            return
        self._write_current(self._current_path)

    def _on_save_as(self):
        os.makedirs(_WORKFLOWS_DIR, exist_ok=True)
        default = os.path.join(_WORKFLOWS_DIR, "new_workflow.json")
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为方案文件", default, "JSON 文件 (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        self._write_current(path)

    def _write_current(self, path):
        errs = self._validate_model()
        if errs:
            shown = "; ".join(errs[:3]) + ("…" if len(errs) > 3 else "")
            self._set_editor_status("校验未通过，未保存: " + shown, "error")
            return
        text = json.dumps(self._to_workflow_dict(), ensure_ascii=False, indent=2)
        try:
            self._atomic_write(path, text)
            self._current_path = path
            self._clear_dirty()           # 落盘即与磁盘一致；先清 dirty 再刷新下拉，避免触发二次保存确认
            self._set_editor_status(f"已保存: {os.path.basename(path)}", "ok")
            self._refresh_schemes()
            # 阻塞信号：避免 setCurrentText 重发 currentTextChanged，递归触发 _on_combo_changed
            self._combo.blockSignals(True)
            self._combo.setCurrentText(os.path.basename(path))
            self._combo.blockSignals(False)
        except Exception as e:
            self._set_editor_status(f"保存失败: {e}", "error")

    @staticmethod
    def _atomic_write(path, text):
        """临时文件 + os.replace 原子落盘，避免写半截损坏（注意9）。"""
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _on_run(self):
        if self._engine is not None and self._engine.is_running():
            self._log("[运行] 已有方案运行中")
            return
        errs = self._validate_model()
        if errs:
            self._log("[运行] 中止——校验未通过: " + "; ".join(errs))
            return
        # A2 运行前校验：每个 jump_target 必须是当前树内的步骤 id，或可作为模块
        # 方案名解析（workflows/<name>.json 存在，与下方 _scheme_loader 同口径）；
        # 否则引擎 _do_jump 解析失败会直接 abort 整个方案——运行前拦截并给出
        # 明确错误（引擎侧 log + 返回 False 的兜底行为保持不变）。
        bad = []
        step_ids = set(collect_step_ids(self._steps_dicts))
        for sid, tgt in _iter_jump_targets(self._steps_dicts):
            if tgt in step_ids or _scheme_file_exists(tgt):
                continue
            bad.append(f'步骤 {sid} 的 jump_target "{tgt}" 既不是步骤也不是方案文件')
        if bad:
            msg = "跳转目标无效：" + "；".join(bad[:3]) + ("…" if len(bad) > 3 else "")
            self._set_editor_status(msg, "error")
            self._log("[运行] 中止——" + msg)
            return
        if self._input is None or self._coord is None:
            self._log("[运行] 缺少输入/坐标引擎，无法运行")
            return
        try:
            wf = workflow_from_dict(self._to_workflow_dict())
        except Exception as e:
            self._log(f"[运行] 模型构建失败: {e}")
            return
        def _scheme_loader(name):
            base = name if name.lower().endswith(".json") else name + ".json"
            path = os.path.join(_WORKFLOWS_DIR, base)
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return workflow_from_dict(data)
        self._engine = WorkflowEngine(self._coord, self._input, parser=self._parser,
                                      cm=self._cm, scheme_loader=_scheme_loader)
        self._engine.on_status = lambda sid, st: self._bridge.status.emit(sid, st)
        self._engine.on_finished = lambda r: self._bridge.finished.emit(r)
        self._engine.on_error = lambda e: self._bridge.error.emit(str(e))
        self._engine.load_def(wf)
        self._set_running_ui(True)
        label = os.path.basename(self._current_path) if self._current_path else "(编辑器内容)"
        self._log(f"[运行] 开始执行方案: {label}")
        self._engine.start()

    def _on_stop(self):
        if self._engine is not None:
            self._engine.abort()
            self._log("[运行] 已发送停止信号")

    # ------------------------------------------------------------------ #
    #  引擎回调（经信号桥，主线程执行）
    # ------------------------------------------------------------------ #
    def _on_engine_status(self, sid, st):
        # 逐步状态只刷新运行状态标签，不进应用主日志（网格循环等场景避免刷屏）
        self._set_run_status(f"运行中: {sid} {st}")

    def _on_engine_finished(self, reason):
        self._log(f"[完成] 退出原因: {reason}")   # 方案级 -> 应用主日志
        self._set_running_ui(False)
        self._set_run_status(f"完成 ({reason})")

    def _on_engine_error(self, msg):
        self._log(f"[错误] {msg}")                # 方案级 -> 应用主日志
        self._set_run_status("错误", "error")

    def _set_running_ui(self, running):
        self._btn_run.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._set_run_status("运行中…" if running else "空闲")

    def _set_run_status(self, msg, level="info"):
        """运行状态标签：颜色走主题（CanvasStatus 的 level 属性），不硬编码。

        运行中/空闲等中性态用默认 info；错误用 error（原红色）。
        """
        self._status_label.setText(msg)
        self._status_label.setProperty("level", level)
        # level 变化后需重跑 QSS：重设属性会触发 unpolish
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _log(self, msg):
        """方案级状态（载入/新建/删除/快捷键/运行/停止/完成/错误）
        → 应用主窗口底部日志状态栏（root logger 的 _QtLogHandler，INFO 级）。"""
        logger.info(msg)

    def _set_editor_status(self, msg, level="info"):
        """编辑相关状态（校验/保存/另存/预览）→ 抽屉内编辑器状态行。

        颜色走主题：状态行 objectName=CanvasStatus，level 区分
        ok/error/info（见 ui/theme.py 两套 QSS），不硬编码 hex。
        """
        panel = getattr(self, "_editor_panel", None)
        if panel is not None:
            panel.set_status(msg, level)
