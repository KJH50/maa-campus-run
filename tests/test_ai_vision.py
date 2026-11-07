import json
import logging
import urllib.error

import pytest

from maa_campus import ai_vision as av


def _logger():
    return logging.getLogger("test-ai")


def test_parse_decision_ok():
    d = av.parse_decision('{"action":"click","target":"开始","params":{},"confidence":0.9,"reason":"命中开始"}')
    assert d.action == "click"
    assert d.target == "开始"
    assert d.confidence == 0.9


def test_parse_decision_invalid():
    bad = [
        {"action": "jump", "confidence": 0.9, "reason": "x"},
        {"action": "click", "confidence": 2, "reason": "x"},
        {"action": "click", "confidence": 0.9, "reason": ""},
        {"action": "click", "params": [], "confidence": 0.9, "reason": "x"},
    ]
    for payload in bad:
        with pytest.raises(av.AIError):
            av.parse_decision(payload)
    with pytest.raises(av.AIError):
        av.parse_decision("not json at all")


def test_mock_provider():
    aw = {"ai": {"provider": "mock", "mock_response": {
        "action": "click", "target": "开始", "params": {},
        "confidence": 0.8, "reason": "mock"}}}
    d = av.request_decision(aw, b"", {}, _logger(), env={})
    assert d.action == "click"


def test_missing_config():
    aw = {"ai": {"provider": "openai-compatible"}}
    with pytest.raises(av.AIError) as exc:
        av.request_decision(aw, b"", {}, _logger(), env={})
    assert exc.value.code == av.AI_NOT_CONFIGURED


def test_http_error_mapped():
    aw = {"ai": {"provider": "openai-compatible", "endpoint": "http://x",
                 "api_key": "k", "model": "m", "timeout_seconds": 1}}

    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 500, "err", {}, None)

    with pytest.raises(av.AIError) as exc:
        av.request_decision(aw, b"", {}, _logger(), env={}, opener=opener)
    assert exc.value.code == av.AI_HTTP


def test_openai_compatible_response():
    aw = {"ai": {"provider": "openai-compatible", "endpoint": "http://x",
                 "api_key": "k", "model": "m", "timeout_seconds": 5}}
    content = json.dumps({"action": "wait", "target": None, "params": {"seconds": 2},
                          "confidence": 0.9, "reason": "等待"})

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def opener(req, timeout):
        assert req.get_header("Authorization") == "Bearer k"
        return Resp()

    d = av.request_decision(aw, b"", {}, _logger(), env={}, opener=opener)
    assert d.action == "wait"
