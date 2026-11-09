import json
import logging

from maa_campus import flow


def _cfg(tmp_path, instance="mumu-1"):
    return {
        "target_distance_km": 2.0,
        "route_lap_km": 0.415,
        "finish_distance_max_km": 2.2,
        "finish_offset_max_km": 0.05,
        "finish_coincide_prob": 0.2,
        "finish_target_avoid_repeat": True,
        "finish_target_min_gap_km": 0.02,
        "log_dir": "logs",
        "instance_name": instance,
    }


def test_state_per_instance_and_date(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = _cfg(tmp_path)
    flow._save_used_finish_targets(cfg, [2.03, 2.05])
    assert flow._load_used_finish_targets(cfg) == [2.03, 2.05]

    other = _cfg(tmp_path, instance="mumu-2")
    assert flow._load_used_finish_targets(other) == []

    p = flow._finish_targets_path(cfg)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["date"] = "2000-01-01"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert flow._load_used_finish_targets(cfg) == []


def test_pick_avoids_used_targets(monkeypatch):
    cfg = _cfg(None)
    draws = iter([(2.03, "重复"), (2.05, "可用")])
    monkeypatch.setattr(flow, "_draw_random_target", lambda *a, **k: next(draws))
    picked = flow._pick_avoiding_repeats(cfg, 2.075, 2.0, 2.2, [2.03])
    assert picked == (2.05, "可用")


def test_pick_fallback_uses_candidate_pool(monkeypatch):
    cfg = _cfg(None)
    monkeypatch.setattr(flow, "_draw_random_target", lambda *a, **k: (2.03, "重复"))
    monkeypatch.setattr(flow.random, "choice", lambda seq: seq[0])
    picked = flow._pick_avoiding_repeats(cfg, 2.075, 2.0, 2.2, [2.03, 2.05])
    assert picked is not None
    assert abs(picked[0] - 2.03) >= 0.02
    assert abs(picked[0] - 2.05) >= 0.02


def test_randomized_target_records_and_avoids_repeat(tmp_path, monkeypatch):
    monkeypatch.setattr(flow, "PROJECT_ROOT", tmp_path)
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(flow, "_draw_random_target", lambda *a, **k: (2.04, "固定值"))
    monkeypatch.setattr(flow.random, "choice", lambda seq: seq[0])

    first = flow.randomized_target(cfg, logging.getLogger("t"))
    assert first == 2.04
    assert 2.04 in flow._load_used_finish_targets(cfg)

    second = flow.randomized_target(cfg, logging.getLogger("t"))
    assert second != 2.04  # 当天已用过，重新选择
    assert len(flow._load_used_finish_targets(cfg)) == 2
