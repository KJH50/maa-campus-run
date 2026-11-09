# 常见问题（FAQ）

**Q：MuMu 没开，脚本会自动启动吗？**
会。`emulator.ensure_emulator` 在 adb 连接失败时按 `mumu_manager` / `mumu_index` 调用 `MuMuManager control -v <idx> launch`，再最多等待 180 秒连接；连接成功后才继续。

**Q：`--dry` 会点击按钮或上传记录吗？**
不会。`--dry` 只截图并识别一次距离/配速，不点击任何按钮、不开始/结束跑步、不上传。

**Q：跑完会自动关闭 MuMu 吗？**
成功跑完并关闭两个 App 后，`shutdown_emulator` 默认会关闭模拟器；下次运行会自动重新拉起。失败时不会关闭，便于排查。可在 `config.json` 将 `shutdown_emulator` 设为 `false` 保留模拟器。

**Q：日志和截图在哪里？保留多久？**
`logs/run_YYYYMMDD.log`、`logs/shots/`；启动时会按 `log_retention_days`（默认 14 天）清理旧文件；一键入口摘要见 `logs/oneclick/`。

**Q：如何调整目标距离/配速？**
修改 `config.json` 的 `target_distance_km`、`min_pace_minutes`、`max_pace_minutes`。注意结束距离会在整圈闭合点附近随机，且始终大于基础目标。

**Q：每次结束距离为什么略有不同？**
`flow.randomized_target` 会围绕路线整圈闭合点随机：约 20% 概率跑满整圈，其余在起点前 20~50 m 结束，避免每次轨迹完全一致。

**Q：失败时怎么看原因？**
先看退出码（见 [退出码与失败处理](exit-codes.md)），再看 `logs/run_*.log` 与 `logs/shots/` 对应阶段截图；一键入口的 `logs/oneclick/result_*.txt` 有摘要。

**Q：提示「已有 run.py 进程在运行」（退出码 5）？**
说明上一次执行尚未结束或残留进程。等待其结束，或在确认没有真实任务后结束残留进程再重试；不要并发运行，避免重复提交记录。

**Q：同一天已经成功跑过，再运行会重复提交吗？**
默认不会：成功完成后会写入当日标记 `logs/.last_success`，当天再次运行会自动跳过（退出码 0）。确需重跑请加 `--force`（可能重复提交记录）。

**Q：如何设置「每天在一个时间段内随机时间执行」？**
在 `config.json` 设置 `"run_window": {"start": "07:00", "end": "08:30"}`，然后用 `run.py`（不带 `--now`）或通过 `install_task.ps1` 注册任务即可；当天随机时间会持久化，重启不会重新随机。详见 [配置说明](configuration.md) 的「定时调度」。

**Q：DSH 定时任务怎么配合随机时间段？**
让 DSH 在每个时间段起点附近触发（如 06:30/09:30/12:30），执行 `run.py --window-once`：只处理当前（或下一个）时间段，区间内随机等待后执行一次即退出，已完成/已错过段自动跳过。示例 RRULE：`RRULE:FREQ=DAILY;BYHOUR=6,9,12;BYMINUTE=30`。

**Q：一天想跑多次、每次在不同时间段怎么办？**
使用 `run_windows` 配置多个时间段（当前默认示例：06:30-07:30、12:00-13:00、09:00-10:00），每个时间段各执行一次（随机时间）；`run.py`（不带 `--now`）会依次等待各时间段，重启会跳过已完成的时间段。注意会产生多条跑步记录。

**Q：如何同时用两个模拟器跑相同任务？**
在 `config.json` 的 `instances` 中配置两个实例（`name` / `adb_serial` / `mumu_index`），`run.py --now` 会自动为每个实例启动独立子进程并行执行；日志与当日标记按实例分开。详见 [配置说明](configuration.md) 的「多实例并行」。

**Q：如何只跑其中一个模拟器？**
在命令后加 `--instance <name 或序号>`，例如 `run.py --window-once --instance mumu-1` 或 `run.py --now --instance 2`；其余实例不会被启动。

**Q：跑完不想留下「今天已完成」记录怎么办？**
加 `--no-record`：不写当日成功标记，也不把时间段标记为完成，便于重复执行或同一时间段分实例执行（如 `run.py --window-once --instance mumu-1 --no-record`）。

**Q：如何设置最高跑步次数？**
在 `config.json` 设置 `"max_runs": 60`（按学校要求）。脚本在进入健行校园首页时读取「26次/60次」或「已跑 X 次」，达到上限后不开始跑步并记录 `logs/.max_runs_reached_<instance>.json`，后续触发可直接跳过；`--force` 可强制忽略。若界面文案变化，可调整 `run_count_patterns`；想在不设上限时也记录次数可设 `"log_run_count": true`。

**Q：MuMu 启动后画面错位/显示异常，拖动一下窗口大小才恢复？**
这是 MuMu 窗口/渲染表面恢复问题（常见于 `window_save_rect=true` 恢复旧窗口位置、Vulkan 渲染器、或由计划任务在隐藏/锁屏会话中拉起）。脚本已默认在连接/启动完成后 `show_window` 并对窗口做一次 1px 尺寸微调来强制刷新（`refresh_window_on_start`，默认 `true`）；若仍出现，可尝试在 MuMu 设置中关闭「记忆窗口位置」或切换渲染器。

**Q：换电脑/移动目录后无法运行？**
`.venv` 与本机环境绑定：删除 `.venv` 后按 README 重新创建并安装依赖；同时更新 `config.json` 中的 adb/MuMu 绝对路径。

**Q：如何安全地试跑？**
先 `run.py --now --dry` 验证连接与 OCR，再在确认可提交记录后执行 `run.py --now`。
