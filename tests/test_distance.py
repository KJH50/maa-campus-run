from maa_campus.distance import parse_stats

CFG = {}


def test_parse_standard_texts():
    texts = ["总距离", "2.04", "00:14:50", "平均配速", "7'27\""]
    dist, pace, elapsed = parse_stats(texts, CFG)
    assert dist == 2.04
    assert abs(pace - (7 + 27 / 60)) < 1e-6
    assert elapsed == 14 * 60 + 50


def test_parse_custom_distance_regex():
    # 自定义正则只接受纯整数距离（默认正则不会命中）
    dist, _, _ = parse_stats(["2", "3.5"], {"distance_regex": r"^\d+$"})
    assert dist == 2.0


def test_parse_missing_items():
    dist, pace, elapsed = parse_stats(["无关文字"], CFG)
    assert dist is None
    assert pace is None
    assert elapsed is None


def test_parse_invalid_regex_falls_back():
    dist, _, _ = parse_stats(["2.04"], {"distance_regex": "["})
    assert dist == 2.04
