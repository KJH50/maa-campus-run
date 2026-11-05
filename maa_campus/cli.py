"""命令行入口：参数解析、日志、配置校验、日志清理、定时等待、OCR 自检。"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from .alerts import send_alert
from .config import load_config, validate_config
from .emulator import ensure_emulator, make_adb
from .evidence import save_shot
from .flow import run_flow
from .maa_tasks import build_tasker
from .tasks import post_and_wait

BASE = Path(__file__).resolve().parent.parent


def setup_logger(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("campus")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    fh = logging.FileHandler(log_dir / f"run_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def cleanup_old_logs(cfg: dict, logger: logging.Logger) -> None:
    """按 config.log_retention_days 清理旧的截图/入口日志（<=0 表示不清理）。"""
    days = int(cfg.get("log_retention_days", 0) or 0)
    if days <= 0:
        return
    cutoff = datetime.now() - timedelta(days=days)
    root = BASE / cfg.get("log_dir", "logs")
    removed = 0
    for sub in ("shots", "oneclick"):
        d = root / sub
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if not f.is_file():
                continue
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    f.unlink()
                    removed += 1
            except OSError:
                pass
    if removed:
        logger.info("已清理 %s 天前的截图/日志 %s 个", days, removed)


def wait_until(hhmm: str, logger: logging.Logger) -> None:
    """等到当天的 HH:MM（已过则等到明天）。"""
    h, m = (int(x) for x in hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    logger.info("等待到 %s（还有 %.1f 分钟）", target.strftime("%Y-%m-%d %H:%M"),
                (target - now).total_seconds() / 60)
    while datetime.now() < target:
        time.sleep(min(30, max(1, (target - datetime.now()).total_seconds())))


def cmd_probe(cfg: dict, logger: logging.Logger, text: str, focus: str | None,
              save_shot_flag: bool) -> int:
    """OCR 自检：识别指定文字后退出。"""
    adb = make_adb(cfg)
    if not ensure_emulator(cfg, adb, logger):
        logger.error("无法连接模拟器 %s", cfg["adb_serial"])
        return 1
    tasker, controller = build_tasker(cfg, adb, logger)
    if tasker is None:
        return 1
    controller.focus_package = focus or cfg["campus"]["package"]
    if save_shot_flag:
        save_shot(controller, "probe", logger)
    job = post_and_wait(tasker, "Probe", {"Probe": {"expected": [text]}})
    ok = job.succeeded
    logger.info("OCR 探测「%s」：%s", text, "命中" if ok else "未命中")
    return 0 if ok else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="校园跑自动值守（MaaFramework，距离触发）")
    parser.add_argument("--config", default=str(BASE / "config.json"))
    parser.add_argument("--now", action="store_true", help="立即执行")
    parser.add_argument("--at", default=None, help="指定时间 HH:MM（覆盖 config.start_time）")
    parser.add_argument("--dry", action="store_true", help="安全演练：只截图/识别距离，不点击任何按钮")
    parser.add_argument("--probe", default=None, help="OCR 自检：识别指定文字后退出")
    parser.add_argument("--focus", default=None, help="--probe 时指定焦点包名")
    parser.add_argument("--screenshot", action="store_true", help="--probe 时保存截图")
    parser.add_argument("--wait-finish", action="store_true", help="跳过启动步骤，只等待距离达标后结束（已手动开跑时用）")
    parser.add_argument("--test-alert", action="store_true", help="发送一条测试告警后退出")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    logger = setup_logger(BASE / cfg.get("log_dir", "logs"))

    try:
        validate_config(cfg)
    except ValueError as e:
        logger.error("配置校验失败：%s", e)
        return 1

    cleanup_old_logs(cfg, logger)

    if args.test_alert:
        ok = send_alert(cfg, logger, "test", "校园跑值守：测试告警",
                        "这是一条测试消息，收到即表示告警通道配置正确。", force=True)
        return 0 if ok else 1

    try:
        if args.probe:
            return cmd_probe(cfg, logger, args.probe, args.focus, args.screenshot)

        if not args.now:
            wait_until(args.at or cfg["start_time"], logger)

        logger.info("===== 开始执行（%s）=====", "dry 演练" if args.dry else "完整流程")
        code = run_flow(cfg, logger, args.dry, skip_start=args.wait_finish)
        logger.info("===== 结束，退出码 %s =====", code)
        return code
    except Exception as e:
        logger.error("执行异常：%s", e)
        import traceback

        logger.error(traceback.format_exc())
        send_alert(cfg, logger, "exception", "校园跑值守：执行异常", f"{type(e).__name__}: {e}")
        return 1
