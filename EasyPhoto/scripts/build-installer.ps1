param([string]$OutputDirectory = 'D:\EasyPhoto-build')
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root 'runtime\ComfyUI_windows_portable\python_embeded\python.exe'
$Zip = Join-Path $Root 'runtime\7zr.exe'
& $Python -s (Join-Path $PSScriptRoot 'check_models.py')
if ($LASTEXITCODE -ne 0) { throw 'Models did not pass verification.' }
$Compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$Automation = Join-Path $env:WINDIR 'Microsoft.Net\assembly\GAC_MSIL\System.Management.Automation\v4.0_3.0.0.0__31bf3856ad364e35\System.Management.Automation.dll'
if (-not (Test-Path -LiteralPath $Compiler)) { throw 'Windows .NET Framework compiler was not found.' }
Add-Type -AssemblyName System.Drawing
$Bitmap = New-Object Drawing.Bitmap 64,64
$Graphics = [Drawing.Graphics]::FromImage($Bitmap)
$Graphics.SmoothingMode = 'AntiAlias'
$Graphics.Clear([Drawing.Color]::FromArgb(82,109,62))
$Font = New-Object Drawing.Font 'Segoe UI',46,([Drawing.FontStyle]::Bold),([Drawing.GraphicsUnit]::Pixel)
$Graphics.DrawString('e',$Font,[Drawing.Brushes]::White,8,0)
$Icon = [Drawing.Icon]::FromHandle($Bitmap.GetHicon())
$IconPath = Join-Path $Root 'installer\easyphoto.ico'
$IconStream = [IO.File]::Create($IconPath); $Icon.Save($IconStream); $IconStream.Dispose()
$Graphics.Dispose(); $Bitmap.Dispose(); $Font.Dispose()
& $Compiler /nologo /target:winexe /platform:anycpu /r:System.Windows.Forms.dll "/r:$Automation" "/win32icon:$IconPath" "/out:$Root\EasyPhoto.exe" (Join-Path $Root 'installer\Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Could not compile launcher.' }
$Build = Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) ('EasyPhoto-Setup-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path (Join-Path $Build 'installer') -Force | Out-Null
& $Compiler /nologo /target:winexe /define:SETUP /platform:anycpu /r:System.Windows.Forms.dll "/r:$Automation" "/win32icon:$IconPath" "/out:$Build\EasyPhoto-Setup.exe" (Join-Path $Root 'installer\Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Could not compile installer.' }
Copy-Item -LiteralPath $Zip -Destination (Join-Path $Build 'installer\7zr.exe')
Copy-Item -Path (Join-Path $Root 'installer\*.ps1') -Destination (Join-Path $Build 'installer')
& (Join-Path $PSScriptRoot 'build-update.ps1')
$Payload = Join-Path $Build 'payload.7z'
Push-Location $Root
try {
    & $Zip a -t7z -mx=0 $Payload app.py model_profiles.py app-version.json profiles Updater.exe EasyPhoto.exe Start.bat README.md WINDOWS_TEST_REPORT.md extra_model_paths.yaml web scripts models '-xr!__pycache__' '-xr!*.part'
    if ($LASTEXITCODE -ne 0) { throw 'Could not package application and models.' }
} finally { Pop-Location }
$Manifest = @{
    version='2026.10.28'; payloadSha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $Payload).Hash.ToLower()
    engineVersion='v0.43.0'
    engineUrl='https://github.com/Comfy-Org/ComfyUI/releases/download/v0.43.0/ComfyUI_windows_portable_nvidia_cu126.7z'
    engineSha256='691dcb5295e73594c6530ff7f3fca8dbe7dfb45114b951328c5dd3df0fff6c6b'
}
$Manifest | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Build 'package.json')
@'
EasyPhoto

Распакуйте весь архив и откройте EasyPhoto-Setup.exe.
Модели уже в комплекте. Установщик скачает движок, Python и библиотеки.
Понадобятся интернет, 18 ГБ свободного места и драйвер NVIDIA.
После установки используйте ярлык EasyPhoto на рабочем столе.
Инструкция находится в правом верхнем углу студии.
'@ | Set-Content -Encoding UTF8 (Join-Path $Build 'НАЧАТЬ ЗДЕСЬ.txt')
& $Zip t $Payload
if ($LASTEXITCODE -ne 0) { throw 'Payload integrity check failed.' }
$Build | Set-Content -Encoding UTF8 (Join-Path ([IO.Path]::GetFullPath($OutputDirectory)) 'latest-build.txt')
Write-Host "Installer folder ready: $Build" -ForegroundColor Green
