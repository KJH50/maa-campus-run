"""MaaFramework 资源加载、控制器绑定与 OCR 原语。"""

from __future__ import annotations

import logging
from pathlib import Path

from .tasks import post_and_wait

BASE = Path(__file__).resolve().parent.parent
ASSETS = BASE / "assets" / "resource"

SETTLE_MARKERS = [
    "上传成功", "提交成功", "已上传", "结算成功", "保存成功",
    "上传完成", "提交完成", "本次跑步已完成", "我的数据",
]


def build_tasker(cfg: dict, adb, logger: logging.Logger):
    """加载资源并绑定控制器，返回 (tasker, controller) 或 (None, None)。"""
    from maa.resource import Resource
    from maa.tasker import Tasker

    from .controller import MuMuAdbController

    resource = Resource()
    job = resource.post_bundle(str(ASSETS))
    job.wait()
    if not job.succeeded:
        logger.error("资源加载失败：%s", ASSETS)
        return None, None

    controller = MuMuAdbController(adb, cfg["campus"]["package"])
    conn = controller.post_connection()
    conn.wait()
    if not conn.succeeded:
        logger.error("控制器连接失败")
        return None, None

    tasker = Tasker()
    if not tasker.bind(resource, controller):
        logger.error("Tasker 绑定失败")
        return None, None
    try:
        tasker.set_stdout_level(2)
    except Exception:
        pass
    return tasker, controller


def ocr_probe(tasker, patterns: list[str]) -> bool:
    """OCR 探测：命中任意一个正则即返回 True（不点击）。"""
    job = post_and_wait(tasker, "Probe", {"Probe": {"expected": patterns}})
    return job.succeeded


def ocr_tap(tasker, patterns: list[str]) -> bool:
    """OCR 定位并点击命中的文字。"""
    job = post_and_wait(tasker, "TapText", {"TapText": {"expected": patterns}})
    return job.succeeded
