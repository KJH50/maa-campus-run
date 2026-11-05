"""MaaFramework 自定义控制器：把截图 / 点击 / 启停应用接到 MuMu 多虚拟屏上。"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
from maa.controller import CustomController

from .adb import Adb


class MuMuAdbController(CustomController):
    """基于 adb 的 MaaFramework 控制器。

    - 截图：抓取 focus_package 当前所在 display 的画面（MuMu 多屏适配）
    - 点击/滑动：向 focus_package 所在 display 发送 input 事件
    - 启停应用：am start / am force-stop
    """

    def __init__(self, adb: Adb, focus_package: str):
        super().__init__()
        self.adb = adb
        self.focus_package = focus_package

    # 让 MaaFramework 直接用 click() 而不是 touch_down/touch_up
    def get_features(self) -> int:
        return 0

    # ------------------------------------------------------------ 连接
    def connect(self) -> bool:
        return self.adb.connect()

    def connected(self) -> bool:
        return self.adb.connected()

    def request_uuid(self) -> str:
        return self.adb.serial

    # ------------------------------------------------------------ 应用
    def start_app(self, intent: str) -> bool:
        self.adb.start_app(intent)
        return True

    def stop_app(self, intent: str) -> bool:
        self.adb.stop_app(intent)
        return True

    # ------------------------------------------------------------ 画面
    def screencap(self) -> np.ndarray:
        display = self.adb.get_display(self.focus_package)
        png = self.adb.screencap(display)
        image = Image.open(io.BytesIO(png)).convert("RGB")
        return np.asarray(image)

    def _display(self) -> int:
        return self.adb.get_display(self.focus_package)

    def click(self, x: int, y: int) -> bool:
        self.adb.tap(self._display(), x, y)
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> bool:
        self.adb.swipe(self._display(), x1, y1, x2, y2, duration)
        return True

    def touch_down(self, contact: int, x: int, y: int, pressure: int) -> bool:
        self.adb.tap(self._display(), x, y)
        return True

    def touch_move(self, contact: int, x: int, y: int, pressure: int) -> bool:
        return True

    def touch_up(self, contact: int) -> bool:
        return True

    def click_key(self, keycode: int) -> bool:
        self.adb.key(self._display(), keycode)
        return True

    def key_down(self, keycode: int) -> bool:
        self.adb.key(self._display(), keycode)
        return True

    def key_up(self, keycode: int) -> bool:
        return True

    def input_text(self, text: str) -> bool:
        self.adb.input_text(self._display(), text)
        return True

    def shell(self, cmd: str, timeout: int) -> str | None:
        try:
            return self.adb.shell(cmd, timeout=max(1, timeout // 1000))
        except Exception:
            return None
