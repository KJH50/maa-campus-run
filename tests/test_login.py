import logging

from maa_campus import flow


class FakeJob:
    def __init__(self, ok=True):
        self.succeeded = ok


class FakeController:
    def __init__(self):
        self.focus_package = ""
        self.inputs = []

    def input_text(self, text):
        self.inputs.append(text)
        return True


def _cfg(username="test-user", password="test-pass"):
    return {"campus": {"package": "c", "login": {
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
