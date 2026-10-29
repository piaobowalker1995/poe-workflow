# -*- coding: utf-8 -*-
"""
纯中文文案字典模块
所有UI显示文本、日志消息、提示信息统一从此处获取，禁止硬编码中文字符串到UI代码中。
"""


class TextResources:
    """集中管理所有中文文案的静态类"""

    # ==================== 主窗口 ====================
    APP_TITLE = "POE MapMaker"
    TAB_HOTKEYS = "快捷指令"
    TAB_GAME_WINDOW = "游戏窗口"
    TAB_STASH = "仓库管理"
    TAB_CURRENCY = "通货管理"
    TAB_STRATEGY = "制图策略"
    TAB_SYSTEM = "系统设置"
    TAB_SAFETY = "安全设置"
    TAB_ABOUT = "关于"
    TAB_FLOWCHART = "制图流程"
    TAB_WORKFLOW = "工作流"
    TAB_WORKFLOW_CANVAS = "工作流画布"

    # ==================== 系统设置页按钮 ====================
    SYS_BTN_WORKFLOW = "工作流编排"

    # ==================== 状态栏 / 日志 ====================
    LOG_CONFIG_LOADED = "配置文件加载成功"
    LOG_CONFIG_SAVE_FAILED = "配置文件保存失败: {}"
    LOG_COORD_CALC = "坐标换算: {}={}→{}"
    LOG_COORD_POINT_NOT_CONFIGURED = "坐标点 '{}' 尚未配置，请先在校准页面完成指认"
    LOG_COORD_SAVE_FAILED = "坐标保存失败: {}"
    LOG_CLIPBOARD_VALIDATE_FAIL = "剪贴板校验失败，重试({}/{})"
    LOG_CLIPBOARD_VALIDATE_OK = "剪贴板校验通过"
    LOG_SESSION_LIMIT_REACHED = "会话上限已达，自动暂停（每小时{}/每日{}）"
    LOG_EMERGENCY_STOP = "紧急停止已触发"
    LOG_STATE_TRANSITION = "状态切换: {} → {}"
    LOG_MAP_STORED = "地图已存入{}仓库"
    LOG_CORRUPT_SUCCESS = "腐化成功，符合参数库+词缀库"
    LOG_CORRUPT_FAIL_PARAM = "腐化失败，不满足参数库"
    LOG_CORRUPT_FAIL_BLACKLIST = "腐化失败，命中黑名单词缀"
    LOG_STASH_FULL = "仓库连续存图失败{}次，判定为仓库满"
    LOG_BACKPACK_EMPTY = "背包地图已耗尽"
    LOG_CALIBRATION_START = "进入校准模式: {}，请按对应快捷键确认"
    # 注意: 此处不可带 "{}" 占位符 —— 三个调用点(tab_stash/tab_inventory/tab_currency)
    # 均以 f"{LOG_CALIBRATION_DONE}: {label} ({x}, {y})" 自行拼接点位名与坐标，
    # 若模板保留 {} 会原样显示成 "校准完成: {}: ..."（V3037-UI-002）。
    LOG_CALIBRATION_DONE = "校准完成"
    LOG_CALIBRATION_CANCELLED = "校准已取消"
    LOG_HOTKEY_CONFLICT = "热键冲突: {} 已被 {} 占用"
    LOG_REGEX_TEST_OK = "正则测试通过 ✓"
    LOG_REGEX_TEST_FAIL = "正则测试失败 ✗"
    LOG_AFFIX_VERSION = "词缀库版本: {}"
    LOG_CONFIG_EXTERNAL_MODIFIED = "检测到配置文件外部修改"
    LOG_CONFIG_RESTART_REQUIRED = "核心配置已变更，需重启程序生效"
    LOG_CONFIG_AUTO_RELOADED = "非核心配置已自动重载"

    # ==================== 统计标签 ====================
    STAT_TOTAL_PROCESSED = "累计处理"
    STAT_YELLOW_MAPS = "黄图"
    STAT_CORRUPT_SUCCESS = "腐化成功"
    STAT_CORRUPT_FAIL = "腐化失败"
    STAT_NEGATIVE_MAPS = "负面废图"
    STAT_BATCH_COUNT = "本批次"

    # ==================== 快捷指令选项卡 ====================
    HK_LABEL_EMERGENCY = "紧急停止"
    HK_LABEL_START_STOP = "开始/暂停制图"
    HK_LABEL_PAUSE_RESUME = "暂停/恢复"
    HK_LABEL_ADD_CURRENCY = "添加通货"
    HK_LABEL_AUTO_CLICK = "自动点击"
    HK_MODE_GLOBAL = "全局热键"
    HK_MODE_FOREGROUND = "仅游戏前台生效"
    HK_BTN_RESTORE_DEFAULT = "恢复默认"
    HK_CONFLICT_WARNING = "热键冲突"

    # ==================== 游戏窗口选项卡 ====================
    GW_AUTO_RESIZE = "自动调整游戏窗口"
    GW_WIDTH = "宽度"
    GW_HEIGHT = "高度"
    GW_POS_X = "X坐标"
    GW_POS_Y = "Y坐标"
    GW_BTN_APPLY = "立即应用"
    GW_BTN_FETCH_CURRENT = "获取当前"
    GW_CURRENT_INFO = "当前窗口信息"
    GW_WINDOW_MINIMIZED = "游戏窗口已最小化"
    GW_WINDOW_NOT_FOUND = "未检测到游戏窗口"
    GW_UI_SCALE_GROUP = "UI缩放设置（仅影响运行时坐标乘数，修改不触发坐标换算）"
    GW_UI_SCALE_LABEL = "UI缩放倍率"
    GW_UI_SCALE_TOOLTIP = "游戏内UI缩放倍率。通常保持1.00；仅当游戏设置中调整了界面缩放、或窗口含标题栏导致坐标偏移时才需修改"
    GW_WINDOW_TITLE_LABEL = "游戏窗口标题"
    GW_WINDOW_TITLE_TOOLTIP = "游戏窗口的标题文本，用于识别和定位游戏窗口。不同语言版本或自定义窗口标题时需修改此项"
    GW_WINDOW_TITLE_GROUP = "窗口识别设置"

    # ==================== 仓库管理选项卡 ====================
    STASH_BTN_CAL_ORIGIN = "页签原点指认"
    STASH_LBL_OFFSET = "页签偏移量"
    STASH_CURRENCY_TAB = "通货仓"
    STASH_FINISHED_TAB = "成品仓"
    # 2026-10-23：三档结论后「优秀图」专指高参数瑕疵图（去向=瑕疵仓），
    # 半成品仓恢复本义「未腐化且符合评估过程的图」，旧标签「优秀仓」易混淆故改
    STASH_SEMI_TAB = "半成品仓"
    STASH_WASTE_TAB = "废图仓"
    STASH_FLAWED_TAB = "瑕疵仓"
    STASH_SWITCH_WAIT = "页签切换等待(ms)"
    STASH_FULL_THRESHOLD = "仓库满判定失败次数"

    # ==================== 通货管理选项卡 ====================
    CUR_BTN_CAL_ANCHOR = "通货仓原点指认"
    CUR_BTN_ADD = "添加通货"
    CUR_ANCHOR_LABEL = "原点X/Y(手动):"
    CUR_SEARCH_PLACEHOLDER = "搜索通货名称..."
    CUR_TBL_COL_NAME = "名称"
    CUR_TBL_COL_X = "相对X"
    CUR_TBL_COL_Y = "相对Y"
    CUR_TBL_COL_ACTION = "操作"
    CUR_ACT_RENAME = "重命名"
    CUR_ACT_DELETE = "删除"
    CUR_ACT_RECAL = "重新指认"

    # ==================== 制图策略选项卡 ====================
    STRAT_ENABLE_CORRUPT = "启用腐化流程"
    STRAT_ENABLE_WHITELIST = "启用白名单"
    STRAT_ENABLE_BLACKLIST = "启用黑名单"
    PARAM_IQ_ENABLE = "物品数量"
    PARAM_IQ_MIN = "≥"
    PARAM_RARITY_ENABLE = "稀有度"
    PARAM_RARITY_MIN = "≥"
    PARAM_PACK_ENABLE = "怪群规模"
    PARAM_PACK_MIN = "≥"
    PARAM_QUALITY_ENABLE = "地图品质"
    PARAM_QUALITY_MIN = "≥"
    CORRUPT_REGEX_LABEL = "腐化判定正则"
    CORRUPT_REGEX_TEST = "测试"
    BLACKLIST_LABEL = "黑名单词缀"
    WHITELIST_LABEL = "白名单词缀"
    CLIPBOARD_PREVIEW = "剪贴板原始内容"

    # ==================== 系统设置选项卡 ====================
    SYS_AUTOSTART = "开机启动"
    SYS_ALWAYS_ON_TOP = "总在最前"
    SYS_BTN_OPEN_LOGS = "打开日志目录"
    SYS_BTN_OPEN_CONFIG = "打开配置目录"
    SYS_BTN_OPEN_BACKUPS = "打开备份目录"
    SYS_BTN_MANUAL_BACKUP = "手动备份配置"
    SYS_BTN_GAME_CONFIG = "修改游戏配置"
    SYS_BTN_RESET_ALL = "重置所有配置"
    SYS_GRP_TAB_MGMT = "页签管理"
    SYS_TAB_VISIBLE_HINT = "取消勾选后对应页签将立即隐藏，重新勾选即可恢复"
    SYS_RESET_CONFIRM = "确定要重置所有配置吗？此操作不可撤销！"
    SYS_BTN_REINIT_CONFIG = "重新初始化配置"
    SYS_REINIT_CONFIRM = ("确定要重新初始化配置吗？\n"
                          "将清零运行统计、重建默认词缀（若为空）、重新换算坐标，"
                          "并需要重启程序后生效。")
    SYS_REINIT_DONE = "已重置首次启动标记，请重启程序以重跑初始化。"

    # ==================== 安全设置选项卡 ====================
    SAFE_BASE_DELAY = "基础延迟(ms)"
    SAFE_JITTER_MEAN = "正态分布均值 μ(ms)"
    SAFE_JITTER_STD = "正态分布标准差 σ(ms)"
    SAFE_BEZIER_ENABLE = "贝塞尔曲线轨迹"
    SAFE_BEZIER_POINTS = "控制点数"
    SAFE_SESSION_LIMIT = "会话上限"
    SAFE_PER_HOUR = "每小时上限"
    SAFE_PER_DAY = "每日上限"
    SAFE_CLIP_VALIDATE = "剪贴板校验"
    SAFE_CLIP_PREFIX = "校验前缀"
    SAFE_PREVIEW_CHART = "概率分布预览"

    # ==================== 关于选项卡 ====================
    ABOUT_VERSION = "程序版本"
    ABOUT_DESC = (
        "POE MapMaker 是一款针对《流放之路》地图制作流程的自动化工具，\n"
        "核心功能是替代人工重复操作，实现全流程自动化：\n"
        "- 背包自动扫描：逐格移动鼠标 → Ctrl+C复制 → 剪贴板校验\n"
        "- 稀有度识别：解析剪贴板内容，判定普通/魔法/稀有/传奇/已腐化\n"
        "- 通货自动应用：知识卷轴鉴定、点金石升级、重铸石重置、瓦尔宝珠腐化\n"
        "- 三级过滤：参数阈值 + 词缀白名单 + 词缀黑名单，均可独立开关\n"
        "- 分类存储：成品/优秀仓(半成品)/废图自动存入对应仓库页签\n"
        "- 操作模拟：贝塞尔曲线鼠标轨迹、随机延迟、会话频次上限\n"
        "- 多分辨率自适应：基于校准基准值动态换算，窗口移动/缩放后自动重算\n"
        "- 配置热加载：修改 poe_config.txt 即时生效，无需重启\n"
        "采用悬停复制 + 模拟键鼠架构，零内存读写。"
    )
    ABOUT_DISCLAIMER = (
        "[WARN] 免责声明\n"
        "继续使用即视为已知悉并接受以下全部条款：\n"
        "1. 用途限定：仅供个人学习、研究与技术交流，禁止商业目的或违反游戏服务条款的行为。\n"
        "2. 账号风险：可能违反《流放之路》用户协议，存在警告、临时封禁或永久封禁风险，使用者自行承担全部后果。\n"
        "3. 数据安全：本工具不收集、上传或传输任何用户数据，账号与配置文件保管责任归使用者。\n"
        "4. 软件现状：按'现状'提供，不附带任何明示或暗示保证，不保证所有环境下均能正常运行，但欢迎基于学习目的在社区友好交流，力所能及地分享经验与思路。\n"
        "5. 责任限制：法律允许范围内，开发者不对任何直接、间接或衍生损失承担责任。\n"
        "6. 第三方内容：不含任何游戏资源或受版权保护的内容，使用者应确保相关文件来源合法。\n"
        "7. 条款变更：开发者保留随时修改本声明的权利，修改后随软件发布即时生效。"
    )
    ABOUT_DEPENDENCIES = ""
    ABOUT_COORD_NOTE = (
        "项目发布帖与详细文档\n"
        "https://www.caimogu.cc/post/2495272.html"
    )

    # ==================== 通用 ====================
    BTN_OK = "确定"
    BTN_CANCEL = "取消"
    BTN_SAVE = "保存"
    BTN_CLOSE = "关闭"
    UNIT_MS = "ms"
    UNIT_PX = "px"
    RANGE_HINT = "有效范围: {} ~ {}"
    CALIBRATION_HINT = "校准模式进行中，按 {} 确认，按 ESC 取消"
    SESSION_PAUSED_TITLE = "会话上限暂停"
    SESSION_PAUSED_MSG = "已达到会话上限，将在 {} 秒后自动恢复"

    # ==================== 工作流编排（原语显示名） ====================
    # 键 = poe_workflow.workflow_model.PRIMITIVES 的英文键（数据 / 序列化 / 引擎
    # 校验永不为中文动）；值 = 仅显示层中文名。8 个非 legacy 名与
    # ui/tab_workflow.py 既有「操作类型」下拉保持一致，保证模块库 / 画布 /
    # 编辑器三处用词统一（单一事实源）。
    WF_PRIMITIVE_LABELS = {
        "click_anchor": "点击锚点",
        "move_to_anchor": "移动至锚点",
        "move_offset": "相对移动",
        "press_key": "按键",
        "read_clipboard": "读剪贴板",
        "copy": "复制",
        "wait_ms": "等待毫秒",
        "recall_cell": "回到当前格",
        "log": "打印日志",
        "abort": "中止方案",
        "use_currency": "使用通货",
        "record_session": "记录会话",
        "pause": "暂停等待",
        "store_to_stash": "存入仓库",
    }
    # 「新建步骤」下拉顺序（不含两个 legacy 原语 click_anchor / wait_ms，
    # 它们仅用于兼容旧 .json，不作为新建选项）
    WF_PRIMITIVE_DROPDOWN = ("move_to_anchor", "move_offset", "press_key",
                             "read_clipboard", "copy", "recall_cell", "log",
                             "abort", "use_currency", "record_session", "pause",
                             "store_to_stash")
    # read_clipboard 副标题里的剪贴板模式（mode 字段）
    WF_CLIP_MODE_LABELS = {"read": "读取", "match": "匹配"}

    @classmethod
    def get_primitive_label(cls, prim: str) -> str:
        """原语英文键 -> 中文显示名；未知键回退键本身（防御旧文件/新原语）。"""
        return cls.WF_PRIMITIVE_LABELS.get(prim, prim or "")

    # ==================== 状态机状态名中文化 ====================
    # 评估决策中文映射
    DECISION_LABELS = {
        "accept": "通过",
        "reject_param": "参数不达标",
        "reject_whitelist": "未命中白名单",
        "reject_blacklist": "命中黑名单",
        "corrupt_success": "腐化成功",
        "corrupt_fail_param": "腐化后参数不达标",
        "corrupt_fail_blacklist": "腐化后命中黑名单",
    }

    # 稀有度中文映射
    RARITY_LABELS = {
        "normal": "普通",
        "magic": "魔法",
        "rare": "稀有",
        "unique": "传奇",
        "unknown": "未知",
    }

    # 参数名中文映射
    PARAM_LABELS = {
        "item_quantity": "物品数量",
        "rarity": "物品稀有度",
        "pack_size": "怪群规模",
        "map_quality": "地图品质",
    }

    STATE_LABELS = {
        "IDLE": "待机",
        "STOPPED": "已停止",
        "CHECK_SESSION_LIMIT": "检查会话上限",
        "SCAN_BACKPACK": "扫描背包",
        "CLIPBOARD_VALIDATE": "剪贴板校验",
        "EVALUATE_RARITY": "识别稀有度",
        "YELLOW_FILTER": "黄图过滤",
        "WHITELIST_CHECK": "白名单检查",
        "BLACKLIST_CHECK": "黑名单检查",
        "CORRUPTION_DECIDE": "腐化决策",
        "CORRUPT_EXECUTE": "执行腐化",
        "POST_CORRUPT_CHECK": "腐化后检查",
        "STORE_RESULT": "存储结果",
        "BEZIER_MOVE": "贝塞尔移动",
        "NORMAL_DELAY": "常规延迟",
        "EVALUATION_GUARD": "评估守卫",
        "SESSION_PAUSED": "会话暂停",
    }

    @classmethod
    def get_state_label(cls, state_name: str) -> str:
        """将英文状态名转为中文显示标签"""
        return cls.STATE_LABELS.get(state_name, "运行中")

    @classmethod
    def get_stat_label(cls, key: str) -> str:
        """根据统计键名获取中文标签"""
        mapping = {
            "total_maps_processed": cls.STAT_TOTAL_PROCESSED,
            "total_yellow_maps": cls.STAT_YELLOW_MAPS,
            "total_corrupted_success": cls.STAT_CORRUPT_SUCCESS,
            "total_corrupted_fail": cls.STAT_CORRUPT_FAIL,
            "total_negative_maps": cls.STAT_NEGATIVE_MAPS,
        }
        return mapping.get(key, key)
