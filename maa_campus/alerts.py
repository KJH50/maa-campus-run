"""失败告警：generic / wecom / dingtalk / serverchan / bark。"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime


def send_alert(cfg: dict, logger: logging.Logger, event: str, title: str, content: str,
               shot=None, force: bool = False) -> bool:
    """按 config.alerts 推送告警，返回是否成功。"""
    alerts = cfg.get("alerts") or {}
    if not alerts.get("enabled") and not force:
        return False
    if not force and event not in (alerts.get("on") or []):
        return False
    url = (alerts.get("webhook_url") or "").strip()
    if not url:
        logger.warning("告警未发送：未配置 alerts.webhook_url")
        return False

    kind = (alerts.get("type") or "generic").lower()
    text = f"{title}\n{content}"
    if shot:
        text += f"\n截图：{shot}"

    try:
        if kind in ("wecom", "dingtalk"):
            payload = {"msgtype": "text", "text": {"content": text}}
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
        elif kind == "serverchan":
            data = urllib.parse.urlencode({"title": title, "desp": text}).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"})
        elif kind == "bark":
            payload = {"title": title, "body": content}
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
        else:  # generic webhook
            payload = {
                "event": event,
                "title": title,
                "content": text,
                "time": datetime.now().isoformat(timespec="seconds"),
            }
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read(512)
        logger.info("告警已发送（%s）：%s", kind, event)
        return True
    except Exception as e:
        logger.warning("告警发送失败（%s）：%s", event, e)
        return False
