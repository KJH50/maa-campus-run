"""配置加载、默认值合并与必填校验。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .schedule import all_windows, parse_hhmm, window_bounds

DEFAULTS: dict = {
    "adb_path": "",
    "adb_serial": "127.0.0.1:16416",
    "mumu_manager": "",
    "mumu_index": 1,
    "instances": [],
    "emulator_boot_timeout_seconds": 300,
    "emulator_restart_on_fail": True,
    "start_time": "07:00",
    "run_window": None,
    "run_windows": [],
    "max_wait_minutes": 120,
    "poll_seconds": 8,
    "target_distance_km": 2.0,
    "check_after_minutes": 12,
    "max_run_minutes": 20,
    "max_pace_minutes": 10.0,
    "min_pace_minutes": 3.0,
    "distance_regex": "^\\d+\\.\\d{2}$",
    "route_text": "标准",
    "close_apps": True,
    "shutdown_emulator": True,
    "skip_if_success_today": True,
    "log_dir": "logs",
    "log_retention_days": 14,
    "pre_click_texts": [],
    "campus": {"package": "", "activity": ""},
    "run": {"package": "", "activity": ""},
    "alerts": {
        "enabled": False,
        "type": "generic",
        "webhook_url": "",
        "on": ["connect_failed", "start_failed", "timeout", "stop_failed", "exception", "progress_anomaly"],
    },
}

REQUIRED: list[str] = [
    "adb_path",
    "adb_serial",
    "campus.package",
    "campus.activity",
    "run.package",
    "run.activity",
]


def _get(cfg: dict, dotted: str):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def load_config(path: Path) -> dict:
    """读取 JSON 配置（允许 BOM），缺失项用默认值补齐（campus/run/alerts 做嵌套合并）。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f) or {}
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    for key in ("campus", "run", "alerts"):
        merged = dict(DEFAULTS[key])
        merged.update(raw.get(key) or {})
        cfg[key] = merged
    return cfg


def validate_config(cfg: dict) -> None:
    """校验必填项；缺项时抛出 ValueError 并一次列出全部缺失项。"""
    missing = [k for k in REQUIRED if not _get(cfg, k)]
    try:
        re.compile(cfg.get("distance_regex") or DEFAULTS["distance_regex"])
    except re.error as e:
        raise ValueError(f"distance_regex 不是合法正则：{e}") from e
    try:
        parse_hhmm(cfg.get("start_time") or DEFAULTS["start_time"])
    except ValueError as e:
        raise ValueError(f"start_time 配置错误：{e}") from e
    try:
        window_bounds(cfg)
    except ValueError as e:
        raise ValueError(f"run_window 配置错误：{e}") from e
    try:
        all_windows(cfg)
    except ValueError as e:
        raise ValueError(f"run_windows 配置错误：{e}") from e
    if cfg.get("run_window") and cfg.get("run_windows"):
        raise ValueError("run_window 与 run_windows 只能设置一个")
    if cfg.get("target_distance_km") is not None and float(cfg["target_distance_km"]) <= 0:
        raise ValueError("target_distance_km 必须大于 0")
    instances = cfg.get("instances") or []
    if instances:
        if not isinstance(instances, list):
            raise ValueError("instances 必须是数组")
        names: set[str] = set()
        serials: set[str] = set()
        for i, inst in enumerate(instances):
            if not isinstance(inst, dict):
                raise ValueError(f"instances[{i}] 必须是对象")
            serial = str(inst.get("adb_serial") or "").strip()
            if not serial:
                raise ValueError(f"instances[{i}].adb_serial 不能为空")
            if serial in serials:
                raise ValueError(f"instances[{i}].adb_serial 重复：{serial}")
            serials.add(serial)
            name = str(inst.get("name") or f"instance{i + 1}").strip()
            if name in names:
                raise ValueError(f"instances[{i}].name 重复：{name}")
            names.add(name)
    if missing:
        raise ValueError("缺少必填配置：" + "、".join(missing))
