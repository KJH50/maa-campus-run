"""模拟器生命周期：adb 连接、按配置拉起 / 重启 / 关闭 MuMu 实例。

另含「窗口刷新」：MuMu 以 window_save_rect=true 恢复上次窗口位置/大小，
且 Vulkan 渲染器在程序化拉起（尤其来自计划任务/隐藏会话）时偶发画面错位，
手动改变窗口大小即可恢复。这里在连接/启动完成后用 Win32 对窗口做一次
「缩小 1px 再恢复」的 nudge（等同手动拖拽窗口边缘），强制重建渲染表面。
"""

from __future__ import annotations

import ctypes
import json
import logging
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from .adb import Adb

DEFAULT_BOOT_TIMEOUT = 300

_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SW_RESTORE = 9


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


def _mumu_info(manager: str, index) -> dict:
    """读取实例信息（含 main_wnd/render_wnd、运行状态）；失败返回空字典。"""
    try:
        p = subprocess.run([manager, "info", "-v", str(index)],
                           capture_output=True, timeout=60)
        if p.returncode != 0:
            return {}
        data = json.loads((p.stdout or b"").decode("utf-8", "replace") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _instance_running(info: dict) -> bool:
    """根据 info 判断 Android 引擎是否已在运行。"""
    if not info:
        return False
    if str(info.get("state") or "").lower() in ("start_finished", "running"):
        return True
    return bool(info.get("is_android_started") or info.get("is_process_started"))


def _nudge_window(handle: int, logger: logging.Logger) -> bool:
    """对窗口做一次「宽 -1px → 恢复」刷新；仅 Windows 有效，失败忽略。"""
    if not handle:
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(int(handle))
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            return False
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, _SW_RESTORE)
        flags = _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE
        user32.SetWindowPos(hwnd, None, 0, 0, max(1, width - 1), height, flags)
        time.sleep(0.2)
        user32.SetWindowPos(hwnd, None, 0, 0, width, height, flags)
        logger.info("已刷新模拟器窗口（%dx%d）", width, height)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("刷新模拟器窗口失败（已忽略）：%s", e)
        return False


def _refresh_player_window(manager: str, index, logger: logging.Logger) -> bool:
    """显示并刷新实例窗口，修复 MuMu 启动后画面错位（需手动改窗口大小才恢复的问题）。"""
    _mumu_control(str(manager), index, "show_window", logger)
    info = _mumu_info(str(manager), index)
    handle = info.get("main_wnd") or info.get("mainWindowHandle") or 0
    try:
        handle = int(str(handle), 16) if isinstance(handle, str) else int(handle)
    except (TypeError, ValueError):
        handle = 0
    if not handle:
        logger.info("未获取到 MuMu 窗口句柄，跳过窗口刷新")
        return False
    time.sleep(0.3)
    return _nudge_window(handle, logger)


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


def _refresh_if_enabled(cfg: dict, manager, index, logger: logging.Logger) -> None:
    if manager and index is not None and cfg.get("refresh_window_on_start", True):
        _refresh_player_window(str(manager), index, logger)


def ensure_emulator(cfg: dict, adb: Adb, logger: logging.Logger) -> bool:
    """连接模拟器；连不上时按配置拉起 MuMu，冷启动轮询到就绪或超时，失败时重启实例一次。"""
    manager = cfg.get("mumu_manager")
    index = cfg.get("mumu_index")
    if adb.connect(wait_seconds=5):
        # 已连接（可能由 oneclick/计划任务刚拉起）：仍做一次窗口刷新，修复画面错位
        _refresh_if_enabled(cfg, manager, index, logger)
        return True

    boot_timeout = float(cfg.get("emulator_boot_timeout_seconds", DEFAULT_BOOT_TIMEOUT))
    can_manage = bool(manager and index is not None and Path(str(manager)).exists())
    if not can_manage:
        logger.info("未配置可用的 mumu_manager，直接等待 adb 连接 ...")
        return adb.connect(wait_seconds=min(boot_timeout, 60))

    # 已在运行但 adb 尚未就绪时不要再重复 launch（重复拉起会加重窗口/渲染错位）
    info = _mumu_info(str(manager), index)
    if _instance_running(info):
        logger.info("MuMu 实例 %s 已在运行，仅等待 adb 就绪（不重复 launch）...", index)
        if _wait_boot(adb, logger, boot_timeout):
            logger.info("模拟器已就绪")
            _refresh_if_enabled(cfg, manager, index, logger)
            return True
        logger.warning("实例已在运行但 %.0f 秒内 adb 仍未就绪", boot_timeout)
    else:
        logger.info("模拟器未连接，尝试启动 MuMu 实例 %s（冷启动最长等待 %.0f 秒）...",
                    index, boot_timeout)
        _mumu_control(str(manager), index, "launch", logger)
        if _wait_boot(adb, logger, boot_timeout):
            logger.info("模拟器已就绪")
            _refresh_if_enabled(cfg, manager, index, logger)
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
        _refresh_if_enabled(cfg, manager, index, logger)
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
