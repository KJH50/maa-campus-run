import logging

import pytest

from maa_campus import flow


class _Job:
    def __init__(self, ok=True):
        self.succeeded = ok


class _Controller:
    focus_package = ""


class _FakeTime:
    """可控时钟：time.time() 每次 +1s，sleep(s) 直接推进 s 秒，避免测试真等待。"""

    def __init__(self):
        self.now = 0.0

    def time(self):
        self.now += 1.0
        return self.now

    def sleep(self, seconds):
        self.now += float(seconds)


CFG = {
    "adb_path": "adb.exe",
    "adb_serial": "127.0.0.1:1",
    "campus": {"package": "c", "activity": "c/.Main"},
    "run": {"package": "r", "activity": "r/.Main"},
    "target_distance_km": 2.0,
    "poll_seconds": 1,
    "max_wait_minutes": 2,
    "check_after_minutes": 12,
    "max_run_minutes": 20,
    "max_pace_minutes": 10.0,
    "min_pace_minutes": 3.0,
    "close_apps": True,
    "shutdown_emulator": True,
}


@pytest.fixture
def patched(monkeypatch):
    state = {"samples": [], "fallback": (999.0, 7.2, 9999), "finish_fail": 0,
             "succeeded_today": False, "marked": False}
    calls = []
    alerts = []

    def fake_read(tasker, cfg):
        if state["samples"]:
            return state["samples"].pop(0)
        return state["fallback"]

    def fake_post(tasker, entry, override=None):
        calls.append(entry)
        if entry == "CampusRunFinish" and state["finish_fail"] > 0:
            state["finish_fail"] -= 1
            return _Job(False)
        return _Job(True)

    monkeypatch.setattr(flow, "make_adb", lambda cfg: object())
    monkeypatch.setattr(flow, "ensure_emulator", lambda cfg, adb, logger: True)
    monkeypatch.setattr(flow, "build_tasker", lambda cfg, adb, logger: (object(), _Controller()))
    monkeypatch.setattr(flow, "prepare_run_simulation", lambda *a, **k: True)
    monkeypatch.setattr(flow, "prepare_campus", lambda *a, **k: True)
    monkeypatch.setattr(flow, "start_run_simulation", lambda *a, **k: True)
    monkeypatch.setattr(flow, "start_campus_run", lambda *a, **k: True)
    monkeypatch.setattr(flow, "verify_running", lambda *a, **k: True)
    monkeypatch.setattr(flow, "read_stats", fake_read)
    monkeypatch.setattr(flow, "post_and_wait", fake_post)
    monkeypatch.setattr(flow, "ocr_probe", lambda tasker, patterns: False)
    monkeypatch.setattr(flow, "save_shot", lambda controller, tag, logger: f"{tag}.png")
    monkeypatch.setattr(flow, "shutdown_emulator", lambda cfg, logger: None)
    monkeypatch.setattr(flow, "send_alert",
                        lambda cfg, logger, event, title, content, shot=None, force=False:
                        alerts.append(event) or True)
    monkeypatch.setattr(flow, "_already_succeeded_today",
                        lambda cfg, logger: state["succeeded_today"])
    monkeypatch.setattr(flow, "_mark_success_today",
                        lambda cfg, logger: state.__setitem__("marked", True))
    monkeypatch.setattr(flow, "_load_used_finish_targets", lambda cfg: [])
    monkeypatch.setattr(flow, "_save_used_finish_targets", lambda cfg, used: None)
    monkeypatch.setattr(flow, "_acquire_run_lock", lambda cfg, logger: object())
    monkeypatch.setattr(flow, "_release_run_lock", lambda lock, logger: None)
    monkeypatch.setattr(flow, "time", _FakeTime())
    return state, calls, alerts


def _run(patched, samples, fallback=None, cfg=None):
    state, calls, alerts = patched
    state["samples"] = list(samples)
    if fallback is not None:
        state["fallback"] = fallback
    code = flow.run_flow(cfg or CFG, logging.getLogger("test"), dry=False, skip_start=False)
    return code, calls, alerts


def test_target_reached_returns_0(patched):
    code, calls, alerts = _run(
        patched,
        [(0.6, 7.3, 130), (1.3, 7.3, 260), (2.4, 7.3, 990)],
        (2.4, 7.3, 1000),
    )
    assert code == 0
    assert "timeout" not in alerts
    assert "CampusRunFinish" in calls


def test_forced_end_returns_2(patched):
    code, calls, alerts = _run(
        patched,
        [(0.6, 7.3, 130), (1.3, 7.3, 260), (1.9, 7.3, 1210)],
        (1.9, 7.3, 1215),
    )
    assert code == 2
    assert "timeout" in alerts
    assert "CampusRunFinish" in calls


def test_wait_timeout_returns_2(patched):
    code, _, alerts = _run(
        patched,
        [(0.6, 7.3, 130), (1.3, 7.3, 260)],
        (1.9, 7.3, 301),
    )
    assert code == 2
    assert "timeout" in alerts


def test_finish_retry_success(patched):
    state, calls, alerts = patched
    state["finish_fail"] = 1
    code, calls, alerts = _run(
        patched,
        [(0.6, 7.3, 130), (1.3, 7.3, 260), (2.4, 7.3, 990)],
        (2.4, 7.3, 1000),
    )
    assert code == 0
    assert calls.count("CampusRunFinish") == 2


def test_progress_issues_normal_and_anomaly():
    cfg = {"min_pace_minutes": 3.0, "max_pace_minutes": 10.0}
    assert flow.progress_issues(cfg, 4, 0.55, 7.3, 240) == []
    assert flow.progress_issues(cfg, 4, 2.0, 7.3, 240)  # 4 分钟 2 km 过快/不匹配
    assert flow.progress_issues(cfg, 4, 0.0, None, 240)
    assert flow.progress_issues(cfg, 4, None, None, 240)


def test_marker_path_per_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    assert flow._marker_path({"log_dir": "logs"}) == tmp_path / "logs" / ".last_success"
    p = flow._marker_path({"log_dir": "logs", "instance_name": "mumu 2"})
    assert p == tmp_path / "logs" / ".last_success_mumu_2"


def test_skip_when_already_succeeded_today(patched):
    state, calls, alerts = patched
    state["succeeded_today"] = True
    code, calls, alerts = _run(patched, [(2.4, 7.3, 1000)])
    assert code == 0
    assert calls == []
    assert alerts == []


def test_marks_success_today(patched):
    state, calls, alerts = patched
    code, _, _ = _run(
        patched,
        [(0.6, 7.3, 130), (1.3, 7.3, 260), (2.4, 7.3, 990)],
        (2.4, 7.3, 1000),
    )
    assert code == 0
    assert state["marked"] is True


def test_force_ignores_daily_marker(patched):
    state, calls, alerts = patched
    state["succeeded_today"] = True
    state["samples"] = [(0.6, 7.3, 130), (1.3, 7.3, 260), (2.4, 7.3, 990)]
    code = flow.run_flow(CFG, logging.getLogger("test"), dry=False, skip_start=False, force=True)
    assert code == 0
    assert "CampusRunFinish" in calls
    assert state["marked"] is True


def test_no_record_skips_marker_and_dedupe(patched):
    state, calls, alerts = patched
    state["succeeded_today"] = True
    state["samples"] = [(0.6, 7.3, 130), (1.3, 7.3, 260), (2.4, 7.3, 990)]
    code = flow.run_flow(CFG, logging.getLogger("test"), dry=False, skip_start=False,
                         record=False)
    assert code == 0
    assert "CampusRunFinish" in calls  # 不因当日标记跳过
    assert state["marked"] is False  # 不写当日成功标记
