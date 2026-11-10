import pytest

from maa_campus import desktop


def _fields(**overrides):
    fields = {
        "target_distance_km": "2.10",
        "max_runs": "60",
        "check_after_minutes": "",
        "max_run_minutes": "",
        "adb_serial": "127.0.0.1:16416",
        "mumu_index": "",
        "instance_start_stagger_seconds": "",
        "skip_if_success_today": False,
        "shutdown_emulator": True,
        "close_apps": False,
        "refresh_window_on_start": True,
        "run_windows": '[{"start":"06:30","end":"07:30"}]',
        "instances": "[]",
    }
    fields.update(overrides)
    return fields


def test_merge_quick_config_updates_and_removes_optional_defaults():
    raw = {"adb_serial": "old", "run_windows": [], "instances": []}
    cfg = desktop.merge_quick_config(raw, _fields())
    assert cfg["target_distance_km"] == 2.10
    assert cfg["max_runs"] == 60
    assert cfg["adb_serial"] == "127.0.0.1:16416"
    assert cfg["skip_if_success_today"] is False
    assert cfg["close_apps"] is False
    assert cfg["run_windows"] == [{"start": "06:30", "end": "07:30"}]
    assert cfg["instances"] == []
    # 空的可选项被删除，交由配置默认值处理
    assert "check_after_minutes" not in cfg
    assert "max_run_minutes" not in cfg
    assert "mumu_index" not in cfg
    assert "instance_start_stagger_seconds" not in cfg


def test_merge_quick_config_rejects_bad_json_array():
    with pytest.raises(ValueError):
        desktop.merge_quick_config({}, _fields(run_windows="{bad json"))
    with pytest.raises(ValueError):
        desktop.merge_quick_config({}, _fields(instances='{"name":"x"}'))


def test_parse_json_list():
    assert desktop.parse_json_list("", "x") == []
    assert desktop.parse_json_list("[1,2]", "x") == [1, 2]
    with pytest.raises(ValueError):
        desktop.parse_json_list("[1,2", "x")


def test_mode_mapping():
    assert desktop.RUN_MODE_LABELS[desktop.DEFAULT_MODE_LABEL] == "dry"
    assert set(desktop.RUN_MODE_LABELS.values()) == {"dry", "now", "window_once", "ai_watch_once"}


def test_launch_without_display_returns_error(monkeypatch):
    class FakeTk:
        def __init__(self):
            raise desktop.tk.TclError("no display")

    monkeypatch.setattr(desktop.tk, "Tk", FakeTk)
    assert desktop.launch() == 1


def test_cli_desktop_flag_is_additive():
    import subprocess
    import sys

    from maa_campus import webui

    proc = subprocess.run([sys.executable, "-X", "utf8", "run.py", "--help"], cwd=webui.PROJECT_ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0
    assert "--desktop" in proc.stdout
    assert "--web" in proc.stdout
    assert "--now" in proc.stdout
