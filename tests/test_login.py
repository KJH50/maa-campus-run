import logging

import pytest

from maa_campus import flow


class FakeJob:
    def __init__(self, ok=True):
        self.succeeded = ok


class FakeController:
    def __init__(self):
        self.focus_package = ""
        self.started = []
        self.inputs = []

    def start_app(self, activity):
        self.started.append(activity)

    def input_text(self, text):
        self.inputs.append(text)
        return True


def _cfg(username="test-user", password="test-pass"):
    return {"campus": {"package": "c", "activity": "c/.Main", "login": {
        "enabled": True, "username": username, "password": password,
        "remember_week": False,
    }}}


def test_login_credentials_env_override(monkeypatch):
    monkeypatch.setenv("MAA_CAMPUS_USERNAME", "env-user")
    monkeypatch.setenv("MAA_CAMPUS_PASSWORD", "env-pass")
    enabled, username, password, remember = flow._campus_login_credentials(_cfg())
    assert enabled is True
    assert username == "env-user"
    assert password == "env-pass"
    assert remember is False


def test_auto_login_missing_credentials(monkeypatch):
    cfg = _cfg(username="", password="")
    ctl = FakeController()
    assert flow.auto_login_campus(object(), ctl, cfg, logging.getLogger("t")) is False
    assert ctl.inputs == []


def test_auto_login_success(monkeypatch):
    cfg = _cfg()
    ctl = FakeController()
    saved = []
    monkeypatch.setattr(flow, "post_and_wait", lambda *a, **k: FakeJob(True))
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["继续征程"])
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: saved.append(tag) or None)
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

    assert flow.auto_login_campus(object(), ctl, cfg, logging.getLogger("t")) is True
    assert ctl.inputs == ["test-user", "test-pass"]
    assert "campus_logged_in" in saved


def test_auto_login_failure_message(monkeypatch):
    cfg = _cfg()
    ctl = FakeController()
    saved = []
    monkeypatch.setattr(flow, "post_and_wait", lambda *a, **k: FakeJob(True))
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["用户名或密码错误"])
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: saved.append(tag) or None)
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

    assert flow.auto_login_campus(object(), ctl, cfg, logging.getLogger("t")) is False
    assert "campus_login_failed" in saved


def test_auto_login_handles_auth_portal(monkeypatch):
    cfg = _cfg()
    ctl = FakeController()
    saved = []
    posts = []
    responses = iter([
        ["健行校园后台管理系统", "进入统一身份认证"],
        ["继续征程"],
    ])

    def post(tasker, entry, override=None):
        posts.append((entry, override))
        return FakeJob(True)

    monkeypatch.setattr(flow, "post_and_wait", post)
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: next(responses))
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: saved.append(tag) or None)
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

    assert flow.auto_login_campus(object(), ctl, cfg, logging.getLogger("t")) is True
    assert ctl.inputs == ["test-user", "test-pass"]
    assert any(entry == "TapText" and "进入统一身份认证" in str(override)
               for entry, override in posts)
    assert "campus_logged_in" in saved


def test_auto_login_uses_cached_session(monkeypatch):
    """认证平台已有缓存会话时，点击引导页可能直接完成登录（不出现账号密码页）。"""
    cfg = _cfg()
    ctl = FakeController()
    saved = []
    texts = iter([["进入统一身份认证"], ["继续征程"], ["继续征程"]])

    def post(tasker, entry, override=None):
        patterns = str(((override or {}).get("TapText") or {}).get("expected") or [])
        return FakeJob("用户名" not in patterns)

    monkeypatch.setattr(flow, "post_and_wait", post)
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: next(texts))
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: saved.append(tag) or None)
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

    assert flow.auto_login_campus(object(), ctl, cfg, logging.getLogger("t")) is True
    assert ctl.inputs == []
    assert "campus_logged_in" in saved


def test_enter_auth_from_landing_detects_cached_login(monkeypatch):
    texts = iter([["进入统一身份认证"], ["继续征程"]])
    monkeypatch.setattr(flow, "post_and_wait", lambda *a, **k: FakeJob(True))
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: next(texts))
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)
    assert flow._enter_auth_from_landing(object(), FakeController(),
                                         logging.getLogger("t")) is True


def test_login_credentials_per_instance_env(monkeypatch):
    """多模拟器：实例级环境变量优先于全局环境变量与配置。"""
    monkeypatch.setenv("MAA_CAMPUS_USERNAME", "global-user")
    monkeypatch.setenv("MAA_CAMPUS_PASSWORD", "global-pass")
    monkeypatch.setenv("MAA_CAMPUS_USERNAME_MUMU_2", "inst-user")
    monkeypatch.setenv("MAA_CAMPUS_PASSWORD_MUMU_2", "inst-pass")
    cfg = _cfg(username="cfg-user", password="cfg-pass")
    cfg["instance_name"] = "mumu-2"
    enabled, username, password, _ = flow._campus_login_credentials(cfg)
    assert enabled is True
    assert username == "inst-user"
    assert password == "inst-pass"


def test_login_credentials_global_env_fallback(monkeypatch):
    """实例级环境变量未设置时回退到全局环境变量。"""
    monkeypatch.setenv("MAA_CAMPUS_USERNAME", "global-user")
    monkeypatch.setenv("MAA_CAMPUS_PASSWORD", "global-pass")
    cfg = _cfg(username="cfg-user", password="cfg-pass")
    cfg["instance_name"] = "mumu-1"
    _, username, password, _ = flow._campus_login_credentials(cfg)
    assert username == "global-user"
    assert password == "global-pass"


def test_campus_login_state_detects_auth_landing(monkeypatch):
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["欢迎登录", "进入统一身份认证"])
    assert flow._campus_login_state(object()) == "login"


def test_campus_login_state_detects_logged_in(monkeypatch):
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["继续征程"])
    assert flow._campus_login_state(object()) == "logged_in"


def test_campus_login_state_unknown(monkeypatch):
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: [])
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)
    assert flow._campus_login_state(object(), timeout=2) == "unknown"


def test_ensure_campus_login_opens_app_and_logs_in(monkeypatch):
    cfg = _cfg()
    ctl = FakeController()
    monkeypatch.setattr(flow, "_campus_login_state", lambda tasker, timeout=10.0: "login")
    monkeypatch.setattr(flow, "auto_login_campus", lambda *a, **k: True)
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

    assert flow.ensure_campus_login(object(), ctl, cfg, logging.getLogger("t"),
                                    start_app=True) is True
    assert ctl.started == ["c/.Main"]
    assert cfg["_campus_login_state"] == "ok"


def test_ensure_campus_login_skips_when_already_logged_in(monkeypatch):
    cfg = _cfg()
    monkeypatch.setattr(flow, "_campus_login_state", lambda tasker, timeout=10.0: "logged_in")
    monkeypatch.setattr(flow, "auto_login_campus",
                        lambda *a, **k: pytest.fail("已登录时不应进入登录流程"))
    assert flow.ensure_campus_login(object(), FakeController(), cfg,
                                    logging.getLogger("t")) is True
    assert cfg["_campus_login_state"] == "ok"


def test_ensure_campus_login_reuses_cached_state(monkeypatch):
    cfg = _cfg()
    cfg["_campus_login_state"] = "ok"
    monkeypatch.setattr(flow, "_campus_login_state",
                        lambda tasker, timeout=10.0: pytest.fail("不应重复 OCR 检测"))
    assert flow.ensure_campus_login(object(), FakeController(), cfg,
                                    logging.getLogger("t")) is True


def test_ensure_campus_login_failure_marks_required(monkeypatch):
    cfg = _cfg()
    saved = []
    monkeypatch.setattr(flow, "_campus_login_state", lambda tasker, timeout=10.0: "login")
    monkeypatch.setattr(flow, "auto_login_campus", lambda *a, **k: False)
    monkeypatch.setattr(flow, "save_shot",
                        lambda controller, tag, logger: saved.append(tag) or None)
    assert flow.ensure_campus_login(object(), FakeController(), cfg,
                                    logging.getLogger("t")) is False
    assert cfg["_campus_login_required"] is True
    assert "campus_login_required" in saved


def test_ensure_campus_login_unknown_does_not_fail(monkeypatch):
    cfg = _cfg()
    called = []
    monkeypatch.setattr(flow, "_campus_login_state", lambda tasker, timeout=10.0: "unknown")
    monkeypatch.setattr(flow, "auto_login_campus",
                        lambda *a, **k: called.append(True) or True)
    assert flow.ensure_campus_login(object(), FakeController(), cfg,
                                    logging.getLogger("t")) is True
    assert called == []
