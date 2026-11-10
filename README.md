# MaaCampusRun · 校园跑值守（MaaFramework 版，距离+配速触发）

参考 [MaaEnd](https://github.com/MaaEnd/MaaEnd) 的工程结构，用 [MaaFramework](https://github.com/MaaXYZ/MaaFramework)
（Python 绑定 `MaaFw`）实现校园跑自动值守。

**MaaCampusRun** 是一个 Windows 本地自动化工具：在 MuMu 模拟器中配合跑步软件与「健行校园」完成校园跑流程，
按距离/配速自动结束、结算，并支持每日定时执行（DSH / Windows 计划任务）。

> 项目状态：`0.2.1` · **GPL-3.0**（OSI 开源，允许商业使用；衍生作品须按 GPL 兼容方式开源，见 [LICENSE](LICENSE) 与 [DISCLAIMER.md](DISCLAIMER.md)）

## 正确流程（用户确认）

1. 先把两个 App 都开到最终界面：
   - **跑步软件**：准备跑步页，并确认当前路线为「**标准**」（不是才切换）；
   - **健行校园**：首页 → 点「**继续征程**」→ 校园跑页（显示「开始」按钮）。
2. **先**点跑步软件的「**开始跑步**」；
3. **再**点健行校园的「**开始 / 点击跑步**」；
4. 开跑前置校验（两个 App 都必须进入跑步状态）→ 先等 12 分钟，再 OCR 轮询「总距离(公里)」「平均配速」「总时间」：
   - 总距离 **≥ 2.00 km**；
   - 平均配速在 **3~10 分/公里**（避免异常）；
   - 两个条件同时满足才继续；
5. 点「**结束**」→ 弹窗「确定结束本次跑步吗」→ 点「**确定结束**」→ 等待结算/上传；
6. 停止跑步软件模拟并关闭两个 App，随后关闭 MuMu 模拟器（可用 `shutdown_emulator` 关闭该行为）。

> ⚠️ 完整流程会**真实开始并结束一次跑步，可能向服务器提交记录**。确认后再运行 `--now`；
> `--dry` 是安全演练（只截图 + 识别距离/配速，不点任何按钮）；
> `--wait-finish` 用于「已经手动开跑」时只等待达标并结束（不点开始）。

## 目录结构

```
maa-campus-run/
├── run.py                     # 入口（薄封装，调用 maa_campus.cli）
├── config.json                # 本机配置（不提交；由 config.example.json 复制修改）
├── config.example.json        # 配置模板（脱敏）
├── requirements.txt           # 运行依赖（MaaFw / pillow / numpy）
├── requirements.lock.txt      # 当前环境锁定版本
├── pyproject.toml             # 项目元数据 + pytest 配置
├── .gitignore                 # 忽略 .venv / __pycache__ / logs 等
├── README.md
├── maa_campus/                # 核心代码
│   ├── cli.py                 #   参数解析、日志、配置校验、日志清理、定时等待、OCR 自检
│   ├── flow.py                #   主业务流程（准备→开始→校验→等待→结束→停止）
│   ├── emulator.py            #   模拟器生命周期（adb 连接 / MuMu 拉起 / 关闭）
│   ├── parallel.py            #   多实例并行编排（每个实例独立子进程）
│   ├── maa_tasks.py           #   MaaFramework 资源加载、控制器绑定、OCR 原语
│   ├── tasks.py               #   MaaFramework 任务投递/等待
│   ├── distance.py            #   距离/配速/时间 OCR 读取与解析
│   ├── evidence.py            #   阶段截图证据
│   ├── alerts.py              #   失败告警（generic/wecom/dingtalk/serverchan/bark）
│   ├── adb.py                 #   adb 封装（逻辑/物理 display 映射、截图、点击、启停应用）
│   ├── controller.py          #   MaaFramework CustomController（MuMu 多屏适配）
│   ├── config.py              #   配置加载、默认值合并与必填校验
│   ├── webui.py               #   本地 Web 控制台（标准库 http.server，补充入口）
│   ├── webui_static/          #   控制台静态页面（原生 HTML/CSS/JS，无构建）
│   ├── desktop.py             #   桌面控制台（Tkinter，标准库，补充入口）
│   ├── packaging.py           #   日志/截图打包 zip（CLI/桌面/Web 共用）
├── assets/
│   ├── interface.json         # ProjectInterface v2（接口示例，见下方说明）
│   └── resource/
│       ├── pipeline/campus_run.json   # 任务流水线（OCR + Click + StartApp/StopApp）
│       └── model/ocr/                 # PaddleOCR 中文模型（det.onnx / rec.onnx / keys.txt）
├── scripts/
│   ├── 一键值守.cmd            # 一键入口（推荐）：自检 → 执行 → 结果摘要
│   ├── 桌面控制台.cmd          # 双击打开桌面控制台（pythonw，无控制台窗口）
│   ├── oneclick.ps1           # 一键入口编排逻辑（由入口脚本调用）
│   ├── run-now.cmd            # 兼容旧入口：等价于「一键值守.cmd」
│   ├── dryrun.cmd             # 双击：安全演练
│   └── install_task.ps1       # 注册/删除 Windows 计划任务（复用一键入口）
├── tools/                     # 调试工具（nav.py / inspect_screen.py / prepare_run.py）
├── tests/                     # 离线测试（mock 设备/OCR，不连模拟器）
└── logs/                      # 运行日志 + shots/ 证据截图 + oneclick/ 入口摘要（运行时生成，已 ignore）
```

## 环境

- Windows + MuMu 模拟器（本机实例 1，adb `127.0.0.1:16416`）
- Python 3.12（`MaaFw==5.15.0` 自带 MaaFramework 原生库与 OCR 引擎）

```powershell
cd maa-campus-run
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> `.venv` 仅为本机环境，不随源码分发；换机（或换 Python 安装位置）必须删除重建，否则 `pyvenv.cfg` 会指向旧解释器。

## 配置 `config.json`

从 `config.example.json` 复制后按本机实际情况修改。

| 字段 | 说明 |
|---|---|
| `adb_path` / `adb_serial` | adb 路径与 MuMu 实例地址（必填） |
| `mumu_manager` / `mumu_index` | 模拟器未启动时自动拉起（可留空） |
| `instances` | 多模拟器并行配置（数组，≥2 项时自动并行）；每项 `{name, adb_serial, mumu_index}`，为空则单实例运行 |
| `instance_start_stagger_seconds` / `run_lock_stale_seconds` | 双实例错峰启动间隔（默认 20 秒）；实例运行锁过期时间（默认 1800 秒） |
| `emulator_boot_timeout_seconds` / `emulator_restart_on_fail` | 冷启动等待上限（秒，默认 `300`）；超时后是否重启实例一次再重试（默认 `true`） |
| `refresh_window_on_start` | 连接/启动完成后自动 `show_window` 并微调窗口尺寸刷新渲染（修复画面错位），默认 `true` |
| `start_time` | 每天几点执行，默认 `07:00`（`run.py` 自身定时与 Windows 计划任务使用） |
| `run_window` | 可选：每日时间区间内随机执行，如 `{"start":"07:00","end":"08:30"}`；设置后 `run.py`（不带 `--now`）会在区间内随机取一个时间，详见下方「定时方式」 |
| `run_windows` | 可选：一天多个时间段，如 `[{...},{...}]`；每个时间段各执行一次（各自区间内随机时间），与 `run_window` 互斥 |
| `target_distance_km` | 目标距离（公里），默认 `2.0` |
| `max_runs` | 最高跑步次数（读取校园跑界面「已跑 X 次」或首页「26次/60次」，达到后跳过；`0` 表示不限制） |
| `run_count_patterns` / `log_run_count` | 自定义「已跑次数」OCR 正则（默认支持「已跑 X 次」「X次/Y次」等）；是否每次记录识别到的次数（默认 `false`） |
| `finish_target_avoid_repeat` / `finish_target_min_gap_km` | 同一设备当天多次运行避免重复/相近结束距离（默认开启，间隔 `0.02` km；两台设备间互不限制） |
| `max_pace_minutes` / `min_pace_minutes` | 结束前要求的配速区间，默认 `3.0 ~ 10.0` 分/公里 |
| `check_after_minutes` | 开始跑步后先等多久再检查距离（正常 2 km 约需 12 分钟），默认 `12` |
| `max_run_minutes` | 跑步总时间上限，超过就强制结束（保证 20 分钟内结束），默认 `20` |
| `distance_regex` | 距离数字的 OCR 匹配（默认 `^\d+\.\d{2}$`） |
| `route_text` | 跑步软件的路线名，默认 `标准`（先检查，不是才切换） |
| `pre_click_texts` | 进校园跑页后、开始前的可选点击（找不到自动跳过） |
| `max_wait_minutes` / `poll_seconds` | 最长等待时间、OCR 轮询间隔 |
| `campus` / `run` | 健行校园 / 跑步软件的包名与 Activity（必填） |
| `close_apps` | 结束后是否停止模拟并关闭应用 |
| `shutdown_emulator` | 成功跑完并关闭 App 后是否同时关闭 MuMu 模拟器，默认 `true`（下次运行会自动重新拉起） |
| `skip_if_success_today` | 当天已成功跑过则跳过，避免重复提交，默认 `true`（`--force` 可忽略） |
| `log_dir` / `log_retention_days` | 日志目录；截图与入口日志保留天数（默认 14，<=0 不清理） |
| `alerts` | 失败告警：`enabled` / `type` / `webhook_url` / `on` |

## 使用

```powershell
# 1) OCR 自检
.venv\Scripts\python run.py --probe 继续征程 --screenshot

# 2) 安全演练：只截图 + 识别当前距离/配速，不点击任何按钮
.venv\Scripts\python run.py --now --dry

# 3) 完整执行一次（会真实开始/结束跑步并可能上传记录！确认后再用）
.venv\Scripts\python run.py --now

# 4) 已经手动开跑：只等到达标并结束（不点开始）
.venv\Scripts\python run.py --now --wait-finish

# 5) 按固定时间执行（config.start_time=07:00，或临时 --at 07:00）
.venv\Scripts\python run.py
.venv\Scripts\python run.py --at 07:00

# 6) 测试告警通道
.venv\Scripts\python run.py --test-alert

# 7) 忽略「当日已成功」标记，强制再执行（谨慎：可能重复提交记录）
.venv\Scripts\python run.py --now --force

# 8) DSH 兼容模式：只处理当前（或下一个）时间段，区间内随机等待后执行一次并退出
.venv\Scripts\python run.py --window-once

# 9) 只运行指定实例（instances 中的 name 或 1-based 序号；其余实例不启动）
.venv\Scripts\python run.py --now --instance mumu-1
.venv\Scripts\python run.py --window-once --instance 2

# 10) 无痕执行：不写当日成功标记 / 时间段完成状态（便于重复或分实例执行）
.venv\Scripts\python run.py --window-once --instance mumu-1 --no-record
```

### 一键执行（手动，推荐）

双击 `scripts\一键值守.cmd`：自动完成 单实例检查 → 环境自检（含 MuMu 自动拉起）→ `run.py --now` → 结果判定与摘要。

- 退出码：`0` 成功；`1` 连接/初始化失败或异常；`2` 未达标/等待超时/开跑未记录/强制结束未达标；`3` 开始·结束·关闭失败；`5` 已有实例在运行（防重复提交）
- 入口日志与结果摘要：`logs/oneclick/`（`oneclick_*.log`、`result_*.txt`）
- 结果只写日志，不弹窗；告警仍按 `config.alerts` 配置（当前未启用）
- 安全演练仍用命令行：`.venv\Scripts\python.exe run.py --now --dry`（只截图识别，不点击、不上传）
- 成功跑完并关闭两个 App 后会自动关闭 MuMu 模拟器（`shutdown_emulator` 默认 `true`）；下次运行会自动重新拉起。如不想自动关闭，可在 `config.json` 里设为 `false`

## 定时方式（三选一）

### 区间随机时间（`run_window`）

在 `config.json` 中设置一个每日时间区间后，`run.py`（**不带 `--now`**）会在区间内随机选一个时间执行（分钟粒度）：

```json
"run_window": {"start": "07:00", "end": "08:30"}
```

- 当天第一次解析时随机选一个时间并写入 `logs/.next_run`；当天内重启会复用该时间，不会重新随机；
- 区间内已过随机时间但未到区间结束：立即执行；已过整个区间：顺延到次日的随机时间；
- `--at HH:MM` 仍可强制固定时间，`--now` 仍为立即执行（忽略 `run_window`）；
- 使用 Windows 计划任务时，`scripts\install_task.ps1` 检测到 `run_window` 会在**区间起点**启动 `run.py`（不带 `--now`），由脚本等待随机时间；未配置时行为不变（运行一键入口）。

#### 一天多个时间段（`run_windows`）

需要一天执行多次时，用数组配置多个时间段，每个时间段各执行一次（随机时间在各自区间内）：

```json
"run_windows": [
  {"start": "06:30", "end": "07:30"},
  {"start": "12:00", "end": "13:00"},
  {"start": "09:00", "end": "10:00"}
]
```

- `run.py`（不带 `--now`）会依次等待每个时间段的随机时间并各执行一次，进程持续到当天最后一个时间段结束；
- 运行时会自动按时间先后排序执行（上例实际顺序：06:30-07:30 → 09:00-10:00 → 12:00-13:00）；
- 每个时间段的随机时间与完成状态保存在 `logs/.run_windows_state.json`：当天重启会跳过已完成的时间段、继续未完成的时间段；
- 时间段之间不能重叠；`run_window` 与 `run_windows` 只能设置一个；
- 多时间段模式下每个时间段都会跑一次（会产生多条跑步记录），`skip_if_success_today` 不再阻止后续时间段；
- Windows 计划任务会在**第一个时间段起点**触发 `run.py`（`install_task.ps1` 自动识别）。

#### 兼容 DeepSeek Harness（DSH）自动化任务

DSH 定时任务本身不能生成随机时间，可让 DSH 在**每个时间段起点附近**各触发一次，每次执行：

```powershell
.venv\Scripts\python.exe run.py --window-once
```

- 该模式只处理**当前（或下一个）时间段**：在区间内随机等待后执行一次并退出；
- 已完成 / 已错过的段自动跳过；DSH 任务不再需要长时间挂住进程；
- 示例 DSH RRULE（每天 3 次触发：06:30、09:30、12:30，分别落在三个区间内）：

```text
DTSTART;TZID=Asia/Shanghai:20261107T063000
RRULE:FREQ=DAILY;BYHOUR=6,9,12;BYMINUTE=30
```

若某次只想跑其中一个模拟器，加 `--instance` 即可（name 或 1-based 序号）：

```powershell
.venv\Scripts\python.exe run.py --window-once --instance mumu-1
```

若本次不想写入完成记录（例如同一时间段稍后还要用另一实例再跑），加 `--no-record`：

```powershell
.venv\Scripts\python.exe run.py --window-once --instance mumu-1 --no-record
```

1. **DeepSeek Harness 自动任务**（专用自动任务会话）：每天 07:00 触发一条任务提示，由 Agent 执行
   `run.py --now`。前提：到点时 DSH 客户端保持运行。
2. **Windows 计划任务**（更稳，不依赖 DSH）：
   `powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1`
   （按 `config.start_time` 注册每天运行一键入口；删除加 `-Uninstall`）。
3. **常驻等待**：`python run.py`，进程等到 `start_time` 再执行（电脑需保持开机）。

## AI 定时页面解析（实验特性）

可选的 AI 页面值守：按周期/cron 检查页面，出现「非确定画面」时截图（先脱敏）并上传 AI 解析，按返回的结构化 JSON 执行 click/input/scroll/wait/retry/abort，并复检页面。

```powershell
.venv\Scripts\python.exe run.py --ai-watch-once   # 只跑一轮（验收/调试）
.venv\Scripts\python.exe run.py --ai-watch        # 常驻循环
```

- 默认关闭；启用与配置见 [docs/ai_watch.md](docs/ai_watch.md)；
- API Key 仅从环境变量读取（默认 `DEEPSEEK_API_KEY` / `DEEPSEEK_ENDPOINT` / `DEEPSEEK_MODEL`），不写入仓库/日志；
- 支持 `mock` provider 做离线验收，正常页面不会上传截图。

## 桌面控制台（补充入口）

除了 Web 控制台，还提供一个 Windows 原生 Tkinter 桌面窗口（同样只依赖 Python 标准库）：

```powershell
.venv\Scripts\python.exe run.py --desktop
```

也可双击 `scripts\桌面控制台.cmd`（使用 `pythonw`，不显示控制台窗口）。

- 概览、执行、配置、日志四个页签；支持 dry / 真实执行 / window-once / AI 单轮、停止任务、配置校验+备份；
- 所有执行仍通过现有 `run.py` 子进程完成；
- 原有 CLI / config / oneclick / DSH / Web 控制台全部保留；详见 [docs/desktop.md](docs/desktop.md)。

## Web 控制台（补充入口）

在保留全部 CLI / 配置 / 脚本入口的前提下，新增一个本地 Web 控制台，用于状态查看、参数配置、触发执行、结果反馈和日志查看：

```powershell
.venv\Scripts\python.exe run.py --web            # 默认 http://127.0.0.1:8765/
.venv\Scripts\python.exe run.py --web --web-port 8765 --web-no-browser
```

- 仅使用 Python 标准库 + 原生 HTML/CSS/JS，**不新增依赖、不需要 Node/构建**；
- 默认只监听 `127.0.0.1`，仅本机使用；
- 所有执行都通过现有 `run.py` 子进程完成，参数/退出码/日志格式与 CLI 一致；
- 原有入口保持不变；详见 [docs/webui.md](docs/webui.md)。

## 日志与截图打包

可将 `logs/` 下的日志、证据截图和少量状态文件打成 zip，便于留存或排障：

```powershell
# 默认最近 7 天、含截图 → logs/exports/maa_campus_logs_<时间戳>.zip
.venv\Scripts\python.exe run.py --pack-logs

# 最近 2 天、不含截图
.venv\Scripts\python.exe run.py --pack-logs --pack-days 2 --pack-no-shots
```

- 桌面控制台「日志」页和 Web 控制台「日志」页也提供“打包日志与截图”按钮；
- 不包含 `config.json`/密钥；截图可能含个人信息，压缩包不加密，请谨慎外发；
- 配置项 `pack_days`（默认 7）、`pack_include_shots`（默认 true）；详见 [docs/packaging.md](docs/packaging.md)。

## 多模拟器并行

在 `config.json` 中配置 `instances`（≥2 项）后，`run.py --now` 会为每个实例启动**独立子进程**并行执行同一套流程；每个子进程有自己的 adb、MaaFw Tasker、日志与当日标记，互不影响。

```json
"instances": [
  {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
  {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2}
]
```

- 两个模拟器都需预先安装好 RunSimulation/跑步软件 与「健行校园」并完成登录；
- `adb_serial` 的端口以 `MuMuManager.exe info -v <index>` 输出中的 `adb_port` 为准（各实例端口不同）；
- 日志按实例分开：`logs/run_YYYYMMDD_<name>.log`；当日成功标记也按实例区分（`.last_success_<name>`）；
- 退出码汇总：全部成功 `0`；任一 `3`（开始/结束/关闭失败）→ `3`；否则任一 `2`（超时/未达标）→ `2`；否则 `1`；
- `instances` 为空或只有 1 项时，行为与原来的单实例模式完全一致（`--force`、`--dry`、`--wait-finish` 对每个实例分别生效）。
- 临时只跑其中一台：加 `--instance mumu-1`（或序号 `1`），其余实例不启动；该参数对 `--now`、`--window-once` 与定时模式均生效。

## 流程细节（pipeline）

| 节点 | 作用 |
|---|---|
| `RunPrepare` | 打开跑步软件；检查路线是否「标准」，不是才切（路线模式 → 路线库 → 标准 → 返回）；停在准备跑步页 |
| `RunStart` | 点跑步软件的「开始跑步」 |
| `CampusBegin` | 点健行校园的「开始 / 点击跑步」（已开跑则跳过） |
| `ReadStats` | OCR 读「总距离(公里)」「平均配速」「总时间」，Python 判断达标 |
| `CampusRunFinish` | 点「结束」→ 等「确定结束本次跑步吗」→ 点「确定结束」（精确匹配按钮，避免点到说明文字）→ 等待结算/上传文字 |
| `CampusRunStop` | 启动跑步软件点「全部停止」，然后关闭两个 App；成功后按 `shutdown_emulator` 关闭 MuMu 模拟器 |

> 健行校园的「准备」（放弃未结束记录 → 首页 → 继续征程）由 `flow.prepare_campus` 的 Python OCR 状态机实现，
> pipeline 中仅保留其余原子节点，避免两套准备逻辑并存。

`assets/interface.json` 为 ProjectInterface v2 的**接口示例**（供外部 UI 参考）：其任务条目已对齐本流水线节点，
但本项目实际使用内置 CustomController 适配 MuMu 多虚拟屏，通用 UI 直接加载时需自行接入该控制器。

执行证据：`logs/shots/` 按阶段保存（`run_prepared` / `campus_prepared` / `run_started` / `campus_started` / `running_check` / `distance_hit` / `finish` / `stop` / `timeout` / `stuck` / `cleanup`）。
退出码：`0` 成功；`1` 连接/初始化失败或异常；`2` 等待超时 / 开跑后距离未增长 / 强制结束未达标；`3` 开始/结束/关闭失败；一键入口另有 `5`（已有实例在运行）。

## 测试

```powershell
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python -m pytest -q
```

- `tests/test_distance.py`：距离/配速/时间解析（含自定义 `distance_regex`、非法正则回退）
- `tests/test_config.py`：默认值合并、必填校验、正则校验
- `tests/test_flow_states.py`：mock 设备/OCR，覆盖达标成功、20 分钟强制结束、等待超时、结束重试

## 调试工具

```powershell
python tools\nav.py dump [包名]        # OCR 打印当前画面文字与坐标
python tools\nav.py tap <文字> [包名]  # 按文字点击
python tools\nav.py shot [包名]        # 截图到 logs/shots
python tools\inspect_screen.py [包名]  # 截图 + 打印 OCR 文本
python tools\prepare_run.py            # 启动跑步模拟并打开健行校园，打印界面
```

## 验证步骤

1. `--probe 继续征程` 返回「命中」；
2. `--now --dry` 能读出当前距离/配速，且不点击任何按钮；
3. 正式跑一次 `--now`：日志出现「准备跑步软件」→「点击跑步软件的开始跑步」→
   「点击健行校园的开始」→「开跑前置校验通过」→ 多次「当前距离/平均配速」→ 达标后「结束与结算流程已完成」→
   「停止与关闭：完成」→「模拟器关闭：完成」，`logs/shots/` 有对应截图；
4. `python -m pytest -q` 全部通过（离线，不连模拟器）。

## 与 MaaEnd 的对应关系（借鉴点）

| MaaEnd | 本项目 |
|---|---|
| `assets/interface.json`（PI v2 项目接口） | 同结构精简版（接口示例，任务条目对齐当前流水线） |
| `assets/resource/pipeline/*.json`（低代码流水线） | `campus_run.json`：OCR + Click + StartApp/StopApp 任务链 |
| `assets/resource/model`（OCR 模型子模块） | 使用官方 `MaaCommonAssets/OCR/ppocr_v5/zh_cn` 模型 |
| `agent/` 自定义 Go/C++ 扩展 | 无需 Agent：用 Python `CustomController` 适配 MuMu 多屏 |
| 标准 `Adb` 控制器 | 自定义控制器（MuMu 会把 App 放到独立虚拟屏，标准 ADB 截图只能抓 display 0） |

## 示例输出（脱敏）

以下为一次成功运行的日志片段（示例数据；实际距离/配速因每次随机结束点而略有不同）：

```text
2026-11-05 07:00:36 [INFO] ===== 开始执行（完整流程）=====
2026-11-05 07:00:37 [INFO] 准备跑步软件（路线：标准）...
2026-11-05 07:00:43 [INFO] 证据截图：...\run_prepared.png（1080x1920）
2026-11-05 07:00:43 [INFO] 准备健行校园（首页 → 继续征程）...
2026-11-05 07:01:57 [INFO] 已进入校园跑页（第 2 次检查）
2026-11-05 07:02:00 [INFO] 点击跑步软件的「开始跑步」...
2026-11-05 07:02:18 [INFO] 点击健行校园的「开始」...
2026-11-05 07:02:22 [INFO] 开跑前置校验通过：跑步软件正在跑步、健行校园正在记录
2026-11-05 07:14:22 [INFO] 已等待 12/12 分钟
2026-11-05 07:14:24 [INFO] 当前距离：1.66 km，总时间：12:07，平均配速：7.28 分/公里
...
2026-11-05 07:16:55 [INFO] 当前距离：2.01 km，总时间：14:38，平均配速：7.27 分/公里
2026-11-05 07:16:55 [INFO] 结束跑步并等待结算 ...
2026-11-05 07:17:04 [INFO] 结束与结算流程已完成
2026-11-05 07:17:08 [INFO] 停止与关闭：完成
2026-11-05 07:17:08 [INFO] 全部完成：距离 2.01 km，配速 7.27 分/公里，已结束并关闭
```

## 常见问题（FAQ）

**Q：MuMu 没开，脚本会自动启动吗？**
会。`run.py` 的 `ensure_emulator` 在连接失败时按 `config.mumu_manager` / `mumu_index` 调 `MuMuManager control -v <idx> launch`，最多等待 180 秒连接。

**Q：`--dry` 会点击按钮或上传记录吗？**
不会。`--dry` 只截图并识别一次距离/配速，不点击任何按钮、不开始/结束跑步、不上传。

**Q：跑完会自动关闭 MuMu 吗？**
成功跑完并关闭两个 App 后会关闭模拟器（`shutdown_emulator`，默认 `true`）；下次运行会自动重新拉起。失败时不关闭，便于排查（可在 `config.json` 中设为 `false` 保留）。

**Q：日志和截图在哪里？保留多久？**
`logs/run_YYYYMMDD.log`、`logs/shots/`；`log_retention_days`（默认 14 天）会在启动时清理过旧文件；一键入口摘要见 `logs/oneclick/`。

**Q：如何调整目标距离/配速？**
修改 `config.json` 的 `target_distance_km`、`min_pace_minutes`、`max_pace_minutes`；结束距离会在整圈闭合点附近随机，保证大于目标。

**Q：失败时怎么看原因？**
按退出码：`1` 连接/初始化失败；`2` 等待超时/开跑未记录/强制结束未达标；`3` 开始·结束·关闭失败；`5` 已有实例在运行。查看 `logs/run_*.log` 与 `logs/shots/` 对应阶段截图。

## 文档

- [文档索引](docs/README.md)：架构与执行流程、配置说明、Web 控制台、退出码与失败处理、FAQ、故障排查

## 反馈与免责声明

- 反馈：通过 GitHub Issues 提交（请勿包含账号、密码等敏感信息）
- 第三方组件许可证：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 变更日志：[CHANGELOG.md](CHANGELOG.md)
- 免责声明：[DISCLAIMER.md](DISCLAIMER.md)

## 许可证说明

本项目**原创代码**采用 **GNU General Public License v3.0**（GPL-3.0，OSI 认可的开源许可），详见 [LICENSE](LICENSE)；版权声明（`Copyright (C) 2026 KJH50`）见 [NOTICE](NOTICE)。

- GPL-3.0 **允许商业使用**（包括收费分发），但衍生作品须以 GPL-3.0 兼容方式开源，并保留版权与许可声明；
- 本仓库中的第三方组件仍按其各自许可证处理，本项目不会改变其授权；
- 历史版本说明：`v0.2.0` 及更早的已发布版本当时采用 PolyForm Noncommercial 1.0.0，其授权不因本次切换而追溯变更；自本提交起的新版本按 GPL-3.0 授权。

第三方组件保持其原有许可证：

- MaaFramework：**LGPL-3.0**，本项目通过 `MaaFw` PyPI 包动态使用其原生库，未修改其源码。
- OCR 模型（`assets/resource/model/ocr`）：来自 MaaXYZ/MaaCommonAssets，**Apache-2.0**，随仓库分发并保留原许可（许可全文见同目录 `LICENSE-APACHE-2.0.txt`）；该模型本身仍可按 Apache-2.0 使用。
- MaaEnd：**AGPL-3.0**，本项目仅参考其工程结构与协议用法，**未复制其代码或资源**。

逐项清单（含 MaaAgentBinary AGPL-3.0 传递依赖、numpy / Pillow / StrEnum 等）与合规提示见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

> 注意：依赖链中的 AGPL-3.0 组件（MaaAgentBinary）与 GPL-3.0 的组合需按 AGPL 评估；详见 `THIRD_PARTY_NOTICES.md`。

## 免责声明

本项目按「现状」提供，不提供任何明示或暗示担保，使用风险由使用者自行承担；作者/维护者不对因使用本项目产生的直接或间接损失承担责任。完整条款见 [DISCLAIMER.md](DISCLAIMER.md)。
