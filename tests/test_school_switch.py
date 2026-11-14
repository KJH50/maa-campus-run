"""登录页学校切换：顶部学校名 → 选择学校 → 目标学校。"""

import logging

from maa_campus import flow
from maa_campus.page_observer import OCText


def _cfg(school="湖南高速铁路职业技术学院"):
    return {"campus": {"package": "c", "activity": "c/.Main", "school": school}}


def _item(text, y=40, x=600):
    return OCText(text=text, score=0.9, box=(x, y, 90, 25))


def test_school_switch_skips_when_not_configured(monkeypatch):
    monkeypatch.setattr(flow, "ocr_texts",
                        lambda tasker: (_ for _ in ()).throw(AssertionError("不应 OCR")))
    assert flow._switch_campus_school(object(), object(), _cfg(school=""),
                                      logging.getLogger("t")) is True


def test_school_switch_already_selected(monkeypatch):
    items = [_item("湖南高速铁路职业技术学院>")]
    from maa_campus import page_observer

    monkeypatch.setattr(page_observer, "scan_ocr", lambda tasker: items)
    assert flow._switch_campus_school(object(), object(), _cfg(),
                                      logging.getLogger("t")) is True


def test_school_switch_opens_selector_and_picks_school(monkeypatch):
    from maa_campus import page_observer

    pages = iter([
        [_item("怀化学院>")],
        [_item("选择学校", y=430, x=60),
         _item("湖南高速铁路职业技术学院", y=810, x=130),
         _item("怀化学院", y=550, x=130)],
        [_item("湖南高速铁路职业技术学院>")],
    ])
    taps = []
    monkeypatch.setattr(page_observer, "scan_ocr", lambda tasker: next(pages))
    monkeypatch.setattr(flow, "ocr_tap", lambda tasker, patterns: taps.append(patterns) or True)
    monkeypatch.setattr(flow.time, "sleep", lambda seconds: None)

    assert flow._switch_campus_school(object(), object(), _cfg(),
                                      logging.getLogger("t")) is True
    assert taps == [["怀化学院>"], ["湖南高速铁路职业技术学院"]]


def test_school_switch_missing_school_in_list(monkeypatch):
    from maa_campus import page_observer

    items = [_item("选择学校", y=430, x=60), _item("怀化学院", y=550, x=130)]
    monkeypatch.setattr(page_observer, "scan_ocr", lambda tasker: items)
    monkeypatch.setattr(flow, "ocr_tap", lambda *a, **k: True)

    assert flow._switch_campus_school(object(), object(), _cfg(),
                                      logging.getLogger("t")) is False


def test_school_switch_no_selector_falls_back(monkeypatch):
    from maa_campus import page_observer

    items = [_item("请输入账号", y=900, x=100), _item("登录→", y=750, x=300)]
    monkeypatch.setattr(page_observer, "scan_ocr", lambda tasker: items)
    assert flow._switch_campus_school(object(), object(), _cfg(),
                                      logging.getLogger("t")) is True


def test_school_selector_text_ignores_non_top_text():
    items = [_item("湖南高速铁路职业技术学院", y=500, x=100)]
    assert flow._school_selector_text(items) is None
    assert flow._school_selector_text([_item("怀化学院>")]) == "怀化学院>"
