# -*- coding: utf-8 -*-
"""配置段名常量（全局共享）。"""

SEC_COORD_BASE = "Coordinates_Base"
SEC_COORD_CUR = "Coordinates_Cur"
SEC_INVENTORY_GRID = "InventoryGrid"
SEC_STASH_TABS = "StashTabs"

# 背包网格默认尺寸（PoE标准背包）
INVENTORY_MAX_COLS = 12
INVENTORY_MAX_ROWS = 5

# L0迁移点名列表：无parent的点，启动时检查是否需要从绝对坐标迁移为相对窗口坐标
L0_MIGRATION_POINTS = [
    # "primary_tab_aux",  # V3026-COORD-002: removed — stash tab coords are
                          # written as relative-to-client by calibration flow;
                          # L0 migration threshold (50px) falsely triggers on
                          # legitimate relative Y values (e.g. 105 > 50),
                          # corrupting the stored value across restarts.
    "inv_origin_offset",
]

# 固定基准常量（永不修改）
FIXED_CALIBRATION_WIDTH = 1366
FIXED_CALIBRATION_HEIGHT = 768
FIXED_CALIBRATION_UI_SCALE = 1.0


# Frame-origin migration: one-time offset adjustment for Cur coords
FRAME_ORIGIN_MIGRATION_DONE_KEY = "frame_origin_migration_done"

# ── 统一延时派生体系：物理下限常量（ms）──
# 与 _derived_delay(min_ms, multiplier) 配合使用
DELAY_MOVE_MIN = 30        # 鼠标移动后等待
DELAY_CLIPBOARD_MIN = 80  # Ctrl+C + 客户端渲染
DELAY_STASH_VERIFY_MIN = 120  # POE存图网络确认
DELAY_TAB_SWITCH_MIN = 150    # 仓库页签加载动画
DELAY_HOLD_CHECK_MIN = 30     # 持有检测纯本地操作
DELAY_RETRY_MIN = 60          # 失败后短暂等待

# 各动作乘数（float）
DELAY_MOVE_MULT = 1.0
DELAY_CLIPBOARD_MULT = 1.1
DELAY_STASH_VERIFY_MULT = 1.8
DELAY_TAB_SWITCH_MULT = 2.3
DELAY_HOLD_CHECK_MULT = 0.3
DELAY_RETRY_MULT = 0.8
