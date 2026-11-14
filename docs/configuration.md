# 配置说明（`config.json`）

从仓库根目录的 `config.example.json` 复制为 `config.json` 后按本机情况修改。`config.json` 含本机路径，已被 `.gitignore` 忽略。

## 字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `adb_path` | string | ✅ | adb 可执行文件绝对路径 |
| `adb_serial` | string | ✅ | 模拟器 adb 地址（如 `127.0.0.1:16416`） |
| `mumu_manager` | string | 否 | MuMuManager 路径；配合 `mumu_index` 用于自动拉起模拟器 |
| `mumu_index` | int | 否 | MuMu 实例序号（默认 1） |
| `emulator_boot_timeout_seconds` | int | 否 | 模拟器冷启动等待上限（秒，默认 `300`） |
| `emulator_restart_on_fail` | bool | 否 | 启动超时后是否重启实例一次再重试（默认 `true`） |
| `refresh_window_on_start` | bool | 否 | 连接/启动完成后自动显示并微调窗口尺寸以刷新渲染（修复画面错位，默认 `true`） |
| `instances` | array | 否 | 多模拟器并行配置；≥2 项时自动并行（每项 `{name, adb_serial, mumu_index}`，可选 `login` 为该实例单独配置登录账号），为空则单实例 |
| `instances[].login` | object | 否 | 实例级登录账号：`{enabled, username, password, remember_week}`，未写的字段沿用全局 `campus.login`；多模拟器可为每台设备配置不同账号 |
| `instance_start_stagger_seconds` | int | 否 | 双实例错峰启动间隔（秒，默认 `20`，0 表示同时启动） |
| `run_lock_stale_seconds` | int | 否 | 实例运行锁过期时间（秒，默认 `1800`；异常退出后可自动回收） |
| `start_time` | "HH:MM" | 否 | `run.py` 常驻等待/Windows 计划任务使用的执行时间（默认 `07:00`） |
| `run_window` | object | 否 | 每日时间区间内随机执行：`{"start":"07:00","end":"08:30"}`；设置后 `run.py`（不带 `--now`）在区间内随机取时间，详见「定时调度」 |
| `run_windows` | array | 否 | 一天多个时间段（如 06:30-07:30、12:00-13:00、09:00-10:00）；每个时间段各执行一次，与 `run_window` 互斥 |
| `target_distance_km` | float | 否 | 基础目标距离（默认 `2.0`） |
| `max_runs` | int | 否 | 最高跑步次数：读取校园跑界面「已跑 X 次」或首页「26次/60次」，达到后跳过本次（默认 `0` 不限制） |
| `run_count_patterns` | array | 否 | 识别「已跑次数」的 OCR 正则列表（默认支持「已跑/已完成/累计/跑步次数 X 次」「X次/Y次」等文案） |
| `log_run_count` | bool | 否 | 未设置上限时也读取并记录已跑次数（默认 `false`，减少 OCR 开销） |
| `min_pace_minutes` / `max_pace_minutes` | float | 否 | 允许的平均配速区间（默认 3~10 分/公里） |
| `check_after_minutes` | int | 否 | 开跑后先等待多久再检查（默认 12 分钟） |
| `campus_start_timeout_seconds` | int | 否 | 点校园跑「开始」后等待真正进入跑步态的上限（默认 `90` 秒；期间检测「加载中」并继续等待，空闲时最多重试点击 3 次） |
| `max_run_minutes` | int | 否 | 跑步总时间上限（默认 20 分钟，超过强制结束） |
| `max_wait_minutes` / `poll_seconds` | int | 否 | 轮询等待上限与 OCR 间隔（默认 120 分钟 / 8 秒） |
| `distance_regex` | string | 否 | 距离数字 OCR 匹配正则（默认 `^\d+\.\d{2}$`） |
| `route_text` | string | 否 | RunSimulation 路线名（默认「标准」） |
| `pre_click_texts` | string[] | 否 | 开始前的可选点击文字（找不到自动跳过） |
| `campus` | object | ✅ | 健行校园：`package` / `activity`；`campus.login` 可配置自动登录 |
| `campus.login.enabled` / `username` / `password` | bool/string | 否 | 登录页自动登录开关与学校统一身份认证账号；建议用环境变量 `MAA_CAMPUS_USERNAME` / `MAA_CAMPUS_PASSWORD` 覆盖，不要提交到仓库。多实例可额外使用 `MAA_CAMPUS_USERNAME_<实例名>` / `MAA_CAMPUS_PASSWORD_<实例名>`（实例名大写、非字母数字转下划线，如 `MAA_CAMPUS_USERNAME_MUMU_1`） |
| `campus.login.remember_week` | bool | 否 | 自动登录时是否勾选「一周内免登录」（默认 `false`） |
| `run` | object | ✅ | RunSimulation：`package` / `activity` |
| `close_apps` | bool | 否 | 结束后是否关闭两个 App（默认 true） |
| `shutdown_emulator` | bool | 否 | 成功跑完后是否关闭 MuMu 模拟器（默认 true） |
| `skip_if_success_today` | bool | 否 | 当天已成功跑过则跳过，避免重复提交（默认 true；CLI `--force` 可忽略） |
| `log_dir` | string | 否 | 日志目录（默认 `logs`） |
| `log_retention_days` | int | 否 | 截图/入口日志保留天数（默认 14，`<=0` 不清理） |
| `pack_days` | int | 否 | 日志/截图打包默认天数（默认 `7`，`0` 表示全部） |
| `pack_include_shots` | bool | 否 | 打包时是否包含 `shots/` 截图（默认 `true`） |
| `alerts` | object | 否 | 失败告警：`enabled` / `type` / `webhook_url` / `on`；`webhook_url` 为空或推送失败时写本地 `logs/alerts_YYYYMMDD.log` |

## 示例（节选）

```json
{
    "adb_path": "C:\\\\path\\\\to\\\\adb.exe",
    "adb_serial": "127.0.0.1:16416",
    "mumu_manager": "C:\\\\Program Files\\\\Netease\\\\MuMu\\\\nx_main\\\\MuMuManager.exe",
    "mumu_index": 1,
    "target_distance_km": 2.0,
    "min_pace_minutes": 3,
    "max_pace_minutes": 10,
    "close_apps": true,
    "shutdown_emulator": true,
    "log_retention_days": 14
}
```

## 可选（代码默认值，无需写入 config.json）

| 键 | 默认 | 说明 |
|---|---|---|
| `route_lap_km` | `0.415` | 路线单圈长度（用于随机结束点） |
| `finish_target_avoid_repeat` | `true` | 同一实例当天避免重复使用相同/相近的结束距离（两台设备之间互不限制） |
| `finish_target_min_gap_km` | `0.02` | 去重最小间隔（km）；候选距离差小于该值时视为「差不多」 |
| `finish_offset_max_km` | `0.05` | 起点前最大随机偏移 |
| `finish_coincide_prob` | `0.2` | 跑满整圈（终点与起点重合）概率 |
| `finish_distance_max_km` | `2.2` | 结束距离上限 |

> 修改 `target_distance_km` / 配速区间前请确认学校要求；`config.json` 不参与版本控制，切勿提交。

## 定时调度（可选）

- `start_time`：固定每天执行时间（默认 `07:00`），`run.py` 不带 `--now` 时使用；
- `run_window`：设置后改为「每日区间内随机时间」：
  - 区间内随机取一个分钟级时间，写入 `logs/.next_run`；当天重启复用，不会重新随机；
  - 若当天随机时间已过但仍在区间内，立即执行；若已过整个区间，则顺延到次日的随机时间；
  - `--at HH:MM` 可强制固定时间，`--now` 立即执行并忽略 `run_window`；
- `run_windows`：一天多个时间段（数组），每个时间段各执行一次（各自区间内随机时间）：
  - 时间段不能重叠，且与 `run_window` 互斥；
  - 随机时间与完成状态保存在 `logs/.run_windows_state.json`，当天重启跳过已完成时间段；
  - 多时间段模式会产生多条跑步记录，`skip_if_success_today` 不阻止后续时间段；
- 示例（也是默认模板配置）：

```json
"run_windows": [
  {"start": "06:30", "end": "07:30"},
  {"start": "12:00", "end": "13:00"},
  {"start": "09:00", "end": "10:00"}
]
```

  > 运行时按时间先后排序执行：06:30-07:30 → 09:00-10:00 → 12:00-13:00。
- Windows 计划任务：`scripts\install_task.ps1` 检测到 `run_window`/`run_windows` 会在**第一个时间段起点**启动 `run.py`（不带 `--now`），由脚本等待随机时间；未配置时仍运行一键入口。
- `--window-once`：DSH 兼容模式，只处理当前（或下一个）时间段，区间内随机等待后执行一次并退出；供 DSH 定时任务按多个触发点调用（如每天 06:30/09:30/12:30）。`--window-once --dry` 只做一次 dry 演练、不等待时间段。

## 多实例并行（可选）

`instances` 配置 ≥2 项时，`run.py --now` 会为每个实例启动独立子进程并行执行同一套任务：

```json
"instances": [
  {"name": "mumu-1", "adb_serial": "127.0.0.1:16416", "mumu_index": 1},
  {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2,
   "login": {"username": "账号2", "password": "密码2"}}
]
```

- 流程开始时每个实例**独立检测登录状态**：未登录则进入自动登录，已登录直接继续；并行子进程之间互不影响；
- 登录账号优先级：实例级环境变量 `MAA_CAMPUS_USERNAME_<实例名>` / `MAA_CAMPUS_PASSWORD_<实例名>` > 全局环境变量 `MAA_CAMPUS_USERNAME` / `MAA_CAMPUS_PASSWORD` > `instances[].login` > `campus.login`；
- `adb_serial` 端口用 `MuMuManager.exe info -v <index>` 的 `adb_port` 确认；
- 两个实例都需要安装两个 App；未登录时脚本会自动登录（失败退出码 3）；
- 并行时每个实例独立写日志 `logs/run_YYYYMMDD_<name>.log` 与当日标记 `.last_success_<name>`；
- 退出码汇总规则见 README「多模拟器并行」；单实例配置保持不变。
- 临时只跑其中一个实例：`--instance <name|1-based 序号>`（如 `--instance mumu-1`），其余实例不启动；可用于 `--now`、`--window-once` 及定时模式。
- 无痕执行：`--no-record` 不写当日成功标记，也不把时间段标记为完成（`--window-once`/多时间段/单实例均生效），便于重复执行或同一时间段分实例执行。
