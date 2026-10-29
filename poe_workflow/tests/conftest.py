# -*- coding: utf-8 -*-
"""pytest 全局夹具（poe-workflow 自包含基线，不依赖 poe-mapmaker / POE_MAPMAKER_ROOT）

职责：
  1. 把仓库内 tests/_stubs 加入 sys.path 最前，使 `import modules.*` / `import ui.*`
     解析到仓库内的桩实现，而不是宿主机上的 poe-mapmaker。
  2. 强制 Qt 走 offscreen 平台，无显示环境下也能构造控件。
  3. 用 _stubs/poe_config.txt 的**临时副本**构造 ConfigManager —— 绝不写原文件。
  4. 提供 ConfigManager→CoordinateEngine→InputSimulator→AffixParser→StateMachine
     的完整依赖链夹具（与 main.py 的真实装配顺序一致），全部来自桩 modules。

迁移说明（Task #171）：原实现把 poe-mapmaker 仓库根加入 sys.path 并直接 import
modules.* / ui.*；现全部由 _stubs/modules、_stubs/ui 提供，POE_MAPMAKER_ROOT 已移除。
"""
import os
import shutil
import sys
from types import SimpleNamespace

import pytest

# ── 自包含桩路径：必须在本文件任何 `import modules` / `import ui` 之前插入 ──
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STUBS_DIR = os.path.join(_THIS_DIR, "_stubs")


def _to_native(path):
    """Windows 下把 MSYS/Git-Bash 风格的 /e/foo 归一为 E:/foo，
    使深层目录也能被 import 可靠解析（不同运行环境的路径形式不统一）。"""
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == "/":
        return f"{path[1].upper()}:/{path[3:]}"
    return path


_STUBS_DIR = _to_native(_STUBS_DIR)
if _STUBS_DIR not in sys.path:
    sys.path.insert(0, _STUBS_DIR)

# 必须在任何 QApplication 构造之前设置：
# Qt 平台插件在 QApplication 构造期解析，import 期不读该变量。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 只读使用的桩自带配置；所有测试都基于它的临时副本，禁止直接写入。
REAL_CONFIG = os.path.join(_STUBS_DIR, "poe_config.txt")

# ── 防御：禁止任何测试写真实桩配置文件（防偶发污染）──
import traceback as _tb
from modules.config_manager import ConfigManager as _CM
_orig_atomic_save = _CM._atomic_save
def _guarded_atomic_save(self):
    if self._config_path is not None and \
       os.path.abspath(self._config_path) == os.path.abspath(REAL_CONFIG):
        _tb.print_stack()
        raise RuntimeError(
            f"[测试隔离守卫] 拦截到对真实配置文件 {self._config_path} 的写盘，"
            f"已阻止。此调用暴露测试隔离缺陷，需修复调用方。"
        )
    return _orig_atomic_save(self)
_CM._atomic_save = _guarded_atomic_save


def make_temp_config(dst_dir: str) -> str:
    """把桩 poe_config.txt 复制到 dst_dir，返回副本绝对路径。

    V3031-QF-003：复制后**按纯文本**剥离运行期用户数据段 [QuickFilter]。
    （桩自带配置不含该段，此逻辑保留以兼容未来换入更完整的配置副本。）
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
    """按 main.py 的真实装配顺序构建完整依赖链（全部来自桩 modules）。"""
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
    """裸 ConfigManager：基于桩 poe_config.txt 的临时副本构造。"""
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
