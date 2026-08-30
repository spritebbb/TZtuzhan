# Package TZtuzhan DEPLOY zip (source + NapCat binary + installer)
# Excludes: .env(secret) / QQ login data / NapCat account configs / venv / data / .git
$ErrorActionPreference = 'Stop'
$Root = 'D:\DSH\TZtuzhan'
$Version = 'v1.3.1'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$OutZip = Join-Path $Root ('TZtuzhan-deploy-' + $Version + '-' + $Stamp + '.zip')

# ---- top-level source excludes (relative to Root) ----
$SrcExcludeDirs = @('.venv', 'data', '.git', '__pycache__', 'node_modules', '.pytest_cache', 'Napcat')
$SrcExcludeFiles = @('*.zip', '.env', 'tools_*.py', '_syntax_check.py', 'commit_msg.txt', 'REPORT.md', 'TESTING.md', 'debug_cli.py', 'import_logs.py', 'napcat_probe.py', 'smoke_test.py', 'test_*.py', 'bot-design.md', 'install-watchdog.ps1', 'watchdog.ps1', 'pack-release.ps1', 'pack-deploy.ps1', 'tools_e2e_compact.py', 'tools_e2e_fun.py', 'tools_e2e_intent.py', 'tools_e2e_proactive.py', 'tools_e2e_real.py', 'tools_e2e_tool_loop.py', 'tools_e2e_topic.py', 'tools_e2e_triples.py', 'tools_list_models.py', 'tools_probe_image_models.py', 'tools_smoke_all.py', 'tools_test_mood.py', 'tools_test_schedule.py', 'tools_check_affection.py', 'tools_debug_affection.py')

# ---- NapCat specific excludes (relative to Napcat dir) ----
# keep the runtime; drop: other-platform native blobs, logs, cache, account configs,
# webui config with token/totp, QQ login state.
$NapcatRoot = 'D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node'
$NapcatExcludeNamePatterns = @('linux', 'darwin')
$NapcatExcludeRel = @(
    'napcat\logs',
    'napcat\cache',
    'napcat\config'
)
$NapcatExcludeNamePatterns2 = @('guild1', '\.db')
$NapcatKeepConfigs = @(
    'napcat.json'
)

$files = @()
# ---- collect source files ----
Get-ChildItem $Root -Recurse -File | Where-Object {
    $rel = $_.FullName.Substring($Root.Length + 1)
    $dirs = $rel -split '\\'
    $skip = $false
    foreach ($d in $dirs[0..($dirs.Length - 2)]) {
        if ($SrcExcludeDirs -contains $d) { $skip = $true; break }
    }
    if (-not $skip) {
        # keep the NapCat config generator helper despite tools_*.py exclude
        if ($_.Name -eq 'tools_gen_napcat_config.py') { $skip = $false }
        else {
            foreach ($p in $SrcExcludeFiles) {
                if ($_.Name -like $p) { $skip = $true; break }
            }
        }
    }
    -not $skip
} | ForEach-Object {
    $rel = $_.FullName.Substring($Root.Length + 1)
    $files += ,@($_.FullName, $rel)
}

# ---- collect NapCat files ----
if (Test-Path $NapcatRoot) {
    Get-ChildItem $NapcatRoot -Recurse -File | Where-Object {
        $rel = $_.FullName.Substring($NapcatRoot.Length + 1)
        $skip = $false
        # drop other-platform blobs
        foreach ($p in $NapcatExcludeNamePatterns) {
            if ($_.Name -match $p) { $skip = $true; break }
        }
        # drop QQ runtime db files (guild1.db etc, locked while running)
        if (-not $skip) {
            foreach ($p in $NapcatExcludeNamePatterns2) {
                if ($_.Name -match $p) { $skip = $true; break }
            }
        }
        # drop excluded rel dirs
        foreach ($d in $NapcatExcludeRel) {
            if ($rel -like ($d + '\*')) { $skip = $true; break }
        }
        # keep only whitelisted configs (drop account configs)
        if ($rel -like 'napcat\config\*') {
            $name = $_.Name
            if ($NapcatKeepConfigs -contains $name) { $skip = $false }
            else { $skip = $true }
        }
        -not $skip
    } | ForEach-Object {
        $rel = 'Napcat\NapCat.Shell.Windows.Node\' + $_.FullName.Substring($NapcatRoot.Length + 1)
        $files += ,@($_.FullName, $rel)
    }
}

Write-Host ('Collected ' + $files.Count + ' files')

if (Test-Path $OutZip) { Remove-Item $OutZip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($OutZip, 'Create')
try {
    foreach ($f in $files) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f[0], $f[1], 'Optimal') | Out-Null
    }
} finally {
    $zip.Dispose()
}
$size = (Get-Item $OutZip).Length
Write-Host ('Pack done: ' + $OutZip + ' (' + $size + ' bytes, ' + $files.Count + ' files)')