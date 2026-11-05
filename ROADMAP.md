# 路线图（Roadmap）

本文件列出 MaaCampusRun 的后续方向与已知限制，不代表承诺的时间表。

## 近期（0.3.x）

- [ ] 提升 OCR/状态机鲁棒性：更多异常页面（弹窗、网络错误、活动页）自动恢复
- [ ] 支持更多 MuMu 多开实例配置（多实例索引/不同分辨率）
- [ ] 增加离线测试覆盖率（OCR 抖动、配置边界、退出码矩阵）
- [ ] `logs/oneclick` 结果摘要增加距离/配速/用时结构化字段（JSON）

## 中期

- [ ] 可选 GUI（Tkinter/托盘）用于一键执行与状态查看
- [ ] 告警通道完善（企业微信/钉钉/Bark 的配置向导与测试）
- [ ] 文档补充架构图、协议交互说明与常见故障排查手册（`docs/`）

## 长期 / 待评估

- [ ] 适配非 MuMu 模拟器或其他 Android 运行环境（需评估 CustomController 差异）
- [ ] 发布流程自动化（tag → Release → 变更说明）
- [ ] 是否发布到 PyPI（当前为脚本项目，暂不发布）

## 已知限制

- 仅支持 Windows + MuMu 模拟器环境；
- 依赖第三方 App（RunSimulation、健行校园）的 UI 与页面结构，App 更新可能导致流程失效；
- 本项目为**非商业** source-available 许可，禁止商业用途；
- 依赖链包含 LGPL/AGPL 组件，二次分发前请阅读 `THIRD_PARTY_NOTICES.md`。
