param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot 'runtime\ComfyUI_windows_portable\python_embeded\python.exe'
$ExtractorPath = Join-Path $ProjectRoot 'runtime\7zr.exe'
$MainPath = Join-Path $ProjectRoot 'runtime\ComfyUI_windows_portable\ComfyUI\main.py'
$TorchPath = Join-Path $ProjectRoot 'runtime\ComfyUI_windows_portable\python_embeded\Lib\site-packages\torch\__init__.py'
foreach ($Required in @($PythonPath, $ExtractorPath, $MainPath, $TorchPath)) {
    if (-not (Test-Path -LiteralPath $Required -PathType Leaf)) {
        throw "Offline runtime is incomplete: $Required. Run Start.bat on the build computer first."
    }
}
& $PythonPath -s (Join-Path $PSScriptRoot 'check_models.py')
if ($LASTEXITCODE -ne 0) { throw 'Bundled models are missing or corrupt. No archive was created.' }

if (-not $OutputPath) {
    $OutputPath = Join-Path $ProjectRoot ('dist\EasyPhoto-Windows-Offline-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.7z')
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $OutputPath) { throw 'The output archive already exists. Choose a new path.' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutputPath) | Out-Null
$Includes = @('app.py', 'Start.bat', 'README.md', 'WINDOWS_TEST_REPORT.md', 'extra_model_paths.yaml', 'web', 'scripts', 'tests', 'models', 'runtime')
$Excludes = @(
    '-xr!__pycache__', '-xr!.git', '-xr!*.part', '-xr!*.log',
    '-x!runtime\ComfyUI_windows_portable\ComfyUI\input',
    '-x!runtime\ComfyUI_windows_portable\ComfyUI\output',
    '-x!runtime\ComfyUI_windows_portable\ComfyUI\temp',
    '-x!runtime\ComfyUI_windows_portable\ComfyUI\user',
    '-x!runtime\ComfyUI_windows_portable\ComfyUI\models'
)
Push-Location $ProjectRoot
try {
    & $ExtractorPath a -t7z -mx=1 $OutputPath @Includes @Excludes
    if ($LASTEXITCODE -ne 0) { throw "Could not create archive: $OutputPath" }
    & $ExtractorPath t $OutputPath
    if ($LASTEXITCODE -ne 0) { throw "Archive integrity check failed: $OutputPath" }
    Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath | Format-List
    Write-Host "Offline package ready: $OutputPath" -ForegroundColor Green
} finally { Pop-Location }
