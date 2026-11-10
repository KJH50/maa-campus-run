# Web 控制台（补充入口）

> 定位：**补充**现有 CLI / `config.json` / DSH 定时任务 / oneclick 脚本，不替代、不删除、不破坏任何原有控制方式。
> 技术栈：Python 标准库 `http.server` + 原生 HTML/CSS/JS（无 Node、无前端构建、无新增 Python 依赖）。

## 1. 为什么选择这个方案

| 方案 | 取舍 |
|---|---|
| 原生 HTML/CSS/JS + Python 标准库服务 | ✅ 零新增依赖，和当前“Python 小工具 + venv”结构一致；✅ 单文件后端、易审计；✅ 离线可用；❌ 不做复杂组件化 |
| React/Vue + Vite | 需要 Node、构建产物、额外维护；对一个本地值守工具过重 |
| Flask/FastAPI + 模板 | 增加依赖和启动方式；收益有限 |

本控制台把“执行”统一转成 **`run.py` 子进程**，因此后端业务逻辑、参数、退出码、日志格式与 CLI 完全一致，前端只是视图层。

## 2. 启动方式

无需新增依赖（仅需现有 `requirements.txt` 中的 MaaFw / pillow / numpy，以及 Python 3.12）：

```powershell
# 默认：http://127.0.0.1:8765/ ，并自动打开浏览器
.venv\Scripts\python.exe run.py --web

# 指定端口 / 不自动打开浏览器
.venv\Scripts\python.exe run.py --web --web-port 8765 --web-no-browser

# 仅本机访问（默认）；如需局域网访问（不推荐）
.venv\Scripts\python.exe run.py --web --web-host 0.0.0.0
```

也可独立启动（不经过 `run.py` 的其它参数）：

```powershell
.venv\Scripts\python.exe -m maa_campus.webui --port 8765
```

`--web` 只启动控制台，不会启动模拟器或执行跑步；它与 `--now/--dry/--window-once/--ai-watch*` 等执行参数互斥（同时传入会直接报错，避免误操作）。

## 3. 页面功能

### 概览
- 连接/运行状态、当前任务标题、开始/结束时间、退出码；
- 配置摘要：目标距离、`max_runs`、时间段、首次检查、总超时、错峰启动、AI 值守开关；
- 实例状态：名称、adb serial、今日成功标记、最高次数标记、运行锁；
- 最近一次运行：目标/完成距离、已跑次数、退出码、错误摘要。

### 执行
- 执行模式：
  - **安全演练（dry）**：只截图/识别，不点击（默认选项，最安全）；
  - **立即执行**：真实跑步，点击前弹出二次确认；
  - **单时间段执行**：`--window-once`；
  - **AI 页面检查一轮**：`--ai-watch-once`；
- 可选 `--force` / `--no-record` / 指定实例；
- 实时输出终端；运行中可“停止当前任务”（Windows 下会终止整个子进程树）；
- 所有参数最终拼成与 CLI 相同的 `run.py` 命令，退出码和日志格式不变。

### 配置
- 常用参数表单（目标距离、`max_runs`、检查间隔、adb、错峰、开关项、`run_windows` / `instances`）；
- 完整 `config.json` 原始 JSON 编辑器；
- 保存前使用现有 `load_config + validate_config` 校验；非法配置不会写入；
- 写入前自动备份为 `config.json.bak-时间戳`；
- 修改配置只影响**之后新启动**的任务，正在运行的任务继续使用旧配置（与 CLI 一致）。

### 日志
- 列出 `logs/` 下的运行/AI/告警/Web 任务日志；
- 按行数查看尾部，`[ERROR]` / `[WARNING]` 高亮；
- 运行中可自动刷新；
- **打包日志与截图**：在页面点击按钮生成 zip，可直接下载；
- 仅允许访问白名单文件，拒绝路径穿越。

### 错误提示
- 后端 API 非 2xx 时页面顶部横幅 + Toast 提示；
- 配置校验错误、启动失败、任务失败均显示具体错误；
- 日志中的 ERROR 行高亮显示。

## 4. HTTP API（仅本机）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/status` | 状态、配置摘要、实例、最近运行、当前任务 |
| GET | `/api/config` | 原始 `config.json`（供编辑器读取） |
| POST | `/api/config` | 保存配置；body：`{"config": {...}}` |
| POST | `/api/run` | 启动任务；body：`{"mode":"dry|now|window_once|ai_watch_once","force":false,"no_record":false,"instance":null}` |
| POST | `/api/run/stop` | 停止当前任务（进程树） |
| GET | `/api/logs` | 日志文件列表 |
| GET | `/api/logs/view?name=...&tail=300` | 读取日志尾部 |
| POST | `/api/export` | 打包日志/截图（body 可选 `days` / `include_shots`） |
| GET | `/api/export/download?name=...` | 下载生成的 zip |
| GET | `/api/health` | 健康检查 |

API 只是本地控制台的内部接口，不改变现有 CLI/脚本的契约。

## 5. 对现有控制方式的影响

- **CLI**：原有参数全部保留；新增 `--web/--web-host/--web-port/--web-no-browser` 为纯增量。不带 `--web` 时行为与之前完全一致。
- **配置文件**：格式不变；控制台保存时仍使用现有 `load_config`/`validate_config`，仅增加备份。
- **脚本/定时任务**：`oneclick.ps1`、DSH 任务、`run.py --now/--window-once` 等不受影响；控制台不会自动注册/修改 Windows 任务或 DSH 任务。
- **日志/状态文件**：沿用 `logs/` 目录与命名；新增 `logs/webui/run_*.log` 保存 Web 启动的任务输出。
- **退出码**：控制台透传 `run.py` 退出码（0/1/2/3/5），页面直接展示。

## 6. 安全说明

- 默认只监听 `127.0.0.1`，无认证；**不要部署到公网 / 不要监听 0.0.0.0 后暴露端口**。
- `GET /api/config` 返回完整配置，可能包含 webhook 等敏感信息；仅限本机可信环境使用。
- 控制台可触发真实跑步；真实执行按钮有二次确认，建议日常优先使用 dry。
- 停止任务使用 `taskkill /T /F`（Windows）终止子进程树；已提交的跑步记录无法撤回。

## 7. 测试步骤

### 7.1 离线（不连接模拟器）
```powershell
# 1) 后端/接口/前端静态资源测试
.venv\Scripts\python.exe -m pytest tests/test_webui.py -q

# 2) 全量回归（原有功能必须全部通过）
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .

# 3) 启动控制台，浏览器打开 http://127.0.0.1:8765/
.venv\Scripts\python.exe run.py --web --web-no-browser
```
在页面中依次检查：
1. 「概览」显示配置/实例/最近运行；
2. 「执行」选择“安全演练”，点击执行（会连接模拟器，但不会点击开始跑步）；
3. 「配置」修改 `target_distance_km` 保存，确认生成备份且 JSON 合法；
4. 「日志」能列出并查看 `run_*.log`；
5. 停止服务器（Ctrl+C）后确认没有遗留 `run.py` 子进程（任务运行中时停止会同时终止）。

### 7.2 与原有控制方式共存
```powershell
# 终端 A：启动 Web 控制台
.venv\Scripts\python.exe run.py --web --web-no-browser

# 终端 B：原有 CLI 仍可正常使用（示例：安全演练）
.venv\Scripts\python.exe run.py --now --dry

# 原有帮助/参数未变
.venv\Scripts\python.exe run.py --help
```
预期：两边都能正常调用同一套 `run.py`；Web 与 CLI 同时执行时，实例运行锁会按既有规则拒绝并发（退出码 5）。

> dry 也会启动/连接模拟器；若当前不想影响真实运行，请只执行 7.1 中不涉及 run 的页面/接口检查。

## 8. 常见问题

| 现象 | 处理 |
|---|---|
| 端口被占用 | `--web-port 8766` 换端口 |
| 页面提示“无法连接后端” | 确认 `run.py --web` 仍在运行；检查终端报错 |
| 配置保存失败 | 按返回的校验错误修正；原始文件未被覆盖，备份在 `config.json.bak-*` |
| 日志列表为空 | 先执行一次任务，或确认 `config.log_dir` 指向 `logs` |
| 中文乱码 | 使用项目自带虚拟环境启动；日志以 UTF-8 读取 |
| 停止后任务仍占用实例 | 等待运行锁 `run_lock_stale_seconds` 过期，或确认没有真实任务后删除 `logs/.run_<instance>.lock` |
