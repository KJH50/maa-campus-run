import json

import pytest

from maa_campus.config import load_config, validate_config


def test_validate_ok():
    cfg = {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:1",
        "campus": {"package": "a.b", "activity": "a.b/.Main"},
        "run": {"package": "c.d", "activity": "c.d/.Main"},
    }
    validate_config(cfg)


def test_validate_missing_lists_all():
    with pytest.raises(ValueError) as exc:
        validate_config({})
    msg = str(exc.value)
    for key in ("adb_path", "adb_serial", "campus.package", "campus.activity",
                "run.package", "run.activity"):
        assert key in msg


def test_validate_bad_regex():
    cfg = {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:1",
        "campus": {"package": "a.b", "activity": "a.b/.Main"},
        "run": {"package": "c.d", "activity": "c.d/.Main"},
        "distance_regex": "[",
    }
    with pytest.raises(ValueError, match="distance_regex"):
        validate_config(cfg)


def test_load_config_merges_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"adb_serial": "1.2.3.4:5", "campus": {"package": "x"}}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["adb_serial"] == "1.2.3.4:5"
    assert cfg["log_retention_days"] == 14
    assert cfg["campus"]["package"] == "x"
    assert cfg["campus"]["activity"] == ""
    assert cfg["instances"] == []


def _base_cfg(**extra):
    cfg = {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:1",
        "campus": {"package": "a.b", "activity": "a.b/.Main"},
        "run": {"package": "c.d", "activity": "c.d/.Main"},
    }
    cfg.update(extra)
    return cfg


def test_validate_instances_ok():
    validate_config(_base_cfg(instances=[
        {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
        {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2},
    ]))


def test_validate_instances_missing_serial():
    with pytest.raises(ValueError, match="adb_serial"):
        validate_config(_base_cfg(instances=[{"name": "mumu-1"}]))


def test_validate_instances_duplicate_serial():
    with pytest.raises(ValueError, match="重复"):
        validate_config(_base_cfg(instances=[
            {"name": "a", "adb_serial": "127.0.0.1:16416"},
            {"name": "b", "adb_serial": "127.0.0.1:16416"},
        ]))
