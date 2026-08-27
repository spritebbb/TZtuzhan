@echo off
chcp 65001 >nul
title 菟菚 QQ bot 一键启动
echo ==========================================
echo   菟菚 QQ bot 一键启动
echo ==========================================

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
