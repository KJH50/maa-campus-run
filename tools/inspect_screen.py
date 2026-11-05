"""调试：对指定包名当前画面做 OCR，打印识别到的文字与坐标。

用法：python tools/inspect_screen.py <包名> [截图前缀]
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
    pkg = sys.argv[1] if len(sys.argv) > 1 else "yx.c520.xyz"
    adb, tasker, controller = build_stack(cfg, pkg)
    shot = controller.screencap()
    out_dir = BASE / "logs" / "shots"
    out_dir.mkdir(parents=True, exist_ok=True)
    from PIL import Image

    shot_path = out_dir / f"{datetime.now():%Y%m%d_%H%M%S}_inspect.png"
    Image.fromarray(shot).save(shot_path)
    print("screenshot:", shot_path, shot.shape)
    print_ocr(tasker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
