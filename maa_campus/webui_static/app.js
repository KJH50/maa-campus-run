/* 校园跑值守 Web 控制台（原生 JS，无外部依赖） */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  status: null,
  config: null,
  logName: "",
  loading: false,
};

function toast(message, kind = "ok") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.add("hidden"), 4200);
}

function showBanner(message, kind = "err") {
  const el = $("banner");
  if (!message) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = message;
  el.className = `banner ${kind === "ok" ? "ok" : ""}`;
}

async function api(path, options = {}) {
  const opts = { headers: {}, ...options };
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, { cache: "no-store", ...opts });
  let data = null;
  try {
    data = await resp.json();
  } catch (_) {
    throw new Error(`HTTP ${resp.status}: 返回内容不是 JSON`);
  }
  if (!resp.ok) {
    throw new Error(data && data.error ? data.error : `HTTP ${resp.status}`);
  }
  return data;
}

function fmtTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function fmtDuration(start, end) {
  if (!start) return "—";
  const a = new Date(start).getTime();
  const b = end ? new Date(end).getTime() : Date.now();
  if (Number.isNaN(a) || Number.isNaN(b)) return "—";
  const sec = Math.max(0, Math.round((b - a) / 1000));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m} 分 ${s} 秒` : `${s} 秒`;
}

function setPill(el, text, cls) {
  if (!el) return;
  el.textContent = text;
  el.className = `pill ${cls}`;
}

function renderTerminal(el, lines, emptyText) {
  el.replaceChildren();
  if (!lines || !lines.length) {
    el.textContent = emptyText;
    return;
  }
  const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  const frag = document.createDocumentFragment();
  for (const line of lines) {
    const span = document.createElement("span");
    const text = String(line);
    span.textContent = text + "\n";
    if (text.includes("[ERROR]")) span.className = "err";
    else if (text.includes("[WARNING]")) span.className = "warn";
    else if (text.includes("[INFO]")) span.className = "info";
    frag.appendChild(span);
  }
  el.appendChild(frag);
  if (nearBottom) el.scrollTop = el.scrollHeight;
}

function renderStatus(st) {
  state.status = st;
  const job = st.job || { status: "idle" };
  const running = job.status === "running";
  const configError = st.config_error;

  setPill($("connPill"), configError ? "配置异常" : running ? "运行中" : "在线",
    configError ? "pill-err" : running ? "pill-run" : "pill-ok");
  $("version").textContent = st.version ? `v${st.version}` : "";

  showBanner(configError || "");

  setPill($("jobPill"), running ? "运行中" : job.status === "succeeded" ? "成功" : job.status === "failed" ? "失败" : job.status === "stopped" ? "已停止" : "空闲",
    running ? "pill-run" : job.status === "succeeded" ? "pill-ok" : job.status === "failed" ? "pill-err" : "pill-idle");
  $("jobTitle").textContent = job.title || "—";
  $("jobStarted").textContent = fmtTime(job.started_at);
  $("jobEnded").textContent = fmtTime(job.ended_at);
  $("jobExit").textContent = job.exit_code === null || job.exit_code === undefined ? "—" : String(job.exit_code);
  $("stopBtn").classList.toggle("hidden", !running);
  $("stopRunBtn").classList.toggle("hidden", !running);

  const cfg = st.config || {};
  const summary = $("configSummary");
  const rows = [
    ["目标距离", cfg.target_distance_km ? `${cfg.target_distance_km} km` : "—"],
    ["最高次数", cfg.max_runs ? `${cfg.max_runs} 次` : "不限制"],
    ["时间段", Array.isArray(cfg.run_windows) && cfg.run_windows.length
      ? cfg.run_windows.map((w) => `${w.start}-${w.end}`).join(" / ") : "未配置"],
    ["首次检查", cfg.check_after_minutes ? `${cfg.check_after_minutes} 分钟` : "—"],
    ["总超时", cfg.max_run_minutes ? `${cfg.max_run_minutes} 分钟` : "—"],
    ["错峰启动", cfg.instance_start_stagger_seconds !== undefined ? `${cfg.instance_start_stagger_seconds} 秒` : "—"],
    ["AI 页面值守", cfg.ai_watch_enabled ? "已启用" : "未启用"],
  ];
  summary.replaceChildren();
  for (const [k, v] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    summary.append(dt, dd);
  }

  // 实例状态表
  const box = $("instanceTable");
  box.replaceChildren();
  const instances = st.instances || [];
  if (!instances.length) {
    box.textContent = "无实例配置（单实例模式）";
  } else {
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>实例</th><th>adb</th><th>今日成功</th><th>最高次数</th><th>运行锁</th></tr></thead>";
    const tbody = document.createElement("tbody");
    for (const inst of instances) {
      const tr = document.createElement("tr");
      const cells = [
        inst.name,
        inst.adb_serial || "—",
        inst.last_success && inst.last_success.today ? `是（${inst.last_success.date}）` : "否",
        inst.max_reached ? `${inst.max_reached.count}/${inst.max_reached.max}` : "—",
        inst.lock ? `有（${inst.lock.age_seconds}s）` : "无",
      ];
      for (const text of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    box.appendChild(table);
  }

  // 实例下拉框
  const sel = $("instanceSelect");
  const prev = sel.value;
  const names = ["", ...instances.map((i) => i.name)];
  if (Array.from(sel.options).map((o) => o.value).join("|") !== names.join("|")) {
    sel.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "全部实例（按配置）";
    sel.appendChild(all);
    for (const inst of instances) {
      const opt = document.createElement("option");
      opt.value = inst.name;
      opt.textContent = inst.name;
      sel.appendChild(opt);
    }
  }
  if (names.includes(prev)) sel.value = prev;

  // 最近一次运行
  const latest = $("latestRun");
  latest.replaceChildren();
  const run = st.latest_run;
  const runRows = run ? [
    ["日志文件", run.file],
    ["修改时间", fmtTime(run.modified)],
    ["目标距离", run.target_km ? `${run.target_km} km` : "—"],
    ["完成距离", run.done_km ? `${run.done_km} km` : "—"],
    ["已跑次数", run.run_count !== undefined ? `${run.run_count} 次` : "—"],
    ["退出码", run.exit_code !== undefined ? String(run.exit_code) : "—"],
  ] : [["状态", "暂无运行日志"]];
  for (const [k, v] of runRows) {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    latest.append(dt, dd);
  }
  const errBox = $("latestErrors");
  errBox.replaceChildren();
  for (const err of (run && run.errors) || []) {
    const div = document.createElement("div");
    div.textContent = err;
    errBox.appendChild(div);
  }

  // 实时输出
  const out = $("jobOutput");
  if (job.status !== "idle") {
    renderTerminal(out, job.lines || [], "（任务已启动，等待输出…）");
    $("outputMeta").textContent = `${job.title || ""} · ${running ? "运行中" : "已结束"} · 耗时 ${fmtDuration(job.started_at, job.ended_at)}`;
  } else {
    $("outputMeta").textContent = "";
  }

  if (!state.loading) {
    loadLogs().catch(() => {});
  }
}

async function loadStatus() {
  try {
    const st = await api("/api/status");
    renderStatus(st);
  } catch (e) {
    setPill($("connPill"), "连接失败", "pill-err");
    showBanner(`无法连接后端：${e.message}`);
  }
}

async function loadConfig() {
  try {
    const data = await api("/api/config");
    state.config = data.config || {};
    $("configPath").textContent = state.status ? state.status.config_path : "";
    $("rawConfig").value = JSON.stringify(state.config, null, 2);
    fillQuick(state.config);
  } catch (e) {
    toast(`读取配置失败：${e.message}`, "err");
  }
}

function fillQuick(cfg) {
  $("qTargetDistance").value = cfg.target_distance_km ?? "";
  $("qMaxRuns").value = cfg.max_runs ?? 0;
  $("qCheckAfter").value = cfg.check_after_minutes ?? "";
  $("qMaxRunMinutes").value = cfg.max_run_minutes ?? "";
  $("qAdbSerial").value = cfg.adb_serial ?? "";
  $("qMumuIndex").value = cfg.mumu_index ?? "";
  $("qStagger").value = cfg.instance_start_stagger_seconds ?? "";
  $("qSkipIfSuccess").checked = cfg.skip_if_success_today !== false;
  $("qShutdownEmulator").checked = cfg.shutdown_emulator !== false;
  $("qCloseApps").checked = cfg.close_apps !== false;
  $("qRefreshWindow").checked = cfg.refresh_window_on_start !== false;
  $("qRunWindows").value = JSON.stringify(cfg.run_windows || [], null, 2);
  $("qInstances").value = JSON.stringify(cfg.instances || [], null, 2);
}

function parseJsonField(id, label) {
  const text = $(id).value.trim();
  if (!text) return [];
  try {
    const value = JSON.parse(text);
    if (!Array.isArray(value)) throw new Error(`${label} 必须是 JSON 数组`);
    return value;
  } catch (e) {
    throw new Error(`${label} 解析失败：${e.message}`);
  }
}

function setOrDelete(cfg, key, value) {
  if (value === "" || value === null || value === undefined) {
    delete cfg[key];
  } else {
    cfg[key] = value;
  }
}

function applyQuickToConfig() {
  let cfg;
  try {
    cfg = JSON.parse($("rawConfig").value || "{}");
  } catch (e) {
    throw new Error(`完整 JSON 当前不是合法 JSON：${e.message}`);
  }
  if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) throw new Error("配置必须是 JSON 对象");
  const valueOrNull = (id) => ($(id).value === "" ? null : Number($(id).value));
  setOrDelete(cfg, "target_distance_km", valueOrNull("qTargetDistance"));
  cfg.max_runs = valueOrNull("qMaxRuns") ?? 0;
  setOrDelete(cfg, "check_after_minutes", valueOrNull("qCheckAfter"));
  setOrDelete(cfg, "max_run_minutes", valueOrNull("qMaxRunMinutes"));
  cfg.adb_serial = $("qAdbSerial").value.trim();
  setOrDelete(cfg, "mumu_index", valueOrNull("qMumuIndex"));
  setOrDelete(cfg, "instance_start_stagger_seconds", valueOrNull("qStagger"));
  cfg.skip_if_success_today = $("qSkipIfSuccess").checked;
  cfg.shutdown_emulator = $("qShutdownEmulator").checked;
  cfg.close_apps = $("qCloseApps").checked;
  cfg.refresh_window_on_start = $("qRefreshWindow").checked;
  cfg.run_windows = parseJsonField("qRunWindows", "run_windows");
  cfg.instances = parseJsonField("qInstances", "instances");
  $("rawConfig").value = JSON.stringify(cfg, null, 2);
  return cfg;
}

async function saveConfig(config) {
  const data = await api("/api/config", { method: "POST", body: { config } });
  toast(`配置已保存${data.backup ? "（已备份）" : ""}`, "ok");
  await loadStatus();
  await loadConfig();
}

async function saveQuick() {
  try {
    await saveConfig(applyQuickToConfig());
  } catch (e) {
    toast(`保存失败：${e.message}`, "err");
    showBanner(`配置保存失败：${e.message}`);
  }
}

async function saveRaw() {
  try {
    const cfg = JSON.parse($("rawConfig").value || "{}");
    if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) throw new Error("配置必须是 JSON 对象");
    await saveConfig(cfg);
  } catch (e) {
    toast(`保存失败：${e.message}`, "err");
    showBanner(`配置保存失败：${e.message}`);
  }
}

function confirmDialog(title, text) {
  return new Promise((resolve) => {
    const dialog = $("confirmDialog");
    $("confirmTitle").textContent = title;
    $("confirmText").textContent = text;
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.returnValue = "cancel";
    dialog.showModal();
  });
}

async function startRun(mode) {
  if (mode === "now") {
    const ok = await confirmDialog("确认真实跑步？",
      "这会启动模拟器、打开两个 App 并真实开始跑步（校园跑记录可能被提交）。\n请确认当前不是上课/考试等需要手动使用手机的时段。");
    if (!ok) return;
  }
  try {
    const job = await api("/api/run", {
      method: "POST",
      body: {
        mode,
        force: $("forceCheck").checked,
        no_record: $("noRecordCheck").checked,
        instance: $("instanceSelect").value || null,
      },
    });
    toast(`已启动：${job.job ? job.job.title : mode}`, "ok");
    switchTab("run");
    await loadStatus();
  } catch (e) {
    toast(`启动失败：${e.message}`, "err");
    showBanner(`启动失败：${e.message}`);
  }
}

async function stopRun() {
  const ok = await confirmDialog("停止当前任务？", "将强制结束当前 run.py 子进程（含并行子进程）。已提交的跑步记录不会撤回。");
  if (!ok) return;
  try {
    await api("/api/run/stop", { method: "POST", body: {} });
    toast("已请求停止任务", "ok");
    await loadStatus();
  } catch (e) {
    toast(`停止失败：${e.message}`, "err");
  }
}

async function loadLogs() {
  try {
    const data = await api("/api/logs");
    const select = $("logSelect");
    const current = state.logName || select.value;
    const names = (data.logs || []).map((x) => x.name);
    if (Array.from(select.options).map((o) => o.value).join("|") !== names.join("|")) {
      select.replaceChildren();
      for (const row of data.logs || []) {
        const opt = document.createElement("option");
        opt.value = row.name;
        opt.textContent = `${row.name}（${(row.size / 1024).toFixed(1)} KB）`;
        select.appendChild(opt);
      }
    }
    if (names.includes(current)) select.value = current;
    state.logName = select.value;
  } catch (e) {
    // 状态轮询失败时静默，避免刷屏
  }
}

async function loadLogView() {
  const name = $("logSelect").value;
  const tail = Number($("tailSelect").value || 300);
  if (!name) {
    $("logOutput").textContent = "（暂无可查看日志）";
    return;
  }
  try {
    const data = await api(`/api/logs/view?name=${encodeURIComponent(name)}&tail=${tail}`);
    renderTerminal($("logOutput"), data.lines || [], "（日志为空）");
    $("logMeta").textContent = `${name} · ${(data.size / 1024).toFixed(1)} KB`;
    state.logName = name;
    if ($("autoRefreshLog").checked) loadLogs().catch(() => {});
  } catch (e) {
    $("logOutput").textContent = `读取失败：${e.message}`;
    $("logMeta").textContent = "";
  }
}

async function exportLogs() {
  const btn = $("exportBtn");
  const result = $("exportResult");
  btn.disabled = true;
  result.textContent = "正在打包…（含截图时可能需要几秒）";
  try {
    const data = await api("/api/export", { method: "POST", body: {} });
    const info = data.export;
    result.replaceChildren();
    result.appendChild(document.createTextNode(
      `已生成：${info.files} 个文件，${(info.archive_bytes / 1048576).toFixed(1)} MB `));
    const link = document.createElement("a");
    link.href = info.download_url;
    link.className = "link";
    link.textContent = "下载 ZIP";
    result.appendChild(link);
    toast("日志/截图打包完成", "ok");
    await loadLogs().catch(() => {});
  } catch (e) {
    result.textContent = `打包失败：${e.message}`;
    toast(`打包失败：${e.message}`, "err");
  } finally {
    btn.disabled = false;
  }
}

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name === "logs") {
    loadLogs().then(loadLogView).catch(() => {});
  }
}

function bind() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("gotoRunBtn").addEventListener("click", () => switchTab("run"));
  $("refreshBtn").addEventListener("click", () => {
    loadStatus();
    loadLogs().catch(() => {});
  });
  $("runBtn").addEventListener("click", () => startRun($("modeSelect").value));
  $("stopBtn").addEventListener("click", stopRun);
  $("stopRunBtn").addEventListener("click", stopRun);
  $("saveQuickBtn").addEventListener("click", saveQuick);
  $("saveRawBtn").addEventListener("click", saveRaw);
  $("reloadConfigBtn").addEventListener("click", loadConfig);
  $("revertRawBtn").addEventListener("click", loadConfig);
  $("loadLogBtn").addEventListener("click", loadLogView);
  $("exportBtn").addEventListener("click", exportLogs);
  $("logSelect").addEventListener("change", () => { state.logName = $("logSelect").value; loadLogView(); });
  $("tailSelect").addEventListener("change", loadLogView);
  $("autoRefreshLog").addEventListener("change", () => {
    if ($("autoRefreshLog").checked) loadLogView();
  });
}

async function init() {
  bind();
  const tab = new URLSearchParams(window.location.search).get("tab");
  if (["overview", "run", "config", "logs"].includes(tab)) switchTab(tab);
  await loadStatus();
  await loadConfig();
  await loadLogs();
  setInterval(loadStatus, 2500);
  setInterval(() => {
    const running = state.status && state.status.job && state.status.job.status === "running";
    if (running && $("autoRefreshLog").checked && document.getElementById("tab-logs").classList.contains("active")) {
      loadLogView();
    }
  }, 3500);
}

init().catch((e) => {
  setPill($("connPill"), "初始化失败", "pill-err");
  showBanner(`初始化失败：${e.message}`);
});
