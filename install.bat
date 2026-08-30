@echo off
chcp 65001 >nul
title 菟菚 QQ Bot 一键安装向导
echo ==========================================
echo   菟菚 QQ Bot 一键安装
echo ==========================================
echo.

set "ROOT=%~dp0"
cd /d "%ROOT%"

REM === 1. 检测 Python ===
echo [1/5] 正在检测 Python ...
set "PY=py"
py -3 --version >nul 2>&1
if %ERRORLEVEL%==0 (
    for /f "delims=" %%v in ('py -3 --version 2^>^&1') do set "PYVER=%%v"
    echo   [OK] 已找到 Python：%PYVER%
) else (
    python --version >nul 2>&1
    if %ERRORLEVEL%==0 (
        for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
        echo   [OK] 已找到 Python：%PYVER%
        set "PY=python"
    ) else (
        echo   [X] 未找到 Python！
        echo   请先安装 Python 3.10+：https://www.python.org/downloads/
        echo   安装时务必勾选「Add python.exe to PATH」
        echo.
        echo   安装完成后重新运行本脚本即可。
        pause
        exit /b 1
    )
)

REM === 2. 创建虚拟环境 ===
echo [2/5] 正在创建虚拟环境 ...
if exist ".venv\Scripts\python.exe" (
    echo   [OK] 虚拟环境已存在
) else (
    %PY% -m venv --without-pip .venv
    if errorlevel 1 (
        echo   [X] 创建虚拟环境失败
        pause
        exit /b 1
    )
    %PY% -m pip --python ".venv\Scripts\python.exe" install --upgrade pip
    echo   [OK] 虚拟环境创建完成
)

REM === 3. 安装依赖 ===
echo [3/5] 正在安装依赖（约需 1-3 分钟）...
set "IDX="
echo.
echo   请选择 pip 下载源：
echo     1）官方 PyPI（默认）
echo     2）清华镜像（国内更快）
set /p SRC="请选择（1/2，默认 1）："
if "%SRC%"=="2" set "IDX=-i https://pypi.tuna.tsinghua.edu.cn/simple"
echo   正在安装：%IDX%
%PY% -m pip --python ".venv\Scripts\python.exe" install -r requirements.txt %IDX%
if errorlevel 1 (
    echo   [X] 依赖安装失败
    echo   提示：网络问题？重新运行并选择清华镜像试试。
    pause
    exit /b 1
)
echo   [OK] 依赖安装完成

REM === 4. 准备 .env 配置 ===
echo [4/5] 正在准备 .env ...
if exist ".env" (
    echo   [OK] .env 已存在，保留现有配置
) else (
    copy /y ".env.example" ".env" >nul
    echo   [OK] 已从模板生成 .env
)

echo   正在检查 BOT_QQ 并生成 NapCat 配置 ...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" tools_gen_napcat_config.py
    if errorlevel 1 (
        echo   [WARN] NapCat 配置生成出现问题
    )
)

echo.
echo   *** 重要提示 ***
echo   请编辑 ".env" 文件，填入以下配置：
echo     - LLM_API_KEY  对话必备（DeepSeek / SiliconFlow 等平台申请）
echo     - BOT_QQ       你的 bot 小号 QQ（NapCat 快速登录用）
echo     - 其他可选：识图 / 生图 / 搜索 / 心情城市 等
echo.
echo   用记事本打开：  notepad ".env"
echo   编辑完成后按任意键继续...
pause >nul

REM === 5. 检查 NapCat ===
echo [5/5] 正在检查 NapCat ...
if exist "Napcat\NapCat.Shell.Windows.Node\napcat\launcher.bat" (
    echo   [OK] 已找到 NapCat
) else (
    echo   [WARN] 本目录未找到 NapCat。
    echo   请从 https://github.com/NapNeko/NapCatQQ/releases 下载
    echo   并解压到：  Napcat\NapCat.Shell.Windows.Node\
)

echo.
echo ==========================================
echo   安装完成！
echo.
echo   接下来：
echo     1）编辑 .env（填 LLM_API_KEY、BOT_QQ）
echo     2）本机安装 QQ 客户端，并登录 bot 小号一次
echo     3）双击 start-all.bat 启动 NapCat + Bot + WebUI
echo        管理面板：http://127.0.0.1:8800
echo ==========================================
pause