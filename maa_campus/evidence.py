"""执行证据：按阶段保存截图（并行模式下文件名带实例标识，避免互相覆盖）。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "shots"

_SAFE_RE = re.compile(r"[^0-9A-Za-z_.-]+")


def _instance_suffix(controller, logger: logging.Logger) -> str:
    """并行子进程的 logger 名为 campus.<instance>，据此给截图名加实例标识。"""
    name = getattr(logger, "name", "") or ""
    if "." in name:
        return _SAFE_RE.sub("_", name.split(".", 1)[1]).strip("_")
    adb = getattr(controller, "adb", None)
    serial = str(getattr(adb, "serial", "") or "")
    if serial and ":" in serial:
        return _SAFE_RE.sub("-", serial.rsplit(":", 1)[1]).strip("-")
    return ""


def save_shot(controller, tag: str, logger: logging.Logger):
    """保存当前焦点 App 的画面作为执行证据，返回路径（失败返回 None）。"""
    try:
        shot = controller.screencap()
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        suffix = _instance_suffix(controller, logger)
        stem = f"{datetime.now():%Y%m%d_%H%M%S}_{tag}"
        path = SHOT_DIR / (f"{stem}_{suffix}.png" if suffix else f"{stem}.png")
        from PIL import Image

        Image.fromarray(shot).save(path)
        logger.info("证据截图：%s（%sx%s）", path, shot.shape[1], shot.shape[0])
        return path
    except Exception as e:
        logger.warning("截图失败（%s）：%s", tag, e)
        return None
