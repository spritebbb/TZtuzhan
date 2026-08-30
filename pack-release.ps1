# Package TZtuzhan v1.3.1 Release zip
# Exclude: .venv / data / Napcat / __pycache__ / old zips / .env(secret) / .git
$ErrorActionPreference = 'Stop'
$Root = 'D:\DSH\TZtuzhan'
$Version = 'v1.3.1'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$OutZip = Join-Path $Root ('TZtuzhan-' + $Version + '-' + $Stamp + '.zip')

$ExcludeDirs = @('.venv', 'data', 'Napcat', '.git', '__pycache__', 'node_modules', '.pytest_cache')
# .env(real secret) / debug scripts / old zips excluded; .env.example kept as template
$ExcludeFiles = @('*.zip', '.env', 'tools_*.py', '_syntax_check.py', 'commit_msg.txt', 'REPORT.md', 'TESTING.md')

$files = Get-ChildItem $Root -Recurse -File | Where-Object {
    $rel = $_.FullName.Substring($Root.Length + 1)
    $dirs = $rel -split '\\'
    $skip = $false
    foreach ($d in $dirs[0..($dirs.Length - 2)]) {
        if ($ExcludeDirs -contains $d) { $skip = $true; break }
    }
    if (-not $skip) {
        foreach ($p in $ExcludeFiles) {
            if ($_.Name -like $p) { $skip = $true; break }
        }
    }
    -not $skip
}

Write-Host ('Collected ' + $files.Count + ' files')

if (Test-Path $OutZip) { Remove-Item $OutZip -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($OutZip, 'Create')
try {
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($Root.Length + 1)
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $f.FullName, $rel, 'Optimal') | Out-Null
    }
} finally {
    $zip.Dispose()
}

$size = (Get-Item $OutZip).Length
Write-Host ('Pack done: ' + $OutZip + ' (' + $size + ' bytes, ' + $files.Count + ' files)')