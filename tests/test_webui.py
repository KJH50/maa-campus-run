import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from maa_campus import webui


def _config(tmp_path: Path, **extra) -> Path:
    cfg = {
        "adb_path": "adb.exe",
        "adb_serial": "127.0.0.1:16416",
        "campus": {"package": "yx.c520.xyz", "activity": "yx.c520.xyz/.MainActivity"},
        "run": {"package": "local.runsimulation.publicapp", "activity": "local.runsimulation.publicapp/.MainActivity"},
        "instances": [
            {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
            {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2},
        ],
        "log_dir": "logs",
    }
    cfg.update(extra)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return path


def _make_app(tmp_path: Path, **extra) -> webui.App:
    return webui.App(config_path=_config(tmp_path, **extra), root=tmp_path)


def test_safe_log_path_blocks_traversal(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    assert webui._safe_log_path(log_dir, "run_20260101.log") is not None
    assert webui._safe_log_path(log_dir, "webui/run_20260101_120000.log") is not None
    assert webui._safe_log_path(log_dir, "../config.json") is None
    assert webui._safe_log_path(log_dir, "evil.txt") is None


def test_start_run_builds_expected_cli_args(tmp_path, monkeypatch):
    app = _make_app(tmp_path)
    captured = {}

    def fake_start(args, title):
        captured["args"] = args
        captured["title"] = title
        return {"status": "running", "lines": []}

    monkeypatch.setattr(app.jobs, "start", fake_start)
    job = app.start_run("now", force=True, no_record=True, instance="mumu-2")
    assert job["status"] == "running"
    assert captured["args"][:1] == ["--now"]
    assert "--force" in captured["args"]
    assert "--no-record" in captured["args"]
    idx = captured["args"].index("--instance")
    assert captured["args"][idx + 1] == "mumu-2"
    assert captured["args"][-2] == "--config"
    assert captured["title"]


def test_start_run_rejects_bad_mode(tmp_path):
    app = _make_app(tmp_path)
    with pytest.raises(ValueError):
        app.start_run("not-a-mode")


def test_status_reads_config_instances_and_markers(tmp_path):
    app = _make_app(tmp_path, max_runs=60)
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / ".last_success_mumu-1").write_text("2026-01-01", encoding="utf-8")
    (log_dir / ".max_runs_reached_mumu-2.json").write_text(
        json.dumps({"count": 60, "max": 60}), encoding="utf-8")
    (log_dir / "run_20260101.log").write_text(
        "2026-01-01 06:30:00 [INFO] 本次结束距离：2.04 km\n"
        "2026-01-01 06:30:00 [INFO] 识别到已跑次数：26 次\n"
        "2026-01-01 06:30:00 [INFO] 全部完成：距离 2.05 km\n",
        encoding="utf-8")
    st = app.status()
    assert st["config_error"] is None
    assert len(st["instances"]) == 2
    assert st["instances"][0]["last_success"]["date"] == "2026-01-01"
    assert st["instances"][1]["max_reached"]["count"] == 60
    assert st["latest_run"]["target_km"] == 2.04
    assert st["latest_run"]["run_count"] == 26


def test_status_survives_invalid_config(tmp_path):
    app = webui.App(config_path=tmp_path / "missing.json", root=tmp_path)
    st = app.status()
    assert st["ok"] is True
    assert st["config_error"]


def test_save_config_validates_and_backs_up(tmp_path):
    app = _make_app(tmp_path)
    raw = json.loads(app.config_path.read_text(encoding="utf-8"))
    raw["max_runs"] = 60
    result = app.save_config(raw)
    assert Path(result["config_path"]).exists()
    assert result["backup"] and Path(result["backup"]).exists()
    assert json.loads(app.config_path.read_text(encoding="utf-8"))["max_runs"] == 60

    with pytest.raises(ValueError):
        app.save_config({"adb_path": ""})


def test_job_manager_runs_a_safe_subprocess(tmp_path):
    (tmp_path / "run.py").write_text(
        "import sys\n"
        "print('hello-from-fake-run', flush=True)\n"
        "print('exit', flush=True)\n",
        encoding="utf-8")
    manager = webui.JobManager(tmp_path)
    manager.start(["--config", "x"], "fake job")
    deadline = time.time() + 15
    while manager.snapshot()["status"] == "running" and time.time() < deadline:
        time.sleep(0.1)
    snap = manager.snapshot()
    assert snap["status"] == "succeeded"
    assert snap["exit_code"] == 0
    assert any("hello-from-fake-run" in line for line in snap["lines"])
    assert Path(snap["log_file"]).exists()


def test_http_endpoints(tmp_path):
    app = _make_app(tmp_path)
    server = webui.create_server(app, host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(path):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def post(path, obj):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        assert get("/")[0] == 200
        assert b"<!DOCTYPE html>" in get("/")[1]
        assert get("/app.js")[0] == 200
        assert get("/style.css")[0] == 200
        status, body = get("/api/status")
        assert status == 200
        assert json.loads(body)["ok"] is True
        assert post("/api/config", {"config": {"adb_path": ""}})[0] == 400
        cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        cfg["max_runs"] = 60
        status, _ = post("/api/config", {"config": cfg})
        assert status == 200
        assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["max_runs"] == 60
        assert list(tmp_path.glob("config.json.bak-*"))
        assert post("/api/run", {"mode": "bad"})[0] == 400
        assert get("/api/logs/view?name=../config.json")[0] == 400

        log_dir = tmp_path / "logs"
        log_dir.mkdir(exist_ok=True)
        (log_dir / "run_20260101.log").write_text("hello\n", encoding="utf-8")
        status, body = post("/api/export", {"days": 0})
        assert status == 200
        export = json.loads(body)["export"]
        assert export["files"] >= 1
        status, zbytes = get(export["download_url"])
        assert status == 200
        assert zbytes[:2] == b"PK"
    finally:
        server.shutdown()
        server.server_close()


def test_cli_web_flags_are_additive():
    proc = subprocess.run([sys.executable, "-X", "utf8", "run.py", "--help"], cwd=webui.PROJECT_ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0
    assert "--web " in proc.stdout
    assert "--web-port" in proc.stdout
    assert "--now" in proc.stdout  # 原有入口仍在
