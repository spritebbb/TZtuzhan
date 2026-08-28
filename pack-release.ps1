# 打包 TZtuzhan v1.2.0 Release zip
# 排除：.venv / data / Napcat / __pycache__ / 旧zip / .env(密钥) / .git
$ErrorActionPreference = 'Stop'
$Root = 'D:\DSH\TZtuzhan'
$Version = 'v1.2.0'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$OutZip = Join-Path $Root "TZtuzhan-$Version-$Stamp.zip"

$ExcludeDirs = @('.venv', 'data', 'Napcat', '.git', '__pycache__', 'node_modules', '.pytest_cache')
$ExcludeFiles = @('*.zip', '.env', '.env.example')

# 收集要打包的文件（相对路径）
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

Write-Host "收集到 $($files.Count) 个文件"

# 删除旧 zip
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
Write-Host "✅ 打包完成: $OutZip ($size 字节, $($files.Count) 个文件)"
