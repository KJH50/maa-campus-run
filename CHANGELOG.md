# Changelog

本文件记录项目的显著变更。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)（`MAJOR.MINOR.PATCH`）。
版本标签格式：`vX.Y.Z`（例如 `v0.2.0`）。

## [Unreleased]

### Added

- 模拟器冷启动改为轮询 `sys.boot_completed`（`emulator_boot_timeout_seconds`，默认 300 秒）；启动超时后自动重启实例一次再重试（`emulator_restart_on_fail`，默认开启）。
- 开跑 4/12 分钟抽检增加进度合理性校验（距离/时间/配速自洽），异常时发送 `progress_anomaly` 告警（不中断流程）。
- 当日成功标记 `logs/.last_success`：当天已成功跑过则跳过，避免重复提交；新增 `--force` 忽略该标记。
- 新增离线测试：模拟器启动/重启路径、进度校验、当日跳过与成功标记（pytest 20 个用例）。

### Changed

- 简化为个人项目：移除 `CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md` 及对应链接，不再维护贡献指南/行为准则/安全策略。
- 重写 `DISCLAIMER.md`：明确用户使用本脚本（含误用、配置错误、操作不当、脚本缺陷等）所进行的一切操作与后果由用户自行承担，作者/维护者不承担任何责任。

## [0.2.1] - 2026-11-05

GPL-3.0 许可版本 + 文档扩展（公开前准备）。

### Changed

- 许可证由 PolyForm Noncommercial 1.0.0 切换为 **GNU GPL v3.0**（OSI 开源，允许商业使用；衍生作品须按 GPL 兼容方式开源）。历史发布版本（`v0.2.0` 及更早）仍按当时的 NC 许可授权，不追溯变更。
- `LICENSE` 改为纯 GNU GPL-3.0 全文；版权声明（`Copyright (C) 2026 KJH50`）移入 `NOTICE`，以适配 GitHub 许可证识别。
- 版本号升至 `0.2.1`。

### Added

- `docs/` 文档：架构与执行流程、配置说明、退出码与失败处理、FAQ、故障排查（入口见 `docs/README.md`）。

## [0.2.0] - 2026-11-05

首个可公开就绪版本（source-available，非商业许可）。

### Added

- 校园跑值守主流程：准备 RunSimulation（标准路线）→ 准备健行校园（首页 → 继续征程）→ 点开始跑步 → 点校园跑开始 → 开跑前置校验 → 距离/配速轮询 → 结束结算 → 停止模拟并关闭 App → 关闭模拟器。
- 开跑后 2/4 分钟距离抽检，提前发现「跑了但没记录」的情况。
- 随机结束距离：围绕 0.415 km 整圈闭合点（循环 5 圈 ≈ 2.075 km），约 20% 概率与起点重合，其余在起点前 20~50 m 结束；距离限制在 2.0~2.2 km。
- 20 分钟强制结束兜底；结束结算与停止关闭各一次自动重试；失败清理（全部停止 + 关闭两个 App）。
- 一键入口 `scripts\一键值守.cmd`：单实例锁、环境自检（含 MuMu 自动拉起）、结果摘要写入 `logs/oneclick/`。
- Windows 计划任务注册脚本 `scripts\install_task.ps1`（复用一键入口）。
- DSH 每日 07:00 定时任务支持（由专用会话的 Agent 执行 `run.py --now`）。
- 离线测试 `tests/`（pytest，覆盖解析/配置校验/达标/强制结束/超时/重试）。
- 配置必填校验、日志保留清理（`log_retention_days`）、`distance_regex` 配置生效。
- 合规与协作文件：`THIRD_PARTY_NOTICES.md`、`DISCLAIMER.md`、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、Issue/PR 模板、GitHub Actions CI。

### Changed

- 项目更名为 **MaaCampusRun**（目录 `maa-campus-run`；Python 包名保持 `maa_campus`）。
- 代码按职责拆分：`emulator.py`（模拟器生命周期）、`maa_tasks.py`（MaaFw 资源/OCR 原语）、`flow.py`（业务流程）。
- README 更新为公开就绪版本：安装、配置、示例输出、FAQ、贡献与安全入口。
- 许可证确定为 PolyForm Noncommercial 1.0.0（非商业），并补充第三方许可证声明。

### Fixed

- 修复 `--dry` 演练分支解包错误。
- 修复校园跑 App 冷启动恢复到「活动与赛事」等非首页页面时准备失败的问题（Python OCR 状态机自动恢复）。

### Removed

- 删除 pipeline 中失效的 `CampusPrepare/CheckRecovery/TapHomeTab/TapContinueJourney/CampusPrepared/ReadDistance/ReadText` 节点（准备逻辑统一到 Python 状态机）。
