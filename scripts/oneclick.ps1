# ============================================================
# 校园跑值守一键入口（由 scripts\一键值守.cmd 双击调用）
#
# 流程：单实例检查 -> 环境自检（含 MuMu 自动拉起）-> 执行 run.py --now
#       -> 结果判定 -> 摘要写入 logs\oneclick\result_*.txt
#
# 约定：不修改 run.py / config.json；结果只写日志（不弹窗、不外发告警）。
# 调试参数（双击入口不会传）：
#   -CheckOnly        只做环境自检，不执行跑步（用于连通性/断连演练）
#   -ParseLog <path>  只解析已有运行日志并打印摘要（用于验证摘要逻辑）
# ============================================================

param(
    [switch]$CheckOnly,
    [string]$ParseLog = ""
)

$ErrorActionPreference = "Continue"

$root       = Split-Path -Parent $PSScriptRoot
$python     = Join-Path $root ".venv\Scripts\python.exe"
$runpy      = Join-Path $root "run.py"
$cfgPath    = Join-Path $root "config.json"
$logsDir    = Join-Path $root "logs"
$oneDir     = Join-Path $logsDir "oneclick"
$shotsDir   = Join-Path $logsDir "shots"
$stamp      = Get-Date -Format "yyyyMMdd_HHmmss"
$entryLog   = Join-Path $oneDir ("oneclick_" + $stamp + ".log")
$resultFile = Join-Path $oneDir ("result_" + $stamp + ".txt")
$lockFile   = Join-Path $oneDir ".oneclick.lock"

New-Item -ItemType Directory -Force -Path $oneDir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONIOENCODING = "utf-8"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$script:runStart = $null
$script:exitCode = 0

function Write-Log {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Host $line
    [System.IO.File]::AppendAllText($entryLog, $line + "`r`n", $utf8)
}

function Connect-Device {
    param($Cfg)
    $adb = [string]$Cfg.adb_path
    $serial = [string]$Cfg.adb_serial
    & $adb connect $serial 2>&1 | Out-Null
    for ($i = 0; $i -lt 5; $i++) {
        $state = (& $adb -s $serial get-state 2>$null | Out-String).Trim()
        if ($state -eq "device") {
            $boot = (& $adb -s $serial shell getprop sys.boot_completed 2>$null | Out-String).Trim()
            if ($boot -eq "1") { return $true, ("设备已连接：" + $serial) }
        }
        Start-Sleep -Seconds 2
    }
    $mgr = [string]$Cfg.mumu_manager
    $idx = $Cfg.mumu_index
    if ($mgr -and (Test-Path -LiteralPath $mgr) -and ($null -ne $idx)) {
        Write-Log ("模拟器未连接，尝试自动拉起 MuMu 实例 " + $idx + "（最多等待 240 秒）...")
        & $mgr control -v $idx launch 2>&1 | Out-Null
        $deadline = (Get-Date).AddSeconds(240)
        while ((Get-Date) -lt $deadline) {
            & $adb connect $serial 2>&1 | Out-Null
            Start-Sleep -Seconds 3
            $state = (& $adb -s $serial get-state 2>$null | Out-String).Trim()
            if ($state -eq "device") {
                $boot = (& $adb -s $serial shell getprop sys.boot_completed 2>$null | Out-String).Trim()
                if ($boot -eq "1") { return $true, ("已自动拉起并连接 MuMu 实例 " + $idx + "（" + $serial + "）") }
            }
        }
        return $false, ("已尝试自动拉起 MuMu 实例 " + $idx + "，但 240 秒内未连接成功")
    }
    return $false, ("无法连接 " + $serial + "，且未配置可用的 mumu_manager 自动拉起")
}

function Test-Env {
    $issues = New-Object System.Collections.ArrayList
    $cfg = $null

    if (-not (Test-Path -LiteralPath $python)) {
        [void]$issues.Add("缺少 ".PadRight(0) + $python + "（venv 未创建或路径不对）")
    }
    else {
        $imp = (& $python -c "import maa, PIL, numpy; print('ok')" 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) {
            [void]$issues.Add("Python 依赖导入失败（maa/PIL/numpy）：" + $imp)
        }
    }

    foreach ($f in @("det.onnx", "rec.onnx", "keys.txt")) {
        $p = Join-Path $root ("assets\resource\model\ocr\" + $f)
        if (-not (Test-Path -LiteralPath $p)) { [void]$issues.Add("缺少 OCR 模型文件：" + $p) }
    }

    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        [void]$issues.Add("config.json 无法解析：" + $_.Exception.Message)
    }

    if ($null -ne $cfg) {
        $adb = [string]$cfg.adb_path
        if (-not (Test-Path -LiteralPath $adb)) {
            [void]$issues.Add("adb 不存在：" + $adb)
        }
        else {
            $ok, $msg = Connect-Device $cfg
            if (-not $ok) { [void]$issues.Add($msg) } else { Write-Log ("自检：" + $msg) }
        }
    }

    return [pscustomobject]@{ Ok = ($issues.Count -eq 0); Issues = $issues; Cfg = $cfg }
}

function Get-RunSummary {
    param([string]$LogFile, [int]$Code)
    $text = ""
    if (Test-Path -LiteralPath $LogFile) {
        $text = Get-Content -LiteralPath $LogFile -Raw -Encoding UTF8
    }
    $finalAll  = [regex]::Matches($text, "全部完成：距离 ([0-9.]+) km，配速 ([^，\r\n]+)")
    $targetCur = [regex]::Matches($text, "本次结束距离[：:]\s*([0-9.]+) km")
    $targetOld = [regex]::Matches($text, "距离阈值 ([0-9.]+) km")
    $distAll   = [regex]::Matches($text, "当前距离：([0-9.]+) km，总时间：([0-9:]+)，平均配速：([^（\r\n]+)")
    $settleAll = [regex]::Matches($text, "结束与结算流程已完成")
    $stopAll   = [regex]::Matches($text, "停止与关闭：完成")

    $distance = ""; $pace = ""; $elapsed = ""; $target = ""
    if ($targetCur.Count -gt 0) {
        $target = $targetCur[$targetCur.Count - 1].Groups[1].Value
    }
    elseif ($targetOld.Count -gt 0) {
        $target = $targetOld[$targetOld.Count - 1].Groups[1].Value
    }
    if ($finalAll.Count -gt 0) {
        $m = $finalAll[$finalAll.Count - 1]
        $distance = $m.Groups[1].Value
        $pace = ($m.Groups[2].Value -replace "分/公里$", "").Trim()
    }
    elseif ($distAll.Count -gt 0) {
        $m = $distAll[$distAll.Count - 1]
        $distance = $m.Groups[1].Value
        $pace = ($m.Groups[3].Value -replace "分/公里$", "").Trim()
    }
    if ($distAll.Count -gt 0) {
        $elapsed = $distAll[$distAll.Count - 1].Groups[2].Value
    }

    $shots = @()
    if (Test-Path -LiteralPath $shotsDir) {
        $since = $script:runStart
        if ($null -eq $since) { $since = (Get-Date).AddHours(-1) }
        $shots = @(Get-ChildItem -LiteralPath $shotsDir -Filter "*.png" -File -ErrorAction SilentlyContinue |
                   Where-Object { $_.LastWriteTime -gt $since.AddSeconds(-5) } |
                   Sort-Object LastWriteTime)
    }

    return [pscustomobject]@{
        Ok       = (($Code -eq 0) -and ($text -match "全部完成"))
        Code     = $Code
        Distance = $distance
        Pace     = $pace
        Elapsed  = $elapsed
        Target   = $target
        Settled  = ($settleAll.Count -gt 0)
        Stopped  = ($stopAll.Count -gt 0)
        Shots    = $shots
        LogFile  = $LogFile
    }
}

function Show-Summary {
    param($Summary)
    $codeText = switch ($Summary.Code) {
        0 { "成功" }
        1 { "连接/初始化失败或异常" }
        2 { "未达标/等待超时/开跑未记录" }
        3 { "开始·结束·关闭失败" }
        5 { "已有实例在运行" }
        default { "未知" }
    }
    Write-Log ("结果：" + $(if ($Summary.Ok) { "成功" } else { "失败" }) + "；退出码 " + $Summary.Code + "（" + $codeText + "）")
    $targetText = if ($Summary.Target) { $Summary.Target + " km" } else { "未知" }
    $paceText = if ($Summary.Pace -and $Summary.Pace -ne "未知") { $Summary.Pace + " 分/公里" } else { "未知" }
    $elapsedText = if ($Summary.Elapsed) { $Summary.Elapsed } else { "未知" }
    Write-Log ("距离阈值：" + $targetText + "；最终距离：" + $Summary.Distance + " km；平均配速：" + $paceText + "；总时间：" + $elapsedText)
    Write-Log ("结算完成：" + $Summary.Settled + "；停止与关闭完成：" + $Summary.Stopped + "；本次截图：" + $Summary.Shots.Count + " 张")
    if (-not $Summary.Ok) {
        $hint = switch ($Summary.Code) {
            1 { "检查 MuMu/adb 连接与 venv 依赖后重试。" }
            2 { "查看日志最后「当前距离」与开跑 2/4 分钟抽检；不要自动重跑，避免重复提交记录。" }
            3 { "查看 logs\shots 对应阶段截图（run_prepared/campus_prepared/finish/stop）。" }
            default { "查看运行日志排查。" }
        }
        Write-Log ("失败建议：" + $hint)
    }
}

function Write-Result {
    param($Summary)
    $lines = @()
    $lines += "时间：" + (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $lines += "结果：" + $(if ($Summary.Ok) { "成功" } else { "失败" })
    $lines += "退出码：" + $Summary.Code
    $lines += "距离阈值：" + $(if ($Summary.Target) { $Summary.Target + " km" } else { "未知" })
    $lines += "最终距离：" + $Summary.Distance + " km"
    $lines += "平均配速：" + $(if ($Summary.Pace -and $Summary.Pace -ne "未知") { $Summary.Pace + " 分/公里" } else { "未知" })
    $lines += "总时间：" + $(if ($Summary.Elapsed) { $Summary.Elapsed } else { "未知" })
    $lines += "结算完成：" + $Summary.Settled
    $lines += "停止与关闭完成：" + $Summary.Stopped
    $lines += "运行日志：" + $Summary.LogFile
    $lines += "入口日志：" + $entryLog
    $lines += "本次截图（" + $Summary.Shots.Count + " 张）："
    foreach ($s in $Summary.Shots) { $lines += "  " + $s.FullName }
    [System.IO.File]::WriteAllText($resultFile, (($lines -join "`r`n") + "`r`n"), $utf8)
    Write-Log ("结果摘要：" + $resultFile)
}

# 执行一次 run.py --now：输出同时写入口日志，返回退出码（正常与重试共用，避免重复代码）
function Invoke-RunOnce {
    $script:runStart = Get-Date
    Write-Log ("开始执行：" + $python + " run.py --now（预计 16~25 分钟）")
    & $python -u $runpy --now 2>&1 | ForEach-Object {
        $line = [string]$_
        [System.IO.File]::AppendAllText($entryLog, $line + "`r`n", $utf8)
        Write-Host $line
    }
    $code = $LASTEXITCODE
    if ($null -eq $code) { $code = 1 }
    return [int]$code
}

# ---------------- 调试：仅解析已有日志 ----------------
if ($ParseLog) {
    if (-not (Test-Path -LiteralPath $ParseLog)) { Write-Host ("找不到日志：" + $ParseLog); exit 1 }
    $script:runStart = (Get-Item -LiteralPath $ParseLog).LastWriteTime.AddMinutes(-45)
    $sum = Get-RunSummary -LogFile (Resolve-Path -LiteralPath $ParseLog).Path -Code 0
    Show-Summary $sum
    exit 0
}

# ---------------- 主流程 ----------------
Write-Log "===== 校园跑值守一键执行开始 ====="
Write-Log ("项目目录：" + $root)

# 1) 单实例检查（锁文件 + 进程）
if (Test-Path -LiteralPath $lockFile) {
    $oldPid = 0
    try { $oldPid = [int]((Get-Content -LiteralPath $lockFile -Raw).Trim()) } catch { $oldPid = 0 }
    if ($oldPid -gt 0 -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Log ("已有一次值守在执行（PID " + $oldPid + "），本次不重复执行。")
        exit 5
    }
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
}
$running = @(Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -and ($_.CommandLine -match "run\.py") })
if ($running.Count -gt 0) {
    $pids = ($running | ForEach-Object { $_.ProcessId }) -join ","
    Write-Log ("已有 run.py 进程在运行（PID: " + $pids + "），本次不重复执行。")
    exit 5
}
Set-Content -LiteralPath $lockFile -Value $PID -Encoding ASCII

try {
    # 2) 环境自检
    $check = Test-Env
    if (-not $check.Ok) {
        foreach ($iss in $check.Issues) { Write-Log ("自检失败：" + $iss) }
        Write-Log "环境自检未通过：未执行任何点击、未开始跑步。"
        $script:exitCode = 1
    }
    elseif ($CheckOnly) {
        Write-Log "环境自检通过；-CheckOnly 模式：仅自检，不执行跑步。"
        $script:exitCode = 0
    }
    else {
        # 3) 执行 run.py --now（连接/初始化类失败自动重试 1 次）
        $code = Invoke-RunOnce
        if ($code -eq 1) {
            $all = ""
            try { $all = Get-Content -LiteralPath $entryLog -Raw -Encoding UTF8 } catch { }
            if ($all -match "无法连接模拟器|控制器初始化失败|资源加载失败") {
                Write-Log "检测到连接/初始化类失败，10 秒后自动重试 1 次 ..."
                Start-Sleep -Seconds 10
                $code = Invoke-RunOnce
            }
        }

        # 4) 结果判定 + 摘要
        $runLog = Join-Path $logsDir ("run_" + (Get-Date -Format "yyyyMMdd") + ".log")
        $sum = Get-RunSummary -LogFile $runLog -Code $code
        Show-Summary $sum
        Write-Result $sum
        Write-Log ("运行日志：" + $runLog)
        Write-Log ("证据截图目录：" + $shotsDir)
        $script:exitCode = $code
    }
}
finally {
    Remove-Item -LiteralPath $lockFile -Force -ErrorAction SilentlyContinue
}

Write-Log ("===== 结束，退出码 " + $script:exitCode + " =====")
exit $script:exitCode
