"""主流程：校园跑完整业务流程。

顺序：登录检测（未登录先进入自动登录）→ 准备 RunSimulation（标准路线）
      → 准备健行校园（首页 → 继续征程）→ 点 RunSimulation 的「开始跑步」
      → 点健行校园的「开始」→ 开跑前置校验
      → 等待 + 轮询距离/配速 → 结束/结算 → 停止模拟并关闭 App → 关闭模拟器。
基础设施（adb/MuMu 启停、MaaFw 初始化、OCR 原语）见 emulator.py / maa_tasks.py。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from datetime import date
from pathlib import Path

from .alerts import send_alert
from .distance import read_stats
from .emulator import ensure_emulator, make_adb, shutdown_emulator
from .evidence import save_shot
from .maa_tasks import SETTLE_MARKERS, build_tasker, ocr_probe, ocr_tap, ocr_texts
from .tasks import post_and_wait


def _fail(cfg: dict, logger: logging.Logger, event: str, title: str, content: str,
          code: int, shot=None) -> int:
    """发送失败告警并返回退出码（统一失败路径）。"""
    send_alert(cfg, logger, event, title, content, shot)
    return code


# 校园跑页状态标记：点「开始」后 App 可能加载较久，需要区分「还在加载」与「真的没起来」
CAMPUS_IDLE_MARKERS = ["^开始$", "^点击跑步$"]
CAMPUS_RUNNING_MARKERS = ["点击结束跑步", "^结束$"]
CAMPUS_LOADING_MARKERS = [
    "加载中", "正在加载", "加载数据", "加载页面", "请稍候", "请稍后",
    "正在同步", "同步中", "正在进入", "正在开始",
]
CAMPUS_LOGIN_MARKERS = [
    "手机号登录", "学号登录", "账号登录", "密码登录", "验证码登录",
    "快捷登录", "登录/注册", "立即登录", "请先登录", "请登录", "未登录",
    "重新登录", "登录已过期", "登录账号", "请输入学号", "请输入手机号",
    "请输入密码", "获取验证码", "^登录$",
    # 学校统一身份认证的引导页/中转页（还没有账号密码输入框）
    "进入统一身份认证", "统一身份认证", "欢迎登录", "身份认证",
]
CAMPUS_LOGGED_IN_MARKERS = ["继续征程", "我的征程", "总距离", "^首页$"]
CAMPUS_LOGIN_ERROR_MARKERS = [
    "用户名或密码错误", "账号或密码错误", "密码错误", "验证码错误",
    "账号不存在", "用户不存在", "账号已被锁定", "登录失败", "认证失败",
]


def _instance_env_suffix(cfg: dict) -> str:
    """实例级环境变量后缀：mumu-1 → MUMU_1（无实例名时为空）。"""
    name = str(cfg.get("instance_name") or "").strip()
    if not name:
        return ""
    return re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").upper()


def _campus_login_credentials(cfg: dict) -> tuple[bool, str, str, bool]:
    """读取自动登录配置；环境变量优先于 config.json（避免把密码写进仓库）。

    多模拟器时支持实例级环境变量：MAA_CAMPUS_USERNAME_MUMU_1 /
    MAA_CAMPUS_PASSWORD_MUMU_1（实例名大写、非字母数字转下划线），
    其次才是全局 MAA_CAMPUS_USERNAME / MAA_CAMPUS_PASSWORD。
    """
    login = ((cfg.get("campus") or {}).get("login") or {})
    enabled = bool(login.get("enabled", True))
    suffix = _instance_env_suffix(cfg)
    username = ""
    password = ""
    if suffix:
        username = os.environ.get(f"MAA_CAMPUS_USERNAME_{suffix}") or ""
        password = os.environ.get(f"MAA_CAMPUS_PASSWORD_{suffix}") or ""
    username = username or os.environ.get("MAA_CAMPUS_USERNAME") or str(login.get("username") or "")
    password = password or os.environ.get("MAA_CAMPUS_PASSWORD") or str(login.get("password") or "")
    return enabled, username.strip(), password, bool(login.get("remember_week", False))


def _first_text_match(texts: list[str], patterns: list[str]) -> str | None:
    for text in texts:
        for pattern in patterns:
            try:
                if re.search(pattern, text or ""):
                    return text
            except re.error:
                continue
    return None


def _auth_form_visible(texts: list[str]) -> bool:
    return any("用户名" in t for t in texts)


def _click_agreement_checkbox(tasker, controller, logger: logging.Logger) -> bool:
    """登录引导页：协议勾选框没有文字，按 OCR 文本框左侧的固定偏移点击。"""
    try:
        from .page_observer import scan_ocr

        items = scan_ocr(tasker)
        target = next((o for o in items if "同意" in o.text and "隐私" in o.text), None)
        if target is None or target.box is None:
            return False
        img = controller.screencap()
        height, width = img.shape[:2]
        sx, sy = width / 720.0, height / 1280.0  # Maa OCR 模型坐标空间为 720x1280
        x = int((target.box[0] + target.box[2] / 2 - 113) * sx)
        y = int((target.box[1] + target.box[3] / 2) * sy)
        controller.click(x, y)
        logger.info("自动登录：点击协议勾选框")
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("自动登录：勾选协议失败（%s）", e)
        return False


def _enter_auth_from_landing(tasker, controller, logger: logging.Logger) -> bool:
    """从「欢迎登录」引导页点击进入统一身份认证账号密码页。"""
    texts = ocr_texts(tasker)
    if not any("进入统一身份认证" in t for t in texts):
        return False
    post_and_wait(tasker, "TapText", {"TapText": {"expected": ["^进入统一身份认证$"]}})
    time.sleep(2.0)
    if _auth_form_visible(ocr_texts(tasker)):
        return True
    # 首次进入时协议可能未勾选，按钮不可用；勾选后再点一次
    if _click_agreement_checkbox(tasker, controller, logger):
        time.sleep(1.0)
        post_and_wait(tasker, "TapText", {"TapText": {"expected": ["^进入统一身份认证$"]}})
        time.sleep(3.0)
    return _auth_form_visible(ocr_texts(tasker))


def auto_login_campus(tasker, controller, cfg: dict, logger: logging.Logger) -> bool:
    """在统一身份认证页用配置/环境变量自动登录；不输出密码。"""
    enabled, username, password, remember = _campus_login_credentials(cfg)
    if not enabled:
        logger.warning("检测到健行校园登录页，但 campus.login.enabled=false")
        return False
    if not username or not password:
        logger.warning("检测到健行校园登录页，但未配置 campus.login.username/password "
                       "（或 MAA_CAMPUS_USERNAME/MAA_CAMPUS_PASSWORD）")
        return False
    campus_pkg = cfg["campus"]["package"]
    controller.focus_package = campus_pkg

    def tap(patterns: list[str]) -> bool:
        job = post_and_wait(tasker, "TapText", {"TapText": {"expected": patterns}})
        return job.succeeded

    logger.info("检测到登录页，尝试自动登录（用户名已配置，密码不记录）...")
    if not tap(["用户名"]):
        if not _enter_auth_from_landing(tasker, controller, logger):
            logger.warning("自动登录失败：未进入账号密码页")
            return False
        if not tap(["用户名"]):
            logger.warning("自动登录失败：未找到用户名输入框")
            return False
    controller.input_text(username)
    time.sleep(0.5)
    if not tap(["^密码$", "密码"]):
        logger.warning("自动登录失败：未找到密码输入框")
        return False
    controller.input_text(password)
    time.sleep(0.5)
    if remember:
        tap(["一周内免登录"])
    if not tap(["^登录$"]):
        logger.warning("自动登录失败：未找到登录按钮")
        return False

    deadline = time.time() + 25
    portal_clicks = 0
    retry_clicks = 0
    while time.time() < deadline:
        texts = ocr_texts(tasker)
        error_text = _first_text_match(texts, CAMPUS_LOGIN_ERROR_MARKERS)
        if error_text:
            logger.error("自动登录失败：页面提示「%s」", error_text)
            save_shot(controller, "campus_login_failed", logger)
            return False
        if _texts_match(texts, CAMPUS_LOGGED_IN_MARKERS):
            save_shot(controller, "campus_logged_in", logger)
            logger.info("健行校园自动登录成功")
            return True
        # 认证平台有时会先停在「健行校园后台管理系统 → 进入统一身份认证」中转页
        if portal_clicks < 2 and any("进入统一身份认证" in t for t in texts):
            post_and_wait(tasker, "TapText",
                          {"TapText": {"expected": ["^进入统一身份认证$"]}})
            portal_clicks += 1
            logger.info("自动登录：点击认证中转页（第 %s 次）", portal_clicks)
            time.sleep(2.0)
            continue
        # 偶发 WebView 加载失败，尝试重试一次
        if retry_clicks < 1 and any(("网页未能加载" in t or "^重试$" in t) for t in texts):
            post_and_wait(tasker, "TapText", {"TapText": {"expected": ["^重试$"]}})
            retry_clicks += 1
            logger.info("自动登录：认证页加载失败，点击重试")
            time.sleep(2.0)
            continue
        time.sleep(1.5)
    logger.error("自动登录超时：未回到健行校园首页")
    save_shot(controller, "campus_login_failed", logger)
    return False


def _campus_login_failure(controller, cfg: dict, logger: logging.Logger) -> bool:
    logger.error("检测到健行校园未登录；自动登录未完成，请先在模拟器中手动登录后再运行")
    save_shot(controller, "campus_login_required", logger)
    cfg["_campus_login_required"] = True
    return False


def _texts_match(texts: list[str], patterns: list[str]) -> bool:
    for text in texts:
        for pattern in patterns:
            try:
                if re.search(pattern, text or ""):
                    return True
            except re.error:
                continue
    return False


def _campus_login_state(tasker, timeout: float = 10.0) -> str:
    """轮询识别健行校园登录状态：login / logged_in / unknown。

    冷启动或 WebView 加载时首屏可能还没有文字，因此最多等待 timeout 秒；
    登录页优先判断，避免首页加载慢时误判。多模拟器下每个实例各自检测。
    """
    attempts = max(1, int(max(1.0, float(timeout))))
    for i in range(attempts):
        texts = ocr_texts(tasker)
        if _texts_match(texts, CAMPUS_LOGIN_MARKERS):
            return "login"
        if _texts_match(texts, CAMPUS_LOGGED_IN_MARKERS + CAMPUS_IDLE_MARKERS):
            return "logged_in"
        if i + 1 < attempts:
            time.sleep(1.0)
    return "unknown"


def ensure_campus_login(tasker, controller, cfg: dict, logger: logging.Logger,
                        start_app: bool = False, refresh: bool = False) -> bool:
    """登录检测 + 登录流程：确认健行校园已登录，未登录则自动登录。

    start_app=True 时先打开健行校园再检测（流程起点使用）；准备校园跑页时
    App 已在前台，直接检测即可。refresh=True 强制重新检测（App 重启后使用），
    否则复用本轮已确认的登录状态，避免重复 OCR。
    返回 False 表示未登录且自动登录失败，调用方应以退出码 3 结束。
    """
    if not refresh and cfg.get("_campus_login_state") == "ok":
        return True
    if start_app:
        controller.focus_package = cfg["campus"]["package"]
        controller.start_app(cfg["campus"]["activity"])
        time.sleep(2.0)
    state = _campus_login_state(tasker)
    if state == "logged_in":
        logger.info("登录检测：健行校园已登录")
        cfg["_campus_login_state"] = "ok"
        return True
    if state == "unknown":
        logger.warning("登录检测：暂未识别到登录页或已登录页面，继续准备流程（准备阶段会再次检测）")
        return True
    logger.info("登录检测：健行校园未登录，进入自动登录流程 ...")
    if not auto_login_campus(tasker, controller, cfg, logger):
        return _campus_login_failure(controller, cfg, logger)
    cfg["_campus_login_state"] = "ok"
    return True


def _campus_page_state(tasker) -> str:
    """判断校园跑页当前状态：running（已在记录）/ loading（仍在加载）/ idle（待开始）/ unknown。

    单次 OCR 文本扫描后本地分类，避免每个状态各投一次 OCR 任务。
    """
    texts = ocr_texts(tasker)
    if _texts_match(texts, CAMPUS_RUNNING_MARKERS):
        return "running"
    if _texts_match(texts, CAMPUS_LOADING_MARKERS):
        return "loading"
    if _texts_match(texts, CAMPUS_IDLE_MARKERS):
        return "idle"
    return "unknown"


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _instance_key(cfg: dict) -> str:
    """当前实例的稳定标识（用于日志、状态文件、运行锁）；单实例为 default。"""
    name = str(cfg.get("instance_name") or "").strip()
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name) if name else "default"


def _run_lock_path(cfg: dict) -> Path:
    return PROJECT_ROOT / cfg.get("log_dir", "logs") / f".run_{_instance_key(cfg)}.lock"


def _acquire_run_lock(cfg: dict, logger: logging.Logger) -> Path | None:
    """获取实例级运行锁；已有未过期锁时返回 None（调用方返回退出码 5）。"""
    path = _run_lock_path(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("创建运行锁目录失败（%s），拒绝执行以避免并发", e)
        return None
    stale = float(cfg.get("run_lock_stale_seconds", 1800))
    if path.exists():
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            age = 0.0
        if age <= stale:
            logger.warning("实例 %s 已有运行锁（%.0f 秒前创建：%s），拒绝并发执行",
                           _instance_key(cfg), age, path)
            return None
        logger.warning("发现过期运行锁（%.0f 秒前），自动回收：%s", age, path)
        try:
            path.unlink()
        except OSError as e:
            logger.warning("回收过期运行锁失败：%s", e)
            return None
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        logger.warning("实例 %s 运行锁创建冲突，拒绝并发执行", _instance_key(cfg))
        return None
    except OSError as e:
        logger.warning("创建运行锁失败（%s），拒绝执行以避免并发", e)
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"pid={os.getpid()} time={date.today().isoformat()}\n")
    return path


def _release_run_lock(lock: Path | None, logger: logging.Logger) -> None:
    if not lock:
        return
    try:
        lock.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("释放运行锁失败（已忽略）：%s", e)


DEFAULT_RUN_COUNT_PATTERNS = [
    r"已跑\D{0,8}(\d+)\s*次",
    r"已完成\D{0,8}(\d+)\s*次",
    r"累计\D{0,8}(\d+)\s*次",
    r"跑步次数\D{0,8}(\d+)",
    r"已跑\s*(\d+)\s*/\s*\d+\s*次",
    r"(\d+)\s*次\s*/\s*(\d+)\s*次",
]


def _max_runs(cfg: dict) -> int:
    try:
        return max(0, int(cfg.get("max_runs") or 0))
    except (TypeError, ValueError):
        return 0


def _need_run_count(cfg: dict) -> bool:
    """是否需要在准备阶段读取「已跑次数」。"""
    return _max_runs(cfg) > 0 or bool(cfg.get("log_run_count", False))


def read_run_count(tasker, cfg: dict, logger: logging.Logger, quiet: bool = False) -> int | None:
    """从当前页面 OCR 文本中解析「已跑 X 次」；支持配置多个正则。"""
    texts = ocr_texts(tasker)
    joined = "\n".join(texts)
    patterns = cfg.get("run_count_patterns") or DEFAULT_RUN_COUNT_PATTERNS
    for pattern in patterns:
        try:
            match = re.search(str(pattern), joined)
        except re.error:
            continue
        if not match:
            continue
        try:
            count = int(match.group(1))
        except (TypeError, ValueError):
            continue
        if 0 <= count <= 100000:
            logger.info("识别到已跑次数：%s 次", count)
            return count
    if not quiet:
        logger.info("未匹配到已跑次数（max_runs=%s）；OCR 文本：%s",
                    _max_runs(cfg), " | ".join(texts)[:300] if texts else "（空）")
    return None


def _remember_run_count(tasker, cfg: dict, logger: logging.Logger,
                        quiet: bool = True) -> int | None:
    """在准备过程中尽量早、尽量少地读取一次已跑次数（静默扫描最多 3 次）。"""
    if not _need_run_count(cfg):
        return None
    if cfg.get("_observed_run_count") is not None:
        return int(cfg["_observed_run_count"])
    attempts = int(cfg.get("_run_count_scans", 0) or 0)
    if quiet and attempts >= 3:
        return None
    cfg["_run_count_scans"] = attempts + 1
    count = read_run_count(tasker, cfg, logger, quiet=quiet)
    if count is not None:
        cfg["_observed_run_count"] = count
    return count


def _max_runs_marker_path(cfg: dict) -> Path:
    return PROJECT_ROOT / cfg.get("log_dir", "logs") / f".max_runs_reached_{_instance_key(cfg)}.json"


def _max_runs_reached(cfg: dict, logger: logging.Logger) -> bool:
    """读取「已达最高次数」标记，用于下一次触发时免启动直接跳过。"""
    max_runs = _max_runs(cfg)
    if max_runs <= 0:
        return False
    try:
        data = json.loads(_max_runs_marker_path(cfg).read_text(encoding="utf-8"))
        count = float(data.get("count"))
        marked_max = float(data.get("max", 0))
    except (OSError, ValueError, TypeError):
        return False
    if marked_max >= max_runs and count >= max_runs:
        logger.info("已记录达到最高跑步次数（已跑 %.0f / 上限 %s），跳过本次执行（--force 可忽略）",
                    count, max_runs)
        return True
    return False


def _mark_max_runs_reached(cfg: dict, count: int, logger: logging.Logger) -> None:
    max_runs = _max_runs(cfg)
    try:
        path = _max_runs_marker_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"count": count, "max": max_runs,
                                   "time": date.today().isoformat()},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        logger.info("已记录最高跑步次数状态：已跑 %s / 上限 %s", count, max_runs)
    except OSError as e:
        logger.warning("写入最高跑步次数标记失败（已忽略）：%s", e)


def _should_skip_for_max_runs(cfg: dict, count: int | None) -> bool:
    max_runs = _max_runs(cfg)
    return bool(max_runs > 0 and count is not None and count >= max_runs)


def _close_after_max_runs(controller, cfg: dict, logger: logging.Logger,
                          run_pkg: str, campus_pkg: str) -> None:
    """达到最高次数时不开始跑步，关闭 App 并按配置关闭模拟器。"""
    logger.info("已达到最高跑步次数，本次不开始跑步；关闭 App ...")
    for pkg in (run_pkg, campus_pkg):
        try:
            controller.stop_app(pkg)
        except Exception as e:  # noqa: BLE001
            logger.warning("关闭 App %s 失败（已忽略）：%s", pkg, e)
    save_shot(controller, "max_runs_reached", logger)
    shutdown_emulator(cfg, logger)


def _marker_path(cfg: dict) -> Path:
    """当日成功标记文件路径（位于 logs 目录下，已被 .gitignore 忽略；多实例按实例名区分）。"""
    name = str(cfg.get("instance_name") or "").strip()
    suffix = ("_" + re.sub(r"[^0-9A-Za-z_.-]+", "_", name)) if name else ""
    return PROJECT_ROOT / cfg.get("log_dir", "logs") / f".last_success{suffix}"


def _already_succeeded_today(cfg: dict, logger: logging.Logger) -> bool:
    """当天是否已成功完成过一次（避免同日重复提交记录）。"""
    try:
        text = _marker_path(cfg).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return text == date.today().isoformat()


def _mark_success_today(cfg: dict, logger: logging.Logger) -> None:
    """写入当日成功标记；失败只告警、不影响主流程。"""
    try:
        p = _marker_path(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(date.today().isoformat() + "\n", encoding="utf-8")
        logger.info("已写入当日成功标记：%s", p)
    except OSError as e:
        logger.warning("写入当日成功标记失败（已忽略）：%s", e)


def progress_issues(cfg: dict, minute: int, dist, pace, elapsed) -> list[str]:
    """抽检进度合理性：距离/时间/配速是否自洽，返回异常描述列表（空列表表示正常）。"""
    issues: list[str] = []
    if dist is None:
        return [f"开跑 {minute} 分钟未识别到距离"]
    if dist <= 0.0:
        return [f"开跑 {minute} 分钟距离仍为 0.00 km"]
    if elapsed is None or elapsed <= 0:
        return issues
    minutes = elapsed / 60.0
    derived = minutes / dist  # 由距离与总时间推算的平均配速（分/公里）
    min_pace = float(cfg.get("min_pace_minutes", 3.0))
    max_pace = float(cfg.get("max_pace_minutes", 10.0))
    if derived < min_pace * 0.7 or derived > max_pace * 1.4:
        issues.append(f"距离/时间推算配速 {derived:.2f} 分/公里，超出合理区间 {min_pace:.0f}~{max_pace:.0f}")
    if pace is not None and abs(float(pace) - derived) > 2.0:
        issues.append(f"OCR 配速 {float(pace):.2f} 与推算配速 {derived:.2f} 差异过大")
    if dist > (minutes / min_pace) * 1.5:
        issues.append(f"距离 {dist:.2f} km 相对 {minutes:.0f} 分钟偏大（疑似识别错误）")
    if dist < (minutes / max_pace) * 0.5:
        issues.append(f"距离 {dist:.2f} km 相对 {minutes:.0f} 分钟偏小（进度明显偏慢）")
    return issues


# ------------------------------------------------------------------ 启动步骤
STOP_STATE_MARKERS = ["请先停止独立路线播放", "独立路线播放", "停止并恢复系统状态"]
RUN_BUTTON_MARKERS = ["^开始跑步$", "^开始$", "^点击跑步$"]


def _stop_finished_playback(tasker, logger: logging.Logger) -> bool:
    """检测「已完成 / 独立路线播放」状态并点击停止恢复；返回是否执行过清理。"""
    if not ocr_probe(tasker, STOP_STATE_MARKERS):
        return False
    logger.warning("检测到「已完成/独立路线播放」状态，先停止并恢复系统状态 ...")
    ok = ocr_tap(tasker, ["^停止并恢复系统状态$", "^全部停止$", "^停止$"])
    logger.info("停止并恢复：%s", "完成" if ok else "未找到停止按钮（继续尝试准备）")
    time.sleep(2.0)
    return True


def prepare_run_simulation(tasker, controller, cfg: dict, logger: logging.Logger, run_pkg: str) -> bool:
    """把 RunSimulation 开到准备跑步页，并确认路线为「标准」。

    若遇到「已完成 / 请先停止独立路线播放」导致的灰按钮状态，会先停止并恢复后重新准备一次。
    """
    route = (cfg.get("route_text") or "标准").strip()
    logger.info("准备 RunSimulation（路线：%s）...", route)
    controller.focus_package = run_pkg
    override = {
        "CheckStandard": {"expected": [f"^{route}$"]},
        "CheckStandardAgain": {"expected": [f"^{route}$"]},
        "PickStandard": {"expected": [f"^{route}$"]},
    }
    job = post_and_wait(tasker, "RunPrepare", override)
    if not job.succeeded:
        # 停止/已完成状态优先由 pipeline 的 CheckStopState 节点处理；
        # 这里只在准备失败时做一次兜底，避免每轮重复 OCR/点击（省 20~40s）。
        if _stop_finished_playback(tasker, logger):
            logger.info("准备失败后清理完成/独立路线播放状态，重新准备 RunSimulation ...")
            job = post_and_wait(tasker, "RunPrepare", override)
    save_shot(controller, "run_prepared", logger)
    if not job.succeeded:
        logger.error("准备 RunSimulation 失败")
        return False
    return True


def prepare_campus(tasker, controller, cfg: dict, logger: logging.Logger, campus_pkg: str) -> bool:
    """把健行校园开到校园跑页（首页 → 继续征程）。

    App 冷启动可能恢复到「活动与赛事」等非首页页面（上一会话遗留），
    因此这里用 OCR 状态机：放弃未结束记录 / 继续征程 / 首页 / 返回键 / 重开 App，
    直到识别到校园跑页（总距离 + 开始按钮）。
    """
    logger.info("准备健行校园（首页 → 继续征程）...")
    controller.focus_package = campus_pkg
    controller.start_app(cfg["campus"]["activity"])
    time.sleep(2.0)
    _remember_run_count(tasker, cfg, logger)
    if not ensure_campus_login(tasker, controller, cfg, logger, refresh=True):
        return False
    start_markers = CAMPUS_IDLE_MARKERS + CAMPUS_RUNNING_MARKERS
    for attempt in range(1, 10):
        if ocr_probe(tasker, ["放弃这条本地记录", "放弃"]):
            logger.info("发现未正常结束的本地记录，点击「放弃」")
            ocr_tap(tasker, ["放弃这条本地记录", "放弃"])
            time.sleep(1.0)
            if ocr_probe(tasker, ["确认放弃", "确定放弃", "^确认$"]):
                logger.info("点击「确认放弃」")
                ocr_tap(tasker, ["确认放弃", "确定放弃", "^确认$"])
            time.sleep(2.0)
            continue
        if ocr_probe(tasker, ["总距离"]) and ocr_probe(tasker, start_markers):
            _remember_run_count(tasker, cfg, logger, quiet=False)
            logger.info("已进入校园跑页（第 %s 次检查）", attempt)
            save_shot(controller, "campus_prepared", logger)
            return True
        if ocr_probe(tasker, ["继续征程"]):
            _remember_run_count(tasker, cfg, logger)
            logger.info("点击「继续征程」")
            ocr_tap(tasker, ["继续征程"])
            time.sleep(2.5)
            continue
        if ocr_probe(tasker, ["^首页$"]):
            _remember_run_count(tasker, cfg, logger)
            logger.info("点击「首页」")
            ocr_tap(tasker, ["^首页$"])
            time.sleep(1.5)
            continue
        if attempt in (4, 7):
            if not ensure_campus_login(tasker, controller, cfg, logger, refresh=True):
                return False
            logger.info("仍未到校园跑页，重新打开健行校园（第 %s 次）", attempt)
            controller.start_app(cfg["campus"]["activity"])
            time.sleep(2.0)
            continue
        logger.info("未识别到首页/继续征程，按返回键（第 %s 次）", attempt)
        controller.click_key(4)
        time.sleep(1.5)
    save_shot(controller, "campus_prepare_failed", logger)
    logger.error("进入校园跑页失败")
    return False


def verify_running(tasker, controller, cfg: dict, logger: logging.Logger,
                   campus_confirmed: bool = False) -> bool:
    """开跑前置校验：确认两个 App 都真的进入跑步状态，才允许进入 12 分钟等待。

    campus_confirmed=True 表示 start_campus_run 已经轮询确认校园跑进入记录状态，
    此时不再重复检查校园跑，只校验 RunSimulation。
    """
    run_pkg = cfg["run"]["package"]
    campus_pkg = cfg["campus"]["package"]
    run_ok = False
    for _ in range(10):
        controller.focus_package = run_pkg
        if ocr_probe(tasker, ["正在跑步", "暂停跑步"]):
            run_ok = True
            break
        time.sleep(1.5)
    campus_ok = bool(campus_confirmed)
    if campus_confirmed:
        # start_campus_run 已确认进入跑步态；这里做一次快速复核，避免两次检查之间页面被意外退回。
        controller.focus_package = campus_pkg
        for _ in range(2):
            if ocr_probe(tasker, CAMPUS_RUNNING_MARKERS):
                campus_ok = True
                break
            time.sleep(1.0)
    else:
        for _ in range(10):
            controller.focus_package = campus_pkg
            if ocr_probe(tasker, CAMPUS_RUNNING_MARKERS):
                campus_ok = True
                break
            time.sleep(1.5)
    save_shot(controller, "running_check", logger)
    if not run_ok:
        logger.error("开跑前置校验失败：RunSimulation 未显示「正在跑步」")
    if not campus_ok:
        logger.error("开跑前置校验失败：健行校园未显示「点击结束跑步」")
    if not (run_ok and campus_ok):
        return False
    logger.info("开跑前置校验通过：RunSimulation 正在跑步、健行校园正在记录")
    return True


def _finish_targets_key(cfg: dict) -> str:
    """按实例区分当日已用距离（两台设备互不影响，但同一设备当天避免重复）。"""
    return _instance_key(cfg)


def _finish_targets_path(cfg: dict) -> Path:
    return PROJECT_ROOT / cfg.get("log_dir", "logs") / f".finish_targets_{_finish_targets_key(cfg)}.json"


def _load_used_finish_targets(cfg: dict) -> list[float]:
    """读取本实例当天已经用过的结束距离；日期不匹配时视为空。"""
    try:
        data = json.loads(_finish_targets_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get("date") != date.today().isoformat():
        return []
    try:
        return [float(x) for x in data.get("targets") or []]
    except (TypeError, ValueError):
        return []


def _save_used_finish_targets(cfg: dict, used: list[float]) -> None:
    try:
        path = _finish_targets_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"date": date.today().isoformat(),
                                   "targets": [round(float(x), 3) for x in used]},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def _route_geometry(cfg: dict) -> tuple[float, float, float]:
    """返回 (base, close, hi)：基础目标、整圈闭合点、结束距离上限。"""
    import math

    base = float(cfg.get("target_distance_km", 2.0))
    lap = float(cfg.get("route_lap_km", 0.415))
    hi = float(cfg.get("finish_distance_max_km", 2.2))
    if lap <= 0:
        lap = 0.415
    laps = max(1, math.ceil(base / lap - 1e-9))
    close = round(laps * lap, 3)
    while close > hi and laps > 1:
        laps -= 1
        close = round(laps * lap, 3)
    if close < base:  # 整圈点不足基础目标时退化
        close = round(base, 3)
    return base, close, hi


def _draw_random_target(cfg: dict, close: float, base: float, hi: float) -> tuple[float, str]:
    """按原随机策略抽一次目标（20% 整圈闭合，其余起点前 20~50m）。"""
    max_off = float(cfg.get("finish_offset_max_km", 0.05))
    coincide_prob = float(cfg.get("finish_coincide_prob", 0.2))
    if random.random() < coincide_prob:
        return close, "跑满整圈：终点与起点重合，轨迹闭合成环"
    off = random.uniform(0.02, max_off)
    target = max(base + 0.01, min(round(close - off, 2), hi))
    return target, f"在起点前 {off * 1000:.0f} m 结束：同侧、不重合（轨迹留小缺口）"


def _pick_avoiding_repeats(cfg: dict, close: float, base: float, hi: float,
                           used: list[float]) -> tuple[float, str] | None:
    """在同一天已用距离之外抽目标；抽不到时用候选池，仍不行返回 None。"""
    gap = float(cfg.get("finish_target_min_gap_km", 0.02))
    for _ in range(20):
        target, note = _draw_random_target(cfg, close, base, hi)
        if all(abs(target - u) >= gap for u in used):
            return target, note
    candidates = [close] + sorted({round(close - off, 2) for off in (0.02, 0.03, 0.04, 0.05)})
    allowed = [c for c in candidates if all(abs(c - u) >= gap for u in used)]
    if allowed:
        return random.choice(allowed), "避免与今日已用距离重复（候选池）"
    return None


def randomized_target(cfg: dict, logger: logging.Logger) -> float:
    """本次结束距离阈值：围绕「整圈闭合点」，保证终点与起点同侧。

    RunSimulation 的「标准」路线是一条约 0.415 km 的闭环（32 个点·415m，循环 5 圈
    ≈ 2.075 km 正好回到起点）：
    - 默认约 20% 的概率跑满整圈 → 终点与起点重合（轨迹闭合成环）；
    - 其余时候在起点前 20~50 m 结束 → 终点仍在起点同侧，但不重合（轨迹留下小缺口）。
    距离始终限制在 2.00~2.20 km 内，且大于基础目标 2.00 km，不会越跑越大。

    多操作时按「实例」记录当天已用距离（`finish_target_avoid_repeat`，默认开启）：
    同一设备当天多次运行尽量不与之前的距离/位置重复；两台设备之间互不限制。
    """
    base, close, hi = _route_geometry(cfg)
    avoid = bool(cfg.get("finish_target_avoid_repeat", True))
    used = _load_used_finish_targets(cfg) if avoid else []
    picked = _pick_avoiding_repeats(cfg, close, base, hi, used) if avoid else None

    if picked is not None:
        target, note = picked
    else:
        # 未开启去重，或今日可选值已用尽：退回普通随机
        target, note = _draw_random_target(cfg, close, base, hi)
        if avoid:
            note += "（今日可用距离已用尽，允许重复）"

    if avoid:
        used.append(round(float(target), 3))
        _save_used_finish_targets(cfg, used)

    used_txt = ("；本机今日已用：" + "、".join(f"{u:.2f}" for u in used[:-1])) if used[:-1] else ""
    logger.info("本次结束距离：%.2f km（整圈闭合点 %.3f km；%s；距离区间 %.2f~%.2f km%s）",
                target, close, note, base, hi, used_txt)
    return target


def _verify_run_button_after_cleanup(tasker, controller, cfg: dict,
                                     logger: logging.Logger) -> bool:
    """清理后重新打开 RunSimulation，校验「开始跑步」是否恢复可用；异常不外抛。"""
    run = cfg["run"]
    ok = False
    try:
        controller.focus_package = run["package"]
        controller.start_app(run["activity"])
        time.sleep(2.5)
        if not ocr_probe(tasker, RUN_BUTTON_MARKERS):
            logger.warning("清理后未识别到「开始跑步」，尝试停止已完成/独立路线播放 ...")
            _stop_finished_playback(tasker, logger)
            time.sleep(1.5)
        ok = ocr_probe(tasker, RUN_BUTTON_MARKERS)
        if ok:
            logger.info("清理后校验：开始跑步按钮可用")
        else:
            logger.warning("清理后校验：仍未恢复「开始跑步」，下次运行前请手动检查")
            save_shot(controller, "cleanup_run_button", logger)
    except Exception as e:  # noqa: BLE001
        logger.warning("清理后校验异常（已忽略）：%s", e)
    finally:
        try:
            controller.stop_app(run["package"])
        except Exception as e:  # noqa: BLE001
            logger.warning("清理后关闭 RunSimulation 失败：%s", e)
    return ok


def cleanup_apps(tasker, controller, cfg: dict, logger: logging.Logger, reason: str = "失败") -> None:
    """开跑失败后的现场清理：尽量「全部停止」并关闭两个 App，异常不外抛。"""
    logger.info("清理现场（%s）：尝试停止模拟并关闭应用 ...", reason)
    try:
        run_pkg = cfg["run"]["package"]
        campus_pkg = cfg["campus"]["package"]
        controller.focus_package = run_pkg
        job = post_and_wait(tasker, "CampusRunStop")
        logger.info("清理：停止与关闭：%s", "完成" if job.succeeded else "部分失败")
        if not job.succeeded:
            controller.stop_app(run_pkg)
            controller.stop_app(campus_pkg)
            logger.info("清理：流水线未完成，已直接 force-stop 两个 App")
        save_shot(controller, "cleanup", logger)
    except Exception as e:  # noqa: BLE001
        logger.warning("清理现场异常（已忽略）：%s", e)
    _verify_run_button_after_cleanup(tasker, controller, cfg, logger)


def start_run_simulation(tasker, controller, cfg: dict, logger: logging.Logger, run_pkg: str) -> bool:
    """点 RunSimulation 的「开始跑步」。"""
    logger.info("点击 RunSimulation 的「开始跑步」...")
    controller.focus_package = run_pkg
    job = post_and_wait(tasker, "RunStart")
    save_shot(controller, "run_started", logger)
    if not job.succeeded:
        logger.error("点击开始跑步失败")
        return False
    logger.info("RunSimulation 已开始")
    return True


def start_campus_run(tasker, controller, cfg: dict, logger: logging.Logger, campus_pkg: str) -> bool:
    """点健行校园的「开始 / 点击跑步」，并轮询等待真正进入跑步状态。

    校园跑 App 点「开始」后可能加载较久（实测可达 20~30 秒，冷启动更慢），
    因此不能只看固定毫秒级超时：
    - 识别到「点击结束跑步 / 结束」→ 成功；
    - 识别到「加载中 / 请稍候」等文字 → 记录日志并继续等待；
    - 仍是「开始 / 点击跑步」→ 间隔重试点击（最多 3 次，避免狂点）；
    - 超过 campus_start_timeout_seconds（默认 90 秒）仍未进入跑步态才判失败。
    """
    raw_timeout = cfg.get("campus_start_timeout_seconds", 90)
    try:
        timeout_s = int(raw_timeout if raw_timeout is not None else 90)
    except (TypeError, ValueError):
        timeout_s = 90
    timeout_s = max(10, timeout_s)
    logger.info("点击健行校园的「开始」...（最长等待 %s 秒，期间检查是否仍在加载）", timeout_s)
    controller.focus_package = campus_pkg
    start_ts = time.time()
    deadline = start_ts + timeout_s
    clicks = 0
    idle_streak = 0
    last_wait_log = 0.0
    while time.time() < deadline:
        state = _campus_page_state(tasker)
        if state == "running":
            save_shot(controller, "campus_started", logger)
            logger.info("健行校园已开始记录（启动耗时 %.1f 秒）", time.time() - start_ts)
            return True
        if state == "loading":
            idle_streak = 0
            if time.time() - last_wait_log >= 5:
                logger.info("校园跑仍在加载中，继续等待 ...")
                last_wait_log = time.time()
        else:
            if state == "unknown" and time.time() - last_wait_log >= 5:
                logger.info("校园跑页面状态未知，继续等待/尝试点击 ...")
                last_wait_log = time.time()
            idle_streak = idle_streak + 1 if state == "idle" else 0
            if clicks == 0 or (idle_streak >= 3 and clicks < 3):
                ok = ocr_tap(tasker, CAMPUS_IDLE_MARKERS)
                clicks += 1
                idle_streak = 0
                last_wait_log = time.time()
                logger.info("点击「开始/点击跑步」（第 %s 次）：%s", clicks, "成功" if ok else "未找到")
        time.sleep(2.0)
    save_shot(controller, "campus_started", logger)
    logger.error("等待 %s 秒后校园跑仍未进入跑步状态（可能仍在加载或页面异常）", timeout_s)
    return False


# ------------------------------------------------------------------ 主流程
def run_flow(cfg: dict, logger: logging.Logger, dry: bool, skip_start: bool = False,
             force: bool = False, record: bool = True) -> int:
    """完整流程入口：真实执行时先获取实例级运行锁，冲突返回退出码 5；dry 不占锁。"""
    if dry:
        return _run_flow_impl(cfg, logger, dry, skip_start, force, record)
    lock = _acquire_run_lock(cfg, logger)
    if lock is None:
        return 5
    try:
        return _run_flow_impl(cfg, logger, dry, skip_start, force, record)
    finally:
        _release_run_lock(lock, logger)


def _run_flow_impl(cfg: dict, logger: logging.Logger, dry: bool, skip_start: bool = False,
                   force: bool = False, record: bool = True) -> int:
    """完整流程实现；dry=True 只截图 + 识别距离；skip_start=True 跳过启动步骤（已手动开跑）。

    record=False 时不写当日成功标记，也不因当日标记跳过（无痕执行，允许重复跑）。
    """
    if (not dry and not force and record and not skip_start
            and cfg.get("skip_if_success_today", True) and _already_succeeded_today(cfg, logger)):
        logger.info("今日已成功完成过校园跑（见 %s），跳过本次执行以避免重复提交；--force 可忽略",
                    _marker_path(cfg))
        return 0
    # 上一轮已确认达到最高次数：本次触发直接跳过，免启动模拟器/打开 App
    if not dry and not force and _max_runs_reached(cfg, logger):
        return 0
    adb = make_adb(cfg)
    if not ensure_emulator(cfg, adb, logger):
        logger.error("无法连接模拟器 %s", cfg["adb_serial"])
        return _fail(cfg, logger, "connect_failed", "校园跑值守：模拟器连接失败",
                     f"无法连接 {cfg['adb_serial']}，请检查 MuMu 是否运行。", 1)
    tasker, controller = build_tasker(cfg, adb, logger)
    if tasker is None:
        return _fail(cfg, logger, "connect_failed", "校园跑值守：控制器初始化失败",
                     "MaaFramework 资源/控制器初始化失败，详见日志。", 1)

    campus_pkg = cfg["campus"]["package"]
    run_pkg = cfg["run"]["package"]
    base_target = float(cfg.get("target_distance_km", 2.0))

    # dry：安全演练，只截图 + 识别距离
    if dry:
        controller.focus_package = campus_pkg
        save_shot(controller, "dry", logger)
        dist, _, _ = read_stats(tasker, cfg)
        logger.info("dry 演练：当前识别距离 = %s km（目标不低于 %.2f km），未点击任何按钮", dist, base_target)
        return 0

    # 每次都随机加量：结束距离/时间不完全相同，但一定大于基础目标
    target = randomized_target(cfg, logger)

    if skip_start:
        logger.info("跳过启动步骤（--wait-finish）：直接等待距离并结束")
    else:
        # 0) 登录检测：先确认健行校园登录状态，未登录则进入自动登录流程
        if not ensure_campus_login(tasker, controller, cfg, logger, start_app=True):
            return _fail(cfg, logger, "start_failed", "校园跑值守：健行校园未登录",
                         "检测到健行校园登录页，自动登录未成功；请手动登录后重试。", 3)

        # 1) 两个 App 都开到最终界面
        if not prepare_run_simulation(tasker, controller, cfg, logger, run_pkg):
            return _fail(cfg, logger, "start_failed", "校园跑值守：准备 RunSimulation 失败",
                         "未能打开 RunSimulation 或确认标准路线。", 3)
        if not prepare_campus(tasker, controller, cfg, logger, campus_pkg):
            if cfg.pop("_campus_login_required", False):
                return _fail(cfg, logger, "start_failed", "校园跑值守：健行校园未登录",
                             "检测到登录页/未登录提示，自动登录未成功；请手动登录健行校园后重试。", 3)
            return _fail(cfg, logger, "start_failed", "校园跑值守：进入校园跑页失败",
                         "未能从首页点到「继续征程」，请检查 App 状态。", 3)

        # 读取「已跑次数」，达到最高次数则不开始跑步
        if _max_runs(cfg) > 0 and not force:
            count = cfg.get("_observed_run_count")
            if count is None:
                count = read_run_count(tasker, cfg, logger, quiet=False)
                if count is not None:
                    cfg["_observed_run_count"] = count
            if _should_skip_for_max_runs(cfg, count):
                _mark_max_runs_reached(cfg, count, logger)
                _close_after_max_runs(controller, cfg, logger, run_pkg, campus_pkg)
                return 0
            if count is None:
                logger.warning("未能读取已跑次数，跳过最高次数判断（max_runs=%s）；"
                               "可按实际界面文字调整 run_count_patterns", _max_runs(cfg))
            else:
                logger.info("已跑次数 %s / 上限 %s，未达上限，继续", count, _max_runs(cfg))
        elif _max_runs(cfg) > 0:
            count = cfg.get("_observed_run_count")
            logger.warning("已跑次数 %s / 上限 %s，但 --force 强制继续",
                           count if count is not None else "未知", _max_runs(cfg))

        # 可选前置点击（如路线选择），找不到自动跳过
        for t in (cfg.get("pre_click_texts") or []):
            j = post_and_wait(tasker, "TapText", {"TapText": {"expected": [t]}})
            logger.info("前置点击「%s」：%s", t, "成功" if j.succeeded else "未找到（跳过）")

        # 2) 先点 RunSimulation「开始跑步」
        if not start_run_simulation(tasker, controller, cfg, logger, run_pkg):
            cleanup_apps(tasker, controller, cfg, logger, "点击开始跑步失败")
            return _fail(cfg, logger, "start_failed", "校园跑值守：点击开始跑步失败",
                         "未能点击 RunSimulation 的「开始跑步」。", 3)

        # 3) 再点健行校园「开始」
        if not start_campus_run(tasker, controller, cfg, logger, campus_pkg):
            cleanup_apps(tasker, controller, cfg, logger, "校园跑开始失败")
            return _fail(cfg, logger, "start_failed", "校园跑值守：校园跑开始失败",
                         "未能点击校园跑页的「开始/点击跑步」。", 3)

        # 3.5) 开跑前置校验：两个 App 都确实进入跑步状态，才进入长等待
        if not verify_running(tasker, controller, cfg, logger, campus_confirmed=True):
            cleanup_apps(tasker, controller, cfg, logger, "开跑前置校验失败")
            return _fail(cfg, logger, "start_failed", "校园跑值守：开跑前置校验失败",
                         "两个 App 未同时进入跑步状态，已停止，请检查 App 画面。", 3)

        # 先等跑步跑一段时间再开始检查（正常跑 2 km 约需 12 分钟）
        wait_min = int(cfg.get("check_after_minutes", 12))
        if wait_min > 0:
            logger.info("已开始跑步，先等待 %s 分钟再检查距离/配速 ...", wait_min)
            zero_samples = 0
            for i in range(wait_min):
                time.sleep(60)
                logger.info("已等待 %s/%s 分钟", i + 1, wait_min)
                minute = i + 1
                # 开跑 2/4 分钟抽读距离，尽早发现「跑了但没记录」；4/12 分钟做进度合理性校验
                if minute in (2, 4, 12):
                    controller.focus_package = campus_pkg
                    early_dist, early_pace, early_elapsed = read_stats(tasker, cfg)
                    if early_dist is not None and early_dist > 0.0:
                        zero_samples = 0
                        logger.info("开跑 %s 分钟：距离 %.2f km，记录正常", minute, early_dist)
                    else:
                        zero_samples += 1
                        logger.warning("开跑 %s 分钟：距离仍为 %s km，疑似未正常记录，继续观察",
                                       minute, early_dist)
                        if zero_samples >= 2:
                            shot = save_shot(controller, "stuck", logger)
                            logger.error("开跑 4 分钟距离仍未增长，判定未正常记录，提前结束")
                            send_alert(cfg, logger, "timeout", "校园跑值守：开跑后距离未增长",
                                       "开跑后 4 分钟总距离仍为 0.00 km，可能 GPS/联动异常，请检查 App。", shot)
                            cleanup_apps(tasker, controller, cfg, logger, "开跑后距离未增长")
                            return 2
                    if minute in (4, 12) and early_dist is not None and early_dist > 0.0:
                        issues = progress_issues(cfg, minute, early_dist, early_pace, early_elapsed)
                        if issues:
                            logger.warning("开跑 %s 分钟进度合理性异常：%s", minute, "；".join(issues))
                            shot = save_shot(controller, "progress_anomaly", logger)
                            send_alert(cfg, logger, "progress_anomaly",
                                       f"校园跑值守：进度异常（开跑 {minute} 分钟）",
                                       "；".join(issues), shot)

    # 4) 轮询距离
    controller.focus_package = campus_pkg
    logger.info("等待距离达到 %.2f km ...", target)
    deadline = time.time() + int(cfg.get("max_wait_minutes", 120)) * 60
    poll = max(1, int(cfg.get("poll_seconds", 8)))
    dist = None
    pace = None
    elapsed = None
    eff_pace = None
    last_pace = None
    last_pace_ts = 0.0
    max_pace = float(cfg.get("max_pace_minutes", 10.0))
    min_pace = float(cfg.get("min_pace_minutes", 3.0))
    max_run_s = int(cfg.get("max_run_minutes", 20)) * 60
    forced = False
    plateau = False
    last_dist = None
    still_count = 0
    while time.time() < deadline:
        dist, pace, elapsed = read_stats(tasker, cfg)
        now = time.time()
        if pace is not None:
            last_pace = pace
            last_pace_ts = now
        # 配速 OCR 会间歇性识别失败：沿用最近 60 秒内的有效读数，避免因此多跑/超时
        eff_pace = pace
        if eff_pace is None and last_pace is not None and (now - last_pace_ts) <= 60:
            eff_pace = last_pace
        if dist is None:
            logger.warning("未识别到距离，%ss 后重试", poll)
        else:
            pace_txt = f"{eff_pace:.2f} 分/公里" if eff_pace is not None else "未知"
            time_txt = f"{elapsed // 60:02d}:{elapsed % 60:02d}" if elapsed is not None else "未知"
            logger.info("当前距离：%.2f km，总时间：%s，平均配速：%s（目标 %.2f km，配速 %.0f~%.0f 分/公里，时间上限 %d 分钟）",
                        dist, time_txt, pace_txt, target, min_pace, max_pace, max_run_s // 60)
            # 模拟器跑满设定圈数（循环 5 圈）后会自动停：距离连续多次不变且已达基础目标则按跑完处理
            if last_dist is not None and abs(dist - last_dist) < 0.005:
                still_count += 1
            else:
                still_count = 0
            last_dist = dist
            if dist >= target and eff_pace is not None and min_pace <= eff_pace <= max_pace:
                break
            if still_count >= 3 and dist >= base_target:
                logger.info("距离连续 %s 次未变化（%.2f km），判定模拟已跑完/已停止，进入结束流程",
                            still_count + 1, dist)
                plateau = True
                break
            if elapsed is not None and elapsed >= max_run_s:
                logger.warning("总时间已达 %d 分钟上限，强制结束（距离 %.2f km）", max_run_s // 60, dist)
                forced = True
                break
        time.sleep(poll)
    pace_ok = eff_pace is not None and min_pace <= eff_pace <= max_pace
    dist_ok = dist is not None and dist >= target
    if not dist_ok and plateau and dist is not None and dist >= base_target:
        logger.info("模拟已自行停止（距离 %.2f km，已达基础目标 %.2f km），按完成处理", dist, base_target)
        dist_ok = True
    if not forced and not (dist_ok and pace_ok):
        shot = save_shot(controller, "timeout", logger)
        logger.warning("等待超时：距离 %.2f km、配速 %s 未满足条件（目标 %.2f km）",
                       dist if dist is not None else 0.0,
                       f"{eff_pace:.2f} 分/公里" if eff_pace is not None else "未知", target)
        return _fail(cfg, logger, "timeout", "校园跑值守：等待距离超时",
                     f"{cfg.get('max_wait_minutes')} 分钟内未达到 {target} km（最后识别 {dist}）。", 2, shot)
    hit_shot = save_shot(controller, "distance_hit", logger)

    # 5) 结束跑步并等待结算（失败先确认是否已结算，否则重试一次）
    logger.info("结束跑步并等待结算 ...")
    controller.focus_package = campus_pkg
    job = post_and_wait(tasker, "CampusRunFinish")
    settled = job.succeeded
    if not settled and ocr_probe(tasker, SETTLE_MARKERS):
        settled = True
        logger.info("结束流程返回失败，但已检测到结算页面，按成功处理")
    if not settled:
        logger.warning("结束跑步首次失败，3 秒后重试一次 ...")
        time.sleep(3)
        save_shot(controller, "finish_retry", logger)
        job = post_and_wait(tasker, "CampusRunFinish")
        settled = job.succeeded or ocr_probe(tasker, SETTLE_MARKERS)
    finish_shot = save_shot(controller, "finish", logger)
    if not settled:
        logger.error("结束跑步失败（已重试一次）")
        return _fail(cfg, logger, "stop_failed", "校园跑值守：结束跑步失败",
                     "未能完成「结束 → 确定结束」流程，请检查 App。", 3, finish_shot)
    logger.info("结束与结算流程已完成")

    # 6) 停止模拟并关闭应用（失败重试一次，仍失败则直接 force-stop 兜底）
    if cfg.get("close_apps", True):
        logger.info("停止模拟并关闭应用 ...")
        controller.focus_package = run_pkg
        job = post_and_wait(tasker, "CampusRunStop")
        if not job.succeeded:
            logger.warning("停止/关闭首次失败，3 秒后重试一次 ...")
            time.sleep(3)
            job = post_and_wait(tasker, "CampusRunStop")
        save_shot(controller, "stop", logger)
        logger.info("停止与关闭：%s", "完成" if job.succeeded else "部分失败")
        if not job.succeeded:
            try:
                controller.stop_app(run_pkg)
                controller.stop_app(campus_pkg)
                logger.info("停止流水线仍失败，已直接 force-stop 两个 App")
            except Exception as e:  # noqa: BLE001
                logger.warning("强制关闭 App 失败：%s", e)
            return _fail(cfg, logger, "stop_failed", "校园跑值守：停止/关闭失败",
                         "RunSimulation 或 App 关闭未完全成功。", 3, hit_shot)

    pace_txt = f"{eff_pace:.2f} 分/公里" if eff_pace is not None else "未知"
    if forced:
        logger.warning("强制结束且未达标：距离 %.2f km、配速 %s（目标 %.2f km、配速 %.0f~%.0f 分/公里、时间上限 %d 分钟），记录可能无效",
                       dist if dist is not None else 0.0, pace_txt, target, min_pace, max_pace, max_run_s // 60)
        _fail(cfg, logger, "timeout", "校园跑值守：超时强制结束且未达标",
              f"总时间达到 {max_run_s // 60} 分钟上限，距离 {dist} km、配速 {pace_txt}，记录可能无效。", 2)
        shutdown_emulator(cfg, logger)
        return 2
    logger.info("全部完成：距离 %.2f km，配速 %s，已结束并关闭（本次距离阈值 %.2f km）", dist, pace_txt, target)
    shutdown_emulator(cfg, logger)
    if record:
        _mark_success_today(cfg, logger)
    else:
        logger.info("--no-record：不写当日成功标记")
    return 0
