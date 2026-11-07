# AI 定时页面解析与操作回传（实验特性）

> 默认关闭。启用前请先阅读「安全与限制」。本功能不会在未配置的情况下上传任何截图。

## 1. 工作方式

```
定时（interval / cron）
  → 截图（当前视口，PNG/JPEG，可压缩/缩放）
  → OCR + 规则判定「非确定画面」
  → 命中规则才：脱敏遮罩 → 上传 AI（OpenAI 兼容视觉接口 / mock）
  → 校验结构化 JSON 决策（动作/目标/参数/置信度）
  → 执行动作（click / input / scroll / wait / retry / abort）
  → 复检页面状态（感知哈希），写 JSONL 日志
```

正常页面不会上传截图；同一任务通过文件锁避免并发重复执行；动作受置信度阈值与动作白名单限制。

## 2. 快速启用

`config.json`：

```json
"ai_watch": {
  "enabled": true,
  "mode": "cron",
  "cron": "*/5 * * * *",
  "target": {"package": "yx.c520.xyz", "display": 0, "url": "app://健行校园/校园跑页"},
  "rules": {
    "expected_selectors": ["^开始$", "总距离"],
    "unique_selectors": ["^开始$"],
    "error_keywords": ["验证码", "网络异常", "加载失败", "重新登录"],
    "blank_screen": {"enabled": true, "threshold": 0.98},
    "low_confidence": {"enabled": true, "threshold": 0.5}
  }
}
```

运行：

```powershell
.venv\Scripts\python.exe run.py --ai-watch-once   # 只跑一轮（验收/调试）
.venv\Scripts\python.exe run.py --ai-watch        # 常驻循环
```

## 3. 配置说明

| 键 | 说明 |
|---|---|
| `enabled` | 总开关，默认 `false` |
| `mode` | `interval` 或 `cron` |
| `interval_seconds` | interval 模式间隔 |
| `cron` | cron 模式表达式（5 段：分 时 日 月 周，0=周日） |
| `cycle_timeout_seconds` | 单次执行超时（记录告警，不强制中断阻塞调用） |
| `max_retries` / `backoff_seconds` | AI/动作失败后的重试次数与退避 |
| `lock_stale_seconds` | 单实例锁过期时间（进程异常退出后自动回收） |
| `cooldown_seconds` | 同一页面/决策的冷却时间（防重复触发） |
| `target` | `package`（Android 包名）、`display`（0 自动）、`url`（页面标识，写入日志与 AI 上下文） |
| `capture.format` / `quality` / `max_width` | 截图格式 PNG/JPEG、压缩质量、最大宽度 |
| `capture.mask_regions` | 上传前遮罩区域：`[{"x":0,"y":0,"w":300,"h":120}]` 或 `[x,y,w,h]` |
| `rules.*` | 见下方「非确定画面规则」 |
| `ai.provider` | `mock`（离线）或 `openai-compatible` |
| `ai.env_endpoint` / `env_api_key` / `env_model` | 从哪个环境变量读取连接信息 |
| `ai.timeout_seconds` / `json_mode` | HTTP 超时；是否请求 JSON mode |
| `action.allowed` | 允许动作白名单 |
| `action.confidence_threshold` | 低于该置信度不执行（默认 0.7） |
| `action.max_wait_seconds` | wait 动作上限 |
| `log_dir` | JSONL 日志与截图目录（默认 `logs/ai_watch`） |

### AI 接入（Deepseek Homesh / 任意 OpenAI 兼容视觉接口）

不要把 API Key 写入仓库。通过环境变量：

```powershell
$env:DEEPSEEK_ENDPOINT = "https://<你的服务>/v1/chat/completions"
$env:DEEPSEEK_API_KEY  = "<key>"
$env:DEEPSEEK_MODEL    = "<模型/服务名>"
```

如果 Deepseek Homesh 的接口不是 OpenAI 兼容格式，需要在 `maa_campus/ai_vision.py` 中实现对应 provider（当前已预留 provider 分支）。`mock` 模式用于离线验收，不联网。

## 4. 非确定画面规则

| 规则 | 触发条件 |
|---|---|
| `missing_expected` | `expected_selectors` 中任一正则未匹配到 OCR 文字（元素未出现） |
| `multiple_candidates` | `unique_selectors` 匹配到多于 1 个元素 |
| `selector_mismatch` | `structure_selectors` 未匹配（页面结构与预设选择器不一致） |
| `error_keyword` | OCR 文字包含 `error_keywords`（错误提示/验证码/异常状态） |
| `blank_screen` | 接近中位数的像素占比 ≥ `threshold`（关键区域空白） |
| `low_confidence` | OCR 最高置信度低于 `threshold` |
| `ocr_empty` | 配置了预期元素但 OCR 未识别到文字 |

每条规则都有 `enabled` 开关；阈值可调，避免正常页面频繁上传。

## 5. AI 返回与动作

AI 必须返回结构化 JSON：

```json
{"action":"click","target":"开始","params":{},"confidence":0.92,"reason":"检测到校园跑开始按钮"}
```

- 动作：`click`（target 或 `{x,y}`）、`input`（`{text}`，可选 target 先聚焦）、`scroll`（`{direction,distance}`）、`wait`（`{seconds}`）、`retry`（重试本轮）、`abort`（中止）；
- 校验：动作白名单、置信度阈值、目标存在且唯一、参数合法（坐标/文本长度/滚动距离/等待上限）；
- 不合法或低置信度：按 `max_retries` 重试，超过后记录 `decision_rejected` 并结束本轮，不会误点击。

## 6. 错误码

| 错误码 | 含义 |
|---|---|
| `AW_001_CONFIG` | 配置/运行异常 |
| `AW_010_LOCK` | 已有实例在运行（锁冲突） |
| `AW_020_CONNECT` | adb 连接失败 |
| `AW_021_TASKER` | MaaFw 资源/控制器初始化失败 |
| `AW_030_SCREENSHOT` | 截图/编码失败 |
| `AW_040_AI` | AI 调用失败（含 `AI_NETWORK`/`AI_TIMEOUT`/`AI_HTTP`/`AI_INVALID_JSON`/`AI_SCHEMA`/`AI_NOT_CONFIGURED`） |
| `AW_050_ACTION` | 动作校验/执行失败（`ACTION_UNSUPPORTED`/`TARGET_MISSING`/`TARGET_AMBIGUOUS`/`PARAMS_INVALID`/`LOW_CONFIDENCE`/`EXEC_FAILED`） |
| `AW_080_RECHECK` | 动作后页面感知哈希未变化（可能未生效） |

## 7. 日志与幂等

- JSONL：`logs/ai_watch/ai_watch_YYYYMMDD.log`，字段含 `task_id`、`time`、`page_url`、`status`、`reasons`、`decision`、`action_result`、`error_code`、`duration_ms`、`screenshot`；
- 截图：`logs/ai_watch/shots/<task_id>.jpg`（已脱敏）；
- 单实例锁：`logs/ai_watch/.ai_watch.lock`（过期自动回收）；
- 同一页面哈希 + 决策在冷却时间内重复出现会被跳过；动作后复检页面哈希，未变化会在日志标记 `recheck=unchanged`。

## 8. 验收步骤（离线）

1. 保持 `ai.enabled=false` 的默认配置；
2. 复制 `config.example.json` → `config.json`，设置 `ai_watch.enabled=true`、`ai.provider="mock"`、`mock_response` 为期望动作；
3. 构造页面状态（例如隐藏「开始」按钮、弹出「网络异常」提示），执行 `run.py --ai-watch-once`；
4. 查看 `logs/ai_watch/ai_watch_*.log`：应出现 `status=uncertain`、上传信息、`decision`、`action_result`、复检结果；
5. 恢复正常页面再执行一次：`status=normal`，不应有上传记录。

## 9. 安全与限制

- 默认关闭；API Key 仅从环境变量读取，不写入日志/仓库；
- 截图先按 `mask_regions` 遮罩后上传，但仍建议避免截入账号/隐私区域；
- 本功能依赖 MaaFramework OCR 与 adb 截图，页面「URL」为 app 内标识；若目标为网页，请自行替换截图/URL 来源；
- `cycle_timeout_seconds` 目前为告警式超时，阻塞中的 HTTP/adb 调用由各自超时控制；
- Deepseek Homesh 的具体接口协议未知，`openai-compatible` 适配器按 Chat Completions 多模态格式实现；如接口不同需新增 provider。
