"""主流程：校园跑完整业务流程。

顺序：准备 RunSimulation（标准路线）→ 准备健行校园（首页 → 继续征程）
      → 点 RunSimulation 的「开始跑步」→ 点健行校园的「开始」→ 开跑前置校验
      → 等待 + 轮询距离/配速 → 结束/结算 → 停止模拟并关闭 App → 关闭模拟器。
基础设施（adb/MuMu 启停、MaaFw 初始化、OCR 原语）见 emulator.py / maa_tasks.py。
"""

from __future__ import annotations

import logging
import random
import time

from .alerts import send_alert
from .distance import read_stats
from .emulator import ensure_emulator, make_adb, shutdown_emulator
from .evidence import save_shot
from .maa_tasks import SETTLE_MARKERS, build_tasker, ocr_probe, ocr_tap
from .tasks import post_and_wait


def _fail(cfg: dict, logger: logging.Logger, event: str, title: str, content: str,
          code: int, shot=None) -> int:
    """发送失败告警并返回退出码（统一失败路径）。"""
    send_alert(cfg, logger, event, title, content, shot)
    return code


# ------------------------------------------------------------------ 启动步骤
def prepare_run_simulation(tasker, controller, cfg: dict, logger: logging.Logger, run_pkg: str) -> bool:
    """把 RunSimulation 开到准备跑步页，并确认路线为「标准」。"""
    route = (cfg.get("route_text") or "标准").strip()
    logger.info("准备 RunSimulation（路线：%s）...", route)
    controller.focus_package = run_pkg
    override = {
        "CheckStandard": {"expected": [f"^{route}$"]},
        "CheckStandardAgain": {"expected": [f"^{route}$"]},
        "PickStandard": {"expected": [f"^{route}$"]},
    }
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
    start_markers = ["^开始$", "^点击跑步$", "点击结束跑步"]
    for attempt in range(1, 10):
        if ocr_probe(tasker, ["放弃这条本地记录", "放弃"]):
            logger.info("发现未正常结束的本地记录，点击「放弃」")
            ocr_tap(tasker, ["放弃这条本地记录", "放弃"])
            time.sleep(2.0)
            continue
        if ocr_probe(tasker, ["总距离"]) and ocr_probe(tasker, start_markers):
            logger.info("已进入校园跑页（第 %s 次检查）", attempt)
            save_shot(controller, "campus_prepared", logger)
            return True
        if ocr_probe(tasker, ["继续征程"]):
            logger.info("点击「继续征程」")
            ocr_tap(tasker, ["继续征程"])
            time.sleep(2.5)
            continue
        if ocr_probe(tasker, ["^首页$"]):
            logger.info("点击「首页」")
            ocr_tap(tasker, ["^首页$"])
            time.sleep(1.5)
            continue
        if attempt in (4, 7):
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


def verify_running(tasker, controller, cfg: dict, logger: logging.Logger) -> bool:
    """开跑前置校验：确认两个 App 都真的进入跑步状态，才允许进入 12 分钟等待。"""
    run_pkg = cfg["run"]["package"]
    campus_pkg = cfg["campus"]["package"]
    run_ok = False
    for _ in range(10):
        controller.focus_package = run_pkg
        if ocr_probe(tasker, ["正在跑步", "暂停跑步"]):
            run_ok = True
            break
        time.sleep(1.5)
    campus_ok = False
    for _ in range(10):
        controller.focus_package = campus_pkg
        if ocr_probe(tasker, ["点击结束跑步", "^结束$"]):
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


def randomized_target(cfg: dict, logger: logging.Logger) -> float:
    """本次结束距离阈值：围绕「整圈闭合点」，保证终点与起点同侧。

    RunSimulation 的「标准」路线是一条约 0.415 km 的闭环（32 个点·415m，循环 5 圈
    ≈ 2.075 km 正好回到起点）：
    - 默认约 20% 的概率跑满整圈 → 终点与起点重合（轨迹闭合成环）；
    - 其余时候在起点前 20~50 m 结束 → 终点仍在起点同侧，但不重合（轨迹留下小缺口）。
    距离始终限制在 2.00~2.20 km 内，且大于基础目标 2.00 km，不会越跑越大。
    """
    import math

    base = float(cfg.get("target_distance_km", 2.0))
    lap = float(cfg.get("route_lap_km", 0.415))
    hi = float(cfg.get("finish_distance_max_km", 2.2))
    max_off = float(cfg.get("finish_offset_max_km", 0.05))
    coincide_prob = float(cfg.get("finish_coincide_prob", 0.2))
    if lap <= 0:
        lap = 0.415
    laps = max(1, math.ceil(base / lap - 1e-9))
    close = round(laps * lap, 3)
    while close > hi and laps > 1:
        laps -= 1
        close = round(laps * lap, 3)
    if close < base:  # 整圈点不足基础目标时退化
        close = round(base, 3)
    if random.random() < coincide_prob:
        target = close
        note = "跑满整圈：终点与起点重合，轨迹闭合成环"
    else:
        off = random.uniform(0.02, max_off)
        target = round(close - off, 2)
        note = f"在起点前 {off * 1000:.0f} m 结束：同侧、不重合（轨迹留小缺口）"
    target = max(base + 0.01, min(target, hi))
    logger.info("本次结束距离：%.2f km（整圈闭合点 %.3f km；%s；距离区间 %.2f~%.2f km）",
                target, close, note, base, hi)
    return target


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
    """点健行校园的「开始 / 点击跑步」。"""
    logger.info("点击健行校园的「开始」...")
    controller.focus_package = campus_pkg
    job = post_and_wait(tasker, "CampusBegin")
    save_shot(controller, "campus_started", logger)
    if not job.succeeded:
        logger.error("点击校园跑开始失败")
        return False
    logger.info("健行校园已开始记录")
    return True


# ------------------------------------------------------------------ 主流程
def run_flow(cfg: dict, logger: logging.Logger, dry: bool, skip_start: bool = False) -> int:
    """完整流程；dry=True 只截图 + 识别距离；skip_start=True 跳过启动步骤（已手动开跑）。"""
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
        # 1) 两个 App 都开到最终界面
        if not prepare_run_simulation(tasker, controller, cfg, logger, run_pkg):
            return _fail(cfg, logger, "start_failed", "校园跑值守：准备 RunSimulation 失败",
                         "未能打开 RunSimulation 或确认标准路线。", 3)
        if not prepare_campus(tasker, controller, cfg, logger, campus_pkg):
            return _fail(cfg, logger, "start_failed", "校园跑值守：进入校园跑页失败",
                         "未能从首页点到「继续征程」，请检查 App 状态。", 3)

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
        if not verify_running(tasker, controller, cfg, logger):
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
                # 开跑后 2 分钟、4 分钟各抽读一次距离，尽早发现「跑了但没记录」
                if i + 1 in (2, 4):
                    controller.focus_package = campus_pkg
                    early_dist, _, _ = read_stats(tasker, cfg)
                    if early_dist is not None and early_dist > 0.0:
                        zero_samples = 0
                        logger.info("开跑 %s 分钟：距离 %.2f km，记录正常", i + 1, early_dist)
                    else:
                        zero_samples += 1
                        logger.warning("开跑 %s 分钟：距离仍为 %s km，疑似未正常记录，继续观察",
                                       i + 1, early_dist)
                        if zero_samples >= 2:
                            shot = save_shot(controller, "stuck", logger)
                            logger.error("开跑 4 分钟距离仍未增长，判定未正常记录，提前结束")
                            send_alert(cfg, logger, "timeout", "校园跑值守：开跑后距离未增长",
                                       "开跑后 4 分钟总距离仍为 0.00 km，可能 GPS/联动异常，请检查 App。", shot)
                            cleanup_apps(tasker, controller, cfg, logger, "开跑后距离未增长")
                            return 2

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
    return 0
