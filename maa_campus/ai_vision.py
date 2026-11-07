"""AI 视觉决策客户端（OpenAI 兼容 / mock）。

Deepseek Homesh 等外部服务若提供 OpenAI 兼容的 Chat Completions（带图片输入）接口，
即可通过环境变量配置接入；不要把 API Key 写入代码或仓库。

配置读取优先级：`ai_watch.ai.*` → 环境变量（默认 DEEPSEEK_ENDPOINT / DEEPSEEK_API_KEY /
DEEPSEEK_MODEL，可在配置里改名）。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field

ALLOWED_ACTIONS = ("click", "input", "scroll", "wait", "retry", "abort")

# 可追踪错误码
AI_NOT_CONFIGURED = "AI_NOT_CONFIGURED"
AI_EMPTY_RESPONSE = "AI_EMPTY_RESPONSE"
AI_INVALID_JSON = "AI_INVALID_JSON"
AI_SCHEMA = "AI_SCHEMA"
AI_NETWORK = "AI_NETWORK"
AI_TIMEOUT = "AI_TIMEOUT"
AI_HTTP = "AI_HTTP"


class AIError(RuntimeError):
    """AI 调用/解析错误，携带稳定错误码。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class Decision:
    action: str
    target: str | None
    params: dict = field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "target": self.target,
            "params": self.params,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AIError(AI_INVALID_JSON, "响应中未找到 JSON 对象")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AIError(AI_INVALID_JSON, f"JSON 解析失败：{e}") from e
    if not isinstance(data, dict):
        raise AIError(AI_INVALID_JSON, "JSON 顶层必须是对象")
    return data


def parse_decision(raw: str | dict) -> Decision:
    """解析并校验 AI 返回的结构化决策。"""
    data = _extract_json_object(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise AIError(AI_SCHEMA, "决策必须是 JSON 对象")
    action = data.get("action")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise AIError(AI_SCHEMA, f"不支持的动作类型：{action!r}")
    target = data.get("target")
    if target is not None and not isinstance(target, str):
        raise AIError(AI_SCHEMA, "target 必须是字符串或 null")
    params = data.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise AIError(AI_SCHEMA, "params 必须是对象")
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError) as e:
        raise AIError(AI_SCHEMA, "confidence 必须是 0~1 的数字") from e
    if not 0.0 <= confidence <= 1.0:
        raise AIError(AI_SCHEMA, f"confidence 超出 0~1：{confidence}")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise AIError(AI_SCHEMA, "reason 必须是非空字符串")
    return Decision(action=action, target=target, params=params,
                    confidence=confidence, reason=reason.strip())


def resolve_ai_config(aw: dict, env: dict | None = None) -> dict:
    """合并配置与环境变量，返回 AI 连接参数（不含明文日志）。"""
    ai = (aw or {}).get("ai") or {}
    env = env if env is not None else os.environ
    provider = str(ai.get("provider") or "openai-compatible").strip().lower()

    def pick(conf_key: str, env_key: str, default_env: str) -> str:
        value = str(ai.get(conf_key) or "").strip()
        if value:
            return value
        return str(env.get(str(ai.get(env_key) or default_env)) or "").strip()

    return {
        "provider": provider,
        "endpoint": pick("endpoint", "env_endpoint", "DEEPSEEK_ENDPOINT"),
        "api_key": pick("api_key", "env_api_key", "DEEPSEEK_API_KEY"),
        "model": pick("model", "env_model", "DEEPSEEK_MODEL"),
        "timeout_seconds": float(ai.get("timeout_seconds") or 30),
        "json_mode": bool(ai.get("json_mode", False)),
        "mock_response": ai.get("mock_response"),
        "mock_file": ai.get("mock_file"),
    }


def _build_payload(cfg: dict, image_bytes: bytes, mime: str, context: dict) -> dict:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "你是自动化页面的视觉解析器。请根据截图与上下文判断当前页面状态，并给出下一步操作。\n"
        "只输出一个 JSON 对象，字段：action, target, params, confidence, reason。\n"
        f"action 只能是 {list(ALLOWED_ACTIONS)} 之一；target 为目标文字/选择器或 null；"
        "params 为对象（如 click: {x,y} 或 input: {text}；scroll: {direction,distance}；wait: {seconds}）。\n"
        "confidence 为 0~1 的小数；reason 用一句话说明判断依据。\n"
        f"上下文：{json.dumps(context, ensure_ascii=False)}"
    )
    return {
        "model": cfg["model"],
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
    }


def _http_post(cfg: dict, payload: dict, opener=None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        cfg["endpoint"], data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(req, timeout=cfg["timeout_seconds"]) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise AIError(AI_HTTP, f"HTTP {e.code}") from e
    except (socket.timeout, TimeoutError) as e:
        raise AIError(AI_TIMEOUT, f"请求超时：{e}") from e
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        code = AI_TIMEOUT if "timed out" in reason.lower() else AI_NETWORK
        raise AIError(code, reason) from e
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        raise AIError(AI_INVALID_JSON, f"HTTP 响应不是 JSON：{e}") from e


def _content_text(resp: dict) -> str:
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(AI_SCHEMA, "响应缺少 choices[0].message.content") from e
    if isinstance(content, list):  # 多模态分段
        text = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    else:
        text = str(content or "")
    if not text.strip():
        raise AIError(AI_EMPTY_RESPONSE, "模型返回内容为空")
    return text


def request_decision(aw: dict, image_bytes: bytes, context: dict,
                     logger: logging.Logger, env: dict | None = None,
                     opener=None, mime: str = "image/jpeg") -> Decision:
    """请求 AI 决策；mock provider 用于离线验收。"""
    cfg = resolve_ai_config(aw, env)
    provider = cfg["provider"]

    if provider == "mock":
        mock = cfg.get("mock_response")
        if mock is None and cfg.get("mock_file"):
            path = os.path.expanduser(str(cfg["mock_file"]))
            try:
                with open(path, "r", encoding="utf-8-sig") as fh:
                    mock = json.load(fh)
            except (OSError, ValueError) as e:
                raise AIError(AI_NOT_CONFIGURED, f"mock_file 读取失败：{e}") from e
        if mock is None:
            raise AIError(AI_NOT_CONFIGURED, "mock provider 未配置 mock_response/mock_file")
        logger.info("AI mock provider：使用本地模拟响应")
        return parse_decision(mock)

    if provider != "openai-compatible":
        raise AIError(AI_NOT_CONFIGURED, f"暂不支持的 provider：{provider}")
    if not cfg["endpoint"] or not cfg["api_key"] or not cfg["model"]:
        raise AIError(AI_NOT_CONFIGURED,
                      "AI 未配置完整：需要 endpoint / api_key / model（环境变量或 ai_watch.ai）")

    payload = _build_payload(cfg, image_bytes, mime, context)
    logger.info("请求 AI 决策：model=%s，图片 %.1f KB", cfg["model"], len(image_bytes) / 1024)
    resp = _http_post(cfg, payload, opener=opener)
    return parse_decision(_content_text(resp))
