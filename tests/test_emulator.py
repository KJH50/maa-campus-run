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
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: True)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": True}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is True
    assert calls == ["launch"]


def test_ensure_emulator_restart_once(monkeypatch):
    calls = []
    monkeypatch.setattr(emulator, "_mumu_control",
                        lambda manager, index, action, logger: calls.append(action) or True)
    waits = [False, True]
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: waits.pop(0))
    monkeypatch.setattr(emulator.time, "sleep", lambda seconds: None)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": True}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is True
    assert calls == ["launch", "shutdown", "launch"]


def test_ensure_emulator_no_restart_when_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(emulator, "_mumu_control",
                        lambda manager, index, action, logger: calls.append(action) or True)
    monkeypatch.setattr(emulator, "_wait_boot", lambda adb, logger, timeout: False)
    cfg = {"mumu_manager": str(Path(emulator.__file__)), "mumu_index": 1,
           "emulator_boot_timeout_seconds": 60, "emulator_restart_on_fail": False}
    assert emulator.ensure_emulator(cfg, _FakeAdb([False]), logging.getLogger("t")) is False
    assert calls == ["launch"]
