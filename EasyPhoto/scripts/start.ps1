param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$RuntimePath = Join-Path $ProjectRoot 'runtime'
$PortablePath = Join-Path $RuntimePath 'ComfyUI_windows_portable'
$PythonPath = Join-Path $PortablePath 'python_embeded\python.exe'
$ComfyPath = Join-Path $PortablePath 'ComfyUI'
Set-Location $ProjectRoot

function Test-Comfy {
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:8188/system_stats' -TimeoutSec 3
        return $true
    } catch { return $false }
}

# Reuse an installed portable runtime, including when moved to a custom folder.
$SettingsPath = Join-Path $ProjectRoot 'data\settings.json'
if (Test-Path $SettingsPath) {
    $Settings = Get-Content -Raw -Encoding UTF8 $SettingsPath | ConvertFrom-Json
    $CandidateComfy = $Settings.comfy_path
    $CandidatePython = Join-Path (Split-Path -Parent $CandidateComfy) 'python_embeded\python.exe'
    if ((Test-Path $CandidatePython) -and (Test-Path (Join-Path $CandidateComfy 'main.py'))) {
        $PythonPath = $CandidatePython
        $ComfyPath = $CandidateComfy
        $PortablePath = Split-Path -Parent $ComfyPath
    }
}

if ((-not (Test-Path $PythonPath)) -or (-not (Test-Path (Join-Path $ComfyPath 'main.py')))) {
    Write-Host ''
    Write-Host 'EasyPhoto - first launch' -ForegroundColor Green
    Write-Host 'ComfyUI Portable includes Python and NVIDIA libraries.'
    Write-Host 'The download is several GB. Allow at least 30 GB of free space.'
    Write-Host 'An NVIDIA driver compatible with the selected build must be installed.'
    New-Item -ItemType Directory -Force -Path $RuntimePath | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Release = Invoke-RestMethod -Uri 'https://api.github.com/repos/Comfy-Org/ComfyUI/releases/latest' -Headers @{ 'User-Agent' = 'EasyPhoto' }
    # CUDA 12.6 has wider driver compatibility than the latest CUDA bundle.
    $Asset = $Release.assets | Where-Object { $_.name -eq 'ComfyUI_windows_portable_nvidia_cu126.7z' } | Select-Object -First 1
    if (-not $Asset) {
        throw 'The compatible NVIDIA portable archive was not found in the latest release. See README.md for manual installation.'
    }
    $ArchivePath = Join-Path $RuntimePath $Asset.name
    $PartialPath = "$ArchivePath.part"
    $ExtractorPath = Join-Path $RuntimePath '7zr.exe'
    if (-not (Test-Path $ArchivePath)) {
        Write-Host "Downloading ComfyUI $($Release.tag_name). Please wait..."
        # BITS supports large transfers with progress and does not buffer the archive in RAM.
        Start-BitsTransfer -Source $Asset.browser_download_url -Destination $PartialPath -DisplayName 'EasyPhoto engine'
        if ((Get-Item $PartialPath).Length -ne $Asset.size) { throw 'The archive download is incomplete. Run Start.bat again.' }
        if ($Asset.digest -and $Asset.digest.StartsWith('sha256:')) {
            $ActualHash = (Get-FileHash -Algorithm SHA256 $PartialPath).Hash.ToLower()
            if ($ActualHash -ne $Asset.digest.Substring(7)) { throw 'Archive checksum mismatch. Run Start.bat again.' }
        }
        Move-Item -Force $PartialPath $ArchivePath
    }
    if (-not (Test-Path $ExtractorPath)) {
        Start-BitsTransfer -Source 'https://www.7-zip.org/a/7zr.exe' -Destination "$ExtractorPath.part" -DisplayName '7-Zip extractor'
        Move-Item -Force "$ExtractorPath.part" $ExtractorPath
    }
    Write-Host 'Extracting the engine...'
    & $ExtractorPath x $ArchivePath "-o$RuntimePath" -y
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $PythonPath)) { throw 'Could not extract ComfyUI. See README.md.' }
    $Release.tag_name | Set-Content -Encoding UTF8 (Join-Path $RuntimePath 'engine-version.txt')
    Remove-Item $ArchivePath
}

$OwnedEngine = $null
try {
    if (-not (Test-Comfy)) {
        Write-Host 'Starting the generation engine...'
        # Pass quoted paths explicitly: Windows installations may contain spaces or Cyrillic.
        $EngineArgs = '-s "' + (Join-Path $ComfyPath 'main.py') + '" --windows-standalone-build --listen 127.0.0.1 --port 8188 --disable-auto-launch --extra-model-paths-config "' + (Join-Path $ProjectRoot 'extra_model_paths.yaml') + '"'
        $LogPath = Join-Path $ProjectRoot 'data\logs'
        New-Item -ItemType Directory -Force -Path $LogPath | Out-Null
        $OwnedEngine = Start-Process -FilePath $PythonPath -ArgumentList $EngineArgs -WorkingDirectory $ComfyPath -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogPath 'engine-out.log') -RedirectStandardError (Join-Path $LogPath 'engine-error.log') -PassThru
        $Ready = $false
        for ($Attempt = 0; $Attempt -lt 120; $Attempt++) {
            if (Test-Comfy) { $Ready = $true; break }
            if ($OwnedEngine.HasExited) { throw "The engine exited. Check $LogPath for GPU/driver errors." }
            Start-Sleep -Seconds 1
        }
        if (-not $Ready) { throw "The engine did not start in time. Check $LogPath." }
    }
    Write-Host 'Opening EasyPhoto. Keep this window open while using the studio.' -ForegroundColor Green
    $AppArgs = @('-s', (Join-Path $ProjectRoot 'app.py'))
    if ($NoBrowser) { $AppArgs += '--no-browser' }
    & $PythonPath @AppArgs
    if ($LASTEXITCODE -ne 0) { throw 'The EasyPhoto server stopped with an error.' }
} finally {
    if ($OwnedEngine -and -not $OwnedEngine.HasExited) {
        Stop-Process -Id $OwnedEngine.Id -ErrorAction SilentlyContinue
    }
}
