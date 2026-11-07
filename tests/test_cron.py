from datetime import datetime

import pytest

from maa_campus import cron


def test_parse_and_match():
    assert cron.cron_matches("*/5 * * * *", datetime(2026, 1, 1, 7, 5))
    assert not cron.cron_matches("*/5 * * * *", datetime(2026, 1, 1, 7, 6))
    assert cron.cron_matches("30 6 * * *", datetime(2026, 1, 1, 6, 30))
    # 2026-01-01 是周四（cron 4）
    assert cron.cron_matches("0 0 * * 4", datetime(2026, 1, 1, 0, 0))
    assert not cron.cron_matches("0 0 * * 5", datetime(2026, 1, 1, 0, 0))


def test_parse_invalid():
    for expr in ("* * * *", "* * * * * *", "60 * * * *", "*/0 * * * *", "a * * * *"):
        with pytest.raises(ValueError):
            cron.parse_cron(expr)


def test_next_delay():
    now = datetime(2026, 1, 1, 6, 29, 0)
    assert cron.next_cron_delay("30 6 * * *", now) == 60
    now = datetime(2026, 1, 1, 6, 31, 0)
    assert cron.next_cron_delay("30 6 * * *", now) == 24 * 3600 - 60
