"""tools 公共：配置加载与 MaaFramework/控制器初始化（避免各脚本重复样板）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from maa.resource import Resource  # noqa: E402
from maa.tasker import Tasker  # noqa: E402

from maa_campus.adb import Adb  # noqa: E402
from maa_campus.controller import MuMuAdbController  # noqa: E402


def load_cfg() -> dict:
    with open(BASE / "config.json", "r", encoding="utf-8-sig") as f:
        return json.load(f)


def build_stack(cfg: dict, package: str):
    """连接 adb、加载资源、绑定控制器，返回 (adb, tasker, controller)。"""
    adb = Adb(cfg["adb_path"], cfg["adb_serial"])
    if not adb.connect(wait_seconds=10):
        raise SystemExit("adb 连接失败")
    resource = Resource()
    resource.post_bundle(str(BASE / "assets" / "resource")).wait()
    controller = MuMuAdbController(adb, package)
    controller.post_connection().wait()
    tasker = Tasker()
    tasker.bind(resource, controller)
    return adb, tasker, controller


def print_ocr(tasker) -> None:
    """打印当前画面 OCR 文本与坐标。"""
    job = tasker.post_task("Probe", {"Probe": {"expected": [".+"]}})
    job.wait()
    detail = job.get()
    if detail is None:
        return
    for node in detail.nodes:
        reco = node.recognition
        if reco is None:
            continue
        for r in (reco.all_results or []):
            text = getattr(r, "text", None)
            if text and text.strip():
                print(f"{getattr(r, 'box', None)}\t{text}")
