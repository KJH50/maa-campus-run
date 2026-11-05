"""调试：启动 RunSimulation 跑步模拟，然后打开健行校园并打印跑动中的界面。

用法：python tools/prepare_run.py
"""

import sys
import time
from datetime import datetime

from _base import BASE, build_stack, load_cfg, print_ocr


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cfg = load_cfg()
    adb, tasker, controller = build_stack(cfg, cfg["run"]["package"])

    # RunPrepare：打开 RunSimulation 并确认「标准」路线；RunStart：点击开始跑步
    for entry in ("RunPrepare", "RunStart"):
        job = tasker.post_task(entry)
        job.wait()
        print(f"{entry}:", job.status)
        if not job.succeeded:
            return 1

    # 打开健行校园并停留，截图 + OCR
    controller.focus_package = cfg["campus"]["package"]
    adb.start_app(cfg["campus"]["activity"])
    time.sleep(6)

    shot = controller.screencap()
    from PIL import Image

    out = BASE / "logs" / "shots" / f"{datetime.now():%Y%m%d_%H%M%S}_running.png"
    Image.fromarray(shot).save(out)
    print("screenshot:", out, shot.shape)
    print_ocr(tasker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
