"""定时策略：固定时间（start_time）或每日时间区间内随机执行（run_window）。

run_window 示例：
    "run_window": {"start": "07:00", "end": "08:30"}

- 当天第一次解析时随机选一个区间内时间（分钟粒度），写入 logs/.next_run；
- 进程在同一天重启会复用已选时间，避免随机时间变化；
- 超过区间仍未执行时，顺延到次日的随机时间；
- 区间内已过随机时间但未到区间结束：立即执行（避免错过）。
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path

STATE_FILE = ".next_run"
WINDOWS_STATE_FILE = ".run_windows_state.json"


def parse_hhmm(text: str) -> tuple[int, int]:
    """解析 HH:MM，返回 (hour, minute)；非法时抛出 ValueError。"""
    raw = str(text).strip()
    if not re.fullmatch(r"\d{2}:\d{2}", raw):
        raise ValueError(f"时间格式应为 HH:MM，当前: {text!r}")
    h, m = (int(x) for x in raw.split(":"))
    if not (0 <= h < 24 and 0 <= m < 60):
        raise ValueError(f"时间超出范围（00:00~23:59）：{text!r}")
    return h, m


def window_bounds(cfg: dict) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """返回 run_window 的 ((h1,m1),(h2,m2))；未配置返回 None。"""
    win = cfg.get("run_window")
    if not win:
        return None
    if not isinstance(win, dict):
        raise ValueError("run_window 必须是对象，如 {\"start\":\"07:00\",\"end\":\"08:30\"}")
    start = parse_hhmm(win.get("start", ""))
    end = parse_hhmm(win.get("end", ""))
    if start >= end:
        raise ValueError("run_window.start 必须早于 run_window.end")
    return start, end


def pick_target(cfg: dict, day: date, rng: random.Random | None = None) -> datetime:
    """在 run_window 区间内为指定日期随机选一个时间（分钟粒度）。"""
    bounds = window_bounds(cfg)
    assert bounds is not None
    (h1, m1), (h2, m2) = bounds
    rng = rng or random
    minute = rng.randint(h1 * 60 + m1, h2 * 60 + m2)
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60)


def pick_target_bounds(bounds: tuple[tuple[int, int], tuple[int, int]], day: date,
                       rng: random.Random | None = None) -> datetime:
    """在给定区间内为指定日期随机选一个时间（分钟粒度）。"""
    (h1, m1), (h2, m2) = bounds
    rng = rng or random
    minute = rng.randint(h1 * 60 + m1, h2 * 60 + m2)
    return datetime(day.year, day.month, day.day, minute // 60, minute % 60)


def window_key(bounds: tuple[tuple[int, int], tuple[int, int]]) -> str:
    (h1, m1), (h2, m2) = bounds
    return f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}"


def all_windows(cfg: dict) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """返回 run_windows 配置（按开始时间排序、校验不重叠）；未配置返回空列表。"""
    raw = cfg.get("run_windows")
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("run_windows 必须是数组，如 [{\"start\":\"07:00\",\"end\":\"08:00\"}]")
    bounds: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for i, win in enumerate(raw):
        if not isinstance(win, dict):
            raise ValueError(f"run_windows[{i}] 必须是对象")
        start = parse_hhmm(win.get("start", ""))
        end = parse_hhmm(win.get("end", ""))
        if start >= end:
            raise ValueError(f"run_windows[{i}].start 必须早于 end")
        bounds.append((start, end))
    bounds.sort(key=lambda b: b[0])
    for (s1, e1), (s2, e2) in zip(bounds, bounds[1:]):
        if s2 < e1:
            raise ValueError("run_windows 时间段不能重叠：" +
                             f"{window_key((s1, e1))} 与 {window_key((s2, e2))}")
    return bounds


def load_windows_state(log_dir: Path, day: date) -> dict[str, dict]:
    """读取当日多窗口状态；日期不匹配时返回空字典。"""
    path = log_dir / WINDOWS_STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("date") != day.isoformat():
        return {}
    windows = data.get("windows")
    return windows if isinstance(windows, dict) else {}


def save_windows_state(log_dir: Path, day: date, windows: dict[str, dict]) -> None:
    path = log_dir / WINDOWS_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": day.isoformat(), "windows": windows},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_windows_state(cfg: dict, day: date, log_dir: Path) -> dict[str, dict]:
    """补齐当日各窗口状态（随机目标时间、done/missed 标记）并持久化。"""
    state = load_windows_state(log_dir, day)
    for bounds in all_windows(cfg):
        key = window_key(bounds)
        entry = state.get(key)
        if not isinstance(entry, dict) or not entry.get("target"):
            state[key] = {
                "start": f"{bounds[0][0]:02d}:{bounds[0][1]:02d}",
                "end": f"{bounds[1][0]:02d}:{bounds[1][1]:02d}",
                "target": pick_target_bounds(bounds, day).strftime("%H:%M"),
                "done": False,
                "missed": False,
            }
    save_windows_state(log_dir, day, state)
    return state


def state_path(log_dir: Path) -> Path:
    return log_dir / STATE_FILE


def save_state(log_dir: Path, target: datetime) -> None:
    path = state_path(log_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(target.strftime("%Y-%m-%dT%H:%M\n"), encoding="utf-8")


def load_state(log_dir: Path) -> datetime | None:
    try:
        text = state_path(log_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def resolve_target(cfg: dict, now: datetime, log_dir: Path,
                   logger: logging.Logger) -> datetime:
    """确定本次执行时间：固定时间或区间随机；返回值可能已过（立即执行）。"""
    bounds = window_bounds(cfg)
    if bounds is None:
        h, m = parse_hhmm(cfg.get("start_time", "07:00"))
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    (h1, m1), (h2, m2) = bounds
    target = load_state(log_dir)
    if target is None or target.date() != now.date():
        target = pick_target(cfg, now.date())
        save_state(log_dir, target)

    window_end = now.replace(hour=h2, minute=m2, second=0, microsecond=0)
    if now > window_end:
        target = pick_target(cfg, now.date() + timedelta(days=1))
        save_state(log_dir, target)
        logger.info("已过今日区间 %02d:%02d~%02d:%02d，明日随机执行时间 %s",
                    h1, m1, h2, m2, target.strftime("%m-%d %H:%M"))
        return target
    if target <= now:
        logger.info("今日随机执行时间 %s 已过（仍在区间内），立即执行",
                    target.strftime("%H:%M"))
        return now
    logger.info("今日随机执行时间 %s（区间 %02d:%02d~%02d:%02d）",
                target.strftime("%H:%M"), h1, m1, h2, m2)
    return target
