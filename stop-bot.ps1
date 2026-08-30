# Cleanly stop TZtuzhan bot + WebUI (kill bot.py / webui.py, keep NapCat)
# Usage: powershell -ExecutionPolicy Bypass -File stop-bot.ps1
$ErrorActionPreference = 'SilentlyContinue'

Write-Host "=== Stop TZtuzhan bot + WebUI ===" -ForegroundColor Cyan
$bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' -or $_.CommandLine -match 'webui\.py' }
if ($bots) {
    Write-Host "Found $($bots.Count) process(es)..." -ForegroundColor Yellow
    $bots | ForEach-Object {
        $kind = if ($_.CommandLine -match 'bot\.py') { 'bot' } else { 'webui' }
        Write-Host "  Stopping $kind PID $($_.ProcessId) (started $($_.CreationDate))" -ForegroundColor Gray
        Stop-Process -Id $_.ProcessId -Force
    }
    Start-Sleep -Seconds 1
    $remaining = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'bot\.py' -or $_.CommandLine -match 'webui\.py' }
    if ($remaining) {
        Write-Host "[X] $($remaining.Count) process(es) still alive!" -ForegroundColor Red
        exit 1
    } else {
        Write-Host "[OK] All stopped" -ForegroundColor Green
    }
} else {
    Write-Host "No bot/webui running" -ForegroundColor Green
}
exit 0