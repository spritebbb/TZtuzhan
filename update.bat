@echo off
chcp 65001 >nul
title 菟菚 QQ Bot 自动更新
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM 静默模式：第 2 个参数传 "quiet"（例如 start-all.bat 调用时）可跳过暂停
set "QUIET=0"
if "%2"=="quiet" set "QUIET=1"

echo ==========================================
echo   菟菚 QQ Bot 自动更新
echo ==========================================
echo.

REM === 1. 检测 git ===
echo [1/4] 正在检测 git ...
git --version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo   [X] 未找到 git！
    echo   请先安装 git：https://git-scm.com/download/win
    echo   安装时勾选「Git from the command line」
    if !QUIET!==0 pause
    exit /b 1
)
echo   [OK] 已找到 git

REM === 2. 选择分支（默认 main；传 "dev" 用开发分支）===
set "BRANCH=main"
if not "%1"=="" set "BRANCH=%1"
echo   更新分支：%BRANCH%

REM === 3. 初始化 git（部署包没有 .git 时）===
echo [2/4] 正在设置 git 仓库 ...
if not exist ".git" (
    echo   [..] 未找到 .git（部署包），正在初始化 ...
    git init
    git remote add origin https://github.com/spritebbb/TZtuzhan.git
    if !ERRORLEVEL! NEQ 0 (
        echo   [X] 初始化 git 失败
        if !QUIET!==0 pause
        exit /b 1
    )
    echo   [OK] 仓库初始化完成
) else (
    echo   [OK] .git 已存在
)

REM === 4. 拉取并更新到远程分支 ===
echo [3/4] 正在从 GitHub 拉取更新（%BRANCH%）...
git fetch origin --tags
if !ERRORLEVEL! NEQ 0 (
    echo   [X] 拉取失败。请检查网络 / 代理设置。
    if !QUIET!==0 pause
    exit /b 1
)

echo   正在更新到 origin/%BRANCH% ...
git checkout -f -B %BRANCH% origin/%BRANCH%
if !ERRORLEVEL! NEQ 0 (
    echo   [X] 更新失败。
    if !QUIET!==0 pause
    exit /b 1
)

echo   当前版本：
for /f "delims=" %%v in ('git describe --tags --always 2^>nul') do echo   %%v

REM === 5. 更新 Python 依赖 ===
echo [4/4] 正在更新 Python 依赖 ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if !ERRORLEVEL! NEQ 0 (
        echo   [WARN] 依赖更新失败。可运行 install.bat 选择镜像重试。
    ) else (
        echo   [OK] 依赖更新完成
    )
) else (
    echo   [WARN] 未找到 .venv，请先运行 install.bat
)

echo.
echo ==========================================
echo   更新完成！
echo   - 已保留 .env / data / Napcat / .venv
echo   - 重新运行 start-all.bat 使更新生效
echo ==========================================
echo.
echo   用法：update.bat dev  —— 拉取 dev 分支
echo         update.bat main —— 拉取 main 分支（默认）
echo.
if !QUIET!==0 pause