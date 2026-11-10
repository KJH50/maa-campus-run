import json
import logging
import os
import time
import zipfile
from pathlib import Path

import pytest

from maa_campus import packaging


def _cfg(tmp_path: Path, **extra):
    cfg = {"log_dir": "logs", "pack_days": 7, "pack_include_shots": True}
    cfg.update(extra)
    return cfg


def _make_logs(tmp_path: Path) -> Path:
    logs = tmp_path / "logs"
    (logs / "shots").mkdir(parents=True)
    (logs / "webui").mkdir()
    (logs / "exports").mkdir()
    (logs / "run_20260101.log").write_text("run log\n", encoding="utf-8")
    (logs / "shots" / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (logs / "webui" / "run_x.log").write_text("web log\n", encoding="utf-8")
    (logs / ".last_success").write_text("2026-01-01", encoding="utf-8")
    (logs / "exports" / "old.zip").write_bytes(b"old")
    (logs / "config.json").write_text("secret", encoding="utf-8")
    return logs


def test_pack_logs_contains_logs_shots_state_but_not_config(tmp_path):
    _make_logs(tmp_path)
    out = tmp_path / "out.zip"
    result = packaging.pack_logs(_cfg(tmp_path), logging.getLogger("t"), output=out,
                                 days=0, root=tmp_path)
    assert Path(result["path"]).exists()
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        assert "logs/run_20260101.log" in names
        assert "logs/shots/a.png" in names
        assert "logs/webui/run_x.log" in names
        assert "logs/.last_success" in names
        assert "manifest.json" in names
        assert "logs/config.json" not in names
        assert "logs/exports/old.zip" not in names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["filters"]["days"] == 0
        assert len(manifest["files"]) == 4
    assert result["files"] == 4
    assert result["archive_bytes"] > 0


def test_pack_logs_days_filter_and_no_shots(tmp_path):
    logs = _make_logs(tmp_path)
    old = time.time() - 10 * 86400
    os.utime(logs / "run_20260101.log", (old, old))
    os.utime(logs / "shots" / "a.png", (old, old))
    result = packaging.pack_logs(_cfg(tmp_path), logging.getLogger("t"),
                                 output=tmp_path / "recent.zip", days=2, include_shots=False,
                                 root=tmp_path)
    with zipfile.ZipFile(result["path"]) as zf:
        names = zf.namelist()
        assert "logs/run_20260101.log" not in names  # 旧日志
        assert "logs/shots/a.png" not in names       # 已关闭截图
        assert "logs/webui/run_x.log" in names


def test_pack_logs_unique_output(tmp_path):
    _make_logs(tmp_path)
    first = packaging.pack_logs(_cfg(tmp_path), logging.getLogger("t"),
                                output=tmp_path / "same.zip", days=0, root=tmp_path)
    second = packaging.pack_logs(_cfg(tmp_path), logging.getLogger("t"),
                                 output=tmp_path / "same.zip", days=0, root=tmp_path)
    assert first["path"] != second["path"]
    assert Path(first["path"]).exists() and Path(second["path"]).exists()


def test_pack_logs_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        packaging.pack_logs(_cfg(tmp_path), logging.getLogger("t"), root=tmp_path)


def test_cli_pack_flag_help():
    import subprocess
    import sys

    proc = subprocess.run([sys.executable, "run.py", "--help"], cwd=packaging.PROJECT_ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0
    assert "--pack-logs" in proc.stdout
    assert "--pack-days" in proc.stdout
    assert "--pack-no-shots" in proc.stdout
    assert "--now" in proc.stdout
