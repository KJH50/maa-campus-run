import logging
import os

from maa_campus import flow


def _cfg(instance="mumu-1"):
    return {"log_dir": "logs", "instance_name": instance, "run_lock_stale_seconds": 60}


def _logger():
    return logging.getLogger("test-lock")


def test_lock_conflict_and_release(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = _cfg()
    lock = flow._acquire_run_lock(cfg, _logger())
    assert lock is not None and lock.exists()
    assert flow._acquire_run_lock(cfg, _logger()) is None  # 冲突
    flow._release_run_lock(lock, _logger())
    assert not lock.exists()
    again = flow._acquire_run_lock(cfg, _logger())
    assert again is not None
    flow._release_run_lock(again, _logger())


def test_stale_lock_reclaimed(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = _cfg()
    lock = flow._acquire_run_lock(cfg, _logger())
    assert lock is not None
    old = 1_000_000
    os.utime(lock, (old, old))
    recovered = flow._acquire_run_lock(cfg, _logger())
    assert recovered is not None and recovered.exists()
    flow._release_run_lock(recovered, _logger())


def test_lock_is_per_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    lock1 = flow._acquire_run_lock(_cfg("mumu-1"), _logger())
    lock2 = flow._acquire_run_lock(_cfg("mumu-2"), _logger())
    assert lock1 is not None and lock2 is not None
    flow._release_run_lock(lock1, _logger())
    flow._release_run_lock(lock2, _logger())


def test_run_flow_returns_5_when_locked(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = _cfg()
    lock = flow._acquire_run_lock(cfg, _logger())
    called = []
    monkeypatch.setattr(flow, "_run_flow_impl", lambda *a, **k: called.append(1) or 0)
    assert flow.run_flow(cfg, _logger(), dry=False) == 5
    assert called == []
    flow._release_run_lock(lock, _logger())


def test_dry_run_skips_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = _cfg()
    lock = flow._acquire_run_lock(cfg, _logger())
    called = []
    monkeypatch.setattr(flow, "_run_flow_impl", lambda *a, **k: called.append(1) or 0)
    assert flow.run_flow(cfg, _logger(), dry=True) == 0
    assert called == [1]  # dry 不占锁，直接执行
    flow._release_run_lock(lock, _logger())
