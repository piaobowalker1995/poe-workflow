# -*- coding: utf-8 -*-
"""待办1：工作流运行快捷键持久化到 poe_config.txt 的回归测试。

验证 ConfigManager.set/get 在 [Workflow]run_hotkey 上的往返与清除，
无需 PyQt5（纯配置层，沙箱可跑）。
"""
import pytest

from modules.config_manager import ConfigManager


def test_workflow_hotkey_persist_roundtrip(tmp_path):
    cfg = tmp_path / "poe_config.txt"
    cm = ConfigManager(str(cfg))
    cm.set("Workflow", "run_hotkey", "Ctrl+Shift+M")
    # flush 强制落盘（绕过 100ms 节流，与生产 tab 内 _persist_hotkey 行为一致）
    cm.flush()
    # 重新从磁盘打开，模拟应用重启
    cm2 = ConfigManager(str(cfg))
    assert cm2.get("Workflow", "run_hotkey", "") == "Ctrl+Shift+M"


def test_workflow_hotkey_clear(tmp_path):
    cfg = tmp_path / "poe_config.txt"
    cm = ConfigManager(str(cfg))
    cm.set("Workflow", "run_hotkey", "F5")
    cm.flush()
    assert cm.get("Workflow", "run_hotkey", "") == "F5"
    cm.set("Workflow", "run_hotkey", "")
    cm.flush()
    cm2 = ConfigManager(str(cfg))
    assert cm2.get("Workflow", "run_hotkey", "") == ""


def test_workflow_hotkey_default_empty(tmp_path):
    cfg = tmp_path / "poe_config.txt"
    cm = ConfigManager(str(cfg))
    # 未设置时返回空串（调用点默认值语义保持）
    assert cm.get("Workflow", "run_hotkey", "") == ""
