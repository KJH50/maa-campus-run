# 退出码与失败处理

## 主流程（`run.py`）

| 退出码 | 含义 | 常见原因 | 建议动作 |
|---|---|---|---|
| `0` | 成功 | 流程完成、结算完成并关闭 | 无 |
| `1` | 连接/初始化失败或执行异常 | adb 不可达、MuMu 未启动/卡死、MaaFw 资源加载失败、配置校验失败 | 检查 `adb devices`、`config.json` 的 `adb_path`/`adb_serial`、`mumu_manager`；重试一次；查看异常 traceback |
| `2` | 等待超时 / 开跑后距离未增长 / 强制结束未达标 | 12 分钟后仍未到目标距离、2/4 分钟抽检距离为 0、20 分钟上限强制结束 | 查看 `logs/shots/` 的 `stuck`/`timeout` 截图与日志最后的距离/配速；确认 App 与 GPS 联动正常；确认未重复提交记录后再决定是否重跑 |
| `3` | 开始/结束/关闭失败 | 未能点击开始、前置校验失败、结束/确定结束按钮未找到、停止/关闭失败 | 查看对应阶段截图（`run_prepared`/`campus_prepared`/`run_started`/`campus_started`/`running_check`/`finish`/`stop`）；确认 App 未被系统弹窗遮挡 |

## 一键入口（`scripts\一键值守.cmd`）

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 环境自检失败（venv/依赖/OCR 模型/config/adb 缺失） |
| `2` / `3` | 与主流程相同（透传） |
| `5` | 已有一次值守在执行（单实例锁或进程检测命中，防止重复提交） |

## 日志与证据

- 运行日志：`logs/run_YYYYMMDD.log`
- 阶段截图：`logs/shots/`（`run_prepared` / `campus_prepared` / `run_started` / `campus_started` / `running_check` / `distance_hit` / `finish` / `stop` / `timeout` / `stuck` / `cleanup`）
- 一键入口日志与摘要：`logs/oneclick/oneclick_*.log`、`result_*.txt`
- 日志保留：`log_retention_days`（默认 14 天）

## 告警

`config.json` 的 `alerts.enabled=true` 时，脚本会在失败事件（`connect_failed` / `start_failed` / `timeout` / `stop_failed` / `exception`）及进度异常（`progress_anomaly`）时按配置发送告警；默认关闭。`webhook_url` 未配置或推送失败时，会兜底写入 `logs/alerts_YYYYMMDD.log`（每行一条 JSON），保证失败有本地留痕。
