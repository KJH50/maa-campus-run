"""ADB 封装：针对 MuMu 模拟器多虚拟屏的截图 / 点击 / 启停应用。

MuMu 会把 App 放到独立的虚拟屏（display）里：
- `dumpsys activity activities` 里拿到的是「逻辑 display id」（input -d 用它）
- `screencap -d` 需要的是「SurfaceFlinger 物理 display id」（大整数）
两者通过 `dumpsys display` 的 `uniqueId "local:<物理 id>"` 映射。
"""

from __future__ import annotations

import re
import subprocess
import time


class AdbError(RuntimeError):
    pass


class Adb:
    def __init__(self, adb_path: str, serial: str):
        self.adb_path = adb_path
        self.serial = serial
        self._map_cache: dict[int, int] = {}
        self._map_time = 0.0

    # ---------------------------------------------------------------- 基础
    def _run(self, args: list[str], timeout: int = 30) -> bytes:
        cmd = [self.adb_path, "-s", self.serial] + args
        try:
            p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise AdbError(f"adb 超时: {' '.join(cmd)}") from e
        if p.returncode != 0:
            err = p.stderr.decode("utf-8", "replace").strip()
            raise AdbError(f"adb 失败({p.returncode}): {' '.join(cmd)} :: {err}")
        return p.stdout

    def shell(self, cmd: str, timeout: int = 30) -> str:
        return self._run(["shell", cmd], timeout=timeout).decode("utf-8", "replace")

    def exec_out(self, cmd: str, timeout: int = 60) -> bytes:
        return self._run(["exec-out", cmd], timeout=timeout)

    # ---------------------------------------------------------------- 连接
    def connect(self, wait_seconds: int = 60) -> bool:
        subprocess.run(
            [self.adb_path, "connect", self.serial],
            capture_output=True,
            timeout=30,
        )
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            try:
                if self.shell("getprop sys.boot_completed", timeout=15).strip() == "1":
                    return True
            except AdbError:
                pass
            time.sleep(2)
        return False

    def connected(self) -> bool:
        try:
            out = self._run(["get-state"], timeout=10).decode().strip()
            return out == "device"
        except Exception:
            return False

    # ---------------------------------------------------------------- 屏幕
    def get_display(self, package: str) -> int:
        """返回指定包名 App 当前所在的逻辑 display id（MuMu 多虚拟屏）。"""
        out = self.shell("dumpsys activity activities", timeout=30)
        current = 0
        for line in out.splitlines():
            m = re.search(r"Display #(\d+)", line)
            if m:
                current = int(m.group(1))
            if "topResumedActivity=" in line and f"{package}/" in line:
                return current
        return 0

    def display_map(self, max_age: float = 30.0) -> dict[int, int]:
        """逻辑 display id -> SurfaceFlinger 物理 display id。"""
        now = time.time()
        if self._map_cache and now - self._map_time < max_age:
            return self._map_cache
        out = self.shell("dumpsys display", timeout=30)
        mapping: dict[int, int] = {}
        for line in out.splitlines():
            m = re.search(r'DisplayInfo\{"[^"]*", displayId (\d+).*?uniqueId "local:(\d+)"', line)
            if m:
                mapping[int(m.group(1))] = int(m.group(2))
        if mapping:
            self._map_cache = mapping
            self._map_time = now
        return self._map_cache

    def screencap(self, display: int) -> bytes:
        """截图指定逻辑 display，返回 PNG 字节。"""
        mapping = self.display_map()
        physical = mapping.get(display)
        if physical is None:
            self._map_cache = {}
            mapping = self.display_map(max_age=0)
            physical = mapping.get(display, display)
        raw = self.exec_out(f"screencap -d {physical} -p")
        idx = raw.find(b"\x89PNG")
        if idx < 0:
            raise AdbError("screencap 输出中没有 PNG 数据")
        return raw[idx:]

    def tap(self, display: int, x: int, y: int) -> None:
        self.shell(f"input -d {display} tap {int(x)} {int(y)}", timeout=20)

    def swipe(self, display: int, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.shell(
            f"input -d {display} swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
            timeout=30,
        )

    def key(self, display: int, keycode: int) -> None:
        self.shell(f"input -d {display} keyevent {int(keycode)}", timeout=20)

    def input_text(self, display: int, text: str) -> None:
        escaped = text.replace(" ", "%s")
        self.shell(f"input -d {display} text {escaped}", timeout=20)

    # ---------------------------------------------------------------- 应用
    def start_app(self, intent: str) -> None:
        self.shell(f"am start -n {intent}", timeout=30)

    def stop_app(self, package: str) -> None:
        self.shell(f"am force-stop {package}", timeout=30)
