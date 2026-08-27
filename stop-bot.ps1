# 干净停止菟菚 bot（杀掉所有 bot.py 进程，保留 NapCat）
# 用法: powershell -ExecutionPolicy Bypass -File stop-bot.ps1
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "=== 停止菟菚 bot ===" -ForegroundColor Cyan
$bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' }
if ($bots) {
    Write-Host "发现 $($bots.Count) 个 bot 进程..." -ForegroundColor Yellow
    $bots | ForEach-Object {
        Write-Host "  停止 PID $($_.ProcessId) (启动于 $($_.CreationDate))" -ForegroundColor Gray
        Stop-Process -Id $_.ProcessId -Force
    }
    Start-Sleep -Seconds 1
    $remaining = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' }
    if ($remaining) {
        Write-Host "[✗] 仍有 $($remaining.Count) 个进程残留！" -ForegroundColor Red
        exit 1
    } else {
        Write-Host "[✓] 已全部停止" -ForegroundColor Green
    }
} else {
    Write-Host "没有 bot 在运行" -ForegroundColor Green
}
exit 0