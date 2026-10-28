@echo off
setlocal
chcp 65001 >nul
color 0A
title EasyPhoto - Download and Install
set "EASYPHOTO_BOOTSTRAP=%~f0"
echo.
echo   EasyPhoto - preparing your photo studio
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$code=([regex]::Split((Get-Content -Raw -Encoding UTF8 -LiteralPath $env:EASYPHOTO_BOOTSTRAP),'(?m)^# POWERSHELL\r?$',2))[1]; & ([scriptblock]::Create($code))"
exit /b %errorlevel%
# POWERSHELL
param([switch]$CheckOnly, [string]$CacheDirectory)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'Continue'
$Release = 'https://github.com/Serkom2000/EasyPhoto/releases/download/v0.1.0/'
$Manifest = @'
{
  "archive": "EasyPhoto-Windows-Setup-20261028.zip",
  "size": 9071488335,
  "sha256": "c463cde122be0d8b60143d0a3586fc1563c4444bf92b6a6e053cf7e0d9962c53",
  "parts": [
    {
      "name": "EasyPhoto-Windows-Setup-20261028.zip.001",
      "size": 1900000000,
      "sha256": "6db521366783983b62418c2e36ff6ac6fc320d6ce85b761b5b0c8e3c8f916f2e"
    },
    {
      "name": "EasyPhoto-Windows-Setup-20261028.zip.002",
      "size": 1900000000,
      "sha256": "7e6d106d368d256349cf00460bbf8764e1e1fa2caa1c6159d9a3aabc94fbcfc9"
    },
    {
      "name": "EasyPhoto-Windows-Setup-20261028.zip.003",
      "size": 1900000000,
      "sha256": "74d1ee636e1482cc8bb8933acecbe679c65a3425a25a6c8063807f0ed1da6e46"
    },
    {
      "name": "EasyPhoto-Windows-Setup-20261028.zip.004",
      "size": 1900000000,
      "sha256": "06b370da397eeae5c64ccc6526c7cd6e568ead86269eee2a5a3186912c5ef873"
    },
    {
      "name": "EasyPhoto-Windows-Setup-20261028.zip.005",
      "size": 1471488335,
      "sha256": "0075960b053bbe08a09caf84784a37e94c9da13f70f2ac39c5727dd2e098a7f8"
    }
  ]
}
'@ | ConvertFrom-Json
if (-not $CacheDirectory) {
    $Base = if ($env:EASYPHOTO_BOOTSTRAP) { Split-Path -Parent $env:EASYPHOTO_BOOTSTRAP } else { $PSScriptRoot }
    $CacheDirectory = Join-Path $Base 'EasyPhoto-v0.1.0'
}
function Assert-File($path, $size, $hash) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Файл не найден: $path" }
    if ((Get-Item -LiteralPath $path).Length -ne $size) { throw "Неверный размер файла: $path" }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLower() -ne $hash) { throw "Контрольная сумма не совпала: $path" }
}
try {
    if ($CheckOnly) {
        foreach ($Part in $Manifest.parts) { Assert-File (Join-Path $CacheDirectory $Part.name) $Part.size $Part.sha256 }
        Write-Host 'Все пять частей проверены.' -ForegroundColor Green
        exit 0
    }
    New-Item -ItemType Directory -Force -Path $CacheDirectory | Out-Null
    $Drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($CacheDirectory)))
    if ($Drive.AvailableFreeSpace -lt 30GB) { throw 'Для загрузки и сборки комплекта нужно около 30 ГБ свободного места. Перенесите этот файл на другой диск и запустите снова.' }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Archive = Join-Path $CacheDirectory $Manifest.archive
    if (-not (Test-Path -LiteralPath $Archive)) {
        $Inputs = @()
        foreach ($Part in $Manifest.parts) {
            $Path = Join-Path $CacheDirectory $Part.name
            # Manually downloaded release parts can be placed beside the CMD.
            if (-not (Test-Path -LiteralPath $Path) -and $Base -and (Test-Path -LiteralPath (Join-Path $Base $Part.name))) { $Path = Join-Path $Base $Part.name }
            if (-not (Test-Path -LiteralPath $Path)) {
                Write-Host ("Загружаем " + $Part.name) -ForegroundColor Green
                Start-BitsTransfer -Priority Foreground -Source ($Release + $Part.name) -Destination $Path -DisplayName 'EasyPhoto: комплект с моделями'
            }
            Assert-File $Path $Part.size $Part.sha256
            $Inputs += $Path
        }
        Write-Host 'Собираем установочный архив…' -ForegroundColor Green
        $Partial = $Archive + '.assembling'
        $Output = [IO.File]::Open($Partial, [IO.FileMode]::Create, [IO.FileAccess]::Write)
        try {
            foreach ($Path in $Inputs) {
                $InputFile = [IO.File]::OpenRead($Path)
                try { $InputFile.CopyTo($Output, 4194304) } finally { $InputFile.Dispose() }
            }
        } finally { $Output.Dispose() }
        Assert-File $Partial $Manifest.size $Manifest.sha256
        Move-Item -LiteralPath $Partial -Destination $Archive
        # Only remove verified cache files created in this downloader's directory.
        foreach ($Path in $Inputs) {
            if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path)) -eq [IO.Path]::GetFullPath($CacheDirectory).TrimEnd('\')) { Remove-Item -LiteralPath $Path }
        }
    }
    Assert-File $Archive $Manifest.size $Manifest.sha256
    $Extracted = Join-Path $CacheDirectory 'unpacked'
    $Setup = Join-Path $Extracted 'EasyPhoto-Setup\EasyPhoto-Setup.exe'
    if (-not (Test-Path -LiteralPath $Setup)) {
        Write-Host 'Распаковываем комплект…' -ForegroundColor Green
        Expand-Archive -LiteralPath $Archive -DestinationPath $Extracted -Force
    }
    # The verified ZIP is temporary; the extracted package retains both models.
    Remove-Item -LiteralPath $Archive
    Write-Host 'Готово. Открываем установщик EasyPhoto.' -ForegroundColor Green
    Start-Process -FilePath $Setup -WorkingDirectory (Split-Path -Parent $Setup) -WindowStyle Normal
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    if (-not $CheckOnly) { Read-Host 'Нажмите Enter, чтобы закрыть окно. Уже скачанные целые части сохранятся' }
    exit 1
}
