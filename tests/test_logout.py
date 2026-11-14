"""退出登录路径：我的 → 退出登录 → 登录引导页。"""

import logging

import pytest

from maa_campus import flow


class FakeController:
    def __init__(self):
        self.focus_package = ""
        self.started = []
        self.clicked_keys = []

    def start_app(self, activity):
        self.started.append(activity)

    def click_key(self, key):
        self.clicked_keys.append(key)


def _cfg():
    return {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:1",
        "campus": {"package": "c", "activity": "c/.Main"},
        "log_dir": "logs",
    }


def _patch_io(monkeypatch, texts, taps=None, shots=None):
    if texts is not None:
        it = iter(texts)
        monkeypatch.setattr(flow, "ocr_texts", lambda tasker: next(it))
    monkeypatch.setattr(flow, "ocr_tap",
                        lambda tasker, patterns: (taps.extend(patterns) if taps is not None else True) or True)
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: (shots.append(tag) if shots is not None else None))
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)


def test_logout_noop_when_already_logged_out(monkeypatch):
    ctl = FakeController()
    taps = []
    _patch_io(monkeypatch, [["欢迎登录健行校园", "进入统一身份认证"]], taps)
    monkeypatch.setattr(flow, "ocr_tap",
                        lambda *a, **k: pytest.fail("已未登录时不应点击"))
    assert flow.logout_campus(object(), ctl, _cfg(), logging.getLogger("t")) is True
    assert ctl.started == ["c/.Main"]
    assert taps == []


def test_logout_from_home_via_my_tab(monkeypatch):
    ctl = FakeController()
    taps = []
    shots = []
    _patch_io(monkeypatch,
              [["首页", "继续征程", "我的"],
               ["首页", "继续征程", "我的"],
               ["退出登录", "我的", "设置"],
               ["我的"],
               ["欢迎登录健行校园", "进入统一身份认证"]],
              taps, shots)
    assert flow.logout_campus(object(), ctl, _cfg(), logging.getLogger("t")) is True
    assert taps == ["^我的$", "退出登录"]
    assert "campus_logged_out" in shots


def test_logout_handles_confirm_dialog(monkeypatch):
    ctl = FakeController()
    taps = []
    shots = []
    _patch_io(monkeypatch,
              [["首页", "我的"],
               ["首页", "我的"],
               ["退出登录", "我的"],
               ["确定退出登录吗", "确定", "取消"],
               ["欢迎登录健行校园"]],
              taps, shots)
    assert flow.logout_campus(object(), ctl, _cfg(), logging.getLogger("t")) is True
    assert "^我的$" in taps
    assert "退出登录" in taps
    assert "确定退出" in taps
    assert "campus_logged_out" in shots


def test_logout_failure_returns_false(monkeypatch):
    ctl = FakeController()
    shots = []
    _patch_io(monkeypatch, [["未知页面"]] * 9, [], shots)
    assert flow.logout_campus(object(), ctl, _cfg(), logging.getLogger("t")) is False
    assert ctl.clicked_keys  # 兜底按返回键
    assert "campus_logout_failed" in shots


def test_run_logout_success(monkeypatch):
    ctl = FakeController()
    monkeypatch.setattr(flow, "_acquire_run_lock", lambda cfg, logger: object())
    monkeypatch.setattr(flow, "_release_run_lock", lambda lock, logger: None)
    monkeypatch.setattr(flow, "ensure_emulator", lambda cfg, adb, logger: True)
    monkeypatch.setattr(flow, "build_tasker", lambda cfg, adb, logger: (object(), ctl))
    monkeypatch.setattr(flow, "logout_campus", lambda *a, **k: True)
    assert flow.run_logout(_cfg(), logging.getLogger("t")) == 0


def test_run_logout_busy_returns_5(monkeypatch):
    monkeypatch.setattr(flow, "_acquire_run_lock", lambda cfg, logger: None)
    assert flow.run_logout(_cfg(), logging.getLogger("t")) == 5


def test_run_logout_emulator_failure_returns_1(monkeypatch):
    monkeypatch.setattr(flow, "_acquire_run_lock", lambda cfg, logger: object())
    monkeypatch.setattr(flow, "_release_run_lock", lambda lock, logger: None)
    monkeypatch.setattr(flow, "ensure_emulator", lambda cfg, adb, logger: False)
    assert flow.run_logout(_cfg(), logging.getLogger("t")) == 1


def test_run_logout_flow_failure_returns_3(monkeypatch):
    monkeypatch.setattr(flow, "_acquire_run_lock", lambda cfg, logger: object())
    monkeypatch.setattr(flow, "_release_run_lock", lambda lock, logger: None)
    monkeypatch.setattr(flow, "ensure_emulator", lambda cfg, adb, logger: True)
    monkeypatch.setattr(flow, "build_tasker", lambda cfg, adb, logger: (object(), FakeController()))
    monkeypatch.setattr(flow, "logout_campus", lambda *a, **k: False)
    assert flow.run_logout(_cfg(), logging.getLogger("t")) == 3
