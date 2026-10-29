# -*- coding: utf-8 -*-
"""选项卡: 工作流画布（GUI 升级 阶段2 · 只读可视化）。

与「工作流」页签**并存**（用户 2026-10-18 定案：新增独立 TAB，画布在主区、
右侧抽屉照旧显示模块库 + 步骤列表），两视图共享同一份步骤 dict 树
（单一事实源），并做双向选中高亮联动。

本阶段只读：画布仅做可视化，不拖动 / 不连线 / 不改数据。
拖拽重排、吸附对齐属阶段3。
"""
import os
import json
import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QMessageBox,
)

from .text_resources import TextResources
from ..workflow_model import (
    remap_jump_targets, assign_step_ids,
)
from .theme import DEFAULT_THEME
from .workflow_canvas import WorkflowCanvasView

logger = logging.getLogger(__name__)

_WORKFLOWS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workflows")


def _load_subworkflow_steps(name):
    """读取子工作流方案的 steps（Q3 只读预览用）；读不到返回 []。"""
    if not name:
        return []
    base = name if name.lower().endswith(".json") else name + ".json"
    path = os.path.join(_WORKFLOWS_DIR, base)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("steps", []) or []
    except Exception as e:
        logger.error(f"读取子工作流 {base} 失败: {e}", exc_info=True)
        return []


def _find_step_by_id(steps, step_id):
    """在步骤树（含 body/then_steps/else_steps）中按 id 查找步骤 dict。

    与 _remove_step_by_id 同构的只读版；找不到返回 None。
    """
    for d in steps or []:
        if str(d.get("id", "")) == str(step_id):
            return d
    for d in steps or []:
        for key in ("body", "then_steps", "else_steps"):
            found = _find_step_by_id(d.get(key, []), step_id)
            if found is not None:
                return found
    return None


def _remove_step_by_id(steps, step_id):
    """在步骤树（含 body/then_steps/else_steps）中按 id 删除步骤，返回是否命中。"""
    for lst in (steps,):
        for i, d in enumerate(lst or []):
            if str(d.get("id", "")) == str(step_id):
                lst.pop(i)
                return True
    for d in (steps or []):
        for key in ("body", "then_steps", "else_steps"):
            if _remove_step_by_id(d.get(key, []), step_id):
                return True
    return False


def _subtree_contains(step, obj) -> bool:
    """step 的子树（body/then_steps/else_steps，不含自身）是否含 obj（按身份）。

    跨容器搬运防环双保险：视图层按 _parent_id 链拦过一遍，handler 作为
    数据真相层按对象身份再拦——容器不能搬进自己或自己的后代。
    """
    for key in ("body", "then_steps", "else_steps"):
        for d in step.get(key) or []:
            if d is obj or _subtree_contains(d, obj):
                return True
    return False


def _find_container_of(steps, obj):
    """obj 所在子区的**直接**容器 → (container_dict, region_key)；顶层 → (None, "")。

    跨容器搬运的结构护栏用：判断被拖步骤搬走后源容器是否会变成空 loop body
    （validate_workflow 拒收「loop 没有 body」——方案将无法运行）。
    """
    for d in steps or []:
        if not isinstance(d, dict):
            continue
        for key in ("body", "then_steps", "else_steps"):
            for child in d.get(key) or []:
                if child is obj:
                    return d, key
            sub_container, sub_key = _find_container_of(
                d.get(key) or [], obj)
            if sub_container is not None:
                return sub_container, sub_key
    return None, ""


class WorkflowCanvasTab(QWidget):
    """工作流画布页签：方案选择 + 只读画布 + 与列表的双向选中联动。"""

    def __init__(self, config_manager, input_simulator=None,
                 coord_engine=None, parser=None):
        super().__init__()
        self._cm = config_manager
        self._input = input_simulator
        self._coord = coord_engine
        self._parser = parser
        self._workflow_tab = None   # 「工作流」页签引用（共享数据源）
        self._syncing = False       # 防联动回环
        self._build()
        self._refresh_schemes()

    # ------------------------------------------------------------------ #
    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QLabel("步骤从左到右，循环 / 分支从上而下；"
                        "点击节点可在右侧列表定位，点列表可在画布高亮。")
        header.setWordWrap(True)
        header.setObjectName("StatusHint")
        layout.addWidget(header)

        # ── 方案选择 + 视图操作 ──
        file_row = QHBoxLayout()
        self._combo = QComboBox()
        self._combo.setMinimumWidth(160)
        self._combo.currentTextChanged.connect(self._on_combo_changed)
        file_row.addWidget(QLabel("方案文件"))
        file_row.addWidget(self._combo, stretch=1)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self._refresh_schemes)
        btn_relayout = QPushButton("重排")
        btn_relayout.setToolTip("按「步骤左→右、容器上→下」重新排布")
        btn_relayout.clicked.connect(self._on_relayout)
        btn_fit = QPushButton("适应")
        btn_fit.clicked.connect(self._on_fit)
        # 阶段3：可编辑开关（拖动重排 / Delete 删除 / 模块库拖入）
        self._chk_edit = QCheckBox("可编辑")
        self._chk_edit.setToolTip("开启后：拖动节点即重排、Delete 删除、"
                                  "可从左侧模块库拖入新步骤")
        self._chk_edit.toggled.connect(self._on_edit_toggled)
        file_row.addWidget(btn_refresh)
        file_row.addWidget(btn_relayout)
        file_row.addWidget(btn_fit)
        file_row.addWidget(self._chk_edit)
        layout.addLayout(file_row)

        # ── 画布 ──
        self._canvas = WorkflowCanvasView(self._cm)
        # 阶段4（Q3）：子工作流点击展开只读预览（读 workflows/<name>.json）
        self._canvas.set_subworkflow_loader(self._load_subworkflow)
        layout.addWidget(self._canvas, stretch=1)
        self._canvas.stepClicked.connect(self._on_canvas_clicked)
        self._canvas.stepReorderRequested.connect(self._on_canvas_reorder)
        # P4-B 增量2：嵌套子节点同子区内拖动改序（与顶层重排互斥）
        self._canvas.stepReorderInRegionRequested.connect(
            self._on_canvas_reorder_in_region)
        # A4 收尾：跨区/跨层/跨容器搬运（顶层↔容器、body→then、then→else）
        self._canvas.stepMoveRequested.connect(self._on_canvas_move)
        self._canvas.stepDeleteRequested.connect(self._on_canvas_delete)
        self._canvas.paletteDropRequested.connect(self._on_canvas_drop)
        # P4-B：拖入落点位于容器子区时走容器插入（与顶层拖入互斥）
        self._canvas.paletteDropInContainer.connect(
            self._on_canvas_drop_in_container)

        self._status = QLabel("就绪")
        self._status.setObjectName("CanvasStatus")
        layout.addWidget(self._status)

    # ------------------------------------------------------------------ #
    #  阶段3：画布可编辑
    # ------------------------------------------------------------------ #
    def _on_edit_toggled(self, on: bool):
        self._canvas.set_editable(on)
        self._set_status("画布已开启编辑：可拖动重排 / Delete 删除 / 模块库拖入"
                         if on else "画布为只读视图", "info" if on else "muted")

    def set_canvas_editable(self, on: bool) -> None:
        """外部（如弹窗）设置画布可编辑状态，同步勾选框。"""
        self._chk_edit.setChecked(bool(on))

    def _on_canvas_reorder(self, step_id: str, new_index: int):
        """拖动即重排（Q1）：改真实数据顺序，再重建画布。"""
        if self._workflow_tab is None or self._syncing:
            return
        try:
            steps = self._workflow_tab._steps_dicts
            target = None
            for d in steps:
                if str(d.get("id", "")) == str(step_id):
                    target = d
                    break
            if target is None:
                return
            steps.remove(target)
            idx = max(0, min(new_index, len(steps)))
            steps.insert(idx, target)
            self._rebuild()
            self._set_status(f"已把步骤 {step_id} 移到第 {idx + 1} 位", "ok")
            self._sync_list_cards()
        except Exception as e:
            logger.error(f"画布重排失败: {e}", exc_info=True)
            self._set_status(f"重排失败：{e}", "error")

    def _on_canvas_reorder_in_region(self, step_id: str, container_id: str,
                                     region_key: str, new_index: int):
        """P4-B 增量2：容器子区内拖动改序（同区移动；跨区/跨容器仍未设计）。

        口径与顶层 _on_canvas_reorder 一致：先 remove 再 insert，画布侧
        算索引时已排除被拖节点自身；越界索引由 min/max 收敛。
        """
        if self._workflow_tab is None or self._syncing:
            return
        if region_key not in self._REGION_LABELS:
            self._set_status(f"未知容器子区：{region_key}", "error")
            return
        label = self._REGION_LABELS[region_key]
        try:
            steps = self._workflow_tab._steps_dicts
            container = _find_step_by_id(steps, container_id)
            if container is None:
                self._set_status(f"未找到容器 {container_id}", "error")
                return
            region = container.get(region_key)
            if not isinstance(region, list):
                self._set_status(
                    f"容器 {container_id} 无{label}", "error")
                return
            target = None
            for d in region:
                if str(d.get("id", "")) == str(step_id):
                    target = d
                    break
            if target is None:
                # 声称在某个区、实际不在（信号与数据不一致的防御路径）
                self._set_status(
                    f"未在 {container_id} 的{label}找到步骤 {step_id}", "error")
                return
            region.remove(target)
            idx = max(0, min(new_index, len(region)))
            region.insert(idx, target)
            self._rebuild()
            self._set_status(
                f"已把步骤 {step_id} 移到{label}第 {idx + 1} 位", "ok")
            self._sync_list_cards()
        except Exception as e:
            logger.error(f"子区重排失败: {e}", exc_info=True)
            self._set_status(f"重排失败：{e}", "error")

    def _on_canvas_delete(self, step_id: str):
        """Delete 删除选中步骤。"""
        if self._workflow_tab is None or self._syncing:
            return
        try:
            found = _remove_step_by_id(self._workflow_tab._steps_dicts, step_id)
            if not found:
                return
            self._rebuild()
            self._set_status(f"已删除步骤 {step_id}", "ok")
            self._sync_list_cards()
        except Exception as e:
            logger.error(f"画布删除失败: {e}", exc_info=True)
            self._set_status(f"删除失败：{e}", "error")

    def _on_canvas_drop(self, descriptor: dict, index: int):
        """从模块库拖入画布落点 → 插入步骤（复用 WorkflowTab 的生成逻辑）。"""
        if self._workflow_tab is None or self._syncing:
            return
        try:
            before = len(self._workflow_tab._steps_dicts)
            self._workflow_tab._on_palette_activated(descriptor)
            # 生成后按落点索引重排到指定位置
            steps = self._workflow_tab._steps_dicts
            if len(steps) > before:
                new_step = steps[-1]
                steps.remove(new_step)
                idx = max(0, min(index, len(steps)))
                steps.insert(idx, new_step)
            self._rebuild()
            self._set_status(f"已插入 {descriptor.get('payload')} 到第 {index + 1} 位",
                             "ok")
            self._sync_list_cards()
        except Exception as e:
            logger.error(f"拖入插入失败: {e}", exc_info=True)
            self._set_status(f"插入失败：{e}", "error")

    # P4-B：容器子区名 → 中文（状态行/提示用），键与 CanvasModel 的
    # _CONTAINER_KIND_KEYS 一致（loop→body；branch→then_steps/else_steps）
    _REGION_LABELS = {"body": "循环体", "then_steps": "条件成立区",
                      "else_steps": "条件不成立区"}

    def _on_canvas_drop_in_container(self, descriptor: dict, container_id: str,
                                     region_key: str, index: int):
        """P4-B：模块库拖入容器子区（loop body / branch then|else）→ 插入该区。

        生成仍复用 WorkflowTab._on_palette_activated（追加到根末尾），再把
        新 dict 移入容器对应子列表的 index 处——与顶层 _on_canvas_drop 同一
        模式，id 重编号 / jump_target 同步改写由后续 _rebuild 与
        _sync_list_cards 完成（A2/A5 既有链路）。
        """
        if self._workflow_tab is None or self._syncing:
            return
        if region_key not in self._REGION_LABELS:
            self._set_status(f"未知容器子区：{region_key}", "error")
            return
        try:
            steps = self._workflow_tab._steps_dicts
            # 容器 dict 先按 id 取到（_on_palette_activated 可能触发列表侧重
            # 编号，持 dict 引用不受影响）
            container = _find_step_by_id(steps, container_id)
            if container is None:
                self._set_status(f"未找到容器 {container_id}", "error")
                return
            # 区域键先补齐再走 _on_palette_activated——它内部会触发列表侧重
            # 建卡片，缺键分支会在 StepCard 硬下标处抛 KeyError（闪退家族）。
            region = container.get(region_key)
            if not isinstance(region, list):
                region = []
                container[region_key] = region
            before = len(steps)
            self._workflow_tab._on_palette_activated(descriptor)
            if len(steps) <= before:
                return
            new_step = steps[-1]
            steps.remove(new_step)
            idx = max(0, min(index, len(region)))
            region.insert(idx, new_step)
            self._rebuild()
            label = self._REGION_LABELS[region_key]
            self._set_status(
                f"已插入 {descriptor.get('payload')} 到 {container_id} 的"
                f"{label}第 {idx + 1} 位", "ok")
            self._sync_list_cards()
        except Exception as e:
            logger.error(f"拖入容器失败: {e}", exc_info=True)
            self._set_status(f"插入失败：{e}", "error")

    def _on_canvas_move(self, step_id: str, dst_parent_id: str,
                        dst_region_key: str, dst_index: int):
        """A4 收尾：跨区/跨层/跨容器搬运（loop body→branch then、then→else、
        顶层↔容器等）。源位置不信任信号声称，按 id 全树定位后移除。

        口径与既有 handler 一致：先 remove 再 insert（画布侧算索引时已排除
        被拖节点自身），越界索引 min/max 收敛；id 重编号 / jump_target 同步
        由后续 _rebuild 与 _sync_list_cards 完成（A2/A5 既有链路）。

        四道拒绝护栏（都不改数据）：
        1. 未知子区键 / 容器或步骤不存在；
        2. 子区键与容器类型不匹配（loop 无 then/else）——防「僵尸子列表」；
        3. 容器搬进自己或后代（视图层按 _parent_id 链拦过，这里按对象身份
           再拦一次——信号与数据不一致时以防万一）；
        4. 搬走 loop body 唯一子步会留下空 body（validate 拒收、方案无法
           运行）→ 拒绝；branch 两区允许为空，无此护栏。
        """
        if self._workflow_tab is None or self._syncing:
            return
        if dst_region_key and dst_region_key not in self._REGION_LABELS:
            self._set_status(f"未知容器子区：{dst_region_key}", "error")
            return
        try:
            steps = self._workflow_tab._steps_dicts
            target = _find_step_by_id(steps, step_id)
            if target is None:
                self._set_status(f"未找到步骤 {step_id}", "error")
                return
            if dst_parent_id:
                container = _find_step_by_id(steps, dst_parent_id)
                if container is None:
                    self._set_status(f"未找到容器 {dst_parent_id}", "error")
                    return
                # 容器类型与子区键必须匹配（loop 只有 body；branch 只有
                # then/else）。不匹配时插入会造出布局层从不渲染的「僵尸
                # 子列表」——步骤从画布消失却留在数据里。视图层只会发出
                # _region_hit 里真实存在的区键，此处是防信号/数据不一致。
                allowed = {"loop": ("body",),
                           "branch": ("then_steps", "else_steps")}.get(
                               container.get("kind"))
                if allowed is not None and dst_region_key not in allowed:
                    self._set_status(
                        f"容器 {dst_parent_id} 没有 {dst_region_key} 子区",
                        "error")
                    return
                if container is target or _subtree_contains(target, container):
                    self._set_status(
                        f"已拒绝：容器 {step_id} 不能搬进自己或自己的后代", "error")
                    return
            # 结构护栏：被拖步骤若是某 loop body 的**唯一**子步，搬走后该
            # loop body 为空 → validate_workflow 判「loop 没有 body」，方案
            # 将无法运行。拒绝并说明；用户可删除整个循环或先保留一个步骤。
            # （branch 的 then/else 允许为空，无需护栏。）
            src_container, _src_region = _find_container_of(steps, target)
            if (src_container is not None
                    and src_container.get("kind") == "loop"
                    and len(src_container.get("body") or []) <= 1
                    and not (dst_parent_id and container is src_container)):
                self._set_status(
                    f"已拒绝：循环 {src_container.get('id')} 的循环体不能为空，"
                    f"请删除整个循环或至少保留一个步骤", "error")
                return
            # 从原位置移除（可能在顶层或任意容器子区）
            if not _remove_step_by_id(steps, step_id):
                self._set_status(f"移除失败：{step_id}", "error")
                return
            if dst_parent_id:
                # 区域键先补齐再插入（缺键分支会在列表侧 StepCard 硬下标
                # 抛 KeyError——闪退家族，与 drop_in_container 同模式）
                region = container.get(dst_region_key)
                if not isinstance(region, list):
                    region = []
                    container[dst_region_key] = region
                idx = max(0, min(int(dst_index), len(region)))
                region.insert(idx, target)
                dst_desc = (f"{dst_parent_id} 的"
                            f"{self._REGION_LABELS[dst_region_key]}第 {idx + 1} 位")
            else:
                idx = max(0, min(int(dst_index), len(steps)))
                steps.insert(idx, target)
                dst_desc = f"顶层第 {idx + 1} 位"
            self._rebuild()
            self._set_status(f"已把步骤 {step_id} 移到{dst_desc}", "ok")
            self._sync_list_cards()
        except Exception as e:
            logger.error(f"跨容器搬运失败: {e}", exc_info=True)
            self._set_status(f"搬运失败：{e}", "error")

    def _sync_list_cards(self):
        """A5：画布结构操作（重排/删除/拖入）后同步刷新列表侧卡片。

        此前三个 handler 只重建画布，切回列表仍是旧卡片——对已脱离数据树的
        僵尸卡片编辑会静默丢失。注意与 A2 联动：_rebuild_cards 内部会做 id
        快照 + jump_target 同步改写，画布侧重排后 id 已变，jump_target 应被
        同步改写——这正是期望行为。
        """
        if self._workflow_tab is None:
            return
        try:
            self._workflow_tab._rebuild_cards()
        except Exception as e:
            logger.error(f"同步列表卡片失败: {e}", exc_info=True)
            self._set_status(f"同步列表失败：{e}", "error")

    # ------------------------------------------------------------------ #
    def attach_workflow_tab(self, tab) -> None:
        """绑定「工作流」页签（共享数据源 + 列表联动）。"""
        self._workflow_tab = tab
        self._rebuild()

    def refresh_from_workflow(self) -> None:
        """列表侧结构变化后由 WorkflowTab 调用，重建画布（保持两视图同源）。"""
        if self._workflow_tab is None:
            return
        self._rebuild()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_schemes()
        self._rebuild()

    # ---- 方案 ----
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

    def _on_combo_changed(self, name):
        if not name:
            return
        self._rebuild()

    # ---- 渲染 ----
    def _load_subworkflow(self, name):
        """供画布 Q3 展开预览调用的读取器。"""
        return _load_subworkflow_steps(name)

    def _current_steps(self):
        """取共享数据源：优先「工作流」页签当前编辑内容，其次读方案文件。"""
        if self._workflow_tab is not None:
            steps = getattr(self._workflow_tab, "_steps_dicts", None)
            if steps:
                return steps
        name = self._combo.currentText()
        if not name:
            return []
        path = os.path.join(_WORKFLOWS_DIR, name)
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("steps", []) or []
        except Exception as e:
            self._set_status(f"读取方案失败：{e}", "error")
            return []

    def _rebuild(self):
        steps = self._current_steps()
        # id 单一事实源：assign_step_ids 按层级位置统一重编号（与列表侧
        # _rebuild_cards 同一函数），并同步改写 jump_target（A2 链路）。
        # 旧实现此处自带一份 _assign_ids 拷贝 + 快照/remap 舞步，与列表侧
        # 各算一份——规则漂移时画布后执行会静默覆盖 dict 里的 id，而卡片
        # 标题用列表侧旧值，两边不一致且无报错。
        remap_jump_targets(steps, assign_step_ids(steps))
        self._canvas.set_theme(self._theme_key())
        self._canvas.set_steps(steps)
        n = self._canvas.node_count()
        mode = "可编辑" if self._canvas.is_editable() else "只读"
        self._set_status(f"已渲染 {n} 个节点（{mode}视图）", "ok")

    def _theme_key(self):
        try:
            key = self._cm.get("General", "visual_style", DEFAULT_THEME)
            return key if key in ("light", "dark") else DEFAULT_THEME
        except Exception:
            return DEFAULT_THEME

    # ---- 联动 ----
    def _on_canvas_clicked(self, step_id: str):
        """画布 → 列表：高亮并滚动到对应卡片。"""
        if self._syncing or not step_id or self._workflow_tab is None:
            return
        self._syncing = True
        try:
            self._workflow_tab.focus_step_by_id(step_id)
        except Exception as e:
            logger.error(f"画布→列表联动失败: {e}", exc_info=True)
        finally:
            self._syncing = False

    def select_step(self, step_id: str):
        """列表 → 画布：高亮对应节点（供 WorkflowTab 调用）。"""
        if self._syncing or not step_id:
            return
        self._syncing = True
        try:
            self._canvas.select_step(step_id)
        finally:
            self._syncing = False

    # ---- 操作 ----
    def _on_relayout(self):
        self._canvas.auto_layout()
        self._set_status("已按「步骤左→右、容器上→下」重新布局", "ok")

    def _on_fit(self):
        self._canvas.fitInView(self._canvas.sceneRect(), Qt.KeepAspectRatio)

    def _set_status(self, msg, level="info"):
        """状态行：颜色走主题（CanvasStatus 的 level 属性），不硬编码。"""
        self._status.setText(msg)
        self._status.setProperty("level", level)
        # level 变化后需重跑 QSS：重设属性会触发 unpolish
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)