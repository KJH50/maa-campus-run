import logging
import os

from PIL import Image

from maa_campus import ai_watch
from maa_campus.page_observer import OCText, PageSnapshot


class FakeAdb:
    def __init__(self):
        self.calls = []

    def connect(self, wait_seconds=5):
        return True

    def get_display(self, package):
        return 0

    def tap(self, display, x, y):
        self.calls.append(("tap", x, y))

    def input_text(self, display, text):
        self.calls.append(("input", text))

    def swipe(self, display, x1, y1, x2, y2, duration_ms=300):
        self.calls.append(("swipe", x1, y1, x2, y2))


class FakeController:
    pass


def _cfg(tmp_path):
    return {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:1",
        "campus": {"package": "pkg", "activity": "pkg/.Main"},
        "ai_watch": {
            "enabled": True,
            "log_dir": str(tmp_path / "logs"),
            "mode": "interval",
            "interval_seconds": 60,
            "max_retries": 0,
            "backoff_seconds": 0,
            "lock_stale_seconds": 300,
            "capture": {"format": "jpeg", "quality": 70, "max_width": 320,
                        "mask_regions": []},
            "target": {"package": "pkg", "display": 0, "url": "app://test"},
            "rules": {"expected_selectors": [], "unique_selectors": []},
            "action": {"allowed": ["click", "input", "scroll", "wait", "retry", "abort"],
                       "confidence_threshold": 0.5, "max_wait_seconds": 10,
                       "max_retries": 2},
            "ai": {"provider": "mock", "mock_response": {
                "action": "click", "target": "开始", "params": {},
                "confidence": 0.9, "reason": "mock"}},
        },
    }


def _snap():
    return PageSnapshot(image=Image.new("RGB", (320, 640), "white"),
                        ocr=[OCText("开始", 0.9, (100, 200, 50, 20))],
                        blank_ratio=0.0, url="app://test")


def test_lock_acquire_release(tmp_path):
    lock = ai_watch._acquire_lock(tmp_path)
    assert lock is not None
    assert ai_watch._acquire_lock(tmp_path) is None
    ai_watch._release_lock(lock)
    assert ai_watch._acquire_lock(tmp_path) is not None


def test_lock_stale_reclaimed(tmp_path):
    lock = ai_watch._acquire_lock(tmp_path)
    assert lock is not None
    old = 1_000_000
    os.utime(lock, (old, old))
    assert ai_watch._acquire_lock(tmp_path, stale_seconds=1) is not None


def test_run_cycle_normal_page_no_upload(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    adb = FakeAdb()
    monkeypatch.setattr(ai_watch, "make_adb", lambda cfg: adb)
    monkeypatch.setattr(ai_watch, "build_tasker", lambda cfg, adb, logger: (object(), FakeController()))
    monkeypatch.setattr(ai_watch, "build_snapshot", lambda *a, **k: _snap())

    def fail_request(*a, **k):
        raise AssertionError("正常页面不应调用 AI")

    monkeypatch.setattr(ai_watch, "request_decision", fail_request)
    record = ai_watch.run_cycle(cfg, logging.getLogger("t"), env={})
    assert record["status"] == "normal"
    assert adb.calls == []


def test_run_cycle_uncertain_executes_action(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg["ai_watch"]["rules"]["expected_selectors"] = ["^不存在的按钮$"]
    adb = FakeAdb()
    monkeypatch.setattr(ai_watch, "make_adb", lambda cfg: adb)
    monkeypatch.setattr(ai_watch, "build_tasker", lambda cfg, adb, logger: (object(), FakeController()))
    monkeypatch.setattr(ai_watch, "build_snapshot", lambda *a, **k: _snap())
    record = ai_watch.run_cycle(cfg, logging.getLogger("t"), env={})
    assert record["status"] == "done"
    assert record["decision"]["action"] == "click"
    assert adb.calls and adb.calls[0][0] == "tap"


def test_run_ai_watch_once(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(ai_watch, "_cycle_with_retries",
                        lambda cfg, logger, env=None, opener=None: {"status": "normal"})
    assert ai_watch.run_ai_watch(cfg, logging.getLogger("t"), once=True) == 0
