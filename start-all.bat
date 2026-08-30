@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 菟菚 QQ bot 一键启动
echo ==========================================
echo   菟菚 QQ bot 一键启动
echo ==========================================

REM 项目根目录（本脚本所在目录，可随包任意放置）
set "ROOT=%~dp0"

REM === 0. 检查 bot / webui 是否已在运行（防重复启动）===
echo.
echo [检查] 检测已有 bot / webui 进程...
powershell -Command "& { $bots = Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'bot\.py' -or $_.CommandLine -match 'webui\.py' }; if ($bots) { Write-Host '[!] 已有 bot/webui 在运行 (PID: ' + ($bots.ProcessId -join ',') + ')，请先停止再启动' -ForegroundColor Yellow; Write-Host '停止命令: powershell -File stop-bot.ps1' -ForegroundColor Yellow; exit 1 } else { exit 0 } }"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 为避免重复启动导致消息重复，已退出。
    echo 也可直接日启动新窗口（不推荐）：
    echo   start "TZtuzhan Bot" cmd /k "chcp 65001 ^>nul ^& cd /d "%ROOT%" ^& .\.venv\Scripts\python.exe bot.py"
    pause
    exit /b
)
echo [OK] 未检测到已有 bot/webui，可以启动.

REM === 1. 检查是否需要管理员权限（NapCat 注入 QQNT 需要）===
net session >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [OK] 已具备管理员权限.

    REM === 1.5 版本检测（GitHub 更新检查）===
    echo.
    echo [更新检查] 正在检测版本...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%check-update.ps1"
    set "UPSTATUS=!ERRORLEVEL!"
    if "!UPSTATUS!"=="1" (
        echo.
        echo   [发现新版本！]
        choice /c YN /n /m "  是否更新到最新版本？[Y=更新 N=跳过直接启动] "
        if errorlevel 2 (
            echo   [跳过更新，直接启动]
        ) else (
            echo   [正在更新，请稍候...]
            call "%ROOT%update.bat" main quiet
            if !ERRORLEVEL! NEQ 0 (
                echo   [!] 更新失败
                choice /c YN /n /m "  是否忽略错误继续启动？[Y=继续 N=退出] "
                if errorlevel 2 (
                    echo   [已退出，请手动运行 update.bat 排查后重试]
                    pause
                    exit /b
                )
            ) else (
                echo   [更新完成：已同步到最新版本]
            )
        )
    ) else if "!UPSTATUS!"=="2" (
        echo   [版本检测跳过（无 git 或无网络），直接启动]
    ) else (
        echo   [已是最新版本]
    )
) else (
    echo [..] 需要管理员权限，正在通过 UAC 提权...
    powershell -Command "Start-Process '%~f0' -Verb runAs"
    exit /b
)

REM === 2. 启动 NapCat（官方 launcher.bat，新窗口）===
REM     -q <BotQQ> 快速登录（从 .env 的 BOT_QQ 读取）：凭据有效则自动登录免扫码；失效才需扫码
REM     未配置 BOT_QQ 时回退到普通登录（不传 -q）
for /f "tokens=2 delims==" %%i in ('findstr /b "BOT_QQ" "%ROOT%.env" 2^>nul') do set "BOT_QQ=%%i"
if not defined BOT_QQ set "BOT_QQ="
echo.
echo [2/4] 正在启动 NapCat（窗口：NapCat，快速登录 %BOT_QQ%）...
if defined BOT_QQ (
    start "NapCat" cmd /k "chcp 65001 >nul & cd /d ""%ROOT%Napcat\NapCat.Shell.Windows.Node\napcat"" & launcher.bat -q %BOT_QQ%"
) else (
    start "NapCat" cmd /k "chcp 65001 >nul & cd /d ""%ROOT%Napcat\NapCat.Shell.Windows.Node\napcat"" & launcher.bat"
)

REM === 3. 启动 bot（venv python，新窗口）===
echo [3/4] 正在启动 TZtuzhan Bot（窗口：Bot）...
start "TZtuzhan Bot" cmd /k "chcp 65001 >nul & cd /d ""%ROOT%"" & .\.venv\Scripts\python.exe bot.py"

REM === 4. 启动 Web 管理面板（venv python，独立进程 :8800）===
echo [4/4] 正在启动 Web 管理面板（窗口：WebUI）...
start "TZtuzhan WebUI" cmd /k "chcp 65001 >nul & cd /d ""%ROOT%"" & .\.venv\Scripts\python.exe webui.py"

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
