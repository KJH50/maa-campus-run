"""执行证据：按阶段保存截图。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

SHOT_DIR = Path(__file__).resolve().parent.parent / "logs" / "shots"


def save_shot(controller, tag: str, logger: logging.Logger):
    """保存当前焦点 App 的画面作为执行证据，返回路径（失败返回 None）。"""
    try:
        shot = controller.screencap()
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SHOT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{tag}.png"
        from PIL import Image

        Image.fromarray(shot).save(path)
        logger.info("证据截图：%s（%sx%s）", path, shot.shape[1], shot.shape[0])
        return path
    except Exception as e:
        logger.warning("截图失败（%s）：%s", tag, e)
        return None
