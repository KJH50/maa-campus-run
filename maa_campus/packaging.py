"""日志与截图打包：把 logs/ 下的运行日志、Web/AI 日志、证据截图和少量状态文件打成 zip。

设计：
- 仅使用标准库 zipfile，不修改原始日志/截图；
- 默认只打包最近 `pack_days` 天（配置项，默认 7；传 0 表示全部）；
- 默认包含截图；可用 --pack-no-shots 排除；
- 不打包 config.json / 环境变量 / 密钥；manifest 只记录文件清单与非敏感摘要；
- 输出默认到 logs/exports/，文件名带时间戳，已存在时自动加序号，避免覆盖。
"""

from __future__ import annotations

import json
import logging
import re
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

LOG_PATTERNS = [
    re.compile(r"^(run_|ai_watch_|alerts_|oneclick_).+\.log$"),
    re.compile(r"^(webui|ai_watch|oneclick)/.+\.(log|jsonl)$"),
]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
STATE_NAMES = [
    re.compile(r"^\.last_success"),
    re.compile(r"^\.max_runs_reached_.+\.json$"),
    re.compile(r"^\.run_windows_state\.json$"),
    re.compile(r"^\.next_run$"),
]


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_log(rel: str) -> bool:
    return any(p.search(rel) for p in LOG_PATTERNS)


def _is_image(rel: str) -> bool:
    return Path(rel).suffix.lower() in IMAGE_SUFFIXES and (
        rel.startswith("shots/") or rel.startswith("ai_watch/shots/"))


def _is_state(rel: str) -> bool:
    return "/" not in rel and any(p.search(rel) for p in STATE_NAMES)


def collect_files(log_dir: Path, cutoff: datetime | None, include_shots: bool,
                  include_state: bool = True) -> list[tuple[str, Path]]:
    """收集待打包文件（不跟随符号链接，跳过 exports/ 与输出自身）。"""
    rows: list[tuple[str, Path]] = []
    if not log_dir.exists():
        return rows
    for path in sorted(log_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            rel = _relative(path, log_dir)
        except ValueError:
            continue
        if rel.startswith("exports/"):
            continue
        if _is_log(rel):
            allowed = True
        elif include_shots and _is_image(rel):
            allowed = True
        elif include_state and _is_state(rel):
            allowed = True
        else:
            allowed = False
        if not allowed:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if cutoff is not None and datetime.fromtimestamp(mtime) < cutoff:
            continue
        rows.append((rel, path))
    return rows


def _unique_output(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix or ".zip"
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一的压缩包文件名：{path}")


def pack_logs(cfg: dict, logger: logging.Logger | None = None, output: str | Path | None = None,
              days: int | None = None, include_shots: bool | None = None,
              include_state: bool = True, root: Path = PROJECT_ROOT) -> dict:
    """打包日志/截图/状态文件，返回 {path, files, source_bytes, archive_bytes, ...}。"""
    logger = logger or logging.getLogger("pack_logs")
    cfg = cfg or {}
    root = Path(root).resolve()
    log_dir = root / (cfg.get("log_dir") or "logs")
    if not log_dir.exists():
        raise FileNotFoundError(f"日志目录不存在：{log_dir}")

    if days is None:
        try:
            days = int(cfg.get("pack_days", 7) or 0)
        except (TypeError, ValueError):
            days = 7
    if include_shots is None:
        include_shots = bool(cfg.get("pack_include_shots", True))
    cutoff = datetime.now() - timedelta(days=days) if days and days > 0 else None

    files = collect_files(log_dir, cutoff, include_shots, include_state)
    now = datetime.now()
    if output:
        out_path = Path(output)
        if not out_path.is_absolute():
            out_path = root / out_path
    else:
        out_path = log_dir / "exports" / f"maa_campus_logs_{now:%Y%m%d_%H%M%S}.zip"
    out_path = _unique_output(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "created_at": now.isoformat(timespec="seconds"),
        "project": "maa-campus-run",
        "filters": {"days": days, "include_shots": include_shots,
                    "include_state": include_state},
        "summary": {
            "target_distance_km": cfg.get("target_distance_km"),
            "max_runs": cfg.get("max_runs"),
            "run_windows": cfg.get("run_windows") or [],
            "instances_count": len(cfg.get("instances") or []),
        },
        "files": [],
    }
    source_bytes = 0
    for rel, path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        source_bytes += size
        manifest["files"].append({
            "path": f"logs/{rel}",
            "size": size,
            "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        })

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=True) as zf:
        for rel, path in files:
            try:
                zf.write(path, arcname=f"logs/{rel}")
            except OSError as e:
                logger.warning("跳过无法读取的文件 %s：%s", path, e)
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2), compress_type=zipfile.ZIP_DEFLATED)

    archive_bytes = out_path.stat().st_size
    result = {
        "path": str(out_path),
        "files": len(manifest["files"]),
        "source_bytes": source_bytes,
        "archive_bytes": archive_bytes,
        "days": days,
        "include_shots": include_shots,
        "created_at": manifest["created_at"],
    }
    ratio = (archive_bytes / source_bytes * 100) if source_bytes else 0.0
    logger.info("日志/截图打包完成：%s（%s 个文件，原始 %.1f MB → 压缩后 %.1f MB，%.1f%%）",
                out_path, result["files"], source_bytes / 1048576, archive_bytes / 1048576, ratio)
    return result


def main() -> int:
    import argparse

    from .config import load_config

    parser = argparse.ArgumentParser(description="打包日志与截图")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.json"))
    parser.add_argument("--output", default=None)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--no-shots", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    try:
        cfg = load_config(Path(args.config))
        result = pack_logs(cfg, logging.getLogger("pack_logs"), output=args.output,
                           days=args.days, include_shots=not args.no_shots)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("pack_logs").error("打包失败：%s", e)
        return 1
    print(result["path"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
