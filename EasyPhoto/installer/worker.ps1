param([string]$Source, [string]$Target, [string]$State)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'http-download.ps1')
$script:CurrentPhase = 'Проверка условий установки'
function Update-State($phase, $detail, $percent, $status = 'working') {
    $script:CurrentPhase = $phase
    @{phase=$phase; detail=$detail; percent=$percent; status=$status} | ConvertTo-Json | Set-Content -Encoding UTF8 -LiteralPath "$State.tmp"
    Move-Item -Force -LiteralPath "$State.tmp" -Destination $State
}
function Assert-Hash($path, $hash) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLower() -ne $hash) { throw "Файл повреждён: $(Split-Path -Leaf $path). Распакуйте установочный архив заново." }
}
try {
    $Target = [IO.Path]::GetFullPath($Target)
    $Manifest = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Source 'package.json') | ConvertFrom-Json
    $Marker = Join-Path $Target '.easyphoto-installing'
    if ((Test-Path -LiteralPath $Target) -and (Get-ChildItem -Force -LiteralPath $Target | Select-Object -First 1) -and -not (Test-Path -LiteralPath $Marker)) {
        throw 'Выберите пустую папку. Существующие файлы и фотографии не будут перезаписаны.'
    }
    if ((Test-Path -LiteralPath $Marker) -and (Get-Content -Raw -LiteralPath $Marker).Trim() -ne $Manifest.payloadSha256) { throw 'Здесь уже начата установка другой версии. Выберите новую пустую папку.' }
    $Drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($Target))
    if ($Drive.AvailableFreeSpace -lt 18GB) { throw 'Для установки нужно минимум 18 ГБ свободного места. Выберите другой диск.' }
    Update-State 'Проверяем комплект' 'Сверяем целостность приложения и моделей. Это может занять минуту.' 5
    $Payload = Join-Path $Source 'payload.7z'
    Assert-Hash $Payload $Manifest.payloadSha256
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $Manifest.payloadSha256 | Set-Content -LiteralPath $Marker -Encoding ASCII
    $Extract = Join-Path $Source 'installer\7zr.exe'
    Update-State 'Добавляем приложение и модели' 'Две модели уже в архиве — повторно скачивать их не нужно.' 15
    & $Extract x $Payload "-o$Target" -y | Out-File -Append -Encoding UTF8 "$State.log"
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось распаковать комплект. Проверьте свободное место и повторите установку.' }
    $Runtime = Join-Path $Target 'runtime'
    New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
    Copy-Item -LiteralPath $Extract -Destination (Join-Path $Runtime '7zr.exe') -Force
    $Archive = Join-Path $Runtime 'engine.7z'
    $Python = Join-Path $Runtime 'ComfyUI_windows_portable\python_embeded\python.exe'
    $EngineMain = Join-Path $Runtime 'ComfyUI_windows_portable\ComfyUI\main.py'
    $VersionFile = Join-Path $Runtime 'engine-version.txt'
    $Prepared = (Test-Path -LiteralPath $Python) -and (Test-Path -LiteralPath $EngineMain) -and (Test-Path -LiteralPath $VersionFile)
    if ($Prepared) { $Prepared = (Get-Content -Raw -LiteralPath $VersionFile).Trim() -eq $Manifest.engineVersion }
    if ($Prepared) {
        Update-State 'Проверяем готовый движок' 'Используем уже подготовленные Python и библиотеки этой версии.' 78
        & $Python -s -c 'import torch; import PIL' 2>&1 | Out-File -Append -Encoding UTF8 "$State.log"
        $Prepared = $LASTEXITCODE -eq 0
    }
    if (-not $Prepared) {
    if (-not (Test-Path -LiteralPath $Archive)) {
        Update-State 'Скачиваем движок' 'Прямая загрузка без службы BITS. Модели повторно не скачиваются.' 30
        Receive-EasyPhotoFile -Url $Manifest.engineUrl -Destination $Archive -Progress {
            param($Done, $Total, $Speed)
            $Fraction = if ($Total -gt 0) { $Done / $Total } else { 0 }
            Update-State 'Скачиваем движок' ('{0:N1}% · {1:N1} МБ · {2:N0} КБ/с' -f ($Fraction*100),($Done/1MB),($Speed/1KB)) (30 + 40*$Fraction)
        }
    }
    Update-State 'Проверяем движок' 'Проверка SHA-256 перед установкой.' 72
    try { Assert-Hash $Archive $Manifest.engineSha256 } catch { Remove-Item -LiteralPath $Archive -Force; throw }
    Update-State 'Готовим вашу мастерскую' 'Распаковываем Python и библиотеки. Вручную устанавливать ничего не нужно.' 78
    & $Extract x $Archive "-o$Runtime" -y | Out-File -Append -Encoding UTF8 "$State.log"
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось распаковать движок. Проверьте свободное место и повторите установку.' }
    }
    $Python = Join-Path $Runtime 'ComfyUI_windows_portable\python_embeded\python.exe'
    if (-not (Test-Path -LiteralPath $Python)) { throw 'В комплекте движка не найден Python. Повторите установку.' }
    Update-State 'Проверяем модели' 'Осталось проверить оба файла и добавить ярлык на рабочий стол.' 94
    & $Python -s (Join-Path $Target 'scripts\check_models.py') | Out-File -Append -Encoding UTF8 "$State.log"
    if ($LASTEXITCODE -ne 0) { throw 'Модель повреждена. Распакуйте установочный архив заново.' }
    $Manifest.engineVersion | Set-Content -Encoding UTF8 (Join-Path $Runtime 'engine-version.txt')
    Update-State 'Создаём ярлык' 'Проверки завершены, добавляем ярлык на рабочий стол.' 97
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'EasyPhoto.lnk'))
    $Shortcut.TargetPath = Join-Path $Target 'EasyPhoto.exe'
    $Shortcut.WorkingDirectory = $Target
    $Shortcut.IconLocation = (Join-Path $Target 'EasyPhoto.exe') + ',0'
    $Shortcut.Save()
    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
    Remove-Item -LiteralPath $Marker -Force
    Update-State 'Всё готово к первому кадру' 'EasyPhoto установлен. Открывайте его ярлыком на рабочем столе — дальше интернет не нужен.' 100 'done'
 } catch {
    $Failure = $_
    $FailedPhase = $script:CurrentPhase
    ($Failure | Format-List * -Force | Out-String) | Add-Content -Encoding UTF8 -LiteralPath "$State.log"
    $Failure.Exception.ToString() | Add-Content -Encoding UTF8 -LiteralPath "$State.log"
    Update-State 'Установка не завершена' ("Этап: $FailedPhase. " + $Failure.Exception.Message) 0 'error'
    exit 1
}
