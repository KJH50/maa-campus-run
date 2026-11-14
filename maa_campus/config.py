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
    "instance_start_stagger_seconds": 20,
    "run_lock_stale_seconds": 1800,
    "emulator_boot_timeout_seconds": 300,
    "emulator_restart_on_fail": True,
    "refresh_window_on_start": True,
    "start_time": "07:00",
    "run_window": None,
    "run_windows": [],
    "max_wait_minutes": 120,
    "poll_seconds": 8,
    "target_distance_km": 2.0,
    "max_runs": 0,
    "run_count_patterns": [
        "已跑\\D{0,8}(\\d+)\\s*次",
        "已完成\\D{0,8}(\\d+)\\s*次",
        "累计\\D{0,8}(\\d+)\\s*次",
        "跑步次数\\D{0,8}(\\d+)",
        "已跑\\s*(\\d+)\\s*/\\s*\\d+\\s*次",
        "(\\d+)\\s*次\\s*/\\s*(\\d+)\\s*次",
    ],
    "log_run_count": False,
    "finish_target_avoid_repeat": True,
    "finish_target_min_gap_km": 0.02,
    "check_after_minutes": 12,
    "max_run_minutes": 20,
    "campus_start_timeout_seconds": 90,
    "max_pace_minutes": 10.0,
    "min_pace_minutes": 3.0,
    "distance_regex": "^\\d+\\.\\d{2}$",
    "route_text": "标准",
    "close_apps": True,
    "shutdown_emulator": True,
    "skip_if_success_today": True,
    "log_dir": "logs",
    "log_retention_days": 14,
    "pack_days": 7,
    "pack_include_shots": True,
    "pre_click_texts": [],
    "campus": {
        "package": "",
        "activity": "",
        "school": "",
        "login": {
            "enabled": True,
            "username": "",
            "password": "",
            "remember_week": False,
        },
    },
    "run": {"package": "", "activity": ""},
    "alerts": {
        "enabled": False,
        "type": "generic",
        "webhook_url": "",
        "on": ["connect_failed", "start_failed", "timeout", "stop_failed", "exception", "progress_anomaly"],
    },
    "ai_watch": {
        "enabled": False,
        "mode": "interval",
        "interval_seconds": 300,
        "cron": "",
        "cycle_timeout_seconds": 120,
        "max_retries": 1,
        "backoff_seconds": 10,
        "lock_stale_seconds": 300,
        "cooldown_seconds": 30,
        "log_dir": "logs/ai_watch",
        "target": {"package": "", "display": 0, "url": ""},
        "capture": {
            "format": "jpeg",
            "quality": 75,
            "max_width": 1280,
            "mask_regions": [],
        },
        "rules": {
            "expected_selectors": [],
            "structure_selectors": [],
            "unique_selectors": [],
            "error_keywords": [],
            "missing_expected": {"enabled": True},
            "selector_mismatch": {"enabled": True},
            "multiple_candidates": {"enabled": True},
            "error_keyword": {"enabled": True},
            "blank_screen": {"enabled": True, "threshold": 0.98},
            "low_confidence": {"enabled": True, "threshold": 0.5},
            "ocr_empty": {"enabled": True},
        },
        "ai": {
            "provider": "mock",
            "env_endpoint": "DEEPSEEK_ENDPOINT",
            "env_api_key": "DEEPSEEK_API_KEY",
            "env_model": "DEEPSEEK_MODEL",
            "timeout_seconds": 30,
            "json_mode": False,
        },
        "action": {
            "allowed": ["click", "input", "scroll", "wait", "retry", "abort"],
            "confidence_threshold": 0.7,
            "max_wait_seconds": 30,
            "max_retries": 2,
        },
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


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并配置（override 优先，dict 逐层合并）。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def apply_instance(cfg: dict, inst: dict, index: int = 0) -> None:
    """把 instances[index] 的覆盖项应用到当前 cfg。

    除 adb / MuMu 序号 / 实例名外，若实例配置了 login，则覆盖全局
    campus.login（多模拟器可为每台设备配置独立账号）。
    """
    cfg["adb_serial"] = inst.get("adb_serial") or cfg.get("adb_serial")
    if inst.get("mumu_index") is not None:
        cfg["mumu_index"] = int(inst["mumu_index"])
    cfg["instance_name"] = str(inst.get("name") or f"instance{index + 1}")
    login = inst.get("login")
    if isinstance(login, dict) and login:
        campus = cfg.setdefault("campus", {})
        merged = dict(campus.get("login") or {})
        merged.update(login)
        campus["login"] = merged
        cfg["_instance_login_configured"] = True


def load_config(path: Path) -> dict:
    """读取 JSON 配置（允许 BOM），缺失项用默认值补齐（嵌套配置递归合并）。"""
    with open(path, "r", encoding="utf-8-sig") as f:
        raw = json.load(f) or {}
    return _deep_merge(DEFAULTS, raw)


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
    aw = cfg.get("ai_watch") or {}
    if aw.get("enabled"):
        from .ai_vision import ALLOWED_ACTIONS
        from .cron import parse_cron

        mode = str(aw.get("mode") or "interval").lower()
        if mode not in ("interval", "cron"):
            raise ValueError("ai_watch.mode 只能是 interval 或 cron")
        if mode == "interval" and float(aw.get("interval_seconds") or 0) <= 0:
            raise ValueError("ai_watch.interval_seconds 必须大于 0")
        if mode == "cron":
            try:
                parse_cron(str(aw.get("cron") or ""))
            except ValueError as e:
                raise ValueError(f"ai_watch.cron 配置错误：{e}") from e
        allowed = (aw.get("action") or {}).get("allowed") or []
        bad = [a for a in allowed if a not in ALLOWED_ACTIONS]
        if bad:
            raise ValueError(f"ai_watch.action.allowed 含不支持的动作：{bad}")
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
            login = inst.get("login")
            if login is not None:
                if not isinstance(login, dict):
                    raise ValueError(f"instances[{i}].login 必须是对象")
                if "enabled" in login and not isinstance(login["enabled"], bool):
                    raise ValueError(f"instances[{i}].login.enabled 必须是布尔值")
                for key in ("username", "password"):
                    if login.get(key) is not None and not isinstance(login[key], str):
                        raise ValueError(f"instances[{i}].login.{key} 必须是字符串")
    if missing:
        raise ValueError("缺少必填配置：" + "、".join(missing))
