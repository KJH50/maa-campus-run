"""最小 5 段 cron 解析（分 时 日 月 周），用于 AI 定时页面检查。

支持：`*`、数字、范围 `a-b`、列表 `a,b`、步长 `*/n` / `a-b/n`。
周字段 0=周日，1=周一 … 6=周六（与 cron 习惯一致）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_CACHE: dict[str, tuple[frozenset[int], ...]] = {}


def _parse_field(spec: str, lo: int, hi: int) -> frozenset[int]:
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"cron 字段为空：{spec!r}")
        step = 1
        if "/" in part:
            part, step_txt = part.split("/", 1)
            try:
                step = int(step_txt)
            except ValueError as e:
                raise ValueError(f"cron 步长非法：{spec!r}") from e
            if step <= 0:
                raise ValueError(f"cron 步长必须大于 0：{spec!r}")
        if part in ("*", "?"):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < lo or end > hi or start > end:
            raise ValueError(f"cron 字段超出范围 {lo}-{hi}：{spec!r}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


def parse_cron(expr: str) -> tuple[frozenset[int], ...]:
    """解析 5 段 cron 表达式，返回各字段允许值集合。"""
    expr = " ".join(str(expr).split())
    if expr in _CACHE:
        return _CACHE[expr]
    parts = expr.split(" ")
    if len(parts) != 5:
        raise ValueError(f"cron 表达式需要 5 段（分 时 日 月 周）：{expr!r}")
    parsed = tuple(_parse_field(p, lo, hi) for p, (lo, hi) in zip(parts, _RANGES))
    _CACHE[expr] = parsed
    return parsed


def cron_matches(expr: str, dt: datetime) -> bool:
    """判断给定分钟是否匹配 cron 表达式。"""
    minute, hour, day, month, weekday = parse_cron(expr)
    cron_weekday = (dt.weekday() + 1) % 7  # Python 周一=0 → cron 周日=0
    return (dt.minute in minute and dt.hour in hour and dt.day in day
            and dt.month in month and cron_weekday in weekday)


def next_cron_delay(expr: str, now: datetime) -> int:
    """返回距离下一个匹配分钟还有多少秒（最多搜索 366 天）。"""
    parse_cron(expr)  # 提前校验
    current = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):
        if cron_matches(expr, current):
            return max(1, int((current - now).total_seconds()))
        current += timedelta(minutes=1)
    raise ValueError(f"cron 表达式在一年内没有匹配时间：{expr!r}")
