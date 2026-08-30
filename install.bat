@echo off
chcp 65001 >nul
title TZtuzhan One-Click Installer
echo ==========================================
echo   TZtuzhan QQ Bot - One-Click Install
echo ==========================================
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM === 1. Check Python ===
echo [1/5] Checking Python ...
set "PY=py"
py -3 --version >nul 2>&1
if %ERRORLEVEL%==0 (
    for /f "delims=" %%v in ('py -3 --version 2^>^&1') do set "PYVER=%%v"
    echo   [OK] Found Python: %PYVER%
) else (
    python --version >nul 2>&1
    if %ERRORLEVEL%==0 (
        for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
        echo   [OK] Found Python: %PYVER%
        set "PY=python"
    ) else (
        echo   [X] Python not found!
        echo   Please install Python 3.10+ from https://www.python.org/downloads/
        echo   (check "Add python.exe to PATH" during install)
        echo.
        echo   After installing, run this script again.
        pause
        exit /b 1
    )
)

REM === 2. Create venv ===
echo [2/5] Creating virtual environment ...
if exist ".venv\Scripts\python.exe" (
    echo   [OK] venv already exists
) else (
    %PY% -m venv --without-pip .venv
    if errorlevel 1 (
        echo   [X] Failed to create venv
        pause
        exit /b 1
    )
    %PY% -m pip --python ".venv\Scripts\python.exe" install --upgrade pip
    echo   [OK] venv created
)

REM === 3. Install dependencies ===
echo [3/5] Installing dependencies (this may take 1-3 min) ...
set "IDX="
echo.
echo   Select pip source:
echo     1) Official PyPI (default)
echo     2) Tsinghua mirror (faster in China)
set /p SRC="Your choice (1/2, default 1): "
if "%SRC%"=="2" set "IDX=-i https://pypi.tuna.tsinghua.edu.cn/simple"
echo   Installing with: %IDX%
%PY% -m pip --python ".venv\Scripts\python.exe" install -r requirements.txt %IDX%
if errorlevel 1 (
    echo   [X] Dependency install failed.
    echo   Tip: network issue? Run again and choose Tsinghua mirror.
    pause
    exit /b 1
)
echo   [OK] Dependencies installed

REM === 4. Prepare .env ===
echo [4/5] Preparing .env ...
if exist ".env" (
    echo   [OK] .env already exists (will keep it)
) else (
    copy /y ".env.example" ".env" >nul
    echo   [OK] Created .env from template
)

echo   Checking BOT_QQ and generating NapCat config ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools_gen_napcat_config.py
    if errorlevel 1 (
        echo   [WARN] NapCat config generation had an issue
    )
)

echo.
echo   *** IMPORTANT ***
echo   Edit ".env" now and fill:
echo     - LLM_API_KEY  (required for chat, get from DeepSeek/SiliconFlow etc.)
echo     - BOT_QQ       (your bot QQ small account, for NapCat quick login)
echo     - other keys as needed (Vision/Image/Search/MOOD_CITY)
echo.
echo   Open with notepad:  notepad ".env"
echo   Press any key after editing...
pause >nul

REM === 5. Check NapCat ===
echo [5/5] Checking NapCat ...
if exist "Napcat\NapCat.Shell.Windows.Node\napcat\launcher.bat" (
    echo   [OK] NapCat found
) else (
    echo   [WARN] NapCat not found in this folder.
    echo   Download NapCat from https://github.com/NapNeko/NapCatQQ/releases
    echo   and place it under:  Napcat\NapCat.Shell.Windows.Node\
)

echo.
echo ==========================================
echo   Install complete!
echo.
echo   Next steps:
echo     1) Edit .env  (fill LLM_API_KEY, BOT_QQ if you have)
echo     2) Install QQ on this PC (needed by NapCat), login once
echo     3) Run  start-all.bat  to launch NapCat + Bot + WebUI
echo        WebUI panel:  http://127.0.0.1:8800
echo ==========================================
pause