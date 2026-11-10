# 桌面控制台（补充入口）

> 定位：在现有 CLI / `config.json` / DSH 定时任务 / oneclick / Web 控制台之外，新增一个**本机原生桌面窗口**，作为补充入口；不替代、不影响任何原有控制方式。
> 技术栈：Python 标准库 `tkinter` + `ttk`，无新增依赖、无 WebView、无 Node。

## 1. 为什么使用 Tkinter

- 项目是 Python 小工具，Tkinter 随 Windows 官方 Python 一起提供，**零新增依赖**；
- 不需要浏览器/Electron/WebView2，双击即可打开原生窗口；
- 桌面控制台复用 `webui.App` 的状态读取、配置校验/备份、任务管理逻辑；执行仍通过 `run.py` 子进程，行为与 CLI 一致；
- 不改变 Web 控制台与 CLI，二者可同时使用（同一时间只允许一个 run.py 任务）。

## 2. 启动方式

```powershell
# 在项目目录
.venv\Scripts\python.exe run.py --desktop
```

也可以双击 `scripts\桌面控制台.cmd`（内部使用 `pythonw.exe`，不显示黑色控制台窗口），或直接启动模块：

```powershell
.venv\Scripts\python.exe -m maa_campus.desktop
```

说明：
- `--desktop` 只打开窗口，不会自动开始跑步；
- 不能与 `--now/--dry/--window-once/--ai-watch*` 等执行参数同时使用；
- 不能与 `--web` 同时使用（两个入口独立启动即可）。

## 3. 页面功能

### 概览
- 运行状态：当前任务、开始/结束时间、退出码；
- 配置摘要：目标距离、`max_runs`、时间段、检查间隔、错峰等；
- 实例状态：名称、adb、今日成功、最高次数标记、运行锁；
- 最近一次运行：目标/完成距离、已跑次数、退出码、错误摘要。

### 执行
- 模式：安全演练（dry，默认）/ 立即执行 / `--window-once` / `--ai-watch-once`；
- 可选实例、`--force`、`--no-record`；
- 真实执行前二次确认；
- 实时输出终端；运行中可停止任务（Windows 下终止子进程树）。

### 配置
- 常用参数表单；`run_windows` / `instances` JSON 编辑；
- “编辑完整 JSON…” 打开高级编辑器；
- 保存前使用现有 `load_config + validate_config`；非法配置不写入；
- 写入前自动备份 `config.json.bak-时间戳`。

### 日志
- 列出 `logs/` 下运行/AI/告警/任务日志；
- 查看尾部、错误/警告高亮；
- 运行中可自动刷新；
- **打包日志与截图**：点击按钮生成 zip，完成后弹窗显示路径、文件数和大小。

## 4. 与现有控制方式的关系

| 入口 | 影响 |
|---|---|
| `run.py --now / --dry / --window-once / --ai-watch*` | 无影响；新增 `--desktop` 为纯增量 |
| `config.json` | 格式不变；桌面端保存仍走同一校验/备份 |
| oneclick / DSH / 计划任务 / Web 控制台 | 不修改、不替代；可同时存在 |
| 日志/状态文件 | 沿用原格式；桌面端只读取，不改变文件结构 |
| 退出码 | 桌面端透传 `run.py` 的 0/1/2/3/5 |

## 5. 测试步骤

### 离线回归
```powershell
.venv\Scripts\python.exe -m pytest tests/test_desktop.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .
```

### 桌面窗口
```powershell
.venv\Scripts\python.exe run.py --desktop
```
依次检查：
1. 「概览」显示配置、实例、最近运行；
2. 「执行」选择“安全演练”并开始（会连接模拟器，但不会点击开始跑步）；观察实时输出；
3. 「配置」修改 `target_distance_km` 保存，确认生成 `config.json.bak-*`；
4. 「日志」选择 `run_*.log` 查看，错误/警告高亮；
5. 运行中点击“停止当前任务”，确认任务结束；
6. 关闭窗口时若任务仍在运行，会提示是否同时停止。

### 与 CLI/Web 共存
```powershell
# 桌面窗口运行时，另开终端
.venv\Scripts\python.exe run.py --help
.venv\Scripts\python.exe run.py --now --dry
```
预期：CLI 参数与行为不变；桌面端与 CLI 同时触发时，实例运行锁按既有规则拒绝并发（退出码 5）。

## 6. 常见问题

| 现象 | 处理 |
|---|---|
| `无法启动桌面控制台（没有可用图形环境）` | 需要在 Windows 桌面会话中运行；SSH/无桌面环境请使用 CLI 或 Web 控制台 |
| Tkinter 导入失败 | 使用项目自带 Windows Python/venv；官方安装包默认包含 tkinter |
| 窗口字体/缩放异常 | Windows 显示缩放设置会影响 Tk；可在系统设置调整缩放 |
| 配置保存失败 | 按错误提示修正；原文件未覆盖，备份在 `config.json.bak-*` |
| 停止后仍占用实例 | 等待运行锁过期（`run_lock_stale_seconds`），或确认无真实任务后删除 `logs/.run_<instance>.lock` |
