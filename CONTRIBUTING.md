# 贡献指南（Contributing）

感谢你愿意为 **MaaCampusRun**（校园跑值守）做出贡献。提交贡献前，请先阅读并同意 [LICENSE](LICENSE) 与 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

> 注意：本项目原创代码采用 **GPL-3.0**（OSI 开源，允许商业使用；衍生作品须按 GPL 兼容方式开源），你提交的代码、文档与资源将按同一许可授权。

## 开发环境

- Windows 10/11
- Python 3.12+
- MuMu 模拟器（仅涉及设备联调时需要；离线测试不需要）
- Git

```powershell
git clone https://github.com/KJH50/maa-campus-run.git
cd maa-campus-run
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install pytest ruff
```

## 目录约定

- `maa_campus/`：核心 Python 代码（`flow` 业务流程、`emulator` 模拟器、`maa_tasks` MaaFw 封装、`distance` OCR 解析等）；
- `assets/resource/`：MaaFramework 流水线与 OCR 模型；
- `scripts/`：Windows 一键入口与计划任务脚本；
- `tools/`：调试工具；
- `tests/`：离线测试（mock 设备/OCR，不连模拟器）。

## 开发与测试

```powershell
# 离线测试（不应连接模拟器）
.venv\Scripts\python -m pytest -q

# 代码规范
.venv\Scripts\python -m ruff check .

# 安全演练（会连接 MuMu，但只截图识别、不点击不上传）
.venv\Scripts\python run.py --now --dry
```

- 新功能请附带 `tests/` 下的离线测试；
- 修复 bug 时请说明复现步骤与退出码；
- 请勿提交 `config.json`、`logs/`、`.venv/`、账号/密码/证书/Token。

## 提交信息与 PR

1. Fork 仓库并从 `main` 创建分支（如 `feat/xxx`、`fix/xxx`）；
2. 提交信息建议使用语义化前缀：`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`；
3. PR 描述请包含：变更目的、影响范围、测试结果（`pytest` 输出）、是否需要更新 README/CHANGELOG；
4. 请确保 CI 通过、工作区不包含敏感文件；
5. 涉及行为变更的 PR 需要更新 `CHANGELOG.md`（`Unreleased` 段）。

## 兼容性与边界

- 不修改第三方组件（MaaFramework / MaaFw / OCR 模型）的许可证与版权声明；
- 引入 GPL/AGPL 代码前需评估与 GPL-3.0 的兼容性（GPL-3.0 兼容；AGPL-3.0 组合需按 AGPL 处理，详见 `THIRD_PARTY_NOTICES.md`）；
- 不提交与“自动完成校园跑”无关的破坏性改动（如修改学校系统、绕过平台安全机制等）。

## 联系方式

- 功能讨论与问题：GitHub Issues
- 安全漏洞：见 [SECURITY.md](SECURITY.md)（请勿公开披露）
