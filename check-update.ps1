# check-update.ps1 - 检查菟菚 GitHub 更新
# 用法:  powershell -NoProfile -ExecutionPolicy Bypass -File check-update.ps1
# 退出码:
#   0 = 已是最新（或首次运行已同步）-> 启动 bot
#   1 = 有更新 -> 由 .bat 询问用户
#   2 = 检查被跳过（无 git / 无网络）-> 直接启动 bot
$ErrorActionPreference = 'SilentlyContinue'
$Root = $PSScriptRoot
Set-Location $Root

# --- 1. 是否有 git ---
git --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[更新检查] 未找到 git - 跳过版本检查'
    exit 2
}

# --- 2. 若是部署包（无 .git）则初始化仓库 ---
if (-not (Test-Path (Join-Path $Root '.git'))) {
    git init | Out-Null
    git remote add origin 'https://github.com/spritebbb/TZtuzhan.git' 2>$null
}

# --- 3. 拉取（需要网络；失败则跳过）---
git fetch origin --quiet --tags 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[更新检查] 拉取失败（网络问题？）- 跳过版本检查'
    exit 2
}

# --- 4. 初始化后首次运行：同步到最新后视为已最新 ---
$local = git rev-parse HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or -not $local) {
    git checkout -f -B main origin/main 2>$null
    $ver = git describe --tags --always
    Write-Host "[更新检查] 首次运行：已同步到最新（$ver）"
    exit 0
}

# --- 5. 比较本地 HEAD 与 origin/main ---
$remote = git rev-parse origin/main
$localTag = git describe --tags --always
$remoteTag = git describe --tags --always origin/main
Write-Host "[更新检查] 本地=$localTag  远程=$remoteTag"
if ($local -eq $remote) {
    exit 0
}
exit 1