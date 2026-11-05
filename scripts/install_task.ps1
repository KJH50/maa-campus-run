# 注册/删除「每天固定时间运行一键入口」的 Windows 计划任务。
# 与 scripts/oneclick.ps1 复用同一套逻辑（单实例锁 / 环境自检 / 结果摘要），行为与手动入口一致。
# 注意：旧任务名 CampusRunMaa 若已注册，请先 -Uninstall 再注册新名称，避免同一时间重复触发。
param(
    [switch]$Uninstall,
    [string]$Time = "",
    [string]$TaskName = "MaaCampusRun"
)

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$entry = Join-Path $root "scripts\oneclick.ps1"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if ($Uninstall) {
    try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop; Write-Host "已删除计划任务 $TaskName" }
    catch { schtasks.exe /Delete /F /TN $TaskName | Out-Null; Write-Host "已尝试删除计划任务 $TaskName" }
    exit 0
}

if (-not $Time) {
    $cfgPath = Join-Path $root "config.json"
    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $Time = $cfg.start_time
}
if ($Time -notmatch '^\d{2}:\d{2}$') { Write-Error "时间格式应为 HH:mm，当前: $Time"; exit 1 }
if (-not (Test-Path -LiteralPath $entry)) { Write-Error "找不到一键入口脚本: $entry"; exit 1 }

$action = New-ScheduledTaskAction -Execute $powershell -Argument ('-NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $entry) -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "已注册计划任务 $TaskName：每天 $Time 运行一键入口 $entry"
