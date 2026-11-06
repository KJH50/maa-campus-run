"""命令行入口：参数解析、日志、配置校验、日志清理、定时等待、OCR 自检。"""

from __future__ import annotations

import argparse
import logging
import os
import re
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
from .schedule import all_windows, resolve_target
from .tasks import post_and_wait

BASE = Path(__file__).resolve().parent.parent


def setup_logger(log_dir: Path, suffix: str | None = None) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    name = f"campus.{suffix}" if suffix else "campus"
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    date_txt = f"{datetime.now():%Y%m%d}"
    safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", suffix) if suffix else ""
    fmt_txt = "%(asctime)s [%(levelname)s] %(message)s"
    stream_fmt = logging.Formatter(fmt_txt, "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(stream_fmt)
    logger.addHandler(sh)
    file_name = f"run_{date_txt}{('_' + safe) if safe else ''}.log"
    fh = logging.FileHandler(log_dir / file_name, encoding="utf-8")
    file_fmt = logging.Formatter((f"[{safe}] " if safe else "") + fmt_txt, "%Y-%m-%d %H:%M:%S")
    fh.setFormatter(file_fmt)
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


def wait_until_dt(target: datetime, logger: logging.Logger) -> None:
    """等待到指定时间点（可能已过，此时立即返回）。"""
    now = datetime.now()
    if target > now:
        logger.info("等待到 %s（还有 %.1f 分钟）", target.strftime("%Y-%m-%d %H:%M"),
                    (target - now).total_seconds() / 60)
    while datetime.now() < target:
        time.sleep(min(30, max(1, (target - datetime.now()).total_seconds())))


def wait_until(hhmm: str, logger: logging.Logger) -> None:
    """等到当天的 HH:MM（已过则等到明天）。"""
    h, m = (int(x) for x in hhmm.split(":"))
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    wait_until_dt(target, logger)


def run_window_once(cfg: dict, logger: logging.Logger, log_dir: Path, run_once,
                    now_fn=datetime.now, sleep_fn=time.sleep) -> int:
    """DSH 兼容模式：本次触发只处理当前（或下一个）时间段，执行一次后退出。

    DSH 定时任务无法生成随机时间，可在每个时间段起点附近触发，
    本函数负责在区间内随机等待、执行一次并记录该时间段完成状态。
    """
    from .schedule import ensure_windows_state, save_windows_state, window_key

    bounds_list = all_windows(cfg)
    if not bounds_list:
        logger.error("未配置 run_windows，--window-once 需要先配置时间段")
        return 1

    now = now_fn()
    day = now.date()
    active = None
    upcoming = None
    for bounds in bounds_list:
        (h1, m1), (h2, m2) = bounds
        start_dt = now.replace(hour=h1, minute=m1, second=0, microsecond=0)
        end_dt = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
        if start_dt <= now <= end_dt:
            active = (bounds, start_dt, end_dt)
            break
        if start_dt > now and upcoming is None:
            upcoming = (bounds, start_dt, end_dt)

    if active is None:
        if upcoming is None:
            logger.info("今日所有时间段已结束（当前 %s），无待执行时间段", now.strftime("%H:%M"))
            return 0
        bounds, start_dt, end_dt = upcoming
        key = window_key(bounds)
        logger.info("当前不在时间段内，等待下一个时间段 %s 开始（%s）", key, start_dt.strftime("%H:%M"))
        while now_fn() < start_dt:
            sleep_fn(min(30, max(1, (start_dt - now_fn()).total_seconds())))
    else:
        bounds, start_dt, end_dt = active

    key = window_key(bounds)
    state = ensure_windows_state(cfg, day, log_dir)
    entry = state.get(key) or {}
    if entry.get("done"):
        logger.info("时间段 %s 今日已完成，跳过", key)
        return 0
    if entry.get("missed"):
        logger.info("时间段 %s 已标记错过，跳过", key)
        return 0

    target_txt = str(entry.get("target") or f"{bounds[0][0]:02d}:{bounds[0][1]:02d}")
    th, tm = (int(x) for x in target_txt.split(":"))
    now = now_fn()
    target_dt = now.replace(hour=th, minute=tm, second=0, microsecond=0)
    if now > end_dt:
        entry["missed"] = True
        state[key] = entry
        save_windows_state(log_dir, day, state)
        logger.warning("时间段 %s 已结束，跳过", key)
        return 0
    if target_dt > now:
        logger.info("时间段 %s：随机执行时间 %s，等待中 ...", key, target_txt)
        while now_fn() < target_dt:
            sleep_fn(min(30, max(1, (target_dt - now_fn()).total_seconds())))

    logger.info("时间段 %s：开始执行（计划时间 %s）", key, target_txt)
    code = run_once()
    if code == 0:
        entry["done"] = True
    state[key] = entry
    save_windows_state(log_dir, day, state)
    logger.info("时间段 %s 执行结束：退出码 %s", key, code)
    return code


def run_multi_window_day(cfg: dict, logger: logging.Logger, log_dir: Path, run_once,
                         now_fn=datetime.now, sleep_fn=time.sleep) -> int:
    """多时间段模式：当天每个时间段最多执行一次（区间内随机时间），返回汇总退出码。"""
    from .parallel import aggregate_exit
    from .schedule import ensure_windows_state, save_windows_state, window_key

    day = now_fn().date()
    bounds_list = all_windows(cfg)
    state = ensure_windows_state(cfg, day, log_dir)
    results: list[tuple[str, int]] = []

    for bounds in bounds_list:
        key = window_key(bounds)
        entry = state.get(key) or {}
        if entry.get("done"):
            logger.info("时间段 %s 今日已完成，跳过", key)
            continue
        if entry.get("missed"):
            logger.info("时间段 %s 已错过，跳过", key)
            continue

        (h1, m1), (h2, m2) = bounds
        now = now_fn()
        end_dt = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
        target_txt = str(entry.get("target") or f"{h1:02d}:{m1:02d}")
        th, tm = (int(x) for x in target_txt.split(":"))
        target_dt = now.replace(hour=th, minute=tm, second=0, microsecond=0)

        if now > end_dt:
            entry["missed"] = True
            state[key] = entry
            save_windows_state(log_dir, day, state)
            logger.warning("时间段 %s 已结束（当前 %02d:%02d），跳过", key, now.hour, now.minute)
            continue
        if target_dt > now:
            logger.info("时间段 %s：随机执行时间 %s，等待中 ...", key, target_txt)
            while now_fn() < target_dt:
                sleep_fn(min(30, max(1, (target_dt - now_fn()).total_seconds())))

        logger.info("时间段 %s：开始执行（计划时间 %s）", key, target_txt)
        code = run_once()
        results.append((key, code))
        if code == 0:
            entry["done"] = True
        else:
            logger.warning("时间段 %s 执行失败（退出码 %s），继续下一时间段", key, code)
        state[key] = entry
        save_windows_state(log_dir, day, state)

    if not results:
        logger.info("多时间段模式：今日无待执行时间段（已完成或已错过）")
        return 0
    result = aggregate_exit([code for _, code in results])
    logger.info("多时间段模式结束：%s（汇总退出码 %s）",
                "，".join(f"{key}={code}" for key, code in results), result)
    return result


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
    parser.add_argument("--at", default=None, help="指定固定时间 HH:MM（覆盖 config.start_time 与 run_window）")
    parser.add_argument("--dry", action="store_true", help="安全演练：只截图/识别距离，不点击任何按钮")
    parser.add_argument("--probe", default=None, help="OCR 自检：识别指定文字后退出")
    parser.add_argument("--focus", default=None, help="--probe 时指定焦点包名")
    parser.add_argument("--screenshot", action="store_true", help="--probe 时保存截图")
    parser.add_argument("--wait-finish", action="store_true", help="跳过启动步骤，只等待距离达标后结束（已手动开跑时用）")
    parser.add_argument("--window-once", action="store_true",
                        help="DSH 兼容：只处理当前（或下一个）时间段，区间内随机等待后执行一次即退出")
    parser.add_argument("--force", action="store_true", help="忽略「当日已成功」标记，强制再执行一次（谨慎：可能重复提交）")
    parser.add_argument("--test-alert", action="store_true", help="发送一条测试告警后退出")
    args = parser.parse_args()
    if args.window_once and (args.now or args.at):
        parser.error("--window-once 不能与 --now/--at 同时使用")

    cfg = load_config(Path(args.config))
    instance_env = os.environ.get("MAA_CAMPUS_INSTANCE")
    if instance_env is not None:
        try:
            idx = int(instance_env)
            instances = cfg.get("instances") or []
            inst = instances[idx]
        except (ValueError, IndexError):
            print(f"无效的 MAA_CAMPUS_INSTANCE：{instance_env}", file=sys.stderr)
            return 1
        cfg["adb_serial"] = inst.get("adb_serial") or cfg["adb_serial"]
        if inst.get("mumu_index") is not None:
            cfg["mumu_index"] = int(inst["mumu_index"])
        cfg["instance_name"] = str(inst.get("name") or f"instance{idx + 1}")

    logger = setup_logger(BASE / cfg.get("log_dir", "logs"), cfg.get("instance_name"))

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

        if args.window_once:
            if args.dry:
                logger.info("--window-once --dry：只做一次 dry 演练（不等待时间段）")
                return run_flow(cfg, logger, True)
            instances = cfg.get("instances") or []
            if len(instances) >= 2:
                from .parallel import run_parallel

                def run_once():
                    return run_parallel(cfg, logger, Path(args.config).resolve(), force=True)
            else:
                def run_once():
                    return run_flow(cfg, logger, False, skip_start=False, force=True)
            code = run_window_once(cfg, logger, BASE / cfg.get("log_dir", "logs"), run_once)
            logger.info("===== 单时间段执行结束，退出码 %s =====", code)
            return code

        if not args.now:
            if args.at:
                wait_until(args.at, logger)
            elif not args.dry and not args.wait_finish and all_windows(cfg):
                instances = cfg.get("instances") or []
                if len(instances) >= 2:
                    from .parallel import run_parallel

                    def run_once():
                        return run_parallel(cfg, logger, Path(args.config).resolve(), force=True)
                else:
                    def run_once():
                        return run_flow(cfg, logger, False, skip_start=False, force=True)
                code = run_multi_window_day(cfg, logger, BASE / cfg.get("log_dir", "logs"),
                                            run_once)
                logger.info("===== 多时间段执行结束，退出码 %s =====", code)
                return code
            else:
                target = resolve_target(cfg, datetime.now(),
                                        BASE / cfg.get("log_dir", "logs"), logger)
                wait_until_dt(target, logger)

        instances = cfg.get("instances") or []
        if len(instances) >= 2 and instance_env is None:
            logger.info("检测到 %d 个实例配置，进入并行模式（每个实例独立子进程）", len(instances))
            from .parallel import run_parallel

            code = run_parallel(cfg, logger, Path(args.config).resolve(),
                                dry=args.dry, skip_start=args.wait_finish, force=args.force)
            logger.info("===== 并行执行结束，退出码 %s =====", code)
            return code

        logger.info("===== 开始执行（%s）=====", "dry 演练" if args.dry else "完整流程")
        code = run_flow(cfg, logger, args.dry, skip_start=args.wait_finish, force=args.force)
        logger.info("===== 结束，退出码 %s =====", code)
        return code
    except Exception as e:
        logger.error("执行异常：%s", e)
        import traceback

        logger.error(traceback.format_exc())
        send_alert(cfg, logger, "exception", "校园跑值守：执行异常", f"{type(e).__name__}: {e}")
        return 1
