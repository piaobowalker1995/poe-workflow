# -*- coding: utf-8 -*-
"""pytest 全局夹具（poe-mapmaker v3.0.30 回归基线）

职责：
  1. 把仓库根加入 sys.path，测试文件可直接 import modules.* / ui.*
  2. 强制 Qt 走 offscreen 平台，无显示环境下也能构造控件
  3. 用仓库 poe_config.txt 的**临时副本**构造 ConfigManager —— 绝不写仓库原文件
  4. 提供 ConfigManager→CoordinateEngine→InputSimulator→AffixParser→StateMachine
     的完整依赖链夹具（与 main.py 的真实装配顺序一致）

问题编号遵循 poe_ai_rules.md 注意5（V{版本}-{类别}-{序号}），
用例内以 docstring 标注迁移来源与台账编号。
"""
import os
import shutil
import sys
from types import SimpleNamespace

import pytest

REPO_ROOT = os.environ.get("POE_MAPMAKER_ROOT", r"E:\AIProgram\poe-mapmaker")
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# 必须在任何 QApplication 构造之前设置：
# Qt 平台插件在 QApplication 构造期解析，import 期不读该变量。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 只读使用的仓库原始配置；所有测试都基于它的临时副本，禁止直接写入。
REAL_CONFIG = os.path.join(REPO_ROOT, "poe_config.txt")

# ── 防御：禁止任何测试写真实 poe_config.txt（防偶发污染用户真实配置）──
import traceback as _tb
from modules.config_manager import ConfigManager as _CM
_orig_atomic_save = _CM._atomic_save
def _guarded_atomic_save(self):
    if os.path.abspath(self._config_path) == os.path.abspath(REAL_CONFIG):
        _tb.print_stack()
        raise RuntimeError(
            f"[测试隔离守卫] 拦截到对真实配置文件 {self._config_path} 的写盘，"
            f"已阻止。此调用暴露测试隔离缺陷，需修复调用方。"
        )
    return _orig_atomic_save(self)
_CM._atomic_save = _guarded_atomic_save


def make_temp_config(dst_dir: str) -> str:
    """把仓库 poe_config.txt 复制到 dst_dir，返回副本绝对路径。

    V3031-QF-003：复制后**按纯文本**剥离运行期用户数据段 [QuickFilter]。
    开发者本机的 poe_config.txt 常带有个人快捷筛选配置（甚至是旧版预置的名字，
    如「物品数量0~79」），原样拷贝会让依赖「空配置 -> 注入 5 条预置」的用例
    失真（filter_count 读到 6 而非 5）。测试基线必须确定，不能随本机配置漂移。

    ⚠️ 必须用纯文本处理，不能用 configparser 读原文件：poe_config.txt 含词缀段等
    原始文本行（如「几率避免元素异常」这类无 key=value 的行），configparser 直接读会
    ParsingError；ConfigManager 是自行 _strip_affix_sections() 之后才交给它解析的。
    """
    dst = os.path.join(dst_dir, "poe_config.txt")
    shutil.copy2(REAL_CONFIG, dst)
    _VOLATILE_SECTIONS = ("[QuickFilter]",)
    with open(dst, "r", encoding="utf-8") as _f:
        lines = _f.readlines()
    out, skipping = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if stripped in _VOLATILE_SECTIONS:
                skipping = True
                continue      # 连段头一起丢弃
            skipping = False
        if skipping:
            continue
        out.append(line)
    with open(dst, "w", encoding="utf-8") as _f:
        _f.writelines(out)
    return dst


def build_stack(config_path: str) -> SimpleNamespace:
    """按 main.py:349-352 的真实装配顺序构建完整依赖链。"""
    from modules.config_manager import ConfigManager
    from modules.coordinate_engine import CoordinateEngine
    from modules.input_simulator import InputSimulator
    from modules.affix_parser import AffixParser
    from modules.state_machine import StateMachine

    cm = ConfigManager(config_path)
    coord = CoordinateEngine(cm.get)
    inp = InputSimulator(cm.get)
    parser = AffixParser(cm.get, cm)
    fsm = StateMachine(cm.get, inp, coord, parser, cm)
    return SimpleNamespace(cm=cm, coord=coord, inp=inp, parser=parser, fsm=fsm)


def teardown_stack(stack: SimpleNamespace) -> None:
    """释放热键监听等系统资源（顺序与 main.py 的 _cleanup_targets 一致）。"""
    for target in (stack.fsm.stop, stack.inp.stop):
        try:
            target()
        except Exception:
            pass


@pytest.fixture
def config_manager(tmp_path):
    """裸 ConfigManager：基于 poe_config.txt 的临时副本构造。"""
    from modules.config_manager import ConfigManager
    return ConfigManager(make_temp_config(str(tmp_path)))


@pytest.fixture
def stack(tmp_path):
    """函数级完整依赖链。每个用例一份独立临时配置，用例间零串扰。"""
    st = build_stack(make_temp_config(str(tmp_path)))
    yield st
    teardown_stack(st)


@pytest.fixture(scope="module")
def ui_stack(tmp_path_factory):
    """模块级依赖链：MainWindow 构造成本高（含 QThread + 热键注册），
    同模块内的 UI 用例复用一个实例，避免反复启停热键监听。"""
    st = build_stack(make_temp_config(str(tmp_path_factory.mktemp("poemap_ui"))))
    yield st
    teardown_stack(st)
