# =============================================================================
#  install-watchdog.ps1 — 把 watchdog.ps1 注册为 Windows 计划任务（开机自启守护）
# =============================================================================
#  用法：
#    powershell -ExecutionPolicy Bypass -File install-watchdog.ps1          # 注册(开机登录自启, 每2分钟兜底)
#    powershell -ExecutionPolicy Bypass -File install-watchdog.ps1 -Remove  # 卸载
#
#  说明：
#    watchdog.ps1 是以"常驻主循环"方式守护 bot。计划任务在 onlogon 触发，
#    但若守护进程被杀，需要周期性兜底重启——这里同时注册一个每 2 分钟的
#    -RunOnce 任务，确保守护脚本随时在跑。
# =============================================================================
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Watchdog = Join-Path $Root 'watchdog.ps1'
$DurableTask = 'TZtuzhanWatchdog'        # 常驻守护（onlogon，隐藏）
$KeepAliveTask = 'TZtuzhanWatchdogKeep'  # 兜底，每 2 分钟 RunOnce

if ($Remove) {
    Write-Host "=== 卸载守护计划任务 ===" -ForegroundColor Cyan
    schtasks /delete /tn $DurableTask /f 2>&1 | Out-Null
    schtasks /delete /tn $KeepAliveTask /f 2>&1 | Out-Null
    Write-Host "[✓] 已删除 $DurableTask / $KeepAliveTask" -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $Watchdog)) {
    Write-Host "[✗] 找不到 $Watchdog" -ForegroundColor Red
    exit 1
}

Write-Host "=== 注册守护计划任务（需管理员，可能弹 UAC）===" -ForegroundColor Cyan

# 任务1：常驻守护，开机登录时以最高权限隐藏运行
Write-Host "[1/2] 注册常驻 $DurableTask ..." -ForegroundColor Yellow
schtasks /create /tn $DurableTask /tr "powershell -NoProfile -ExecutionPolicy Bypass -File `"$Watchdog`"" /sc onlogon /rl highest /f 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  [✓] 注册成功（onlogon 启动守护）" -ForegroundColor Green }
else { Write-Host "  [✗] 注册失败（可能需管理员）" -ForegroundColor Red }

# 任务2：兜底，每 2 分钟 RunOnce 自检（若守护意外退出则拉起）
Write-Host "[2/2] 注册兜底 $KeepAliveTask ..." -ForegroundColor Yellow
schtasks /create /tn $KeepAliveTask /tr "powershell -NoProfile -ExecutionPolicy Bypass -File `"$Watchdog`" -RunOnce" /sc minute /mo 2 /rl highest /f 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  [✓] 注册成功（每 2 分钟兜底）" -ForegroundColor Green }
else { Write-Host "  [✗] 注册失败（可能需管理员）" -ForegroundColor Red }

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Cyan
Write-Host "  立即启动守护： powershell -ExecutionPolicy Bypass -File `"$Watchdog`"" -ForegroundColor Green
Write-Host "  查看任务：      schtasks /query /tn $DurableTask /v" -ForegroundColor Gray
Write-Host "  卸载：          powershell -File install-watchdog.ps1 -Remove" -ForegroundColor Gray
