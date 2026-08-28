# =============================================================================
#  菟菚 QQ bot 守护脚本 (watchdog.ps1)
# =============================================================================
#  用途：常驻后台，监控 bot.py 与 NapCat(WS 3001) 的健康状态，
#        崩溃/掉线时自动拉起，防止重复实例，并记录日志与状态。
#
#  用法（在 D:\DSH\TZtuzhan 目录下）：
#     powershell -ExecutionPolicy Bypass -File watchdog.ps1            # 常驻守护
#     powershell -ExecutionPolicy Bypass -File watchdog.ps1 -RunOnce   # 自检一次后退出
#     powershell -ExecutionPolicy Bypass -File watchdog.ps1 -WithNapCat # 连 NapCat 也守护(提权)
#
#  建议：把本脚本也加入 start-all.bat 之后运行，或另开一个窗口常驻。
# =============================================================================
param(
    [switch]$RunOnce,        # 只自检一轮就退出（用于定时任务/手动检查）
    [switch]$WithNapCat,     # 同时守护 NapCat（UAC 提权拉起，慎用）
    [int]$Interval = 15      # 检查间隔（秒）
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$DataDir = Join-Path $Root 'data'
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$BotPy = Join-Path $Root 'bot.py'
$Log = Join-Path $DataDir 'watchdog.log'
$StateFile = Join-Path $DataDir 'watchdog_state.json'   # 守护脚本自身状态
$BotPidFile = Join-Path $DataDir 'bot.pid'              # bot 主进程 pid（供外部查询/清理）
$NapcatLauncher = Join-Path $Root 'Napcat\NapCat.Shell.Windows.Node\napcat\launcher.bat'

if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Path $DataDir -Force | Out-Null }

# ---- 防重复：用 PID 文件记录守护脚本进程，进程存活才算"有守护在跑" ----
# 比文件句柄独占更可靠：异常退出后不会残留死锁
$lockPath = Join-Path $DataDir 'watchdog.pid'
function Test-WatchdogRunning {
    if (-not (Test-Path $lockPath)) { return $false }
    try {
        $rpid = [int](Get-Content $lockPath -Raw -ErrorAction SilentlyContinue).Trim()
        $p = Get-Process -Id $rpid -ErrorAction SilentlyContinue
        if ($p -and $p.ProcessName -match 'powershell|pwsh') { return $true }
    } catch {}
    return $false
}
if (Test-WatchdogRunning -and -not $RunOnce) {
    Write-Host "[watchdog] 已有守护脚本在运行，退出。" -ForegroundColor Yellow
    exit 0
}
# 写入当前 pid 作为锁
try { $PID | Set-Content -Path $lockPath -Encoding UTF8 } catch {}

# ---- 日志助手 ----
function Log([string]$msg, [string]$color = 'Gray') {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] $msg"
    Write-Host $line -ForegroundColor $color
    try { Add-Content -Path $Log -Value $line -Encoding UTF8 } catch {}
}

# ---- 写状态文件（供 check-bot.ps1 / webui / 外部读取）----
function Write-State([hashtable]$extra = @{}) {
    $state = @{
        pid        = $PID
        started    = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        checked    = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        bot_running = $false
        napcat_ws   = $false
    }
    foreach ($k in $extra.Keys) { $state[$k] = $extra[$k] }
    try {
        $state | ConvertTo-Json | Set-Content -Path $StateFile -Encoding UTF8
    } catch {}
}

# ---- 检测 bot.py 是否在运行 ----
function Get-BotProcesses {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'bot\.py' }
}

# ---- 启动 bot.py（只在没有运行实例时）----
function Start-Bot {
    $bots = @(Get-BotProcesses)
    if ($bots.Count -gt 0) {
        Log "[bot] 已在运行 (PID: $($bots[0].ProcessId))，跳过启动" 'Cyan'
        return $bots[0].ProcessId
    }
    if (-not (Test-Path $VenvPy)) {
        Log "[bot] ✗ 找不到 $VenvPy，检查 venv" 'Red'
        return $null
    }
    Log "[bot] 启动 bot.py ..." 'Cyan'
    try {
        $proc = Start-Process -FilePath $VenvPy -ArgumentList "-X utf8 $BotPy" `
            -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $DataDir 'bot.out.log') `
            -RedirectStandardError (Join-Path $DataDir 'bot.err.log') `
            -PassThru
        Start-Sleep -Seconds 1
        # 记录主 pid
        $proc.Id | Set-Content -Path $BotPidFile -Encoding UTF8
        Log "[bot] ✓ 已启动 (PID: $($proc.Id))" 'Green'
        return $proc.Id
    } catch {
        Log "[bot] ✗ 启动失败: $($_.Exception.Message)" 'Red'
        return $null
    }
}

# ---- 停止 bot.py（守护脚本要求退出时调用，避免残留）----
function Stop-Bot {
    $bots = @(Get-BotProcesses)
    if ($bots.Count -eq 0) { return }
    Log "[bot] 停止 $($bots.Count) 个进程 ..." 'Yellow'
    $bots | ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
    Start-Sleep -Seconds 1
}

# ---- NapCat 是否在线：判据 = 3001 端口在监听（WS 服务端）或旧版 node server.js 进程 ----
function Test-Napcat {
    $port = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue
    if ($port) { return $true }
    # 兼容旧版：node server.js 是 NapCat 主进程
    $node = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'server\.js' }
    if ($node) { return $true }
    return $false
}

# ---- 启动 NapCat（可选，需要管理员/会弹 UAC）----
function Start-Napcat {
    if (-not (Test-Path $NapcatLauncher)) {
        Log "[napcat] ✗ 找不到 launcher.bat" 'Red'
        return
    }
    Log "[napcat] 尝试拉起 launcher.bat（需管理员，可能弹 UAC）..." 'Yellow'
    try {
        Start-Process -FilePath 'cmd.exe' `
            -ArgumentList "/c chcp 65001 >nul & cd /d `"$(Split-Path $NapcatLauncher)`" & launcher.bat" `
            -WorkingDirectory (Split-Path $NapcatLauncher)
    } catch {
        Log "[napcat] ✗ 启动失败: $($_.Exception.Message)" 'Red'
    }
}

# ---- 主逻辑（单轮自检 + 必要的拉起）----
function Invoke-Guard {
    $report = @{}

    # ① bot.py
    $bots = @(Get-BotProcesses)
    $conn = @(Get-NetTCPConnection -LocalPort 3001 -State Established -ErrorAction SilentlyContinue)
    if ($bots.Count -eq 0) {
        Log '[guard] bot 未运行，拉起 ...' 'Yellow'
        $report.bot_running = $false
        Start-Bot | Out-Null
        Start-Sleep -Seconds 3   # 等它连上
    } elseif ($conn.Count -gt 1) {
        Log "[guard] ⚠️ 检测到 $($conn.Count) 条 WS 连接（疑似重复实例）——清理多余进程 ..." 'Yellow'
        $report.bot_running = $true
        $report.dup_ws = $conn.Count
        Stop-Bot | Out-Null
        Start-Bot | Out-Null
    } else {
        Log "[guard] bot 正常 (PID: $($bots[0].ProcessId), WS: $($conn.Count) 条)" 'Green'
        $report.bot_running = $true
    }

    # ② NapCat
    $nap = Test-Napcat
    $report.napcat_ws = $nap
    if (-not $nap) {
        Log '[guard] ⚠️ NapCat (WS 3001) 未运行' 'Yellow'
        if ($WithNapCat) {
            Start-Napcat
        } else {
            Log '[guard] （未启用 WithNapCat，仅提醒；可加 -WithNapCat 自动拉起）' 'Gray'
        }
    } else {
        Log '[guard] NapCat WS 正常' 'Green'
    }

    Write-State $report
}

# =============================================================================
# 入口
# =============================================================================
Write-Host "=== 菟菚 bot 守护脚本启动 ===" -ForegroundColor Cyan
Log "[watchdog] 守护脚本启动 (PID: $PID, Interval: ${Interval}s, WithNapCat: $WithNapCat)" 'Cyan'

# 首次启动即守护一轮
Invoke-Guard

if ($RunOnce) {
    Log "[watchdog] RunOnce 模式，自检完成，退出。" 'Cyan'
    exit 0
}

# 常驻主循环
Write-Host "守护中，Ctrl+C 或关闭窗口退出。每 ${Interval}s 检查一次。" -ForegroundColor Cyan
try {
    while ($true) {
        Start-Sleep -Seconds $Interval
        Invoke-Guard
    }
} finally {
    # 清理：删锁 + 状态文件
    Log '[watchdog] 守护脚本退出，清理状态 ...' 'Yellow'
    try { Remove-Item $StateFile -Force -ErrorAction SilentlyContinue } catch {}
    try { Remove-Item $lockPath -Force -ErrorAction SilentlyContinue } catch {}
}

Write-Host "=== 守护脚本已退出 ===" -ForegroundColor Cyan
