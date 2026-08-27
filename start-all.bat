@echo off
chcp 65001 >nul
title 菟菚 QQ bot 一键启动
echo ==========================================
echo   菟菚 QQ bot 一键启动
echo ==========================================

REM === 0. 检查 bot 是否已在运行（防重复启动）===
echo.
echo [检查] 检测已有 bot 进程...
powershell -Command "& { $bots = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot\.py' }; if ($bots) { Write-Host '[!] 已有 bot 在运行 (PID: ' + ($bots.ProcessId -join ',') + ')，请先停止再启动' -ForegroundColor Yellow; Write-Host '停止命令: powershell -File stop-bot.ps1' -ForegroundColor Yellow; exit 1 } else { exit 0 } }"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 为避免重复启动导致消息重复，已退出。
    echo 也可直接日启动新窗口（不推荐）：
    echo   start "TZtuzhan Bot" cmd /k "chcp 65001 ^>nul ^& cd /d D:\DSH\TZtuzhan ^& .\.venv\Scripts\python.exe bot.py"
    pause
    exit /b
)
echo [OK] 未检测到已有 bot，可以启动.

REM === 1. 检查是否需要管理员权限（NapCat 注入 QQNT 需要）===
net session >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [OK] 已具备管理员权限.
) else (
    echo [..] 需要管理员权限，正在通过 UAC 提权...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit /b
)

REM === 2. 启动 NapCat（官方 launcher.bat，新窗口）===
echo.
echo [1/2] 正在启动 NapCat（窗口：NapCat）...
start "NapCat" cmd /k "chcp 65001 >nul & cd /d D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node\napcat & launcher.bat"

REM === 3. 启动 bot（venv python，新窗口）===
echo [2/2] 正在启动 TZtuzhan Bot（窗口：Bot）...
start "TZtuzhan Bot" cmd /k "chcp 65001 >nul & cd /d D:\DSH\TZtuzhan & .\.venv\Scripts\python.exe bot.py"

echo.
echo ==========================================
echo   两个窗口已启动：
echo   - NapCat 窗口：等它出现 WebUI 地址 / 二维码（有登录就自动登）
echo   - Bot 窗口：等它出现 "OneBot V11 | Bot ... connected"
echo   保持这两个窗口开着，bot 就一直在线上。
echo   关闭两个窗口即可下线。
echo ==========================================
pause
