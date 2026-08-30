# check-update.ps1 - Check TZtuzhan for GitHub updates (ASCII only, no encoding issues)
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File check-update.ps1
# Exit codes:
#   0 = up to date (or first-run just synced) -> start bot
#   1 = update available -> ask user in the .bat
#   2 = check skipped (no git / no network)  -> start bot without update
# The .bat decides what to do; this script only checks and reports.
$ErrorActionPreference = 'SilentlyContinue'
$Root = $PSScriptRoot
Set-Location $Root

# --- 1. git present? ---
git --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[update] git not found - skip version check'
    exit 2
}

# --- 2. init repo if this is a deployment package (no .git) ---
if (-not (Test-Path (Join-Path $Root '.git'))) {
    git init | Out-Null
    git remote add origin 'https://github.com/spritebbb/TZtuzhan.git' 2>$null
}

# --- 3. fetch (network needed; on failure just skip) ---
git fetch origin --quiet --tags 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[update] fetch failed (network?) - skip version check'
    exit 2
}

# --- 4. first run after init: sync to latest then treat as up-to-date ---
$local = git rev-parse HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or -not $local) {
    git checkout -f -B main origin/main 2>$null
    $ver = git describe --tags --always
    Write-Host "[update] first-run: synced to latest ($ver)"
    exit 0
}

# --- 5. compare local HEAD vs origin/main ---
$remote = git rev-parse origin/main
$localTag = git describe --tags --always
$remoteTag = git describe --tags --always origin/main
Write-Host "[update] local=$localTag  remote=$remoteTag"
if ($local -eq $remote) {
    exit 0
}
exit 1
