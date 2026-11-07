"""动作校验与执行：click / input / scroll / wait / retry / abort。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from .ai_vision import Decision
from .page_observer import PageSnapshot

ACTION_UNSUPPORTED = "ACTION_UNSUPPORTED"
ACTION_DENIED = "ACTION_DENIED"
ACTION_LOW_CONFIDENCE = "ACTION_LOW_CONFIDENCE"
ACTION_TARGET_MISSING = "ACTION_TARGET_MISSING"
ACTION_TARGET_AMBIGUOUS = "ACTION_TARGET_AMBIGUOUS"
ACTION_PARAMS_INVALID = "ACTION_PARAMS_INVALID"
ACTION_EXEC_FAILED = "ACTION_EXEC_FAILED"


class ActionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ActionResult:
    ok: bool
    message: str
    error_code: str | None = None
    retry: bool = False
    abort: bool = False


def _action_cfg(cfg: dict) -> dict:
    aw = (cfg or {}).get("ai_watch") or {}
    return aw.get("action") or {}


def _find_target(snapshot: PageSnapshot, target: str | None) -> tuple[int, int] | None:
    if not target:
        return None
    try:
        regex = re.compile(str(target))
    except re.error:
        regex = None
    matches = [o for o in snapshot.ocr if regex.search(o.text or "")] if regex else \
        [o for o in snapshot.ocr if target in (o.text or "")]
    if not matches:
        raise ActionError(ACTION_TARGET_MISSING, f"目标未找到：{target}")
    if len(matches) > 1:
        raise ActionError(ACTION_TARGET_AMBIGUOUS, f"目标存在多个候选：{target}（{len(matches)}）")
    center = matches[0].center()
    if center is None:
        raise ActionError(ACTION_TARGET_MISSING, f"目标缺少坐标：{target}")
    return center


def _coords(params: dict) -> tuple[int, int] | None:
    if "x" in params and "y" in params:
        try:
            return int(params["x"]), int(params["y"])
        except (TypeError, ValueError) as e:
            raise ActionError(ACTION_PARAMS_INVALID, "x/y 必须是整数") from e
    return None


def validate(decision: Decision, snapshot: PageSnapshot, cfg: dict) -> None:
    """校验 AI 决策是否允许执行；不合法时抛出 ActionError。"""
    action_cfg = _action_cfg(cfg)
    allowed = action_cfg.get("allowed") or list(
        ("click", "input", "scroll", "wait", "retry", "abort"))
    if decision.action not in allowed:
        raise ActionError(ACTION_DENIED, f"动作未在允许列表：{decision.action}")
    threshold = float(action_cfg.get("confidence_threshold", 0.7))
    if decision.confidence < threshold:
        raise ActionError(ACTION_LOW_CONFIDENCE,
                          f"置信度 {decision.confidence:.2f} 低于阈值 {threshold:.2f}")

    if decision.action == "click":
        if not decision.target and _coords(decision.params) is None:
            raise ActionError(ACTION_PARAMS_INVALID, "click 需要 target 或 x/y 坐标")
        if decision.target:
            _find_target(snapshot, decision.target)  # 找不到/多个会抛错
    elif decision.action == "input":
        text = decision.params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ActionError(ACTION_PARAMS_INVALID, "input 需要非空 params.text")
        if len(text) > 200:
            raise ActionError(ACTION_PARAMS_INVALID, "input 文本过长（>200）")
        if decision.target:
            _find_target(snapshot, decision.target)
    elif decision.action == "scroll":
        direction = str(decision.params.get("direction", "down")).lower()
        if direction not in ("up", "down", "left", "right", "上", "下", "左", "右"):
            raise ActionError(ACTION_PARAMS_INVALID, f"scroll 方向非法：{direction}")
        distance = int(decision.params.get("distance", 400))
        if not 10 <= distance <= 4000:
            raise ActionError(ACTION_PARAMS_INVALID, "scroll distance 需在 10~4000")
    elif decision.action == "wait":
        seconds = float(decision.params.get("seconds", 5))
        max_wait = float(action_cfg.get("max_wait_seconds", 60))
        if not 0 <= seconds <= max_wait:
            raise ActionError(ACTION_PARAMS_INVALID, f"wait seconds 需在 0~{max_wait}")
    elif decision.action == "retry":
        attempts = int(decision.params.get("attempts", 1))
        max_retries = int(action_cfg.get("max_retries", 2))
        if not 1 <= attempts <= max_retries:
            raise ActionError(ACTION_PARAMS_INVALID, f"retry attempts 需在 1~{max_retries}")


def execute(decision: Decision, snapshot: PageSnapshot, adb, display: int, cfg: dict,
            logger: logging.Logger, sleep=time.sleep) -> ActionResult:
    """执行已校验的决策（不做 AI 调用；执行失败返回 ActionResult）。"""
    action = decision.action
    try:
        if action == "click":
            coords = _coords(decision.params) or _find_target(snapshot, decision.target)
            if coords is None:
                raise ActionError(ACTION_TARGET_MISSING, "click 没有可用坐标")
            adb.tap(display, coords[0], coords[1])
            return ActionResult(True, f"点击 ({coords[0]}, {coords[1]})")

        if action == "input":
            text = str(decision.params["text"])
            if decision.target:
                center = _find_target(snapshot, decision.target)
                if center:
                    adb.tap(display, center[0], center[1])
                    sleep(0.5)
            adb.input_text(display, text)
            return ActionResult(True, f"输入文本（{len(text)} 字符）")

        if action == "scroll":
            direction = str(decision.params.get("direction", "down")).lower()
            distance = int(decision.params.get("distance", 400))
            width, height = (snapshot.image.size if snapshot.image else (1080, 1920))
            cx, cy = width // 2, height // 2
            vectors = {
                "up": (0, distance), "down": (0, -distance),
                "left": (distance, 0), "right": (-distance, 0),
                "上": (0, distance), "下": (0, -distance),
                "左": (distance, 0), "右": (-distance, 0),
            }
            dx, dy = vectors[direction]
            end_x, end_y = max(0, min(width - 1, cx + dx)), max(0, min(height - 1, cy + dy))
            adb.swipe(display, cx, cy, end_x, end_y, 300)
            return ActionResult(True, f"滚动 {direction} {distance}px")

        if action == "wait":
            seconds = float(decision.params.get("seconds", 5))
            logger.info("按 AI 决策等待 %.1f 秒", seconds)
            sleep(seconds)
            return ActionResult(True, f"等待 {seconds:.1f} 秒")

        if action == "retry":
            return ActionResult(True, "按 AI 决策重试", retry=True)

        if action == "abort":
            return ActionResult(True, "按 AI 决策中止任务", abort=True)

        raise ActionError(ACTION_UNSUPPORTED, f"未知动作：{action}")
    except ActionError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ActionError(ACTION_EXEC_FAILED, f"动作执行失败：{e}") from e
