"""AI 定时页面解析与操作回传（实验特性）。

流程：定时 → 截图 → OCR/规则判定「非确定画面」→ 脱敏/压缩 → 上传 AI →
校验结构化决策 → 执行动作 → 复检页面 → 记录 JSONL 日志。

安全：默认关闭；API Key 只从环境变量读取，不写日志；截图先脱敏再上传。
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from .ai_vision import AIError, request_decision
from .cron import next_cron_delay
from .emulator import make_adb
from .page_actions import ActionError, execute, validate
from .page_observer import (PageSnapshot, build_snapshot, encode_image, evaluate_rules,
                            mask_regions)
from .maa_tasks import build_tasker

BASE = Path(__file__).resolve().parent.parent

AW_CONFIG = "AW_001_CONFIG"
AW_LOCK = "AW_010_LOCK"
AW_CONNECT = "AW_020_CONNECT"
AW_TASKER = "AW_021_TASKER"
AW_SCREENSHOT = "AW_030_SCREENSHOT"
AW_AI = "AW_040_AI"
AW_ACTION = "AW_050_ACTION"
AW_RECHECK = "AW_080_RECHECK"


def _aw(cfg: dict) -> dict:
    return (cfg or {}).get("ai_watch") or {}


def _log_dir(cfg: dict) -> Path:
    aw = _aw(cfg)
    path = BASE / str(aw.get("log_dir") or "logs/ai_watch")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _jsonl(log_dir: Path, record: dict) -> None:
    """追加一条 JSONL 日志（不记录敏感字段）。"""
    try:
        path = log_dir / f"ai_watch_{datetime.now():%Y%m%d}.log"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _acquire_lock(log_dir: Path, stale_seconds: int = 300) -> Path | None:
    """获取单实例锁；返回锁路径，失败返回 None。"""
    path = log_dir / ".ai_watch.lock"
    if path.exists():
        try:
            age = time.time() - path.stat().st_mtime
            if age > stale_seconds:
                path.unlink(missing_ok=True)
        except OSError:
            return None
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()} time={datetime.now().isoformat(timespec='seconds')}\n")
        return path
    except FileExistsError:
        return None


def _release_lock(path: Path | None) -> None:
    if path:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _page_hash(snapshot: PageSnapshot) -> str:
    """页面感知哈希（8x8 均值哈希），用于动作后复检/防重复触发。"""
    if snapshot.image is None:
        return ""
    img = snapshot.image.convert("L").resize((8, 8))
    pixels = list(img.tobytes())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return hashlib.sha256(bits.encode()).hexdigest()[:16]


def _save_shot(log_dir: Path, task_id: str, image) -> str:
    shots = log_dir / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    path = shots / f"{task_id}.jpg"
    image.convert("RGB").save(path, format="JPEG", quality=80)
    return str(path)


def run_cycle(cfg: dict, logger: logging.Logger, env: dict | None = None,
              opener=None, sleep=time.sleep) -> dict:
    """执行一次「检查-判定-上传-执行-复检」；返回结构化结果。"""
    aw = _aw(cfg)
    target = aw.get("target") or {}
    package = str(target.get("package") or cfg.get("campus", {}).get("package") or "")
    url = str(target.get("url") or package or "unknown")
    task_id = uuid.uuid4().hex[:12]
    log_dir = _log_dir(cfg)
    record = {
        "task_id": task_id,
        "time": datetime.now().isoformat(timespec="seconds"),
        "page_url": url,
        "status": "started",
    }
    started = time.monotonic()
    adb = None
    try:
        adb = make_adb(cfg)
        if not adb.connect(wait_seconds=5):
            record.update(status="connect_failed", error_code=AW_CONNECT)
            _jsonl(log_dir, record)
            return record

        display = int(target.get("display") or adb.get_display(package) or 0)
        tasker_cfg = copy.deepcopy(cfg)
        tasker_cfg.setdefault("campus", {})
        if package:
            tasker_cfg["campus"]["package"] = package
        tasker, controller = build_tasker(tasker_cfg, adb, logger)
        if tasker is None:
            record.update(status="tasker_failed", error_code=AW_TASKER)
            _jsonl(log_dir, record)
            return record

        snapshot = build_snapshot(controller, tasker, url, logger)
        verdict = evaluate_rules(snapshot, aw.get("rules") or {})
        record.update(
            status="uncertain" if verdict.uncertain else "normal",
            reasons=verdict.reasons,
            rule_codes=verdict.codes,
            page_hash=_page_hash(snapshot),
            ocr_texts=[o.text for o in snapshot.ocr][:20],
        )
        if not verdict.uncertain:
            record["duration_ms"] = int((time.monotonic() - started) * 1000)
            _jsonl(log_dir, record)
            logger.info("页面状态正常，不上传（%s）", url)
            return record

        capture = aw.get("capture") or {}
        masked = mask_regions(snapshot.image, capture.get("mask_regions") or [])
        image_bytes, mime = encode_image(
            masked,
            fmt=str(capture.get("format") or "jpeg"),
            quality=int(capture.get("quality") or 75),
            max_width=int(capture.get("max_width") or 1280),
        )
        record["screenshot"] = _save_shot(log_dir, task_id, masked)
        record["upload"] = {"size_bytes": len(image_bytes), "mime": mime,
                            "provider": (aw.get("ai") or {}).get("provider", "openai-compatible")}
        context = {
            "task_id": task_id,
            "page_url": url,
            "timestamp": record["time"],
            "reasons": verdict.reasons,
            "ocr_texts": [t for t in snapshot.texts][:30],
            "screen": {"width": snapshot.image.width, "height": snapshot.image.height},
        }
        decision = request_decision(aw, image_bytes, context, logger, env=env, opener=opener)
        record["decision"] = {
            "action": decision.action,
            "target": decision.target,
            "confidence": decision.confidence,
            "reason": decision.reason,
        }
        logger.info("AI 决策：%s target=%s confidence=%.2f", decision.action,
                    decision.target, decision.confidence)

        try:
            validate(decision, snapshot, cfg)
        except ActionError as e:
            record.update(status="decision_rejected", error_code=e.code)
            _jsonl(log_dir, record)
            logger.warning("AI 决策被拒绝：%s", e)
            return record

        if decision.action == "abort":
            record.update(status="aborted_by_ai")
            _jsonl(log_dir, record)
            return record
        if decision.action == "retry":
            record.update(status="retry_requested")
            _jsonl(log_dir, record)
            return record

        result = execute(decision, snapshot, adb, display, cfg, logger, sleep=sleep)
        record["action_result"] = result.message

        sleep(1.0)
        try:
            after = build_snapshot(controller, tasker, url, logger)
            after_hash = _page_hash(after)
            record["page_hash_after"] = after_hash
            if after_hash and after_hash == record.get("page_hash"):
                record["recheck"] = "unchanged"
                logger.warning("动作后页面未变化（%s），可能未生效", url)
        except Exception as e:  # noqa: BLE001
            record["recheck"] = f"failed: {e}"

        record["status"] = "done"
        record["duration_ms"] = int((time.monotonic() - started) * 1000)
        _jsonl(log_dir, record)
        return record
    except AIError as e:
        record.update(status="ai_failed", error_code=e.code, error=str(e)[:300])
        _jsonl(log_dir, record)
        logger.error("AI 调用失败：%s", e)
        return record
    except ActionError as e:
        record.update(status="action_failed", error_code=e.code, error=str(e)[:300])
        _jsonl(log_dir, record)
        logger.error("动作失败：%s", e)
        return record
    except Exception as e:  # noqa: BLE001
        record.update(status="error", error_code=AW_CONFIG, error=f"{type(e).__name__}: {e}"[:300])
        _jsonl(log_dir, record)
        logger.exception("AI 值守单次执行异常")
        return record


def _cycle_with_retries(cfg: dict, logger: logging.Logger, env: dict | None = None,
                        opener=None) -> dict:
    aw = _aw(cfg)
    max_retries = int(aw.get("max_retries") or 0)
    backoff = float(aw.get("backoff_seconds") or 5)
    result = run_cycle(cfg, logger, env=env, opener=opener)
    attempts = 1
    while result.get("status") in ("ai_failed", "decision_rejected", "action_failed",
                                   "retry_requested") and attempts <= max_retries:
        logger.info("本次结果 %s，%.1f 秒后重试（%s/%s）", result.get("status"), backoff,
                    attempts, max_retries)
        time.sleep(backoff)
        result = run_cycle(cfg, logger, env=env, opener=opener)
        attempts += 1
    return result


def _next_delay(aw: dict) -> float:
    mode = str(aw.get("mode") or "interval").lower()
    if mode == "cron":
        expr = str(aw.get("cron") or "").strip()
        if not expr:
            raise ValueError("ai_watch.mode=cron 但未配置 cron")
        return float(next_cron_delay(expr, datetime.now()))
    return max(1.0, float(aw.get("interval_seconds") or 300))


def run_ai_watch(cfg: dict, logger: logging.Logger, once: bool = False,
                 env: dict | None = None, opener=None) -> int:
    """AI 定时检查主循环；once=True 只执行一轮（用于验收/调试）。"""
    aw = _aw(cfg)
    if not aw.get("enabled"):
        logger.error("ai_watch 未启用：请在 config.json 设置 ai_watch.enabled=true")
        return 1
    log_dir = _log_dir(cfg)
    lock = _acquire_lock(log_dir, int(aw.get("lock_stale_seconds") or 300))
    if lock is None:
        logger.error("另一个 AI 值守实例正在运行（锁：%s）", log_dir / ".ai_watch.lock")
        return 5
    logger.info("AI 值守启动：mode=%s，once=%s，日志目录=%s",
                aw.get("mode") or "interval", once, log_dir)
    try:
        while True:
            cycle_started = time.monotonic()
            result = _cycle_with_retries(cfg, logger, env=env, opener=opener)
            elapsed = time.monotonic() - cycle_started
            timeout = float(aw.get("cycle_timeout_seconds") or 0)
            if timeout and elapsed > timeout:
                logger.warning("单次执行超时：%.1fs > %.1fs", elapsed, timeout)
            logger.info("AI 值守单轮结束：status=%s（%.1fs）", result.get("status"), elapsed)
            if once:
                return 0 if result.get("status") not in ("error",) else 2
            try:
                delay = _next_delay(aw)
            except ValueError as e:
                logger.error("调度配置错误：%s", e)
                return 1
            logger.info("等待下一次检查：%.0f 秒", delay)
            time.sleep(delay)
    except KeyboardInterrupt:
        logger.info("AI 值守已停止（Ctrl+C）")
        return 0
    finally:
        _release_lock(lock)
