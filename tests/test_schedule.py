import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from maa_campus import cli, schedule
from maa_campus.config import validate_config


def _logger():
    return logging.getLogger("test-schedule")


def _base_cfg(**extra):
    cfg = {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:1",
        "campus": {"package": "a.b", "activity": "a.b/.Main"},
        "run": {"package": "c.d", "activity": "c.d/.Main"},
    }
    cfg.update(extra)
    return cfg


def test_parse_hhmm():
    assert schedule.parse_hhmm("07:05") == (7, 5)
    for bad in ("7:05", "24:00", "07:60", "abc", ""):
        with pytest.raises(ValueError):
            schedule.parse_hhmm(bad)


def test_window_bounds():
    cfg = {"run_window": {"start": "07:00", "end": "08:30"}}
    assert schedule.window_bounds(cfg) == ((7, 0), (8, 30))
    with pytest.raises(ValueError):
        schedule.window_bounds({"run_window": {"start": "08:00", "end": "07:00"}})


def test_resolve_fixed_time():
    cfg = {"start_time": "07:00"}
    assert schedule.resolve_target(cfg, datetime(2026, 1, 1, 6, 0), Path("logs"),
                                   _logger()) == datetime(2026, 1, 1, 7, 0)
    assert schedule.resolve_target(cfg, datetime(2026, 1, 1, 8, 0), Path("logs"),
                                   _logger()) == datetime(2026, 1, 2, 7, 0)


def test_resolve_window_persists_daily_choice(tmp_path):
    cfg = {"run_window": {"start": "07:00", "end": "08:30"}}
    now = datetime(2026, 1, 1, 6, 0)
    first = schedule.resolve_target(cfg, now, tmp_path, _logger())
    assert datetime(2026, 1, 1, 7, 0) <= first <= datetime(2026, 1, 1, 8, 30)
    second = schedule.resolve_target(cfg, now, tmp_path, _logger())
    assert first == second
    assert schedule.load_state(tmp_path) == first


def test_resolve_window_inside_window_immediate(tmp_path):
    cfg = {"run_window": {"start": "07:00", "end": "08:30"}}
    schedule.save_state(tmp_path, datetime(2026, 1, 1, 7, 10))
    now = datetime(2026, 1, 1, 7, 40)
    assert schedule.resolve_target(cfg, now, tmp_path, _logger()) == now


def test_resolve_window_after_end_rolls_to_next_day(tmp_path):
    cfg = {"run_window": {"start": "07:00", "end": "08:30"}}
    schedule.save_state(tmp_path, datetime(2026, 1, 1, 7, 10))
    now = datetime(2026, 1, 1, 9, 0)
    target = schedule.resolve_target(cfg, now, tmp_path, _logger())
    assert target.date() == datetime(2026, 1, 2).date()
    assert datetime(2026, 1, 2, 7, 0) <= target <= datetime(2026, 1, 2, 8, 30)


def test_validate_rejects_bad_window():
    cfg = _base_cfg(run_window={"start": "09:00", "end": "08:00"})
    with pytest.raises(ValueError, match="run_window"):
        validate_config(cfg)


def test_validate_accepts_window():
    validate_config(_base_cfg(run_window={"start": "07:00", "end": "08:30"}))


def test_all_windows_sorted_and_validated():
    cfg = {"run_windows": [{"start": "12:00", "end": "13:00"},
                           {"start": "07:00", "end": "08:00"}]}
    assert schedule.all_windows(cfg) == [((7, 0), (8, 0)), ((12, 0), (13, 0))]
    with pytest.raises(ValueError, match="重叠"):
        schedule.all_windows({"run_windows": [{"start": "07:00", "end": "09:00"},
                                              {"start": "08:00", "end": "10:00"}]})


def test_validate_rejects_run_window_and_run_windows_together():
    cfg = _base_cfg(run_window={"start": "07:00", "end": "08:00"},
                    run_windows=[{"start": "12:00", "end": "13:00"}])
    with pytest.raises(ValueError, match="只能设置一个"):
        validate_config(cfg)


def test_ensure_windows_state_persists(tmp_path):
    cfg = {"run_windows": [{"start": "07:00", "end": "08:00"}]}
    day = datetime(2026, 1, 1).date()
    first = schedule.ensure_windows_state(cfg, day, tmp_path)["07:00-08:00"]["target"]
    second = schedule.ensure_windows_state(cfg, day, tmp_path)["07:00-08:00"]["target"]
    assert first == second


def _multi_cfg():
    return {"run_windows": [{"start": "07:00", "end": "08:00"},
                            {"start": "12:00", "end": "13:00"}]}


def test_run_multi_window_day_executes_each_window(tmp_path):
    clock = {"now": datetime(2026, 1, 1, 6, 0)}

    def now_fn():
        return clock["now"]

    def sleep_fn(seconds):
        clock["now"] += timedelta(seconds=seconds)

    calls = []

    def run_once():
        calls.append(clock["now"])
        return 0

    code = cli.run_multi_window_day(_multi_cfg(), logging.getLogger("t"), tmp_path, run_once,
                                    now_fn=now_fn, sleep_fn=sleep_fn)
    assert code == 0
    assert len(calls) == 2
    assert all(call.date() == datetime(2026, 1, 1).date() for call in calls)


def test_run_multi_window_day_skips_done_on_restart(tmp_path):
    clock = {"now": datetime(2026, 1, 1, 6, 0)}

    def now_fn():
        return clock["now"]

    def sleep_fn(seconds):
        clock["now"] += timedelta(seconds=seconds)

    calls = []

    def run_once():
        calls.append(clock["now"])
        return 0

    assert cli.run_multi_window_day(_multi_cfg(), logging.getLogger("t"), tmp_path, run_once,
                                    now_fn=now_fn, sleep_fn=sleep_fn) == 0
    assert len(calls) == 2
    assert cli.run_multi_window_day(_multi_cfg(), logging.getLogger("t"), tmp_path, run_once,
                                    now_fn=now_fn, sleep_fn=sleep_fn) == 0
    assert len(calls) == 2


def test_run_multi_window_day_continues_after_failure(tmp_path):
    clock = {"now": datetime(2026, 1, 1, 6, 0)}
    codes = [3, 0]

    def now_fn():
        return clock["now"]

    def sleep_fn(seconds):
        clock["now"] += timedelta(seconds=seconds)

    def run_once():
        return codes.pop(0)

    assert cli.run_multi_window_day(_multi_cfg(), logging.getLogger("t"), tmp_path, run_once,
                                    now_fn=now_fn, sleep_fn=sleep_fn) == 3


def test_run_multi_window_day_missed_windows_are_skipped(tmp_path):
    clock = {"now": datetime(2026, 1, 1, 14, 0)}
    calls = []

    def run_once():
        calls.append("run")
        return 0

    code = cli.run_multi_window_day(_multi_cfg(), logging.getLogger("t"), tmp_path, run_once,
                                    now_fn=lambda: clock["now"], sleep_fn=lambda s: None)
    assert code == 0
    assert calls == []
