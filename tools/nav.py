"""调试：基于 OCR 的界面导航助手。

用法：
    python tools/nav.py dump [包名]           # OCR 打印当前画面文字
    python tools/nav.py tap <文字> [包名]      # 按文字点击（MaaFramework 处理缩放/多屏）
    python tools/nav.py shot [包名]            # 保存当前画面截图
"""

import sys
from datetime import datetime

from _base import BASE, build_stack, load_cfg, print_ocr


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    cfg = load_cfg()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dump"

    if cmd == "tap":
        text = sys.argv[2]
        pkg = sys.argv[3] if len(sys.argv) > 3 else cfg["campus"]["package"]
        adb, tasker, controller = build_stack(cfg, pkg)
        job = tasker.post_task("TapText", {"TapText": {"expected": [text]}})
        job.wait()
        print(f"tap '{text}': {job.status}")
        return 0 if job.succeeded else 2

    if cmd == "shot":
        pkg = sys.argv[2] if len(sys.argv) > 2 else cfg["campus"]["package"]
        adb, tasker, controller = build_stack(cfg, pkg)
        shot = controller.screencap()
        from PIL import Image

        out = BASE / "logs" / "shots" / f"{datetime.now():%Y%m%d_%H%M%S}_nav.png"
        Image.fromarray(shot).save(out)
        print("screenshot:", out, shot.shape)
        return 0

    pkg = sys.argv[2] if len(sys.argv) > 2 else cfg["campus"]["package"]
    adb, tasker, controller = build_stack(cfg, pkg)
    print_ocr(tasker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
