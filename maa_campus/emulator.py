"""模拟器生命周期：adb 连接、按配置拉起 / 重启 / 关闭 MuMu 实例。"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from .adb import Adb

DEFAULT_BOOT_TIMEOUT = 300


def make_adb(cfg: dict) -> Adb:
    """按配置创建 adb 封装。"""
    return Adb(cfg["adb_path"], cfg["adb_serial"])


def _mumu_control(manager: str, index, action: str, logger: logging.Logger) -> bool:
    """调用 MuMuManager 控制实例，返回是否成功（兼容 JSON errcode 返回）。"""
    try:
        p = subprocess.run([manager, "control", "-v", str(index), action],
                           capture_output=True, timeout=120)
    except Exception as e:  # noqa: BLE001
        logger.warning("MuMu %s 调用异常（已忽略）：%s", action, e)
        return False
    text = (p.stdout or b"").decode("utf-8", "replace").strip()
    ok = (p.returncode == 0)
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if "errcode" in data:
                ok = (data.get("errcode") == 0)
        except Exception:  # noqa: BLE001
            pass
    if not ok:
        logger.warning("MuMu %s 返回失败（返回码 %s）：%s", action, p.returncode, text[:200])
    return ok


def _wait_boot(adb: Adb, logger: logging.Logger, timeout: float) -> bool:
    """轮询等待模拟器 boot_completed（adb.connect 内部会检查 sys.boot_completed）。"""
    deadline = time.time() + max(1.0, timeout)
    next_log = time.time() + 15
    while time.time() < deadline:
        if adb.connect(wait_seconds=5):
            return True
        now = time.time()
        if now >= next_log:
            logger.info("等待模拟器启动完成（约剩 %d 秒）...", max(0, int(deadline - now)))
            next_log = now + 15
        time.sleep(2)
    return False


def ensure_emulator(cfg: dict, adb: Adb, logger: logging.Logger) -> bool:
    """连接模拟器；连不上时按配置拉起 MuMu，冷启动轮询到就绪或超时，失败时重启实例一次。"""
    if adb.connect(wait_seconds=5):
        return True

    manager = cfg.get("mumu_manager")
    index = cfg.get("mumu_index")
    boot_timeout = float(cfg.get("emulator_boot_timeout_seconds", DEFAULT_BOOT_TIMEOUT))
    can_manage = bool(manager and index is not None and Path(str(manager)).exists())
    if not can_manage:
        logger.info("未配置可用的 mumu_manager，直接等待 adb 连接 ...")
        return adb.connect(wait_seconds=min(boot_timeout, 60))

    logger.info("模拟器未连接，尝试启动 MuMu 实例 %s（冷启动最长等待 %.0f 秒）...",
                index, boot_timeout)
    _mumu_control(str(manager), index, "launch", logger)
    if _wait_boot(adb, logger, boot_timeout):
        logger.info("模拟器已就绪")
        return True

    logger.warning("启动后 %.0f 秒内模拟器仍未就绪", boot_timeout)
    if not cfg.get("emulator_restart_on_fail", True):
        return False

    logger.info("尝试重启 MuMu 实例 %s（shutdown → launch）后再次等待 ...", index)
    _mumu_control(str(manager), index, "shutdown", logger)
    time.sleep(5)
    _mumu_control(str(manager), index, "launch", logger)
    if _wait_boot(adb, logger, boot_timeout):
        logger.info("重启后模拟器已就绪")
        return True
    logger.error("重启后模拟器仍未能就绪，放弃本次连接")
    return False


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
    if not manager or index is None or not Path(str(manager)).exists():
        logger.info("未配置可用的 mumu_manager，跳过关闭模拟器")
        return
    try:
        logger.info("关闭 MuMu 模拟器（实例 %s）...", index)
        ok = _mumu_control(str(manager), index, "shutdown", logger)
        if ok:
            logger.info("模拟器关闭：完成")
    except Exception as e:  # noqa: BLE001
        logger.warning("关闭模拟器异常（已忽略）：%s", e)
