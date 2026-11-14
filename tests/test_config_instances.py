"""多模拟器实例配置：实例级覆盖与实例级登录账号。"""

from pathlib import Path

import pytest

from maa_campus import cli, config

ROOT = Path(__file__).resolve().parent.parent


def _cfg():
    return config.load_config(ROOT / "config.example.json")


def test_apply_instance_overrides_adb_and_login():
    cfg = _cfg()
    cfg["campus"]["login"] = {"enabled": True, "username": "global",
                              "password": "global-pass", "remember_week": True}
    inst = {
        "name": "mumu-2",
        "adb_serial": "127.0.0.1:16448",
        "mumu_index": 2,
        "login": {"username": "inst", "password": "inst-pass"},
    }
    config.apply_instance(cfg, inst, 1)
    assert cfg["adb_serial"] == "127.0.0.1:16448"
    assert cfg["mumu_index"] == 2
    assert cfg["instance_name"] == "mumu-2"
    assert cfg["campus"]["login"]["username"] == "inst"
    assert cfg["campus"]["login"]["password"] == "inst-pass"
    # 实例未覆盖的字段沿用全局配置
    assert cfg["campus"]["login"]["enabled"] is True
    assert cfg["campus"]["login"]["remember_week"] is True
    assert cfg["_instance_login_configured"] is True


def test_apply_instance_without_login_keeps_global():
    cfg = _cfg()
    cfg["campus"]["login"] = {"username": "global", "password": "global-pass"}
    inst = {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1}
    config.apply_instance(cfg, inst, 0)
    assert cfg["campus"]["login"]["username"] == "global"
    assert cfg["instance_name"] == "mumu-1"
    assert "_instance_login_configured" not in cfg


def test_validate_instance_login_must_be_object():
    cfg = _cfg()
    cfg["instances"] = [{"name": "mumu-1", "adb_serial": "127.0.0.1:16416",
                         "login": "bad"}]
    with pytest.raises(ValueError, match="login 必须是对象"):
        config.validate_config(cfg)


def test_validate_instance_login_password_must_be_string():
    cfg = _cfg()
    cfg["instances"] = [{"name": "mumu-1", "adb_serial": "127.0.0.1:16416",
                         "login": {"username": "u", "password": 123}}]
    with pytest.raises(ValueError, match="password 必须是字符串"):
        config.validate_config(cfg)


def test_validate_instance_login_enabled_must_be_bool():
    cfg = _cfg()
    cfg["instances"] = [{"name": "mumu-1", "adb_serial": "127.0.0.1:16416",
                         "login": {"enabled": "yes"}}]
    with pytest.raises(ValueError, match="enabled 必须是布尔值"):
        config.validate_config(cfg)


def test_instance_selection_applies_login():
    cfg = _cfg()
    cfg["campus"]["login"] = {"enabled": True, "username": "global", "password": "gp"}
    cfg["instances"] = [
        {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
        {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2,
         "login": {"username": "inst2", "password": "p2"}},
    ]
    cli.apply_instance_selection(cfg, "mumu-2")
    assert cfg["instance_name"] == "mumu-2"
    assert cfg["instances"] == []
    assert cfg["campus"]["login"]["username"] == "inst2"
    assert cfg["campus"]["login"]["password"] == "p2"
