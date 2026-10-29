"""宿主服务契约（Protocol）。

poe-workflow 引擎通过构造注入依赖宿主能力（坐标 / 输入模拟 / 配置 /
词缀解析 / 方案加载），**不反向依赖** poe-mapmaker 等宿主。以下 Protocol
仅描述引擎实际调用的「鸭子接口」，宿主只需结构化地实现对应方法即可，
无需继承本类。

这是 Phase 1 抽取时确立的契约边界，供新仓库满足文档要求（注意13）与主仓
对接参考。UI 层（Phase 2 抽取）所需的 DrawerHost / ThemeService 等契约
将在第二阶段补充。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Protocol, runtime_checkable

if TYPE_CHECKING:  # 避免运行时循环导入；类型标注用字符串前向引用
    from .workflow_model import WorkflowDef


@runtime_checkable
class CoordService(Protocol):
    """锚点 / 仓库页坐标解析。"""

    def get_absolute_position(self, name: str) -> Tuple[int, int]:
        """锚点名 -> 屏幕绝对坐标 (x, y)；未校准返回 (0, 0) 哨兵。"""
        ...

    def stash_tab_position(self, tab_index: int) -> Tuple[int, int]:
        """仓库页签索引 -> 页签点击坐标 (x, y)。"""
        ...

    def stash_currency_position(self, currency_name: str) -> Tuple[int, int]:
        """通货名 -> 通货在仓库中的坐标 (x, y)。"""
        ...


@runtime_checkable
class InputService(Protocol):
    """鼠标 / 键盘 / 剪贴板模拟。"""

    def click(self, x: int, y: int, button: str = "left") -> None:
        ...

    def move_mouse(self, x: int, y: int) -> None:
        ...

    def press_mouse(self, key: str) -> None:
        """鼠标键 / 滚轮 token（mouse_left / ctrl+mouse_right ...）。"""
        ...

    def press_key(self, key: str) -> None:
        """键盘键或组合（ctrl+c）。"""
        ...

    def read_clipboard(self) -> Optional[str]:
        ...

    def clear_clipboard(self) -> None:
        ...

    def record_action(self) -> None:
        """会话限速器登记一次动作。"""
        ...

    def normal_delay(self) -> None:
        """通货应用后的常规物理延迟。"""
        ...

    # —— 以下为可选能力，引擎以 getattr 容错调用，缺失时静默跳过 ——
    def get_mouse_pos(self) -> Tuple[int, int]:
        """当前光标位置（悬停评估场景取目标格用）。"""
        ...

    def check_session_limit(self) -> Tuple[bool, str]:
        """返回 (ok, reason) 会话限速状态。"""
        ...

    def clipboard_stash_verify(self) -> bool:
        """存仓后校验光标处已清空。"""
        ...


@runtime_checkable
class ConfigService(Protocol):
    """配置读取（兼容 configparser 风格 API）。"""

    def get(self, section: str, key: str, default: str = "") -> str:
        ...

    def get_affix_entries(self, section: str) -> List[str]:
        """返回某词缀区块（如 AffixBlackList）的全部条目。"""
        ...


@runtime_checkable
class AffixService(Protocol):
    """地图词缀 / 稀有度解析。"""

    def detect_rarity(self, text: str) -> str:
        """从物品文本解析稀有度（normal/magic/rare/unique/unknown）。"""
        ...

    def evaluate_map(self, text: str, blacklist: List[str], whitelist: List[str]) -> Dict[str, Any]:
        """评估地图词缀，返回含 final_decision / params_pass 等字段的字典。"""
        ...


@runtime_checkable
class SchemeLoader(Protocol):
    """模块方案加载：方案名 -> WorkflowDef（供 on_error=jump 与子工作流调用）。"""

    def __call__(self, name: str) -> "WorkflowDef":
        ...
