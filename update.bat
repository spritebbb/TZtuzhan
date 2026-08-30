@echo off
chcp 65001 >nul
title TZtuzhan Auto-Update
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ==========================================
echo   TZtuzhan Auto-Update from GitHub
echo ==========================================
echo.

REM === 1. Check git ===
echo [1/4] Checking git ...
git --version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo   [X] git not found!
    echo   Please install git from https://git-scm.com/download/win
    echo   (check "Git from the command line and also from 3rd-party software")
    pause
    exit /b 1
)
echo   [OK] git found

REM === 2. Choose branch (default: main; pass "dev" for dev branch) ===
set "BRANCH=main"
if not "%1"=="" set "BRANCH=%1"
echo   Branch: %BRANCH%

REM === 3. Init git if needed (deployment package has no .git) ===
echo [2/4] Setting up git repository ...
if not exist ".git" (
    echo   [..] No .git found (deployment package). Initializing ...
    git init
    git remote add origin https://github.com/spritebbb/TZtuzhan.git
    if !ERRORLEVEL! NEQ 0 (
        echo   [X] Failed to init git
        pause
        exit /b 1
    )
    echo   [OK] Repository initialized
) else (
    echo   [OK] .git exists
)

REM === 4. Fetch and reset to remote ===
echo [3/4] Fetching updates from GitHub (%BRANCH%) ...
git fetch origin --tags
if !ERRORLEVEL! NEQ 0 (
    echo   [X] Fetch failed. Check your network / proxy settings.
    pause
    exit /b 1
)

echo   Updating to origin/%BRANCH% ...
git checkout -B %BRANCH% origin/%BRANCH%
if !ERRORLEVEL! NEQ 0 (
    echo   [X] Checkout failed.
    pause
    exit /b 1
)

echo   Current version:
for /f "delims=" %%v in ('git describe --tags --always 2^>nul') do echo   %%v

REM === 5. Update pip dependencies ===
echo [4/4] Updating Python dependencies ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo   [WARN] pip install failed. Run install.bat to retry with mirror.
    ) else (
        echo   [OK] Dependencies updated
    )
) else (
    echo   [WARN] .venv not found. Run install.bat first.
)

echo.
echo ==========================================
echo   Update complete!
echo   - .env / data / Napcat / .venv preserved
echo   - Restart bot (start-all.bat) to apply
echo ==========================================
echo.
echo   Tip: update.bat dev  -- pull from dev branch
echo        update.bat main -- pull from main branch (default)
echo.
pause