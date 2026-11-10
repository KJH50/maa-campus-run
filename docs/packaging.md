# 日志与截图打包

把 `logs/` 下的运行日志、AI/Web 日志、证据截图和少量状态文件打成 zip，便于留存、排障或反馈问题。

## 1. 打包内容

默认包含最近 `pack_days` 天（默认 7 天）的：

- `run_*.log`、`onclick`/`webui`/`ai_watch`/`alerts` 日志；
- `logs/shots/` 下的证据截图（PNG/JPG/JPEG/WebP）；
- `logs/ai_watch/` 下的 JSONL 日志与 AI 截图；
- `logs/.last_success*`、`.max_runs_reached_*.json`、`.run_windows_state.json`、`.next_run` 等状态文件；
- `manifest.json`：生成时间、过滤条件、非敏感配置摘要、文件清单（路径/大小/修改时间）。

**不包含**：`config.json`、API Key、环境变量、`logs/exports/` 里已有的压缩包。截图可能包含个人信息，压缩包本身不加密，请谨慎外发。

## 2. 使用方式

### CLI

```powershell
# 默认：最近 7 天、含截图，输出到 logs/exports/maa_campus_logs_<时间戳>.zip
.venv\Scripts\python.exe run.py --pack-logs

# 只打包最近 2 天、不含截图
.venv\Scripts\python.exe run.py --pack-logs --pack-days 2 --pack-no-shots

# 指定输出路径（相对项目根目录或绝对路径）
.venv\Scripts\python.exe run.py --pack-logs --pack-output logs/exports/debug.zip

# 全部历史（0 = 不按天数过滤）
.venv\Scripts\python.exe run.py --pack-logs --pack-days 0
```

也可以直接调用模块：

```powershell
.venv\Scripts\python.exe -m maa_campus.packaging --days 7
```

### 桌面控制台

打开「日志」页 → 点击 **打包日志与截图**。使用 `config.pack_days` / `config.pack_include_shots` 的默认值，完成后弹窗显示 zip 路径、文件数和大小。

### Web 控制台

打开「日志」页 → 点击 **打包日志与截图**。生成后可点“下载 ZIP”直接保存到浏览器下载目录。对应 HTTP API：

- `POST /api/export`（body 可选 `{"days": 7, "include_shots": true}`）；
- `GET /api/export/download?name=<zip 文件名>`。

### 配置

```json
"pack_days": 7,
"pack_include_shots": true
```

| 键 | 默认 | 说明 |
|---|---|---|
| `pack_days` | `7` | 打包最近 N 天；`0` 表示全部 |
| `pack_include_shots` | `true` | 是否包含 `shots/` 截图 |

CLI 的 `--pack-days` / `--pack-no-shots` 可临时覆盖配置。

## 3. 实现与兼容性

- 新模块 `maa_campus/packaging.py`，仅使用标准库 `zipfile`；
- 不修改原始日志/截图；不改变 CLI/config/脚本/定时任务；
- 默认输出文件名带时间戳，已存在时自动加序号，避免覆盖；
- 默认使用 `ZIP_DEFLATED` 压缩；PNG/JPG 本身已压缩，zip 后体积通常只小幅下降，想显著减小可加 `--pack-no-shots` 或先降低截图保留量。

## 4. 验证步骤

```powershell
# 1) 单元测试（临时目录，不碰真实日志）
.venv\Scripts\python.exe -m pytest tests/test_packaging.py -q
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .

# 2) 真实打包（不含截图，快速）
.venv\Scripts\python.exe run.py --pack-logs --pack-days 1 --pack-no-shots
# 终端会打印 zip 路径；用资源管理器打开 logs/exports 查看

# 3) 解压检查（可选）
python -c "import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print(z.namelist()[:20])" logs/exports/<生成的zip>
```

> dry/真实执行不属于本功能必需步骤；打包只读取已存在的日志与截图，不会启动模拟器。
