import logging
from types import SimpleNamespace

from maa_campus import flow, maa_tasks


class _FakeJob:
    def __init__(self, detail):
        self.succeeded = True
        self._detail = detail

    def get(self):
        return self._detail


def test_ocr_texts_extracts_all_results(monkeypatch):
    detail = SimpleNamespace(nodes=[
        SimpleNamespace(recognition=SimpleNamespace(raw_detail={
            "all": [{"text": "已跑 7 次"}, {"text": "总距离"}]})),
    ])
    monkeypatch.setattr(maa_tasks, "post_and_wait", lambda *a, **k: _FakeJob(detail))
    assert maa_tasks.ocr_texts(object()) == ["已跑 7 次", "总距离"]


def test_read_run_count_default_patterns(monkeypatch):
    monkeypatch.setattr(flow, "ocr_texts",
                        lambda tasker: ["校园跑", "已跑 7 次", "总距离 0.00"])
    assert flow.read_run_count(object(), {}, logging.getLogger("t")) == 7


def test_read_run_count_slash_format(monkeypatch):
    # 健行校园首页实际文案：26次/60次
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["健行校园", "26次/60次"])
    assert flow.read_run_count(object(), {}, logging.getLogger("t")) == 26


def test_read_run_count_custom_pattern(monkeypatch):
    cfg = {"run_count_patterns": [r"总次数\s*[:：]\s*(\d+)"]}
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["总次数：12"])
    assert flow.read_run_count(object(), cfg, logging.getLogger("t")) == 12


def test_read_run_count_not_found(monkeypatch):
    monkeypatch.setattr(flow, "ocr_texts", lambda tasker: ["没有相关文字"])
    assert flow.read_run_count(object(), {}, logging.getLogger("t"), quiet=True) is None


def test_max_runs_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = {"log_dir": "logs", "instance_name": "mumu-1", "max_runs": 5}
    assert flow._max_runs_reached(cfg, logging.getLogger("t")) is False
    flow._mark_max_runs_reached(cfg, 5, logging.getLogger("t"))
    assert flow._max_runs_reached(cfg, logging.getLogger("t")) is True

    cfg["max_runs"] = 6  # 提高上限后旧标记不再生效
    assert flow._max_runs_reached(cfg, logging.getLogger("t")) is False


def test_should_skip_for_max_runs():
    assert flow._should_skip_for_max_runs({"max_runs": 5}, 5) is True
    assert flow._should_skip_for_max_runs({"max_runs": 5}, 4) is False
    assert flow._should_skip_for_max_runs({"max_runs": 0}, 100) is False
    assert flow._should_skip_for_max_runs({"max_runs": 5}, None) is False


def test_run_flow_skips_early_when_max_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = {"log_dir": "logs", "instance_name": "mumu-1", "max_runs": 5,
           "skip_if_success_today": True}
    flow._mark_max_runs_reached(cfg, 5, logging.getLogger("t"))
    monkeypatch.setattr(flow, "_already_succeeded_today", lambda cfg, logger: False)

    def boom(cfg, logger):
        raise AssertionError("达到上限后不应启动模拟器")

    monkeypatch.setattr(flow, "make_adb", boom)
    assert flow._run_flow_impl(cfg, logging.getLogger("t"), dry=False) == 0
