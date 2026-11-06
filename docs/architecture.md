# 架构与执行流程

## 模块职责

| 模块 | 职责 |
|---|---|
| `run.py` | 入口薄封装，调用 `maa_campus.cli` |
| `maa_campus/cli.py` | 参数解析、日志与配置校验、日志清理、定时等待、`--probe` OCR 自检 |
| `maa_campus/flow.py` | 主业务流程：准备 → 开始 → 前置校验 → 等待/轮询 → 结束结算 → 停止关闭 → 关闭模拟器 |
| `maa_campus/emulator.py` | 模拟器生命周期：`make_adb` / `ensure_emulator`（自动拉起 MuMu）/ `shutdown_emulator` |
| `maa_campus/parallel.py` | 多实例并行编排：为 `config.instances` 每项启动独立子进程，转发日志并汇总退出码 |
| `maa_campus/maa_tasks.py` | MaaFramework `Resource`/`Tasker`/`CustomController` 绑定与 OCR 原语（`ocr_probe`/`ocr_tap`） |
| `maa_campus/distance.py` | OCR 文本解析：总距离、平均配速、总时间（支持 `distance_regex` 配置） |
| `maa_campus/evidence.py` | 阶段截图（`logs/shots/`） |
| `maa_campus/alerts.py` | 失败告警（generic / wecom / dingtalk / serverchan / bark） |
| `maa_campus/adb.py` | adb 封装（MuMu 多虚拟屏的 display 映射、截图、点击、启停应用） |
| `maa_campus/controller.py` | MaaFramework `CustomController` 实现（多屏适配） |
| `maa_campus/config.py` | 配置默认值、嵌套合并、必填与正则校验 |
| `assets/resource/pipeline/campus_run.json` | MaaFramework 流水线（OCR + Click + StartApp/StopApp） |

## 执行流程（`flow.run_flow`）

1. **连接模拟器**：`emulator.ensure_emulator`（失败时按 `mumu_manager` 自动拉起）→ `maa_tasks.build_tasker`；
2. **准备**：`RunPrepare`（打开 RunSimulation 并确认「标准」路线）→ `prepare_campus`（Python OCR 状态机：放弃未结束记录 / 首页 / 继续征程）；
3. **开始**：`RunStart`（RunSimulation 开始跑步）→ `CampusBegin`（健行校园开始记录）；
4. **前置校验**：`verify_running` 确认两个 App 均已进入跑步状态，否则清理现场并返回 3；
5. **等待**：先等 `check_after_minutes`（默认 12 分钟）；期间在 2、4 分钟各抽读一次距离，连续为 0 则提前失败（退出码 2）；
6. **轮询**：读取距离/配速/时间，满足 `距离 ≥ target_distance_km` 且配速在区间内即结束；`max_run_minutes` 到时强制结束（返回 2）；模拟器自行停止时按平台判定处理；
7. **结束结算**：`CampusRunFinish`（结束 → 确定结束 → 等待结算）；失败时先检测是否已结算，否则重试一次；
8. **停止关闭**：`CampusRunStop`（全部停止 → 关闭两个 App），失败重试并 fallback `force-stop`；
9. **关闭模拟器**：`shutdown_emulator`（`close_apps` + `shutdown_emulator` 为 true 时）。

## 随机结束点

`flow.randomized_target` 以「整圈闭合点」为基准：RunSimulation「标准」路线约 0.415 km/圈（32 个点·415m，循环 5 圈 ≈ 2.075 km）。每次约 20% 概率跑满整圈（终点与起点重合），其余在起点前 20~50 m 结束；距离限制在 2.0~2.2 km，且始终大于基础目标。

## 目录与依赖

- `assets/resource/model/ocr/`：Apache-2.0 OCR 模型（随仓库分发，许可文本见同目录）；
- `scripts/`：一键入口与 Windows 计划任务注册；
- `tools/`：调试工具（`nav.py` / `inspect_screen.py` / `prepare_run.py`）；
- `tests/`：离线测试（mock 设备/OCR，不连接模拟器）。
