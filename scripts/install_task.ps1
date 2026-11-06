# 注册/删除「每天固定时间运行」的 Windows 计划任务。
# - 未配置 run_window：在 start_time 运行一键入口（scripts\oneclick.ps1，行为与手动入口一致）。
# - 配置 run_window：在区间起点启动 run.py（不带 --now），由脚本在区间内随机时间执行。
# 注意：旧任务名 CampusRunMaa 若已注册，请先 -Uninstall 再注册新名称，避免同一时间重复触发。
param(
    [switch]$Uninstall,
    [string]$Time = "",
    [string]$TaskName = "MaaCampusRun"
)

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$entry = Join-Path $root "scripts\oneclick.ps1"
$runPy = Join-Path $root "run.py"
$cfgPath = Join-Path $root "config.json"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if ($Uninstall) {
    try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop; Write-Host "已删除计划任务 $TaskName" }
    catch { schtasks.exe /Delete /F /TN $TaskName | Out-Null; Write-Host "已尝试删除计划任务 $TaskName" }
    exit 0
}

$cfg = $null
if (Test-Path -LiteralPath $cfgPath) {
    try { $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { Write-Error "无法读取 config.json：$_"; exit 1 }
}

$windowStart = ""
$windowEnd = ""
$windowCount = 0
if ($cfg -and $cfg.PSObject.Properties.Name -contains 'run_window' -and $cfg.run_window) {
    $windowStart = [string]$cfg.run_window.start
    $windowEnd = [string]$cfg.run_window.end
    $windowCount = 1
}
elseif ($cfg -and $cfg.PSObject.Properties.Name -contains 'run_windows' -and $cfg.run_windows) {
    $starts = @($cfg.run_windows | ForEach-Object { [string]$_.start } | Sort-Object)
    $ends = @($cfg.run_windows | ForEach-Object { [string]$_.end } | Sort-Object)
    if ($starts.Count -gt 0) {
        $windowCount = $starts.Count
        $windowStart = $starts[0]
        $windowEnd = $ends[$ends.Count - 1]
    }
}

if (-not $Time) {
    if ($windowStart) { $Time = $windowStart }
    elseif ($cfg) { $Time = [string]$cfg.start_time }
    else { $Time = "07:00" }
}
if ($Time -notmatch '^\d{2}:\d{2}$') { Write-Error "时间格式应为 HH:mm，当前: $Time"; exit 1 }

if ($windowStart) {
    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python)) { $python = "python" }
    $action = New-ScheduledTaskAction -Execute $python -Argument ('"{0}"' -f $runPy) -WorkingDirectory $root
}
else {
    if (-not (Test-Path -LiteralPath $entry)) { Write-Error "找不到一键入口脚本: $entry"; exit 1 }
    $action = New-ScheduledTaskAction -Execute $powershell -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $entry) -WorkingDirectory $root
}

$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

if ($windowStart) {
    if ($windowCount -gt 1) {
        Write-Host "已注册计划任务 $TaskName：每天 $Time 启动 run.py，并按配置的 $windowCount 个时间段分别随机执行（最早 $windowStart，最晚 $windowEnd 结束）"
    }
    else {
        Write-Host "已注册计划任务 $TaskName：每天 $Time 启动 run.py，并在区间 $windowStart ~ $windowEnd 内按随机时间执行"
    }
}
else {
    Write-Host "已注册计划任务 $TaskName：每天 $Time 运行一键入口 $entry"
}
