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
# bot QQ 号（快速登录用）：从环境变量 BOT_QQ 读，未设置则读 .env 的 BOT_QQ
# 未配置则回退为普通登录（不传 -q），绝不从 PROACTIVE_USER_ID 取（那是用户号）
$BotQQ = $env:BOT_QQ
if (-not $BotQQ) {
    $envLine = Get-Content (Join-Path $Root '.env') -Encoding UTF8 -ErrorAction SilentlyContinue |
        Where-Object { $_ -match '^BOT_QQ\s*=' } | Select-Object -First 1
    if ($envLine) { $BotQQ = (($envLine -split '=', 2)[1]).Trim().Trim('"') }
}

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

# ---- QQ 是否真在线：调用 napcat_probe.py 发 get_status 探测 ----
# 比仅测 3001 端口更可靠——QQ 被风控踢下线时 WS 端口可能仍在监听。
# 返回 $true 表示 QQ 在线；$false 表示离线/未连接。
function Test-QqOnline {
    $probe = Join-Path $Root 'napcat_probe.py'
    if (-not (Test-Path $probe)) {
        Log "[napcat] ✗ 找不到 $probe, 回退到端口检测" 'Yellow'
        $port = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue
        return ($null -ne $port -and $port.Count -ge 1)
    }
    $out = & $VenvPy -X utf8 $probe 'ws://127.0.0.1:3001/' 8 2>&1
    return $LASTEXITCODE -eq 0
}

# ---- NapCat 是否在线（端口监听的后备判据）----
function Test-NapcatPort {
    $port = Get-NetTCPConnection -LocalPort 3001 -State Listen -ErrorAction SilentlyContinue
    if ($port) { return $true }
    # 兼容旧版：node server.js 是 NapCat 主进程
    $node = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'server\.js' }
    if ($node) { return $true }
    return $false
}

# ---- 干净重启 NapCat：杀掉 QQ/NapCat 进程后重新拉起 launcher ----
# QQ 被风控踢下线时，先停掉旧进程再拉起，NapCat 会自动重新登录。
function Restart-Napcat {
    Log '[napcat] 检测到 QQ 离线/NapCat 异常，尝试重启 ...' 'Yellow'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    # 写本次重启时间（供去抖：连续重启太频繁说明有问题，暂停几轮）
    $stamp | Set-Content -Path (Join-Path $DataDir 'napcat_restart_ts') -Encoding UTF8

    # 1) 停掉 QQ 与 NapCat（用提权，避免权限不足残留）
    try {
        $killCmd = 'taskkill /f /im QQ.exe; taskkill /f /im QQEX.exe; taskkill /f /im NapCatWinBootMain.exe; Start-Sleep 1'
        Start-Process powershell -Verb runAs -ArgumentList "-NoProfile -Command `"$killCmd`"" -Wait -ErrorAction SilentlyContinue
    } catch {
        Log "[napcat] ✗ 停止旧进程失败（需管理员）: $($_.Exception.Message)" 'Red'
    }

    # 2) 等端口释放
    Start-Sleep -Seconds 3

    # 3) 拉起 launcher（-q 快速登录：凭据有效则自动登录，失效才需扫码一次）
    Start-Napcat

    # 4) 等 NapCat 起来并等 bot 重连
    Start-Sleep -Seconds 10
    Log '[napcat] 已重启，等待 QQ 重新登录与 bot 重连 ...' 'Green'
}

# ---- 启动 NapCat ----
function Start-Napcat {
    if (-not (Test-Path $NapcatLauncher)) {
        Log "[napcat] ✗ 找不到 launcher.bat" 'Red'
        return
    }
    if ($BotQQ) {
        Log "[napcat] 拉起 launcher.bat -q $BotQQ（快速登录，需管理员，可能弹 UAC）..." 'Yellow'
        $napArg = "/c chcp 65001 >nul & cd /d `"$(Split-Path $NapcatLauncher)`" & launcher.bat -q $BotQQ"
    } else {
        Log '[napcat] 拉起 launcher.bat（未配置 BOT_QQ，普通登录）...' 'Yellow'
        $napArg = "/c chcp 65001 >nul & cd /d `"$(Split-Path $NapcatLauncher)`" & launcher.bat"
    }
    try {
        Start-Process -FilePath 'cmd.exe' `
            -ArgumentList $napArg `
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

    # ② QQ / NapCat 是否真正在线
    $qqOnline = Test-QqOnline
    $report.qq_online = $qqOnline
    $report.napcat_ws = (Test-NapcatPort)
    if ($qqOnline) {
        Log '[guard] QQ 在线 (get_status=online)' 'Green'
    } else {
        Log '[guard] ⚠️ QQ 离线 / NapCat 未连接（WS 服务端可能还在，但账号已掉线）' 'Yellow'
        if ($WithNapCat) {
            # 重启去抖：距上次重启不足 5 分钟则跳过，避免 QQ 反复被踢时无限重启风暴
            $tsFile = Join-Path $DataDir 'napcat_restart_ts'
            $tooSoon = $false
            if (Test-Path $tsFile) {
                try {
                    $last = [datetime]::ParseExact((Get-Content $tsFile -Raw).Trim(), 'yyyyMMdd-HHmmss', $null)
                    $tooSoon = ((Get-Date) - $last).TotalMinutes -lt 5
                } catch { $tooSoon = $false }
            }
            if ($tooSoon) {
                Log '[guard] 距上次重启 NapCat 不到 5 分钟，跳过本次重启（避免重启风暴）' 'Gray'
            } else {
                Restart-Napcat
            }
        } else {
            Log '[guard] （未启用 WithNapCat，仅提醒；可加 -WithNapCat 自动重启 NapCat）' 'Gray'
        }
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
