# 停止菟菚 bot + WebUI（停 bot.py / webui.py，保留 NapCat）
# 用法: powershell -ExecutionPolicy Bypass -File stop-bot.ps1
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "=== 停止菟菚 bot + WebUI ===" -ForegroundColor Cyan
$bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' -or $_.CommandLine -match 'webui\.py' }
if ($bots) {
    Write-Host "找到 $($bots.Count) 个进程..." -ForegroundColor Yellow
    $bots | ForEach-Object {
        $kind = if ($_.CommandLine -match 'bot\.py') { 'bot' } else { 'WebUI' }
        Write-Host "  正在停止 $kind PID $($_.ProcessId)（启动于 $($_.CreationDate)）" -ForegroundColor Gray
        Stop-Process -Id $_.ProcessId -Force
    }
    Start-Sleep -Seconds 1
    $remaining = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' -or $_.CommandLine -match 'webui\.py' }
    if ($remaining) {
        Write-Host "[X] 仍有 $($remaining.Count) 个进程存活！" -ForegroundColor Red
        exit 1
    } else {
        Write-Host "[OK] 已全部停止" -ForegroundColor Green
    }
} else {
    Write-Host "当前没有运行中的 bot/WebUI" -ForegroundColor Green
}
exit 0