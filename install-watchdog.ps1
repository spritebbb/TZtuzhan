# =============================================================================
#  install-watchdog.ps1 — 把 watchdog.ps1 注册为 Windows 计划任务（开机自启守护）
# =============================================================================
#  用法：
#    powershell -ExecutionPolicy Bypass -File install-watchdog.ps1          # 注册(开机登录自启, 每2分钟兜底)
#    powershell -ExecutionPolicy Bypass -File install-watchdog.ps1 -Remove  # 卸载
#
#  说明：
#    watchdog.ps1 是以"常驻主循环"方式守护 bot，并带 -WithNapCat 守护 QQ：
#     - 通过 OneBot WS 发 get_status 探测 QQ 是否真在线（比端口更可靠）
#     - QQ 被风控踢下线（WS 端口还在但账号掉线）时，自动重启 NapCat 让其重新登录
#     - 重启带 5 分钟去抖，避免 QQ 反复被踢时无限重启
#    计划任务在 onlogon 触发，若守护进程被杀，每 2 分钟的 -RunOnce 兜底。
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

# 任务1：常驻守护，开机登录时以最高权限隐藏运行（带 -WithNapCat：QQ 掉线自动重启 NapCat）
Write-Host "[1/2] 注册常驻 $DurableTask ..." -ForegroundColor Yellow
schtasks /create /tn $DurableTask /tr "powershell -NoProfile -ExecutionPolicy Bypass -File `"$Watchdog`" -WithNapCat" /sc onlogon /rl highest /f 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  [✓] 注册成功（onlogon 启动守护，QQ 掉线自动重启 NapCat）" -ForegroundColor Green }
else { Write-Host "  [✗] 注册失败（可能需管理员）" -ForegroundColor Red }

# 任务2：兜底，每 2 分钟 RunOnce 自检（若守护意外退出则拉起，并顺带探测 QQ 掉线）
Write-Host "[2/2] 注册兜底 $KeepAliveTask ..." -ForegroundColor Yellow
schtasks /create /tn $KeepAliveTask /tr "powershell -NoProfile -ExecutionPolicy Bypass -File `"$Watchdog`" -RunOnce -WithNapCat" /sc minute /mo 2 /rl highest /f 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "  [✓] 注册成功（每 2 分钟兜底 + 探测 QQ）" -ForegroundColor Green }
else { Write-Host "  [✗] 注册失败（可能需管理员）" -ForegroundColor Red }

Write-Host ""
Write-Host "=== 完成 ===" -ForegroundColor Cyan
Write-Host "  立即启动守护： powershell -ExecutionPolicy Bypass -File `"$Watchdog`"" -ForegroundColor Green
Write-Host "  查看任务：      schtasks /query /tn $DurableTask /v" -ForegroundColor Gray
Write-Host "  卸载：          powershell -File install-watchdog.ps1 -Remove" -ForegroundColor Gray
