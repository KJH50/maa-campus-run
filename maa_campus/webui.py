"""本地 Web 控制台（补充入口，不替代 CLI / 配置 / 脚本）。

设计原则：
- 仅使用 Python 标准库（http.server + subprocess + json），不引入前端构建链和额外依赖；
- 所有“执行”都通过现有 `run.py` 命令行子进程完成，不复制、不修改业务逻辑；
- 现有 CLI、config.json、定时任务、oneclick 脚本全部保持不变；
- 默认只监听 127.0.0.1，适合本机使用；配置写入前自动备份并沿用现有校验。

启动：python run.py --web
      （或 python -m maa_campus.webui）
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .config import load_config, validate_config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "webui_static"
DEFAULT_CONFIG = PROJECT_ROOT / "config.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

LOG_NAME_PATTERNS = [
    re.compile(r"^run_[0-9_A-Za-z.-]+\.log$"),
    re.compile(r"^ai_watch_[0-9_A-Za-z.-]+\.log$"),
    re.compile(r"^alerts_[0-9_A-Za-z.-]+\.log$"),
    re.compile(r"^webui/run_[0-9_A-Za-z.-]+\.log$"),
    re.compile(r"^oneclick/[0-9_A-Za-z.-]+\.log$"),
]

RUN_MODES = {
    "now": ("立即执行（真实跑步）", ["--now"]),
    "dry": ("安全演练（dry，不点击）", ["--now", "--dry"]),
    "window_once": ("单时间段执行（--window-once）", ["--window-once"]),
    "ai_watch_once": ("AI 页面检查一轮（--ai-watch-once）", ["--ai-watch-once"]),
}


class JobError(RuntimeError):
    """任务启动/停止失败（用于转换为 HTTP 400/409）。"""


def _today() -> str:
    return date.today().isoformat()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _instance_key(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name) if name else "default"


def _log_dir(root: Path, cfg: dict | None) -> Path:
    return root / ((cfg or {}).get("log_dir") or "logs")


def _safe_log_path(log_dir: Path, name: str) -> Path | None:
    """只允许查看 logs 下已知格式的日志，防止路径穿越。"""
    name = (name or "").replace("\\", "/").lstrip("/")
    if ".." in name.split("/"):
        return None
    if not any(p.match(name) for p in LOG_NAME_PATTERNS):
        return None
    path = (log_dir / name).resolve()
    try:
        path.relative_to(log_dir.resolve())
    except ValueError:
        return None
    return path


def _tail_text(path: Path, tail: int = 300, max_bytes: int = 512 * 1024) -> list[str]:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return []
    text = data.decode("utf-8", "replace").splitlines()
    return text[-max(1, min(tail, 5000)):]


def _python_exe() -> str:
    """优先使用同目录的 python.exe；避免 pythonw 启动时子进程没有控制台/标准输出。"""
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.exists():
            return str(console)
    return str(exe)


class JobManager:
    """单任务运行器：一次只允许一个子进程，输出写入 logs/webui 并保留内存尾行。"""

    MAX_LINES = 5000

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._job: dict | None = None
        self._thread: threading.Thread | None = None

    def _log_dir(self) -> Path:
        path = self.root / "logs" / "webui"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def is_running(self) -> bool:
        with self._lock:
            return bool(self._proc and self._proc.poll() is None)

    def start(self, args: list[str], title: str) -> dict:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                raise JobError("已有任务在运行，请先停止或等待结束")
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = self._log_dir() / f"run_{job_id}.log"
            cmd = [_python_exe(), str(self.root / "run.py")] + args
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["MAA_CAMPUS_WEBUI"] = "1"
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
            proc = subprocess.Popen(
                cmd, cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                creationflags=creationflags,
            )
            self._proc = proc
            self._job = {
                "id": job_id,
                "title": title,
                "args": list(args),
                "command": " ".join(cmd),
                "status": "running",
                "exit_code": None,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "ended_at": None,
                "log_file": str(log_path),
                "lines": [],
                "stop_requested": False,
            }
            self._thread = threading.Thread(target=self._pump, args=(self._job, proc, log_path),
                                            name=f"webui-job-{job_id}", daemon=True)
            self._thread.start()
            return self.snapshot()

    def _pump(self, job: dict, proc: subprocess.Popen, log_path: Path) -> None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"===== {job['title']} =====\n")
                if proc.stdout is not None:
                    for raw in proc.stdout:
                        line = raw.rstrip("\r\n")
                        with self._lock:
                            job["lines"].append(line)
                            if len(job["lines"]) > self.MAX_LINES:
                                del job["lines"][: len(job["lines"]) - self.MAX_LINES]
                        fh.write(line + "\n")
                rc = proc.wait()
        except Exception as e:  # noqa: BLE001
            rc = -1
            with self._lock:
                job["lines"].append(f"[webui] 读取任务输出失败：{e}")
        with self._lock:
            job["exit_code"] = rc
            job["ended_at"] = datetime.now().isoformat(timespec="seconds")
            if job.get("stop_requested"):
                job["status"] = "stopped"
            else:
                job["status"] = "succeeded" if rc == 0 else "failed"

    def stop(self) -> dict:
        with self._lock:
            proc = self._proc
            job = self._job
            if not proc or not job or proc.poll() is not None:
                return self.snapshot()
            job["stop_requested"] = True
            pid = proc.pid
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, text=True, timeout=30)
            else:
                proc.terminate()
        except Exception as e:  # noqa: BLE001
            with self._lock:
                job["lines"].append(f"[webui] 停止任务失败：{e}")
        return self.snapshot()

    def shutdown(self) -> None:
        self.stop()

    def snapshot(self) -> dict:
        with self._lock:
            if not self._job:
                return {"status": "idle", "lines": []}
            job = dict(self._job)
            job["lines"] = list(job.get("lines") or [])[-300:]
            job.pop("stop_requested", None)
            return job


class App:
    """Web UI 的业务适配层：读取状态、读写配置、启动/停止现有 CLI 子进程。"""

    def __init__(self, config_path: Path = DEFAULT_CONFIG, root: Path = PROJECT_ROOT):
        self.config_path = Path(config_path).resolve()
        self.root = Path(root).resolve()
        self.jobs = JobManager(self.root)
        self.started_at = datetime.now().isoformat(timespec="seconds")

    # ------------------------------------------------------------ 配置/状态
    def load_config_safe(self) -> tuple[dict | None, str | None]:
        cfg = None
        try:
            cfg = load_config(self.config_path)
        except Exception as e:  # noqa: BLE001
            return None, f"读取 config.json 失败：{e}"
        try:
            validate_config(cfg)
        except ValueError as e:
            return cfg, f"配置校验失败：{e}"
        return cfg, None

    def _instances(self, cfg: dict | None, log_dir: Path) -> list[dict]:
        cfg = cfg or {}
        rows = []
        instances = cfg.get("instances") or []
        if instances:
            for i, inst in enumerate(instances):
                name = str(inst.get("name") or f"instance{i + 1}")
                rows.append({"name": name, "adb_serial": inst.get("adb_serial"),
                             "mumu_index": inst.get("mumu_index"),
                             "last_success": self._last_success(log_dir, name),
                             "max_reached": self._max_reached(log_dir, name),
                             "lock": self._lock_info(log_dir, name)})
        else:
            name = str(cfg.get("instance_name") or "default")
            rows.append({"name": name, "adb_serial": cfg.get("adb_serial"),
                         "mumu_index": cfg.get("mumu_index"),
                         "last_success": self._last_success(log_dir, name),
                         "max_reached": self._max_reached(log_dir, name),
                         "lock": self._lock_info(log_dir, name)})
        return rows

    def _last_success(self, log_dir: Path, name: str) -> dict | None:
        suffix = "" if name in ("default", "") else "_" + _instance_key(name)
        path = log_dir / f".last_success{suffix}"
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return {"date": None, "today": False}
        return {"date": text, "today": text == _today()}

    def _max_reached(self, log_dir: Path, name: str) -> dict | None:
        path = log_dir / f".max_runs_reached_{_instance_key(name)}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _lock_info(self, log_dir: Path, name: str) -> dict | None:
        path = log_dir / f".run_{_instance_key(name)}.lock"
        try:
            stat = path.stat()
        except OSError:
            return None
        return {"path": path.name, "age_seconds": int(time.time() - stat.st_mtime)}

    def _config_summary(self, cfg: dict | None) -> dict:
        cfg = cfg or {}
        return {
            "adb_serial": cfg.get("adb_serial"),
            "mumu_index": cfg.get("mumu_index"),
            "campus_package": (cfg.get("campus") or {}).get("package"),
            "run_package": (cfg.get("run") or {}).get("package"),
            "target_distance_km": cfg.get("target_distance_km"),
            "max_runs": cfg.get("max_runs"),
            "run_windows": cfg.get("run_windows") or [],
            "run_window": cfg.get("run_window"),
            "check_after_minutes": cfg.get("check_after_minutes"),
            "max_run_minutes": cfg.get("max_run_minutes"),
            "skip_if_success_today": cfg.get("skip_if_success_today"),
            "shutdown_emulator": cfg.get("shutdown_emulator"),
            "close_apps": cfg.get("close_apps"),
            "refresh_window_on_start": cfg.get("refresh_window_on_start"),
            "instance_start_stagger_seconds": cfg.get("instance_start_stagger_seconds"),
            "ai_watch_enabled": (cfg.get("ai_watch") or {}).get("enabled", False),
        }

    def status(self) -> dict:
        cfg, error = self.load_config_safe()
        log_dir = _log_dir(self.root, cfg)
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        recent_logs = self.list_logs(limit=8)
        return {
            "ok": True,
            "version": self._version(),
            "server_time": datetime.now().isoformat(timespec="seconds"),
            "started_at": self.started_at,
            "config_path": str(self.config_path),
            "config_error": error,
            "config": self._config_summary(cfg),
            "instances": self._instances(cfg, log_dir),
            "job": self.jobs.snapshot(),
            "recent_logs": recent_logs,
            "latest_run": self._latest_run(log_dir),
            "markers": {
                "last_success": (cfg or {}).get("instance_name"),
                "run_windows_state": self._read_json_quiet(log_dir / ".run_windows_state.json"),
                "next_run": self._read_text_quiet(log_dir / ".next_run"),
            },
            "coexist_note": "Web 控制台是补充入口；CLI、config.json、DSH/计划任务脚本均保持不变。",
        }

    def _version(self) -> str:
        try:
            import tomllib

            data = tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))
            return str(data.get("project", {}).get("version", "unknown"))
        except Exception:  # noqa: BLE001
            return "unknown"

    def _latest_run(self, log_dir: Path) -> dict | None:
        files = sorted(log_dir.glob("run_*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return None
        path = files[0]
        lines = _tail_text(path, tail=4000)
        data = {"file": path.name, "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")}
        for line in lines:
            m = re.search(r"本次结束距离：([0-9.]+) km", line)
            if m:
                data["target_km"] = float(m.group(1))
            m = re.search(r"全部完成：距离 ([0-9.]+) km", line)
            if m:
                data["done_km"] = float(m.group(1))
            m = re.search(r"识别到已跑次数：(\d+) 次", line)
            if m:
                data["run_count"] = int(m.group(1))
            m = re.search(r"结束，退出码 (\d+)", line)
            if m:
                data["exit_code"] = int(m.group(1))
            if "[ERROR]" in line:
                data.setdefault("errors", []).append(re.sub(r"^.*?\[ERROR\]\s*", "", line)[:200])
        data["tail"] = lines[-30:]
        return data

    def _read_json_quiet(self, path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _read_text_quiet(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return None

    # ------------------------------------------------------------ 配置读写
    def raw_config(self) -> dict:
        return _read_json(self.config_path)

    def save_config(self, raw: dict) -> dict:
        if not isinstance(raw, dict):
            raise ValueError("配置必须是 JSON 对象")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_name(self.config_path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
            cfg = load_config(tmp)
            validate_config(cfg)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        backup = None
        if self.config_path.exists():
            backup = self.config_path.with_name(
                self.config_path.name + f".bak-{datetime.now():%Y%m%d_%H%M%S}")
            backup.write_bytes(self.config_path.read_bytes())
        os.replace(tmp, self.config_path)
        logging.getLogger("webui").info("配置已保存：%s（备份：%s）", self.config_path, backup)
        return {"ok": True, "config_path": str(self.config_path),
                "backup": str(backup) if backup else None}

    # ------------------------------------------------------------ 操作
    def start_run(self, mode: str, force: bool = False, no_record: bool = False,
                  instance: str | None = None) -> dict:
        if mode not in RUN_MODES:
            raise ValueError(f"不支持的执行模式：{mode}")
        cfg, error = self.load_config_safe()
        if error:
            raise ValueError(f"配置不可用：{error}")
        args: list[str] = list(RUN_MODES[mode][1])
        if force:
            args.append("--force")
        if no_record:
            args.append("--no-record")
        if instance:
            names = {str(i.get("name")) for i in (cfg.get("instances") or [])}
            if names and instance not in names:
                raise ValueError(f"实例不存在：{instance}")
            args.extend(["--instance", instance])
        args.extend(["--config", str(self.config_path)])
        return self.jobs.start(args, RUN_MODES[mode][0])

    def stop_run(self) -> dict:
        return self.jobs.stop()

    def export_logs(self, days: int | None = None, include_shots: bool | None = None) -> dict:
        """打包日志/截图；供 Web 与桌面控制台共用。"""
        cfg, error = self.load_config_safe()
        if error:
            raise ValueError(f"配置不可用：{error}")
        from .packaging import pack_logs

        return pack_logs(cfg, logging.getLogger("webui"), days=days,
                         include_shots=include_shots, root=self.root)

    # ------------------------------------------------------------ 日志
    def list_logs(self, limit: int = 50) -> list[dict]:
        cfg, _ = self.load_config_safe()
        log_dir = _log_dir(self.root, cfg)
        rows = []
        for pattern in ("*.log", "webui/*.log", "oneclick/*.log"):
            for path in log_dir.glob(pattern):
                if not path.is_file():
                    continue
                rel = path.relative_to(log_dir).as_posix()
                if not any(p.match(rel) for p in LOG_NAME_PATTERNS):
                    continue
                try:
                    st = path.stat()
                except OSError:
                    continue
                rows.append({"name": rel, "size": st.st_size,
                             "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
        rows.sort(key=lambda r: r["modified"], reverse=True)
        return rows[:max(1, limit)]

    def read_log(self, name: str, tail: int = 300) -> dict:
        cfg, _ = self.load_config_safe()
        log_dir = _log_dir(self.root, cfg)
        path = _safe_log_path(log_dir, name)
        if path is None:
            raise ValueError("日志文件不允许访问")
        if not path.exists():
            raise FileNotFoundError(name)
        return {"name": name, "lines": _tail_text(path, tail=tail),
                "size": path.stat().st_size}


def _json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class WebUIHandler(BaseHTTPRequestHandler):
    server_version = "MaaCampusWebUI/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        logging.getLogger("webui").info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, _json_bytes(obj), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > 2 * 1024 * 1024:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                self._serve_static("index.html", "text/html; charset=utf-8")
            elif path in ("/app.js", "/style.css"):
                ctype = "application/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8"
                self._serve_static(path.lstrip("/"), ctype)
            elif path == "/api/health":
                self._json(200, {"ok": True, "time": datetime.now().isoformat(timespec="seconds")})
            elif path == "/api/status":
                self._json(200, self.app.status())
            elif path == "/api/config":
                self._json(200, {"ok": True, "config": self.app.raw_config()})
            elif path == "/api/logs":
                self._json(200, {"ok": True, "logs": self.app.list_logs(limit=100)})
            elif path == "/api/logs/view":
                query = parse_qs(parsed.query)
                name = (query.get("name") or [""])[0]
                try:
                    tail = int((query.get("tail") or ["300"])[0])
                except ValueError:
                    tail = 300
                self._json(200, {"ok": True, **self.app.read_log(name, tail=tail)})
            elif path == "/api/export/download":
                name = (parse_qs(parsed.query).get("name") or [""])[0]
                self._download_export(name)
            else:
                self._error(404, "not found")
        except FileNotFoundError as e:
            self._error(404, f"文件不存在：{e}")
        except ValueError as e:
            self._error(400, str(e))
        except Exception as e:  # noqa: BLE001
            logging.getLogger("webui").exception("GET %s 失败", path)
            self._error(500, f"服务器内部错误：{e}")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            data = self._body()
            if path == "/api/config":
                raw = data.get("config") if "config" in data else data
                result = self.app.save_config(raw)
                self._json(200, result)
            elif path == "/api/run":
                mode = str(data.get("mode") or "")
                result = self.app.start_run(
                    mode,
                    force=bool(data.get("force")),
                    no_record=bool(data.get("no_record")),
                    instance=(str(data["instance"]).strip() if data.get("instance") else None),
                )
                self._json(200, {"ok": True, "job": result})
            elif path == "/api/run/stop":
                self._json(200, {"ok": True, "job": self.app.stop_run()})
            elif path == "/api/export":
                try:
                    days = int(data["days"]) if data.get("days") is not None else None
                except (TypeError, ValueError):
                    raise ValueError("days 必须是整数")
                include_shots = data.get("include_shots")
                if include_shots is not None:
                    include_shots = bool(include_shots)
                result = self.app.export_logs(days=days, include_shots=include_shots)
                name = Path(result["path"]).name
                result["download_url"] = "/api/export/download?name=" + quote(name)
                self._json(200, {"ok": True, "export": result})
            else:
                self._error(404, "not found")
        except JobError as e:
            self._error(409, str(e))
        except ValueError as e:
            self._error(400, str(e))
        except Exception as e:  # noqa: BLE001
            logging.getLogger("webui").exception("POST %s 失败", path)
            self._error(500, f"服务器内部错误：{e}")

    def _serve_static(self, name: str, content_type: str) -> None:
        path = (STATIC_DIR / name).resolve()
        try:
            path.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self._error(400, "非法静态资源")
            return
        if not path.exists():
            self._error(404, "静态资源不存在")
            return
        self._send(200, path.read_bytes(), content_type)

    def _download_export(self, name: str) -> None:
        if not re.fullmatch(r"maa_campus_logs_[0-9_A-Za-z.-]+\.zip", name or ""):
            self._error(400, "非法的压缩包名称")
            return
        cfg, _ = self.app.load_config_safe()
        exports = _log_dir(self.app.root, cfg) / "exports"
        path = (exports / name).resolve()
        try:
            path.relative_to(exports.resolve())
        except ValueError:
            self._error(400, "非法路径")
            return
        if not path.exists():
            self._error(404, "压缩包不存在")
            return
        try:
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as fh:
                while True:
                    chunk = fh.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception as e:  # noqa: BLE001
            logging.getLogger("webui").warning("下载压缩包失败：%s", e)
            self._error(500, f"下载失败：{e}")


class WebUIServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, app: App):
        super().__init__(server_address, WebUIHandler)
        self.app = app


def create_server(app: App, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> WebUIServer:
    return WebUIServer((host, port), app)


def serve(config_path: Path = DEFAULT_CONFIG, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          open_browser: bool = True, root: Path = PROJECT_ROOT) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger("webui")
    app = App(config_path=config_path, root=root)
    try:
        server = create_server(app, host=host, port=port)
    except OSError as e:
        logger.error("启动 Web 控制台失败：%s（端口 %s 是否被占用？）", e, port)
        return 1
    url = f"http://{host if host != '0.0.0.0' else '127.0.0.1'}:{server.server_address[1]}/"
    logger.info("Web 控制台已启动：%s", url)
    logger.info("这是补充入口，原有 CLI/配置/脚本控制方式不受影响；按 Ctrl+C 退出。")
    if host not in ("127.0.0.1", "localhost"):
        logger.warning("当前监听 %s，同网段其他设备可访问；请勿在公网环境开放。", host)
    try:
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断，正在关闭 Web 控制台 ...")
    finally:
        app.jobs.shutdown()
        server.server_close()
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="校园跑值守本地 Web 控制台（补充入口）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    return serve(Path(args.config), host=args.host, port=args.port,
                 open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
