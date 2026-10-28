param([string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $Root 'dist\update' }
$Compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$Automation = Join-Path $env:WINDIR 'Microsoft.Net\assembly\GAC_MSIL\System.Management.Automation\v4.0_3.0.0.0__31bf3856ad364e35\System.Management.Automation.dll'
& $Compiler /nologo /target:winexe /define:UPDATER /platform:anycpu /r:System.Windows.Forms.dll "/r:$Automation" "/out:$Root\Updater.exe" (Join-Path $Root 'installer\Launcher.cs')
if ($LASTEXITCODE -ne 0) { throw 'Could not compile Updater.exe.' }
$Python = Join-Path $Root 'runtime\ComfyUI_windows_portable\python_embeded\python.exe'
& $Python -I (Join-Path $PSScriptRoot 'build_update.py') $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'Could not build update manifest.' }
