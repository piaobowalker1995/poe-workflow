# -*- coding: utf-8 -*-
"""工作流画布的数据适配层（非 Qt，可单测）。

把现有「步骤 dict 树」（WorkflowTab._steps_dicts 的形状）封装为可增删改、
可校验的模型。画布视图（阶段2）与列表视图（现有 StepCard）共享同一份根列表
对象，本层只负责结构性读写与校验，不依赖任何 Qt。

设计原则（见 workflow_gui_upgrade_spec.md §2）：
- 单一事实源：CanvasModel 持有对根列表的引用，原地修改；列表视图读同一对象即为单一事实源。
- 引擎零改动：仅调用 poe_workflow.workflow_model 的 workflow_from_dict / validate_workflow。
- 可测试：本模块无任何 Qt 依赖，单测在普通 Python 解释器即可跑（无需 offscreen）。
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..workflow_model import workflow_from_dict, validate_workflow


# 容器类型：其「子列表」键与展示区名（用于画布 阶段2 的嵌套组框）
_CONTAINER_KIND_KEYS: Dict[str, List[Tuple[str, str]]] = {
    "loop": [("body", "循环体")],
    "branch": [("then_steps", "条件成立"), ("else_steps", "条件不成立")],
}


class CanvasModel:
    """步骤 dict 树的非 Qt 适配层。

    构造时传入的根列表会被**原样持有**（不拷贝）：列表视图（WorkflowTab._steps_dicts）
    与此处的 self._root 指向同一对象，任一处追加/删除都即时反映到另一方，从而保证
    单一事实源。载入新方案 / 新建时根列表会被重新赋值，须调用 set_root 同步引用。
    """

    def __init__(self, root_steps: Optional[List[Dict[str, Any]]] = None,
                 on_change: Optional[Callable[[], None]] = None):
        self._root: List[Dict[str, Any]] = root_steps if root_steps is not None else []
        self._on_change: List[Callable[[], None]] = []
        if on_change is not None:
            self._on_change.append(on_change)

    # ---- 事实源访问 ----
    def root(self) -> List[Dict[str, Any]]:
        return self._root

    def set_root(self, steps: List[Dict[str, Any]]) -> None:
        """替换根列表（载入新方案 / 新建时调用，保持引用同步）。"""
        self._root = steps
        self._emit()

    def add_change_listener(self, cb: Callable[[], None]) -> None:
        if cb not in self._on_change:
            self._on_change.append(cb)

    # ---- 结构读写 ----
    def insert_step(self, step_dict: Dict[str, Any],
                    parent_list: Optional[List[Dict[str, Any]]] = None,
                    index: Optional[int] = None) -> Dict[str, Any]:
        """在 parent_list（默认根）的 index 处插入一步；index=None 追加到末尾。"""
        lst = parent_list if parent_list is not None else self._root
        if index is None or index > len(lst):
            index = len(lst)
        if index < 0:
            index = 0
        lst.insert(index, step_dict)
        self._emit()
        return step_dict

    def delete_step(self, step_dict: Dict[str, Any],
                    parent_list: Optional[List[Dict[str, Any]]] = None) -> bool:
        """从 parent_list（默认根）删除指定步骤 dict；成功返回 True。"""
        lst = parent_list if parent_list is not None else self._root
        if step_dict in lst:
            lst.remove(step_dict)
            self._emit()
            return True
        return False

    def move_step(self, step_dict: Dict[str, Any],
                  parent_list: Optional[List[Dict[str, Any]]] = None,
                  new_index: Optional[int] = None) -> bool:
        """在 parent_list（默认根）内移动 step_dict 到 new_index（阶段3 重排用）。"""
        lst = parent_list if parent_list is not None else self._root
        if step_dict not in lst:
            return False
        lst.remove(step_dict)
        if new_index is None or new_index > len(lst):
            new_index = len(lst)
        if new_index < 0:
            new_index = 0
        lst.insert(new_index, step_dict)
        self._emit()
        return True

    def children_regions(self, step_dict: Dict[str, Any]) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
        """返回容器步的子列表区 [(region_key, region_label, list)]；非容器返回 []。"""
        kind = step_dict.get("kind")
        if kind not in _CONTAINER_KIND_KEYS:
            return []
        return [(k, label, step_dict.get(k, [])) for k, label in _CONTAINER_KIND_KEYS[kind]]

    # ---- 校验 / 序列化 ----
    def to_workflow_dict(self) -> Dict[str, Any]:
        return {"steps": [copy.deepcopy(s) for s in self._root]}

    def to_workflow_def(self):
        return workflow_from_dict(self.to_workflow_dict())

    def validate(self) -> List[str]:
        """返回校验错误列表（空列表 = 合法）。"""
        return validate_workflow(self.to_workflow_def())

    # ---- 内部 ----
    def _emit(self) -> None:
        for cb in self._on_change:
            try:
                cb()
            except Exception:
                # 监听器异常不应中断结构变更
                pass
