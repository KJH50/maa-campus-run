"""距离 / 配速 / 时间识别与解析。"""

from __future__ import annotations

import re

from .tasks import post_and_wait

DEFAULT_DIST_RE = r"^\d+\.\d{2}$"
_PACE_RE = re.compile(r"^(\d{1,2})['′](\d{1,2})[″\"”]?$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")


def collect_texts(detail) -> list[str]:
    """从 MaaFramework TaskDetail 中收集全部 OCR 文本。"""
    texts: list[str] = []
    if detail is None:
        return texts
    for node in detail.nodes:
        reco = node.recognition
        if reco is None:
            continue
        for r in (reco.all_results or []):
            t = getattr(r, "text", "") or ""
            t = t.strip()
            if t:
                texts.append(t)
    return texts


def parse_stats(texts: list[str], cfg: dict) -> tuple[float | None, float | None, int | None]:
    """从 OCR 文本解析（总距离 km、平均配速 min/km、总时间 s），识别失败的项为 None。"""
    try:
        dist_re = re.compile(cfg.get("distance_regex") or DEFAULT_DIST_RE)
    except re.error:
        dist_re = re.compile(DEFAULT_DIST_RE)

    dist = None
    pace = None
    time_s = None
    for t in texts:
        if dist is None and dist_re.fullmatch(t):
            try:
                dist = float(t)
            except ValueError:
                pass
            continue
        if time_s is None:
            m = _TIME_RE.fullmatch(t)
            if m:
                time_s = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                continue
        if pace is None:
            m = _PACE_RE.fullmatch(t)
            if m:
                pace = int(m.group(1)) + int(m.group(2)) / 60.0
    return dist, pace, time_s


def read_stats(tasker, cfg: dict) -> tuple[float | None, float | None, int | None]:
    """OCR 读取总距离（公里）、平均配速（分钟/公里）、总时间（秒）。"""
    job = post_and_wait(tasker, "ReadStats", {"ReadStats": {"expected": [".+"]}})
    if not job.succeeded:
        return None, None, None
    return parse_stats(collect_texts(job.get()), cfg)
