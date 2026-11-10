"""桌面控制台（Tkinter，补充入口，不替代 CLI / Web / 配置 / 脚本）。

启动：python run.py --desktop
      python -m maa_campus.desktop

实现方式：
- 使用 Python 标准库 tkinter/ttk，不新增依赖；
- 复用 webui.App 的状态、配置校验/备份、JobManager 子进程执行逻辑；
- 所有执行仍通过现有 run.py 子进程完成，与 CLI 参数/退出码/日志一致。
"""

from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from .webui import DEFAULT_CONFIG, PROJECT_ROOT, App

RUN_MODE_LABELS = {
    "安全演练（dry，不点击）": "dry",
    "立即执行（真实跑步）": "now",
    "单时间段执行（--window-once）": "window_once",
    "AI 页面检查一轮（--ai-watch-once）": "ai_watch_once",
}
DEFAULT_MODE_LABEL = "安全演练（dry，不点击）"

BG = "#0b1020"
PANEL = "#131a2e"
PANEL_2 = "#182138"
BORDER = "#27324d"
TEXT = "#e8eefc"
MUTED = "#93a1bd"
ACCENT = "#4f8cff"
SUCCESS = "#2fbf71"
WARNING = "#e0a63a"
DANGER = "#e05555"
MONO = ("Cascadia Code", 9)


def parse_json_list(text: str, label: str) -> list:
    text = (text or "").strip()
    if not text:
        return []
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{label} 不是合法 JSON：{e}") from e
    if not isinstance(value, list):
        raise ValueError(f"{label} 必须是 JSON 数组")
    return value


def merge_quick_config(raw: dict, fields: dict) -> dict:
    """把界面上的常用参数合并进原始配置；空的可选项删除以使用默认值。"""
    cfg = json.loads(json.dumps(raw or {}, ensure_ascii=False))

    def num(name: str, as_int: bool):
        value = str(fields.get(name, "") or "").strip()
        if not value:
            return None
        try:
            return int(value) if as_int else float(value)
        except ValueError as e:
            raise ValueError(f"{name} 必须是数字") from e

    def set_or_delete(key: str, value) -> None:
        if value is None or value == "":
            cfg.pop(key, None)
        else:
            cfg[key] = value

    set_or_delete("target_distance_km", num("target_distance_km", False))
    cfg["max_runs"] = num("max_runs", True) or 0
    set_or_delete("check_after_minutes", num("check_after_minutes", True))
    set_or_delete("max_run_minutes", num("max_run_minutes", True))
    cfg["adb_serial"] = str(fields.get("adb_serial", "") or "").strip()
    set_or_delete("mumu_index", num("mumu_index", True))
    set_or_delete("instance_start_stagger_seconds",
                  num("instance_start_stagger_seconds", True))
    cfg["skip_if_success_today"] = bool(fields.get("skip_if_success_today", True))
    cfg["shutdown_emulator"] = bool(fields.get("shutdown_emulator", True))
    cfg["close_apps"] = bool(fields.get("close_apps", True))
    cfg["refresh_window_on_start"] = bool(fields.get("refresh_window_on_start", True))
    cfg["run_windows"] = parse_json_list(fields.get("run_windows", ""), "run_windows")
    cfg["instances"] = parse_json_list(fields.get("instances", ""), "instances")
    return cfg


class DesktopConsole:
    def __init__(self, root: tk.Tk, app: App):
        self.root = root
        self.app = app
        self._closing = False
        self._last_job_lines = 0
        self._last_job_id = None
        self._apply_style()
        self._build()
        self.refresh_status()
        self.load_config_form()
        self.refresh_logs()
        self._schedule()

    # ------------------------------------------------------------ 外观/布局
    def _apply_style(self) -> None:
        self.root.title("校园跑值守 · 桌面控制台")
        self.root.geometry("1180x760")
        self.root.minsize(980, 640)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL_2,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("Card.TLabel", background=PANEL, foreground=TEXT)
        style.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Title.TLabel", background=BG, foreground=TEXT,
                        font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=MUTED,
                        font=("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(10, 5))
        style.configure("Primary.TButton", padding=(12, 6))
        style.configure("Danger.TButton", foreground="#ffd7d7")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 7))
        style.configure("TLabelframe", background=PANEL, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=PANEL, foreground=MUTED)
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, rowheight=24, bordercolor=BORDER)
        style.configure("Treeview.Heading", background=PANEL_2, foreground=MUTED)
        style.map("Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", "#ffffff")])
        style.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT)
        style.configure("TCombobox", fieldbackground=PANEL_2, foreground=TEXT)

    def _label(self, parent, textvariable=None, text="", style="CardMuted.TLabel", **kw):
        return ttk.Label(parent, textvariable=textvariable, text=text, style=style, **kw)

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 14, 18, 8))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="校园跑值守  桌面控制台", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="补充入口 · CLI / config.json / 计划任务 / Web 控制台保持可用",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 0))
        right = ttk.Frame(header)
        right.pack(side="right")
        self.conn_var = tk.StringVar(value="连接中…")
        self.conn_label = tk.Label(right, textvariable=self.conn_var, bg=PANEL_2, fg=MUTED,
                                   padx=10, pady=4, font=("Microsoft YaHei UI", 9))
        self.conn_label.pack(side="left", padx=(0, 8))
        self.version_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.version_var, style="Muted.TLabel").pack(side="left",
                                                                                  padx=(0, 10))
        ttk.Button(right, text="刷新", command=self.refresh_status).pack(side="left")

        self.banner_var = tk.StringVar(value="")
        self.banner = tk.Label(self.root, textvariable=self.banner_var, bg="#2a1414",
                               fg="#ffc7c7", anchor="w", padx=12, pady=8,
                               font=("Microsoft YaHei UI", 9), justify="left")
        self.banner.pack(fill="x", padx=18, pady=(0, 8))
        self.banner.pack_forget()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        self._build_overview()
        self._build_run()
        self._build_config()
        self._build_logs()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _e: self._on_tab_changed())

    def _card(self, parent, title: str):
        frame = ttk.LabelFrame(parent, text=title, padding=12)
        return frame

    def _kv(self, parent, row: int, key: str, var: tk.StringVar):
        ttk.Label(parent, text=key, style="CardMuted.TLabel").grid(row=row, column=0, sticky="w",
                                                                  padx=(0, 12), pady=2)
        ttk.Label(parent, textvariable=var, style="Card.TLabel").grid(row=row, column=1, sticky="w",
                                                                     pady=2)

    def _build_overview(self) -> None:
        frame = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame, text="概览")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=0)
        frame.rowconfigure(1, weight=1)

        card1 = self._card(frame, "运行状态")
        card1.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        self.job_status_var = tk.StringVar(value="空闲")
        self.job_title_var = tk.StringVar(value="—")
        self.job_started_var = tk.StringVar(value="—")
        self.job_ended_var = tk.StringVar(value="—")
        self.job_exit_var = tk.StringVar(value="—")
        self._kv(card1, 0, "状态", self.job_status_var)
        self._kv(card1, 1, "任务", self.job_title_var)
        self._kv(card1, 2, "开始时间", self.job_started_var)
        self._kv(card1, 3, "结束时间", self.job_ended_var)
        self._kv(card1, 4, "退出码", self.job_exit_var)
        buttons = ttk.Frame(card1)
        buttons.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="去执行", command=lambda: self.notebook.select(1)).pack(side="left")
        self.stop_btn = ttk.Button(buttons, text="停止任务", style="Danger.TButton",
                                   command=self.stop_run, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        card2 = self._card(frame, "配置摘要")
        card2.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 8))
        self.summary_var = tk.StringVar(value="—")
        ttk.Label(card2, textvariable=self.summary_var, style="Card.TLabel",
                  justify="left").pack(anchor="w")

        card3 = self._card(frame, "实例状态")
        card3.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 0))
        self.instance_tree = ttk.Treeview(
            card3, columns=("name", "adb", "success", "max", "lock"), show="headings", height=5)
        for col, text, width in (("name", "实例", 90), ("adb", "adb", 140),
                                 ("success", "今日成功", 95), ("max", "最高次数", 90),
                                 ("lock", "运行锁", 80)):
            self.instance_tree.heading(col, text=text)
            self.instance_tree.column(col, width=width, anchor="w")
        self.instance_tree.pack(fill="both", expand=True)

        card4 = self._card(frame, "最近一次运行")
        card4.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))
        self.latest_var = tk.StringVar(value="暂无运行日志")
        ttk.Label(card4, textvariable=self.latest_var, style="Card.TLabel",
                  justify="left").pack(anchor="w")
        self.latest_errors = tk.Label(card4, text="", bg=PANEL, fg="#ffb3b3", anchor="w",
                                      justify="left", font=("Microsoft YaHei UI", 9))
        self.latest_errors.pack(fill="x", pady=(6, 0))

    def _build_run(self) -> None:
        frame = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame, text="执行")
        controls = ttk.LabelFrame(frame, text="触发执行", padding=12)
        controls.pack(fill="x", pady=(0, 8))
        ttk.Label(controls, text="执行模式", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
        self.mode_var = tk.StringVar(value=DEFAULT_MODE_LABEL)
        self.mode_combo = ttk.Combobox(controls, textvariable=self.mode_var, state="readonly",
                                       values=list(RUN_MODE_LABELS), width=30)
        self.mode_combo.grid(row=1, column=0, padx=(0, 16), pady=(2, 10), sticky="w")

        ttk.Label(controls, text="实例", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w")
        self.instance_var = tk.StringVar(value="全部实例")
        self.instance_combo = ttk.Combobox(controls, textvariable=self.instance_var, state="readonly",
                                           values=["全部实例"], width=20)
        self.instance_combo.grid(row=1, column=1, padx=(0, 16), pady=(2, 10), sticky="w")

        self.force_var = tk.BooleanVar(value=False)
        self.no_record_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="--force（忽略当日成功标记）",
                        variable=self.force_var).grid(row=1, column=2, padx=(0, 16), sticky="w")
        ttk.Checkbutton(controls, text="--no-record（不写完成记录）",
                        variable=self.no_record_var).grid(row=1, column=3, sticky="w")

        ttk.Label(controls, text="真实执行前会二次确认；所有执行仍是 run.py 子进程，参数与 CLI 一致。",
                  style="CardMuted.TLabel").grid(row=2, column=0, columnspan=4, sticky="w")
        buttons = ttk.Frame(controls)
        buttons.grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text="开始执行", style="Primary.TButton",
                   command=self.start_run).pack(side="left")
        self.stop_run_btn = ttk.Button(buttons, text="停止当前任务", style="Danger.TButton",
                                       command=self.stop_run, state="disabled")
        self.stop_run_btn.pack(side="left", padx=(10, 0))
        self.output_meta_var = tk.StringVar(value="")

        output_card = ttk.LabelFrame(frame, text="实时输出", padding=10)
        output_card.pack(fill="both", expand=True)
        ttk.Label(output_card, textvariable=self.output_meta_var,
                  style="CardMuted.TLabel").pack(anchor="w", pady=(0, 4))
        self.output = scrolledtext.ScrolledText(output_card, wrap="word", height=20,
                                                bg="#070b16", fg=TEXT, insertbackground=TEXT,
                                                relief="flat", font=MONO)
        self.output.pack(fill="both", expand=True)
        self.output.configure(state="disabled")
        self.output.tag_configure("err", foreground="#ff9b9b")
        self.output.tag_configure("warn", foreground="#ffd18a")
        self.output.tag_configure("info", foreground="#a9c4ff")

    def _build_config(self) -> None:
        frame = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame, text="配置")
        quick = ttk.LabelFrame(frame, text="常用参数", padding=12)
        quick.pack(fill="x", pady=(0, 8))
        self.cfg_vars: dict[str, tk.Variable] = {}
        fields = [
            ("target_distance_km", "目标距离（km）"),
            ("max_runs", "最高次数 max_runs"),
            ("check_after_minutes", "开跑后首次检查（分钟）"),
            ("max_run_minutes", "总超时（分钟）"),
            ("adb_serial", "adb_serial"),
            ("mumu_index", "MuMu 实例序号"),
            ("instance_start_stagger_seconds", "错峰启动（秒）"),
        ]
        for i, (key, label) in enumerate(fields):
            row, col = divmod(i, 4)
            ttk.Label(quick, text=label, style="CardMuted.TLabel").grid(
                row=row * 2, column=col, sticky="w", padx=(0, 14), pady=(0, 2))
            var = tk.StringVar()
            self.cfg_vars[key] = var
            ttk.Entry(quick, textvariable=var, width=22).grid(
                row=row * 2 + 1, column=col, sticky="w", padx=(0, 14), pady=(0, 8))

        self.cfg_checks: dict[str, tk.BooleanVar] = {}
        check_defs = [
            ("skip_if_success_today", "当日成功后跳过"),
            ("shutdown_emulator", "跑完关闭模拟器"),
            ("close_apps", "跑完关闭 App"),
            ("refresh_window_on_start", "启动后刷新窗口"),
        ]
        for i, (key, label) in enumerate(check_defs):
            var = tk.BooleanVar(value=True)
            self.cfg_checks[key] = var
            ttk.Checkbutton(quick, text=label, variable=var).grid(
                row=4 + i // 4, column=i % 4, sticky="w", pady=(4, 0))

        ttk.Label(quick, text="run_windows（JSON 数组，空表示不使用多时间段）",
                  style="CardMuted.TLabel").grid(row=5, column=0, columnspan=4, sticky="w",
                                                 pady=(10, 2))
        self.windows_text = tk.Text(quick, height=3, bg="#0d1426", fg=TEXT,
                                    insertbackground=TEXT, relief="flat", font=MONO)
        self.windows_text.grid(row=6, column=0, columnspan=4, sticky="ew")
        ttk.Label(quick, text="instances（JSON 数组，空表示单实例）",
                  style="CardMuted.TLabel").grid(row=7, column=0, columnspan=4, sticky="w",
                                                 pady=(8, 2))
        self.instances_text = tk.Text(quick, height=4, bg="#0d1426", fg=TEXT,
                                      insertbackground=TEXT, relief="flat", font=MONO)
        self.instances_text.grid(row=8, column=0, columnspan=4, sticky="ew")
        for col in range(4):
            quick.columnconfigure(col, weight=1)

        row = ttk.Frame(quick)
        row.grid(row=9, column=0, columnspan=4, sticky="w", pady=(10, 0))
        ttk.Button(row, text="保存常用参数", style="Primary.TButton",
                   command=self.save_quick_config).pack(side="left")
        ttk.Button(row, text="重新载入", command=self.load_config_form).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="编辑完整 JSON…", command=self.open_raw_config).pack(side="left",
                                                                                padx=(8, 0))
        self.config_msg_var = tk.StringVar(value="")
        ttk.Label(quick, textvariable=self.config_msg_var,
                  style="CardMuted.TLabel").grid(row=10, column=0, columnspan=4, sticky="w",
                                                 pady=(8, 0))

    def _build_logs(self) -> None:
        frame = ttk.Frame(self.notebook, padding=4)
        self.notebook.add(frame, text="日志")
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 6))
        ttk.Label(controls, text="日志文件", style="Muted.TLabel").pack(side="left")
        self.log_var = tk.StringVar(value="")
        self.log_combo = ttk.Combobox(controls, textvariable=self.log_var, state="readonly",
                                      width=44, values=[])
        self.log_combo.pack(side="left", padx=(6, 12))
        ttk.Label(controls, text="行数", style="Muted.TLabel").pack(side="left")
        self.tail_var = tk.StringVar(value="300")
        ttk.Combobox(controls, textvariable=self.tail_var, state="readonly", width=6,
                     values=["100", "300", "800"]).pack(side="left", padx=(6, 12))
        self.auto_log_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(controls, text="运行中自动刷新", variable=self.auto_log_var).pack(side="left")
        ttk.Button(controls, text="刷新列表", command=self.refresh_logs).pack(side="left", padx=(12, 0))
        ttk.Button(controls, text="加载", command=self.load_selected_log).pack(side="left", padx=(8, 0))
        self.export_btn = ttk.Button(controls, text="打包日志与截图", command=self.export_logs)
        self.export_btn.pack(side="left", padx=(8, 0))
        self.export_meta_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.export_meta_var, style="Muted.TLabel").pack(anchor="w",
                                                                                      pady=(0, 4))
        self.log_meta_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.log_meta_var, style="Muted.TLabel").pack(anchor="w",
                                                                                   pady=(0, 4))
        self.log_output = scrolledtext.ScrolledText(frame, wrap="word", bg="#070b16", fg=TEXT,
                                                    relief="flat", font=MONO)
        self.log_output.pack(fill="both", expand=True)
        self.log_output.configure(state="disabled")
        self.log_output.tag_configure("err", foreground="#ff9b9b")
        self.log_output.tag_configure("warn", foreground="#ffd18a")
        self.log_output.tag_configure("info", foreground="#a9c4ff")

    # ------------------------------------------------------------ 状态刷新
    def _schedule(self) -> None:
        if self._closing:
            return
        self.refresh_status()
        self.root.after(2500, self._schedule)

    def _set_banner(self, text: str = "") -> None:
        if text:
            self.banner_var.set(text)
            self.banner.pack(fill="x", padx=18, pady=(0, 8), before=self.notebook)
        else:
            self.banner_var.set("")
            self.banner.pack_forget()

    def refresh_status(self) -> None:
        try:
            st = self.app.status()
        except Exception as e:  # noqa: BLE001
            self._set_banner(f"无法读取状态：{e}")
            self.conn_var.set("连接失败")
            self.conn_label.configure(fg="#ffb3b3")
            return
        self._render_status(st)

    def _render_status(self, st: dict) -> None:
        error = st.get("config_error")
        self._set_banner(error or "")
        self.conn_var.set("配置异常" if error else "在线")
        self.conn_label.configure(fg="#ffb3b3" if error else "#8ef0bd")
        self.version_var.set(f"v{st.get('version', '')}")
        cfg = st.get("config") or {}
        windows = " / ".join(f"{w.get('start')}-{w.get('end')}" for w in (cfg.get("run_windows") or []))
        summary = [
            f"目标距离：{cfg.get('target_distance_km', '—')} km",
            f"最高次数：{cfg.get('max_runs') or '不限制'}",
            f"时间段：{windows or '未配置'}",
            f"首次检查：{cfg.get('check_after_minutes', '—')} 分钟",
            f"总超时：{cfg.get('max_run_minutes', '—')} 分钟",
            f"错峰启动：{cfg.get('instance_start_stagger_seconds', '—')} 秒",
            f"AI 页面值守：{'已启用' if cfg.get('ai_watch_enabled') else '未启用'}",
        ]
        self.summary_var.set("\n".join(summary))

        job = st.get("job") or {"status": "idle"}
        status = job.get("status", "idle")
        running = status == "running"
        status_text = {"running": "运行中", "succeeded": "成功", "failed": "失败",
                       "stopped": "已停止", "idle": "空闲"}.get(status, status)
        self.job_status_var.set(status_text)
        self.job_title_var.set(job.get("title") or "—")
        self.job_started_var.set(job.get("started_at") or "—")
        self.job_ended_var.set(job.get("ended_at") or "—")
        self.job_exit_var.set(str(job["exit_code"]) if job.get("exit_code") is not None else "—")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.stop_run_btn.configure(state="normal" if running else "disabled")
        if job.get("id") != self._last_job_id or len(job.get("lines") or []) != self._last_job_lines:
            self._last_job_id = job.get("id")
            self._last_job_lines = len(job.get("lines") or [])
            self._render_lines(self.output, job.get("lines") or [],
                               "（尚未启动任务；点击“开始执行”后这里会实时显示 run.py 输出）")
            if running:
                self.output_meta_var.set(f"{job.get('title', '')} · 运行中")
            elif job.get("id"):
                self.output_meta_var.set(f"{job.get('title', '')} · {status_text} · 退出码 {job.get('exit_code')}")
            else:
                self.output_meta_var.set("")

        # 实例状态
        for item in self.instance_tree.get_children():
            self.instance_tree.delete(item)
        instances = st.get("instances") or []
        names = ["全部实例"]
        for inst in instances:
            names.append(str(inst.get("name")))
            success = inst.get("last_success") or {}
            maxr = inst.get("max_reached") or {}
            lock = inst.get("lock") or {}
            self.instance_tree.insert("", "end", values=(
                inst.get("name", ""),
                inst.get("adb_serial") or "—",
                f"是（{success.get('date')}）" if success.get("today") else "否",
                f"{maxr.get('count')}/{maxr.get('max')}" if maxr else "—",
                f"有（{lock.get('age_seconds')}s）" if lock else "无",
            ))
        if list(self.instance_combo["values"]) != names:
            selected = self.instance_var.get()
            self.instance_combo["values"] = names
            self.instance_var.set(selected if selected in names else "全部实例")

        latest = st.get("latest_run")
        if latest:
            lines = [
                f"日志：{latest.get('file', '—')}",
                f"修改：{latest.get('modified', '—')}",
                f"目标：{latest.get('target_km', '—')} km",
                f"完成：{latest.get('done_km', '—')} km",
                f"已跑次数：{latest.get('run_count', '—')}",
                f"退出码：{latest.get('exit_code', '—')}",
            ]
            self.latest_var.set("\n".join(lines))
            errors = latest.get("errors") or []
            self.latest_errors.configure(text="\n".join(errors[:3]))
        else:
            self.latest_var.set("暂无运行日志")
            self.latest_errors.configure(text="")

        if running and self.auto_log_var.get() and self.notebook.index("current") == 3:
            self.load_selected_log()

    def _render_lines(self, widget: scrolledtext.ScrolledText, lines: list[str], empty: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if not lines:
            widget.insert("1.0", empty)
        else:
            for line in lines:
                text = str(line)
                tag = None
                if "[ERROR]" in text:
                    tag = "err"
                elif "[WARNING]" in text:
                    tag = "warn"
                elif "[INFO]" in text:
                    tag = "info"
                if tag:
                    widget.insert("end", text + "\n", tag)
                else:
                    widget.insert("end", text + "\n")
            widget.see("end")
        widget.configure(state="disabled")

    # ------------------------------------------------------------ 执行
    def start_run(self) -> None:
        mode = RUN_MODE_LABELS.get(self.mode_var.get())
        if not mode:
            return
        if mode == "now":
            ok = messagebox.askyesno(
                "确认真实跑步",
                "这会启动模拟器、打开两个 App 并真实开始跑步。\n请确认当前不是上课/考试等需要手动使用手机的时段。\n\n继续？",
                parent=self.root)
            if not ok:
                return
        instance = self.instance_var.get()
        if instance == "全部实例":
            instance = None
        try:
            self.app.start_run(mode, force=self.force_var.get(),
                               no_record=self.no_record_var.get(), instance=instance)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("启动失败", str(e), parent=self.root)
            return
        self.notebook.select(1)
        self.refresh_status()

    def stop_run(self) -> None:
        if not messagebox.askyesno("停止任务", "将强制结束当前 run.py 子进程（含并行子进程）。\n继续？",
                                   parent=self.root):
            return

        def worker():
            try:
                self.app.stop_run()
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.root.after(0, lambda: messagebox.showerror("停止失败", err, parent=self.root))
            self.root.after(0, self.refresh_status)

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ 配置
    def load_config_form(self) -> None:
        try:
            raw = self.app.raw_config()
        except Exception as e:  # noqa: BLE001
            self.config_msg_var.set(f"读取配置失败：{e}")
            return
        for key, var in self.cfg_vars.items():
            value = raw.get(key)
            var.set("" if value is None else str(value))
        for key, var in self.cfg_checks.items():
            var.set(bool(raw.get(key, True)))
        self.windows_text.delete("1.0", "end")
        self.windows_text.insert("1.0", json.dumps(raw.get("run_windows") or [], ensure_ascii=False, indent=2))
        self.instances_text.delete("1.0", "end")
        self.instances_text.insert("1.0", json.dumps(raw.get("instances") or [], ensure_ascii=False, indent=2))
        self.config_msg_var.set("")

    def _collect_quick_fields(self) -> dict:
        fields = {key: var.get() for key, var in self.cfg_vars.items()}
        fields.update({key: var.get() for key, var in self.cfg_checks.items()})
        fields["run_windows"] = self.windows_text.get("1.0", "end")
        fields["instances"] = self.instances_text.get("1.0", "end")
        return fields

    def save_quick_config(self) -> None:
        try:
            raw = self.app.raw_config()
            cfg = merge_quick_config(raw, self._collect_quick_fields())
            result = self.app.save_config(cfg)
            self.config_msg_var.set("配置已保存" + ("，已生成备份" if result.get("backup") else ""))
            self.load_config_form()
            self.refresh_status()
        except Exception as e:  # noqa: BLE001
            self.config_msg_var.set(f"保存失败：{e}")
            messagebox.showerror("配置保存失败", str(e), parent=self.root)

    def open_raw_config(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("完整配置 JSON")
        win.geometry("820x620")
        win.configure(bg=BG)
        win.transient(self.root)
        win.grab_set()
        text = scrolledtext.ScrolledText(win, bg="#070b16", fg=TEXT, insertbackground=TEXT,
                                         font=MONO, relief="flat")
        text.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        try:
            text.insert("1.0", json.dumps(self.app.raw_config(), ensure_ascii=False, indent=2))
        except Exception as e:  # noqa: BLE001
            text.insert("1.0", f"// 读取失败：{e}")

        def save_raw():
            try:
                cfg = json.loads(text.get("1.0", "end"))
                if not isinstance(cfg, dict):
                    raise ValueError("配置必须是 JSON 对象")
                result = self.app.save_config(cfg)
                self.config_msg_var.set("完整 JSON 已保存" + ("，已生成备份" if result.get("backup") else ""))
                win.destroy()
                self.load_config_form()
                self.refresh_status()
            except Exception as e:  # noqa: BLE001
                messagebox.showerror("保存失败", str(e), parent=win)

        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="保存完整 JSON", style="Primary.TButton",
                   command=save_raw).pack(side="left")
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="left", padx=(8, 0))

    # ------------------------------------------------------------ 日志
    def refresh_logs(self) -> None:
        try:
            logs = self.app.list_logs(limit=100)
        except Exception as e:  # noqa: BLE001
            self.log_meta_var.set(f"读取日志列表失败：{e}")
            return
        names = [row["name"] for row in logs]
        current = self.log_var.get()
        self.log_combo["values"] = names
        if current in names:
            self.log_var.set(current)
        elif names:
            self.log_var.set(names[0])
        else:
            self.log_var.set("")

    def load_selected_log(self) -> None:
        name = self.log_var.get()
        if not name:
            self._render_lines(self.log_output, [], "（暂无可查看日志）")
            self.log_meta_var.set("")
            return
        try:
            tail = int(self.tail_var.get() or "300")
        except ValueError:
            tail = 300
        try:
            data = self.app.read_log(name, tail=tail)
            self._render_lines(self.log_output, data.get("lines") or [], "（日志为空）")
            self.log_meta_var.set(f"{name} · {data.get('size', 0) / 1024:.1f} KB")
        except Exception as e:  # noqa: BLE001
            self._render_lines(self.log_output, [f"读取失败：{e}"], "")

    def export_logs(self) -> None:
        if not messagebox.askyesno(
                "打包日志与截图",
                "将把 logs/ 下的运行日志、AI/Web 日志、证据截图和少量状态文件打成 zip。\n"
                "压缩包保存在 logs/exports 下（不会包含 config.json 或密钥）。\n\n继续？",
                parent=self.root):
            return
        self.export_btn.configure(state="disabled")
        self.export_meta_var.set("正在打包…（含截图时可能需要几秒）")

        def worker():
            try:
                result = self.app.export_logs()
                self.root.after(0, lambda: self._export_done(result, None))
            except Exception as e:  # noqa: BLE001
                err = str(e)
                self.root.after(0, lambda: self._export_done(None, err))

        threading.Thread(target=worker, daemon=True).start()

    def _export_done(self, result: dict | None, error: str | None) -> None:
        self.export_btn.configure(state="normal")
        if error:
            self.export_meta_var.set(f"打包失败：{error}")
            messagebox.showerror("打包失败", error, parent=self.root)
            return
        assert result is not None
        size_mb = result["archive_bytes"] / 1048576
        self.export_meta_var.set(
            f"已生成：{result['path']}（{result['files']} 个文件，{size_mb:.1f} MB）")
        self.refresh_logs()
        messagebox.showinfo(
            "打包完成",
            f"压缩包已生成：\n{result['path']}\n\n"
            f"文件数：{result['files']}\n"
            f"原始大小：{result['source_bytes'] / 1048576:.1f} MB\n"
            f"压缩后：{size_mb:.1f} MB",
            parent=self.root)

    def _on_tab_changed(self) -> None:
        if self.notebook.index("current") == 3:
            self.refresh_logs()
            self.load_selected_log()

    # ------------------------------------------------------------ 关闭
    def on_close(self) -> None:
        job = self.app.jobs.snapshot()
        if job.get("status") == "running":
            if not messagebox.askyesno("退出控制台", "当前任务仍在运行；退出将同时停止任务。\n继续退出？",
                                       parent=self.root):
                return
        self._closing = True
        try:
            self.app.jobs.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()


def launch(config_path: Path = DEFAULT_CONFIG, root_dir: Path = PROJECT_ROOT) -> int:
    """启动桌面控制台；无图形环境时返回错误码。"""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"无法启动桌面控制台（没有可用图形环境）：{e}", file=sys.stderr)
        return 1
    app = App(config_path=config_path, root=root_dir)
    DesktopConsole(root, app)
    root.mainloop()
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="校园跑值守桌面控制台（补充入口）")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()
    return launch(Path(args.config))


if __name__ == "__main__":
    sys.exit(main())
