import logging

import pytest

from maa_campus.ai_vision import Decision
from maa_campus.page_actions import (ACTION_LOW_CONFIDENCE, ACTION_TARGET_AMBIGUOUS,
                                     ACTION_TARGET_MISSING, ActionError, execute, validate)
from maa_campus.page_observer import OCText, PageSnapshot


class FakeAdb:
    def __init__(self):
        self.calls = []

    def tap(self, display, x, y):
        self.calls.append(("tap", x, y))

    def input_text(self, display, text):
        self.calls.append(("input", text))

    def swipe(self, display, x1, y1, x2, y2, duration_ms=300):
        self.calls.append(("swipe", x1, y1, x2, y2))


def _cfg(threshold=0.5):
    return {"ai_watch": {"action": {
        "allowed": ["click", "input", "scroll", "wait", "retry", "abort"],
        "confidence_threshold": threshold,
        "max_wait_seconds": 10,
        "max_retries": 2,
    }}}


def _snap(texts):
    return PageSnapshot(image=None,
                        ocr=[OCText(text=t, score=s, box=(100, 200, 50, 20))
                             for t, s in texts])


def _decision(action, target=None, params=None, confidence=0.9):
    return Decision(action=action, target=target, params=params or {},
                    confidence=confidence, reason="test")


def test_click_by_text():
    snap = _snap([("开始", 0.9)])
    d = _decision("click", "开始")
    cfg = _cfg()
    validate(d, snap, cfg)
    adb = FakeAdb()
    result = execute(d, snap, adb, 0, cfg, logging.getLogger("t"))
    assert result.ok
    assert adb.calls == [("tap", 125, 210)]


def test_click_missing_target():
    d = _decision("click", "结束")
    with pytest.raises(ActionError) as exc:
        validate(d, _snap([("开始", 0.9)]), _cfg())
    assert exc.value.code == ACTION_TARGET_MISSING


def test_click_ambiguous_target():
    d = _decision("click", "开始")
    with pytest.raises(ActionError) as exc:
        validate(d, _snap([("开始", 0.9), ("开始", 0.8)]), _cfg())
    assert exc.value.code == ACTION_TARGET_AMBIGUOUS


def test_low_confidence_rejected():
    d = _decision("click", "开始", confidence=0.3)
    with pytest.raises(ActionError) as exc:
        validate(d, _snap([("开始", 0.9)]), _cfg())
    assert exc.value.code == ACTION_LOW_CONFIDENCE


def test_input_and_abort_and_retry():
    snap = _snap([("输入框", 0.9)])
    cfg = _cfg()
    adb = FakeAdb()
    result = execute(_decision("input", "输入框", {"text": "hello"}), snap, adb, 0, cfg,
                     logging.getLogger("t"))
    assert result.ok
    assert ("input", "hello") in adb.calls

    assert execute(_decision("abort"), snap, adb, 0, cfg, logging.getLogger("t")).abort
    assert execute(_decision("retry"), snap, adb, 0, cfg, logging.getLogger("t")).retry


def test_scroll_and_wait():
    snap = _snap([("列表", 0.9)])
    cfg = _cfg()
    adb = FakeAdb()
    execute(_decision("scroll", None, {"direction": "down", "distance": 200}), snap, adb, 0,
            cfg, logging.getLogger("t"))
    assert adb.calls and adb.calls[0][0] == "swipe"

    slept = []
    execute(_decision("wait", None, {"seconds": 2}), snap, adb, 0, cfg,
            logging.getLogger("t"), sleep=lambda s: slept.append(s))
    assert slept == [2]
