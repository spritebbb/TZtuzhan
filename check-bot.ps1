# 菟菚 bot 健康自检
# 用法: powershell -ExecutionPolicy Bypass -File check-bot.ps1
# 退出码: 0 = 健康; 1 = 有异常（重复进程/未连接等）
$ErrorActionPreference = 'SilentlyContinue'
$issues = @()

Write-Host "=== 菟菚 bot 健康自检 ===" -ForegroundColor Cyan

# 1. bot.py 进程（NoneBot 正常是 父+子 两个进程，都算同一个实例）
$bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' }
if (-not $bots) {
    Write-Host "[✗] bot.py 未在运行" -ForegroundColor Red
    $issues += "bot 未运行"
} else {
    Write-Host "[✓] bot.py 进程 $($bots.Count) 个 (PID: $($bots.ProcessId -join ', '))" -ForegroundColor Green
}

# 2. WS 3001 连接数（NapCat 每个 bot 实例 1 条连接；>1 说明有重复实例）
$conn = Get-NetTCPConnection -LocalPort 3001 -State Established
if (-not $conn) {
    Write-Host "[✗] 未连上 NapCat WS (3001)" -ForegroundColor Red
    $issues += "未连上 WS"
} elseif ($conn.Count -gt 1) {
    Write-Host "[✗] WS 连接 $($conn.Count) 条 —— 疑似有多个 bot 实例在跑！" -ForegroundColor Red
    $issues += "WS 连接数 $($conn.Count)"
} else {
    Write-Host "[✓] WS 3001 连接正常 (1 条)" -ForegroundColor Green
}

# 3. NapCat 进程
$napcat = Get-CimInstance Win32_Process -Filter "Name='node.exe'" | Where-Object { $_.CommandLine -match 'server\.js' }
if ($napcat) {
    Write-Host "[✓] NapCat 运行中 (PID: $($napcat.ProcessId -join ', '))" -ForegroundColor Green
} else {
    Write-Host "[✗] NapCat (server.js) 未运行" -ForegroundColor Red
    $issues += "NapCat 未运行"
}

# 4. 最近日志是否有 ERROR/异常
$log = Join-Path $PSScriptRoot 'data\bot.log'
if (Test-Path $log) {
    $tail = Get-Content $log -Tail 20
    $errs = $tail | Select-String -Pattern 'ERROR|Traceback|TimeoutError'
    if ($errs) {
        Write-Host "[!] 最近日志有异常（可能已自愈）:" -ForegroundColor Yellow
        $errs | Select-Object -First 3 | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
    } else {
        Write-Host "[✓] 最近日志无异常" -ForegroundColor Green
    }
} else {
    Write-Host "[!] 未找到日志文件 (data\bot.log)" -ForegroundColor Yellow
}

Write-Host ""
if ($issues) {
    Write-Host "=== 结论: 有问题 ===" -ForegroundColor Red
    $issues | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    Write-Host "提示: 若有重复实例，运行: powershell -File stop-bot.ps1 后重新 start-all.bat" -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "=== 结论: 一切正常 ===" -ForegroundColor Green
    exit 0
}
