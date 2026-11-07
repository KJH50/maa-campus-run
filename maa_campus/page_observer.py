"""页面观察：截图、OCR 文本、脱敏、空白检测与非确定画面判定。"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from PIL import Image

from .tasks import post_and_wait

# 判定原因/错误码
UNCERTAIN_MISSING = "missing_expected"
UNCERTAIN_MULTIPLE = "multiple_candidates"
UNCERTAIN_ERROR_KEYWORD = "error_keyword"
UNCERTAIN_BLANK = "blank_screen"
UNCERTAIN_LOW_CONFIDENCE = "low_confidence"
UNCERTAIN_OCR_EMPTY = "ocr_empty"
UNCERTAIN_SELECTOR_MISMATCH = "selector_mismatch"


@dataclass
class OCText:
    text: str
    score: float
    box: tuple[int, int, int, int] | None = None  # x, y, w, h

    def center(self) -> tuple[int, int] | None:
        if not self.box:
            return None
        x, y, w, h = self.box
        return x + w // 2, y + h // 2


@dataclass
class PageSnapshot:
    image: Image.Image | None
    ocr: list[OCText] = field(default_factory=list)
    blank_ratio: float = 0.0
    url: str = ""
    captured_at: str = ""

    @property
    def texts(self) -> list[str]:
        return [o.text for o in self.ocr if o.text]

    def find(self, pattern: str) -> list[OCText]:
        try:
            regex = re.compile(pattern)
        except re.error:
            return []
        return [o for o in self.ocr if regex.search(o.text or "")]


@dataclass
class RuleVerdict:
    uncertain: bool
    reasons: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)


def _box_value(raw) -> tuple[int, int, int, int] | None:
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        try:
            return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
        except (TypeError, ValueError):
            return None
    if isinstance(raw, dict):
        try:
            return (int(raw.get("x", 0)), int(raw.get("y", 0)),
                    int(raw.get("w", 0)), int(raw.get("h", 0)))
        except (TypeError, ValueError):
            return None
    return None


def ocr_texts_from_detail(detail) -> list[OCText]:
    """从 MaaFw TaskDetail 中提取 OCR 文本/置信度/位置（兼容 raw_detail 结构）。"""
    out: list[OCText] = []
    if detail is None:
        return out
    try:
        nodes = getattr(detail, "nodes", None) or []
    except Exception:  # noqa: BLE001
        nodes = []
    for node in nodes:
        reco = getattr(node, "recognition", None) or getattr(node, "reco", None)
        raw = getattr(reco, "raw_detail", None) if reco is not None else None
        if not isinstance(raw, dict):
            continue
        items = raw.get("all") or raw.get("filtered") or []
        if isinstance(items, dict):
            items = [items]
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "")
            try:
                score = float(item.get("score", item.get("confidence", 0.0)))
            except (TypeError, ValueError):
                score = 0.0
            box = _box_value(item.get("box", item.get("rect")))
            out.append(OCText(text=text, score=score, box=box))
    return out


def scan_ocr(tasker) -> list[OCText]:
    """用现有 Probe 节点（OCR expected=.*）扫描整屏文字。"""
    job = post_and_wait(tasker, "Probe")
    return ocr_texts_from_detail(job.get())


def capture_image(controller) -> Image.Image:
    """从控制器截图并转为 PIL Image。"""
    arr = controller.screencap()
    return Image.fromarray(arr)


def mask_regions(image: Image.Image, regions: list) -> Image.Image:
    """对配置区域画黑遮罩（脱敏后用于上传/留档）。"""
    if not regions:
        return image
    from PIL import ImageDraw

    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    width, height = masked.size
    for region in regions:
        try:
            if isinstance(region, dict):
                x, y = int(region.get("x", 0)), int(region.get("y", 0))
                w, h = int(region.get("w", region.get("width", 0))), \
                    int(region.get("h", region.get("height", 0)))
            else:
                x, y, w, h = (int(v) for v in region[:4])
        except (TypeError, ValueError):
            continue
        draw.rectangle([x, y, min(width, x + max(0, w)), min(height, y + max(0, h))],
                       fill=(0, 0, 0))
    return masked


def encode_image(image: Image.Image, fmt: str = "jpeg", quality: int = 75,
                 max_width: int = 1280) -> tuple[bytes, str]:
    """压缩/缩放后编码为 PNG/JPEG，返回 (bytes, mime)。"""
    fmt = (fmt or "jpeg").lower()
    img = image
    if max_width and img.width > max_width:
        ratio = max_width / float(img.width)
        img = img.resize((max_width, max(1, int(img.height * ratio))), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt == "png":
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    quality = max(1, min(100, int(quality)))
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue(), "image/jpeg"


def blank_ratio(image: Image.Image) -> float:
    """计算接近中位数的像素占比（用于空白页/关键区域缺失检测）。"""
    gray = np.asarray(image.convert("L"), dtype=np.int16)
    if gray.size == 0:
        return 1.0
    median = int(np.median(gray))
    return float(np.mean(np.abs(gray - median) <= 8))


def evaluate_rules(snapshot: PageSnapshot, rules: dict | None) -> RuleVerdict:
    """按配置规则判断当前画面是否属于「非确定画面」。"""
    rules = rules or {}
    reasons: list[str] = []
    codes: list[str] = []

    def add(code: str, reason: str) -> None:
        if code not in codes:
            codes.append(code)
        reasons.append(reason)

    expected = rules.get("expected_selectors") or []
    if rules.get("missing_expected", {}).get("enabled", True):
        for pattern in expected:
            if not snapshot.find(str(pattern)):
                add(UNCERTAIN_MISSING, f"预期元素未出现：{pattern}")

    structure = rules.get("structure_selectors") or []
    if rules.get("selector_mismatch", {}).get("enabled", True):
        for pattern in structure:
            if not snapshot.find(str(pattern)):
                add(UNCERTAIN_SELECTOR_MISMATCH, f"页面结构与预设选择器不匹配：{pattern}")

    unique = rules.get("unique_selectors") or []
    if rules.get("multiple_candidates", {}).get("enabled", True):
        for pattern in unique:
            matches = snapshot.find(str(pattern))
            if not matches:
                add(UNCERTAIN_MISSING, f"唯一元素未出现：{pattern}")
            elif len(matches) > 1:
                add(UNCERTAIN_MULTIPLE, f"元素出现多个候选：{pattern}（{len(matches)}）")

    keywords = rules.get("error_keywords") or []
    if rules.get("error_keyword", {}).get("enabled", True) and keywords:
        for keyword in keywords:
            for text in snapshot.texts:
                if str(keyword) in text:
                    add(UNCERTAIN_ERROR_KEYWORD, f"出现异常提示：{keyword}")
                    break

    blank_cfg = rules.get("blank_screen") or {}
    if blank_cfg.get("enabled", True):
        threshold = float(blank_cfg.get("threshold", 0.98))
        if snapshot.blank_ratio >= threshold:
            add(UNCERTAIN_BLANK, f"关键区域接近空白（blank_ratio={snapshot.blank_ratio:.3f}）")

    conf_cfg = rules.get("low_confidence") or {}
    if conf_cfg.get("enabled", True):
        threshold = float(conf_cfg.get("threshold", 0.5))
        if not snapshot.ocr:
            if rules.get("ocr_empty", {}).get("enabled", True) and expected:
                add(UNCERTAIN_OCR_EMPTY, "OCR 未识别到任何文字（可能加载中/遮挡）")
        else:
            best = max(o.score for o in snapshot.ocr)
            if best < threshold:
                add(UNCERTAIN_LOW_CONFIDENCE, f"OCR 置信度偏低（best={best:.2f} < {threshold:.2f}）")

    return RuleVerdict(uncertain=bool(codes), reasons=reasons, codes=codes)


def build_snapshot(controller, tasker, url: str = "", logger: logging.Logger | None = None) -> PageSnapshot:
    """抓取当前页面并构建快照（截图失败抛异常，由调用方记录错误码）。"""
    image = capture_image(controller)
    try:
        ocr = scan_ocr(tasker)
    except Exception as e:  # noqa: BLE001
        if logger:
            logger.warning("OCR 扫描失败（按空结果处理）：%s", e)
        ocr = []
    return PageSnapshot(
        image=image,
        ocr=ocr,
        blank_ratio=blank_ratio(image),
        url=url,
        captured_at=datetime.now().isoformat(timespec="seconds"),
    )
