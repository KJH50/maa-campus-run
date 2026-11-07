"""失败告警：generic / wecom / dingtalk / serverchan / bark；无 webhook 时写本地留档。"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def local_alert_path(cfg: dict) -> Path:
    """本地告警留档路径：<log_dir>/alerts_YYYYMMDD.log。"""
    log_dir = Path(cfg.get("log_dir") or "logs")
    if not log_dir.is_absolute():
        log_dir = Path(__file__).resolve().parent.parent / log_dir
    return log_dir / f"alerts_{datetime.now():%Y%m%d}.log"


def _write_local(cfg: dict, logger: logging.Logger, record: dict) -> bool:
    """把告警追加写入本地文件（webhook 未配置或推送失败时的兜底）。"""
    try:
        path = local_alert_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("告警本地留档失败：%s", e)
        return False


def send_alert(cfg: dict, logger: logging.Logger, event: str, title: str, content: str,
               shot=None, force: bool = False) -> bool:
    """按 config.alerts 推送告警；未配置 webhook 或推送失败时自动写本地留档。

    返回 True 表示告警已落地（远端推送成功，或已写入本地 alerts_YYYYMMDD.log）。
    """
    alerts = cfg.get("alerts") or {}
    if not alerts.get("enabled") and not force:
        return False
    if not force and event not in (alerts.get("on") or []):
        return False

    kind = (alerts.get("type") or "generic").lower()
    url = (alerts.get("webhook_url") or "").strip()
    text = f"{title}\n{content}"
    if shot:
        text += f"\n截图：{shot}"
    record = {
        "event": event,
        "title": title,
        "content": text,
        "time": datetime.now().isoformat(timespec="seconds"),
    }

    pushed = False
    if url:
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
                    "time": record["time"],
                }
                req = urllib.request.Request(
                    url, data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read(512)
            logger.info("告警已发送（%s）：%s", kind, event)
            pushed = True
        except Exception as e:  # noqa: BLE001
            logger.warning("告警发送失败（%s）：%s", event, e)
    else:
        logger.warning("告警 webhook 未配置（alerts.webhook_url 为空），改走本地留档")

    written = _write_local(cfg, logger, record)
    if written and not pushed:
        logger.warning("告警已写入本地文件：%s", local_alert_path(cfg))
    return pushed or written
