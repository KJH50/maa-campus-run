# 故障排查（Troubleshooting）

## 1. 连接失败（退出码 1）

1. 确认模拟器已启动：`adb devices` 能看到 `127.0.0.1:16416 device`；
2. 检查 `config.json` 的 `adb_path`（adb 可执行文件）与 `adb_serial` 是否与当前实例一致；
3. 若 `mumu_manager` 已配置但仍无法连接，可能是实例卡死：用 MuMuManager 重启实例后重试；
4. 检查 `.venv` 依赖是否完整：`.venv\Scripts\python -c "import maa, PIL, numpy"`。

## 2. App 状态异常 / 准备失败（退出码 3）

- `logs/shots/` 中 `run_prepared` / `campus_prepared` / `campus_prepare_failed` 截图可看到当时页面；
- 健行校园冷启动可能恢复到「活动与赛事」等非首页页面，`flow.prepare_campus` 会自动尝试「放弃未结束记录 → 首页 → 继续征程」；若仍失败，手动把 App 打开到校园跑页后重试；
- RunSimulation 若不在「准备跑步」或路线不是「标准」，`RunPrepare` 会尝试切换；失败时检查是否有系统权限弹窗遮挡。

## 3. 认不到距离/配速（日志频繁「未识别到距离」）

1. 查看 `logs/shots/` 最近截图，确认校园跑页显示「总距离(公里)」「平均配速」；
2. 确认分辨率/布局未变（MuMu 实例分辨率变化会影响 OCR 坐标与点击）；
3. 确认 `assets/resource/model/ocr/` 下 `det.onnx` / `rec.onnx` / `keys.txt` 存在；
4. 若 OCR 偶发失败属正常，脚本会沿用最近 60 秒内有效配速；持续失败则按退出码 2 处理。

## 4. 结束/结算失败（退出码 2/3）

- 查看 `finish` / `finish_retry` / `stop` 截图，确认「结束」「确定结束」按钮未被弹窗遮挡；
- 脚本对结束结算与停止关闭各重试一次，并检测结算页（我的数据/上传成功等）后按成功处理；
- 若已产生跑步记录但结算失败，请先到 App 内手动处理，避免重复提交。

## 5. 路径/虚拟环境问题

- 移动项目目录或换机后：删除 `.venv` 重新创建（`python -m venv .venv` + `pip install -r requirements.txt`）；
- 出现 `pyvenv.cfg` 指向旧路径时按上条重建；
- 修改 `config.json` 后无需改代码；配置校验失败会返回退出码 1 并提示缺失项。

## 登录页 / 未登录（退出码 3）

- 现象：流程开始后日志提示「登录检测：健行校园未登录」或「自动登录失败」，并保存 `campus_login_required` / `campus_login_failed` 截图。
- 处理：
  1. 确认 `campus.login.username/password` 或环境变量 `MAA_CAMPUS_USERNAME` / `MAA_CAMPUS_PASSWORD` 正确；
  2. 多模拟器使用不同账号时，确认对应实例的 `instances[].login` 或实例级环境变量（如 `MAA_CAMPUS_USERNAME_MUMU_2`）正确；
  3. 若账号需要验证码/短信/首次改密，自动登录会失败，请手动在 MuMu 中完成登录；
  4. 确认学校选择为「湖南高速铁路职业技术学院」；
  5. 确认能看到首页或校园跑页后再运行。
- 说明：脚本不会记录密码；`config.json` 已被 `.gitignore` 忽略，不要提交真实账号密码。

### 退出登录 / 换账号

```powershell
# 退出指定模拟器的健行校园登录（我的 → 退出登录）
.venv\Scripts\python.exe run.py --logout --instance mumu-1
```

- 成功后回到「欢迎登录健行校园」引导页；已处于未登录状态时直接返回成功（可重复执行）；
- 退出后再正常执行，脚本会用该实例配置的账号自动登录；
- 退出码：`0` 成功；`1` 模拟器/控制器失败或多实例未指定 `--instance`；`3` 未能找到「我的/退出登录」或未回到登录页；`5` 该实例正在运行。

## 6. 收集信息提交 Issue

请提供（脱敏后）：

- 退出码、`logs/run_YYYYMMDD.log` 相关片段；
- `logs/shots/` 对应阶段截图（不要包含账号/个人隐私）；
- 环境：Windows 版本、Python 版本、MuMu 版本/实例、`adb_serial`；
- 复现步骤与是否可稳定复现。
