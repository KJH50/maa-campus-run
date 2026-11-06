"""多实例并行执行：为 config.instances 中每个实例启动独立子进程运行 run.py --now。

每个子进程拥有自己的 adb / MaaFw Tasker / 日志文件，避免在同进程内共享 MaaFramework
原生资源；父进程只负责启动、转发日志与汇总退出码。
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def aggregate_exit(codes: list[int]) -> int:
    """汇总多个子进程退出码：全 0 → 0；任一 3 → 3；否则任一 2 → 2；否则 1。"""
    if not codes:
        return 1
    if all(c == 0 for c in codes):
        return 0
    if 3 in codes:
        return 3
    if 2 in codes:
        return 2
    return 1


def build_child_cmd(config_path: str | Path, dry: bool, skip_start: bool, force: bool) -> list[str]:
    """构造单个实例的子进程命令。"""
    cmd = [sys.executable, str(PROJECT_ROOT / "run.py"), "--now", "--config", str(config_path)]
    if dry:
        cmd.append("--dry")
    if skip_start:
        cmd.append("--wait-finish")
    if force:
        cmd.append("--force")
    return cmd


def run_parallel(cfg: dict, logger: logging.Logger, config_path: str | Path,
                 dry: bool = False, skip_start: bool = False, force: bool = False) -> int:
    """并行执行 config.instances；返回汇总退出码。"""
    instances = cfg.get("instances") or []
    if len(instances) < 2:
        logger.error("并行模式需要至少 2 个 instances 配置")
        return 1

    cmd = build_child_cmd(config_path, dry, skip_start, force)
    procs: list[tuple[str, subprocess.Popen]] = []
    for i, inst in enumerate(instances):
        name = str(inst.get("name") or f"instance{i + 1}")
        env = os.environ.copy()
        env["MAA_CAMPUS_INSTANCE"] = str(i)
        env["MAA_CAMPUS_PARALLEL"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        logger.info("启动并行实例 %s：adb=%s，mumu_index=%s", name,
                    inst.get("adb_serial"), inst.get("mumu_index"))
        p = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        procs.append((name, p))

    def pump(name: str, stream) -> None:
        try:
            for line in stream:
                logger.info("[%s] %s", name, line.rstrip())
        except Exception:  # noqa: BLE001
            pass

    threads = [threading.Thread(target=pump, args=(name, p.stdout), daemon=True)
               for name, p in procs]
    for t in threads:
        t.start()
    codes: list[int] = []
    for name, p in procs:
        code = p.wait()
        codes.append(code)
        logger.info("并行实例 %s 结束：退出码 %s", name, code)
    for t in threads:
        t.join(timeout=10)

    logger.info("并行执行结束：%s",
                "，".join(f"{name}={code}" for (name, _), code in zip(procs, codes)))
    return aggregate_exit(codes)
