import logging

from maa_campus import flow


class FakeController:
    def __init__(self):
        self.focus_package = ""


class FakeClock:
    """可推进的假时钟：避免真实等待，同时让 deadline 逻辑生效。"""

    def __init__(self, step: float = 3.0):
        self.now = 0.0
        self.step = step

    def time(self) -> float:
        self.now += self.step
        return self.now

    def sleep(self, _seconds: float) -> None:
        return None


def _patch_common(monkeypatch, states, timeout=90, step=3.0):
    seq = list(states)
    last = {"state": "loading"}

    def state_of(_tasker):
        if seq:
            last["state"] = seq.pop(0)
        return last["state"]

    monkeypatch.setattr(flow, "_campus_page_state", state_of)
    monkeypatch.setattr(flow, "ocr_tap", lambda tasker, patterns: True)
    monkeypatch.setattr(flow, "save_shot", lambda *a, **k: None)
    monkeypatch.setattr(flow, "time", FakeClock(step=step))
    return {"campus": {"package": "c"}, "campus_start_timeout_seconds": timeout}


def test_campus_start_waits_while_loading(monkeypatch):
    # 点击后先加载几轮才进入跑步态：应继续等待而不是判失败
    cfg = _patch_common(monkeypatch, ["idle", "loading", "loading", "loading", "running"])
    ok = flow.start_campus_run(object(), FakeController(), cfg, logging.getLogger("t"), "c")
    assert ok is True


def test_campus_start_retries_click_when_still_idle(monkeypatch):
    cfg = _patch_common(monkeypatch, ["idle", "idle", "idle", "idle", "running"])
    taps = []
    monkeypatch.setattr(flow, "ocr_tap",
                        lambda tasker, patterns: taps.append(list(patterns)) or True)
    ok = flow.start_campus_run(object(), FakeController(), cfg, logging.getLogger("t"), "c")
    assert ok is True
    # 第 1 次点击后连续 3 轮仍 idle，应再点第 2 次；随后 running 结束
    assert len(taps) == 2


def test_campus_start_times_out_when_loading_forever(monkeypatch):
    cfg = _patch_common(monkeypatch, ["loading"], timeout=20)
    ok = flow.start_campus_run(object(), FakeController(), cfg, logging.getLogger("t"), "c")
    assert ok is False


def test_campus_page_state_classification(monkeypatch):
    cases = {
        "running": "点击结束跑步",
        "loading": "加载中",
        "idle": "开始",
        "unknown": None,
    }
    for expected, marker in cases.items():
        if marker is None:
            monkeypatch.setattr(flow, "ocr_texts", lambda tasker: [])
        else:
            monkeypatch.setattr(flow, "ocr_texts", lambda tasker, m=marker: [m])
        assert flow._campus_page_state(object()) == expected


def test_campus_start_unknown_then_timeout(monkeypatch):
    cfg = _patch_common(monkeypatch, ["unknown"], timeout=20)
    taps = []
    monkeypatch.setattr(flow, "ocr_tap",
                        lambda tasker, patterns: taps.append(list(patterns)) or False)
    ok = flow.start_campus_run(object(), FakeController(), cfg, logging.getLogger("t"), "c")
    assert ok is False
    assert len(taps) == 1  # unknown 首轮仍尝试点击一次，之后等待超时


def test_verify_running_quick_campus_recheck_when_confirmed(monkeypatch):
    checks = []

    def probe(tasker, patterns):
        checks.append(list(patterns))
        return ("正在跑步" in patterns) or ("点击结束跑步" in patterns)

    monkeypatch.setattr(flow, "ocr_probe", probe)
    cfg = {"run": {"package": "r"}, "campus": {"package": "c"}}
    ctl = FakeController()
    assert flow.verify_running(object(), ctl, cfg, logging.getLogger("t"), campus_confirmed=True) is True
    campus_checks = [p for p in checks if "点击结束跑步" in p]
    assert len(campus_checks) == 1  # 单次快速复核，不再走 10 轮等待
