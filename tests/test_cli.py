import pytest

from maa_campus import cli


def _cfg():
    return {
        "adb_serial": "127.0.0.1:1",
        "mumu_index": 9,
        "instances": [
            {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
            {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2},
        ],
    }


def test_select_instance_by_name():
    cfg = _cfg()
    cli.apply_instance_selection(cfg, "mumu-2")
    assert cfg["adb_serial"] == "127.0.0.1:16448"
    assert cfg["mumu_index"] == 2
    assert cfg["instance_name"] == "mumu-2"
    assert cfg["instances"] == []


def test_select_instance_by_index():
    cfg = _cfg()
    cli.apply_instance_selection(cfg, "1")
    assert cfg["adb_serial"] == "127.0.0.1:16416"
    assert cfg["mumu_index"] == 1
    assert cfg["instance_name"] == "mumu-1"
    assert cfg["instances"] == []


def test_select_instance_unknown():
    cfg = _cfg()
    with pytest.raises(ValueError, match="找不到实例"):
        cli.apply_instance_selection(cfg, "mumu-3")


def test_select_instance_without_instances():
    cfg = {"instances": []}
    with pytest.raises(ValueError, match="未配置 instances"):
        cli.apply_instance_selection(cfg, "mumu-1")


def test_logout_requires_instance_for_multi(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda path: _cfg())
    monkeypatch.delenv("MAA_CAMPUS_INSTANCE", raising=False)
    monkeypatch.setattr(cli.sys, "argv", ["run.py", "--logout"])
    assert cli.main() == 1
    assert "--instance" in capsys.readouterr().err


def test_logout_conflicts_with_now(monkeypatch):
    monkeypatch.setattr(cli.sys, "argv", ["run.py", "--logout", "--now"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
