"""模拟器生命周期：adb 连接、按配置拉起 / 关闭 MuMu 实例。"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .adb import Adb


def make_adb(cfg: dict) -> Adb:
    """按配置创建 adb 封装。"""
    return Adb(cfg["adb_path"], cfg["adb_serial"])


def ensure_emulator(cfg: dict, adb: Adb, logger: logging.Logger) -> bool:
    """连接模拟器；连不上时按配置尝试拉起 MuMu 实例。"""
    if adb.connect(wait_seconds=5):
        return True
    manager = cfg.get("mumu_manager")
    index = cfg.get("mumu_index")
    if manager and Path(manager).exists():
        logger.info("模拟器未连接，尝试启动 MuMu 实例 %s ...", index)
        subprocess.run([manager, "control", "-v", str(index), "launch"], capture_output=True, timeout=120)
        return adb.connect(wait_seconds=180)
    return adb.connect(wait_seconds=60)


def shutdown_emulator(cfg: dict, logger: logging.Logger) -> None:
    """成功跑完并关闭 App 后关闭 MuMu 模拟器（config.shutdown_emulator=false 可关闭本行为）。"""
    if not cfg.get("shutdown_emulator", True):
        logger.info("按配置不关闭模拟器（shutdown_emulator=false）")
        return
    if not cfg.get("close_apps", True):
        logger.info("close_apps=false，保留模拟器运行")
        return
    manager = cfg.get("mumu_manager")
    index = cfg.get("mumu_index")
    if not manager or index is None or not Path(manager).exists():
        logger.info("未配置可用的 mumu_manager，跳过关闭模拟器")
        return
    try:
        logger.info("关闭 MuMu 模拟器（实例 %s）...", index)
        p = subprocess.run([str(manager), "control", "-v", str(index), "shutdown"],
                           capture_output=True, timeout=120)
        text = (p.stdout or b"").decode("utf-8", "replace").strip()
        ok = (p.returncode == 0)
        if text.startswith("{"):
            try:
                import json as _json

                data = _json.loads(text)
                if "errcode" in data:
                    ok = (data.get("errcode") == 0)
            except Exception:
                pass
        if ok:
            logger.info("模拟器关闭：完成")
        else:
            logger.warning("模拟器关闭：失败（返回码 %s）：%s", p.returncode, text[:200])
    except Exception as e:  # noqa: BLE001
        logger.warning("关闭模拟器异常（已忽略）：%s", e)
