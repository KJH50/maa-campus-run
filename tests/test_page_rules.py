from maa_campus.page_observer import OCText, PageSnapshot, evaluate_rules


def _snap(texts, blank=0.0):
    ocr = [OCText(text=t, score=s) for t, s in texts]
    return PageSnapshot(image=None, ocr=ocr, blank_ratio=blank, url="app://test")


def test_normal_page():
    rules = {"expected_selectors": ["^开始$"], "unique_selectors": ["^开始$"],
             "error_keywords": ["验证码"]}
    verdict = evaluate_rules(_snap([("开始", 0.95)]), rules)
    assert verdict.uncertain is False
    assert verdict.reasons == []


def test_missing_expected():
    verdict = evaluate_rules(_snap([("首页", 0.9)]), {"expected_selectors": ["^开始$"]})
    assert verdict.uncertain
    assert "missing_expected" in verdict.codes


def test_multiple_candidates():
    verdict = evaluate_rules(_snap([("开始", 0.9), ("开始", 0.8)]),
                             {"unique_selectors": ["^开始$"]})
    assert verdict.uncertain
    assert "multiple_candidates" in verdict.codes


def test_error_keyword():
    verdict = evaluate_rules(_snap([("网络异常，请重试", 0.9)]),
                             {"error_keywords": ["网络异常"]})
    assert verdict.uncertain
    assert "error_keyword" in verdict.codes


def test_blank_screen():
    verdict = evaluate_rules(_snap([], blank=0.995),
                             {"blank_screen": {"enabled": True, "threshold": 0.98}})
    assert verdict.uncertain
    assert "blank_screen" in verdict.codes


def test_low_confidence():
    verdict = evaluate_rules(_snap([("开始", 0.2)]),
                             {"low_confidence": {"enabled": True, "threshold": 0.5}})
    assert verdict.uncertain
    assert "low_confidence" in verdict.codes


def test_ocr_empty_with_expected():
    verdict = evaluate_rules(_snap([], blank=0.1), {"expected_selectors": ["^开始$"]})
    assert verdict.uncertain
    assert "ocr_empty" in verdict.codes or "missing_expected" in verdict.codes
