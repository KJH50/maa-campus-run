import logging
from pathlib import Path

from maa_campus import emulator


class _FakeAdb:
    def __init__(self, results):
        self.results = list(results)

    def connect(self, wait_seconds=60):
        return self.results.pop(0) if self.results else True


def test_ensure_emulator_without_manager():
    cfg = {"emulator_boot_timeout_seconds": 5}
    adb = _FakeAdb([False, True])
    assert emulator.ensure_emulator(cfg, adb, logging.getLogger("t")) is True


def test_ensure_emulator_launch_ok(monkeypatch):
    calls = []
    monkeypatch.setattr(emulator, "_mumu_control",
                        lambda manager, index, action, logger: calls.append(action) or True)
    monkeypatch.setattr(emulator, "_mumu_info", lambda manager, index: {})
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: True)
    monkeypatch.setattr(emulator, "_refresh_player_window", lambda *a, **k: True)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": True}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is True
    assert calls == ["launch"]


def test_ensure_emulator_already_running_no_launch(monkeypatch):
    calls = []
    refreshes = []
    monkeypatch.setattr(emulator, "_mumu_control",
                        lambda manager, index, action, logger: calls.append(action) or True)
    monkeypatch.setattr(emulator, "_mumu_info",
                        lambda manager, index: {"state": "start_finished"})
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: True)
    monkeypatch.setattr(emulator, "_refresh_player_window",
                        lambda manager, index, logger: refreshes.append(index) or True)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": True}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is True
    assert calls == []  # 已在运行：不重复 launch
    assert refreshes == [1]


def test_ensure_emulator_connected_refreshes_window(monkeypatch):
    refreshes = []
    monkeypatch.setattr(emulator, "_refresh_player_window",
                        lambda manager, index, logger: refreshes.append(index) or True)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 2,
           "refresh_window_on_start": True}
    assert emulator.ensure_emulator(cfg, _FakeAdb([True]), logging.getLogger("t")) is True
    assert refreshes == [2]


def test_nudge_window_invalid_handle():
    assert emulator._nudge_window(0, logging.getLogger("t")) is False


def test_refresh_player_window_without_handle(monkeypatch):
    monkeypatch.setattr(emulator, "_mumu_control", lambda *a, **k: True)
    monkeypatch.setattr(emulator, "_mumu_info", lambda manager, index: {})
    assert emulator._refresh_player_window("mgr.exe", 1, logging.getLogger("t")) is False


def test_ensure_emulator_restart_once(monkeypatch):
    calls = []
    monkeypatch.setattr(emulator, "_mumu_control",
                        lambda manager, index, action, logger: calls.append(action) or True)
    monkeypatch.setattr(emulator, "_mumu_info", lambda manager, index: {})
    waits = [False, True]
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: waits.pop(0))
    monkeypatch.setattr(emulator.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(emulator, "_refresh_player_window", lambda *a, **k: True)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": True}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is True
    assert calls == ["launch", "shutdown", "launch"]


def test_ensure_emulator_no_restart_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(emulator, "_mumu_control",
                        lambda manager, index, action, logger: calls.append(action) or True)
    monkeypatch.setattr(emulator, "_mumu_info", lambda manager, index: {})
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: False)
    monkeypatch.setattr(emulator, "_refresh_player_window", lambda *a, **k: True)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": False}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is False
    assert calls == ["launch"]
