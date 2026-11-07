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
| `instances` | array | 否 | 多模拟器并行配置；≥2 项时自动并行（每项 `{name, adb_serial, mumu_index}`），为空则单实例 |
| `start_time` | "HH:MM" | 否 | `run.py` 常驻等待/Windows 计划任务使用的执行时间（默认 `07:00`） |
| `run_window` | object | 否 | 每日时间区间内随机执行：`{"start":"07:00","end":"08:30"}`；设置后 `run.py`（不带 `--now`）在区间内随机取时间，详见「定时调度」 |
| `run_windows` | array | 否 | 一天多个时间段（如 06:30-07:30、12:00-13:00、09:00-10:00）；每个时间段各执行一次，与 `run_window` 互斥 |
| `target_distance_km` | float | 否 | 基础目标距离（默认 `2.0`） |
| `min_pace_minutes` / `max_pace_minutes` | float | 否 | 允许的平均配速区间（默认 3~10 分/公里） |
| `check_after_minutes` | int | 否 | 开跑后先等待多久再检查（默认 12 分钟） |
| `max_run_minutes` | int | 否 | 跑步总时间上限（默认 20 分钟，超过强制结束） |
| `max_wait_minutes` / `poll_seconds` | int | 否 | 轮询等待上限与 OCR 间隔（默认 120 分钟 / 8 秒） |
| `distance_regex` | string | 否 | 距离数字 OCR 匹配正则（默认 `^\d+\.\d{2}$`） |
| `route_text` | string | 否 | RunSimulation 路线名（默认「标准」） |
| `pre_click_texts` | string[] | 否 | 开始前的可选点击文字（找不到自动跳过） |
| `campus` | object | ✅ | 健行校园：`package` / `activity` |
| `run` | object | ✅ | RunSimulation：`package` / `activity` |
| `close_apps` | bool | 否 | 结束后是否关闭两个 App（默认 true） |
| `shutdown_emulator` | bool | 否 | 成功跑完后是否关闭 MuMu 模拟器（默认 true） |
| `skip_if_success_today` | bool | 否 | 当天已成功跑过则跳过，避免重复提交（默认 true；CLI `--force` 可忽略） |
| `log_dir` | string | 否 | 日志目录（默认 `logs`） |
| `log_retention_days` | int | 否 | 截图/入口日志保留天数（默认 14，`<=0` 不清理） |
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
  {"name": "mumu-2", "adb_serial": "127.0.0.1:16448", "mumu_index": 2}
]
```

- `adb_serial` 端口用 `MuMuManager.exe info -v <index>` 的 `adb_port` 确认；
- 两个实例都需要安装并登录两个 App；
- 并行时每个实例独立写日志 `logs/run_YYYYMMDD_<name>.log` 与当日标记 `.last_success_<name>`；
- 退出码汇总规则见 README「多模拟器并行」；单实例配置保持不变。
- 临时只跑其中一个实例：`--instance <name|1-based 序号>`（如 `--instance mumu-1`），其余实例不启动；可用于 `--now`、`--window-once` 及定时模式。
- 无痕执行：`--no-record` 不写当日成功标记，也不把时间段标记为完成（`--window-once`/多时间段/单实例均生效），便于重复执行或同一时间段分实例执行。
