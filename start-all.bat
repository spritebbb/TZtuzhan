@echo off
chcp 65001 >nul
title 菟菚 QQ bot 一键启动
echo ==========================================
echo   菟菚 QQ bot 一键启动
echo ==========================================

REM === 0. 检查 bot / webui 是否已在运行（防重复启动）===
echo.
echo [检查] 检测已有 bot / webui 进程...
powershell -Command "& { $bots = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot\.py' -or $_.CommandLine -match 'webui\.py' }; if ($bots) { Write-Host '[!] 已有 bot/webui 在运行 (PID: ' + ($bots.ProcessId -join ',') + ')，请先停止再启动' -ForegroundColor Yellow; Write-Host '停止命令: powershell -File stop-bot.ps1' -ForegroundColor Yellow; exit 1 } else { exit 0 } }"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 为避免重复启动导致消息重复，已退出。
    echo 也可直接日启动新窗口（不推荐）：
    echo   start "TZtuzhan Bot" cmd /k "chcp 65001 ^>nul ^& cd /d D:\DSH\TZtuzhan ^& .\.venv\Scripts\python.exe bot.py"
    pause
    exit /b
)
echo [OK] 未检测到已有 bot/webui，可以启动.

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
REM     -q <BotQQ> 快速登录（从 .env 的 BOT_QQ 读取）：凭据有效则自动登录免扫码；失效才需扫码
REM     未配置 BOT_QQ 时回退到普通登录（不传 -q）
for /f "tokens=2 delims==" %%i in ('findstr /b "BOT_QQ" .env 2^>nul') do set "BOT_QQ=%%i"
if not defined BOT_QQ set "BOT_QQ="
echo.
echo [1/3] 正在启动 NapCat（窗口：NapCat，快速登录 %BOT_QQ%）...
if defined BOT_QQ (
    start "NapCat" cmd /k "chcp 65001 >nul & cd /d D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node\napcat & launcher.bat -q %BOT_QQ%"
) else (
    start "NapCat" cmd /k "chcp 65001 >nul & cd /d D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node\napcat & launcher.bat"
)

REM === 3. 启动 bot（venv python，新窗口）===
echo [2/3] 正在启动 TZtuzhan Bot（窗口：Bot）...
start "TZtuzhan Bot" cmd /k "chcp 65001 >nul & cd /d D:\DSH\TZtuzhan & .\.venv\Scripts\python.exe bot.py"

REM === 4. 启动 Web 管理面板（venv python，独立进程 :8800）===
echo [3/3] 正在启动 Web 管理面板（窗口：WebUI）...
start "TZtuzhan WebUI" cmd /k "chcp 65001 >nul & cd /d D:\DSH\TZtuzhan & .\.venv\Scripts\python.exe webui.py"

echo.
echo ==========================================
echo   三个窗口已启动：
echo   - NapCat 窗口：等它出现 WebUI 地址 / 二维码（有登录就自动登）
echo   - Bot 窗口：等它出现 "OneBot V11 | Bot ... connected"
echo   - WebUI 窗口：管理面板 http://127.0.0.1:8800
echo   保持这三个窗口开着，bot 就一直在线上。
echo   关闭三个窗口即可下线。
echo ==========================================
pause
