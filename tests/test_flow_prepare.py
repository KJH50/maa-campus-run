import json
import logging
from pathlib import Path

from maa_campus import flow

ROOT = Path(__file__).resolve().parent.parent


class FakeJob:
    def __init__(self, ok=True):
        self.succeeded = ok


class FakeController:
    def __init__(self):
        self.focus_package = ""
        self.started = []
        self.stopped = []

    def start_app(self, activity):
        self.started.append(activity)

    def stop_app(self, package):
        self.stopped.append(package)


def test_prepare_campus_clicks_confirm_abandon(monkeypatch):
    taps = []
    state = {"abandon_checked": False}

    def probe(tasker, patterns):
        ps = list(patterns)
        if "放弃这条本地记录" in ps:
            if not state["abandon_checked"]:
                state["abandon_checked"] = True
                return True
            return False
        if "确认放弃" in ps:
            return True
        if "总距离" in ps:
            return True
        if "^开始$" in ps:
            return True
        return False

    def tap(tasker, patterns):
        taps.append(list(patterns))
        return True

    monkeypatch.setattr(flow, "ocr_probe", probe)
    monkeypatch.setattr(flow, "ocr_tap", tap)
    monkeypatch.setattr(flow, "save_shot", lambda *a, **k: None)
    monkeypatch.setattr(flow.time, "sleep", lambda s: None)

    ctl = FakeController()
    ok = flow.prepare_campus(object(), ctl,
                             {"campus": {"activity": "c/.Main"}},
                             logging.getLogger("t"), "c")
    assert ok is True
    assert any("确认放弃" in patterns for patterns in taps)


def test_prepare_campus_detects_login_required(monkeypatch):
    shots = []

    def probe(tasker, patterns):
        ps = list(patterns)
        return any(("登录" in p) or p == "^登录$" for p in ps)

    monkeypatch.setattr(flow, "ocr_probe", probe)
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: shots.append(tag) or None)
    monkeypatch.setattr(flow.time, "sleep", lambda s: None)

    cfg = {"campus": {"activity": "c/.Main"}}
    ctl = FakeController()
    ok = flow.prepare_campus(object(), ctl, cfg, logging.getLogger("t"), "c")
    assert ok is False
    assert cfg["_campus_login_required"] is True
    assert "campus_login_required" in shots


def test_stop_finished_playback(monkeypatch):
    taps = []
    monkeypatch.setattr(flow, "ocr_probe",
                        lambda tasker, patterns: "请先停止独立路线播放" in list(patterns))
    monkeypatch.setattr(flow, "ocr_tap", lambda tasker, patterns: taps.append(list(patterns)) or True)
    monkeypatch.setattr(flow.time, "sleep", lambda s: None)
    assert flow._stop_finished_playback(object(), logging.getLogger("t")) is True
    assert taps and any(any("停止并恢复系统状态" in s for s in patterns) for patterns in taps)


def test_prepare_run_retries_after_stop_state(monkeypatch):
    posts = []

    def post(tasker, entry, override=None):
        posts.append(entry)
        return FakeJob(len(posts) > 1)  # 第一次失败，清理后第二次成功

    monkeypatch.setattr(flow, "post_and_wait", post)
    monkeypatch.setattr(flow, "ocr_probe", lambda tasker, patterns: True)
    monkeypatch.setattr(flow, "ocr_tap", lambda tasker, patterns: True)
    monkeypatch.setattr(flow, "save_shot", lambda *a, **k: None)
    monkeypatch.setattr(flow.time, "sleep", lambda s: None)

    ctl = FakeController()
    ok = flow.prepare_run_simulation(object(), ctl, {"route_text": "标准"},
                                     logging.getLogger("t"), "r")
    assert ok is True
    assert posts.count("RunPrepare") == 2


def test_prepare_run_no_extra_stop_probe_when_ready(monkeypatch):
    probes = []
    monkeypatch.setattr(flow, "post_and_wait", lambda *a, **k: FakeJob(True))
    monkeypatch.setattr(flow, "ocr_probe",
                        lambda tasker, patterns: probes.append(patterns) or False)
    monkeypatch.setattr(flow, "save_shot", lambda *a, **k: None)

    ctl = FakeController()
    ok = flow.prepare_run_simulation(object(), ctl, {"route_text": "标准"},
                                     logging.getLogger("t"), "r")
    assert ok is True
    assert probes == []  # 成功时不再做停止状态 OCR（由 pipeline 处理）


def test_cleanup_verifies_run_button(monkeypatch):
    monkeypatch.setattr(flow, "post_and_wait", lambda tasker, entry, override=None: FakeJob(True))
    monkeypatch.setattr(flow, "ocr_probe", lambda tasker, patterns: "^开始跑步$" in list(patterns))
    monkeypatch.setattr(flow, "save_shot", lambda *a, **k: None)
    monkeypatch.setattr(flow.time, "sleep", lambda s: None)

    ctl = FakeController()
    flow.cleanup_apps(object(), ctl,
                      {"run": {"package": "r", "activity": "r/.Main"},
                       "campus": {"package": "c", "activity": "c/.Main"}},
                      logging.getLogger("t"))
    assert "r/.Main" in ctl.started
    assert "r" in ctl.stopped


def test_pipeline_has_stop_state_node():
    data = json.loads((ROOT / "assets/resource/pipeline/campus_run.json")
                      .read_text(encoding="utf-8"))
    assert "CheckStopState" in data
    assert data["RunPrepare"]["next"] == ["CheckStopState"]
    assert "^停止并恢复系统状态$" in data["CheckStopState"]["expected"]
