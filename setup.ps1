# setup.ps1 — 一键初始化 venv 并安装依赖
# 用法：
#   powershell -ExecutionPolicy Bypass -File setup.ps1          # 默认 PyPI
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Mirror  # 清华镜像（国内网络推荐）

param(
    [switch]$Mirror
)
$ErrorActionPreference = "Stop"

# 1. 找 Python 启动器（优先 py，其次 python）
$python = "py"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    $python = "python"
}

# 2. 创建 venv（用 --without-pip，再用系统 pip 引导，兼容 Python 3.14 的 ensurepip 问题）
Write-Host ">> 创建 venv ..."
& $python -m venv --without-pip .venv
if ($LASTEXITCODE -ne 0) { throw "venv 创建失败" }

$index = @()
if ($Mirror) { $index = @("-i", "https://pypi.tuna.tsinghua.edu.cn/simple") }

# 3. 把 pip 装进 venv
Write-Host ">> 引导 pip ..."
& $python -m pip --python .\.venv\Scripts\python.exe install --upgrade pip @index
if ($LASTEXITCODE -ne 0) { throw "pip 引导失败" }

# 4. 安装依赖
Write-Host ">> 安装依赖 ..."
& $python -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt @index
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }

Write-Host ""
Write-Host "完成！接下来："
Write-Host "  1. Copy-Item .env.example .env   （填写 LLM key）"
Write-Host "  2. .\.venv\Scripts\python.exe debug_cli.py --mock   （本地调试）"
Write-Host "  3. 按 napcat-guide.md 部署 NapCat 后：.\.venv\Scripts\python.exe bot.py"
