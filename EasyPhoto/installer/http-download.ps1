function Receive-EasyPhotoFile {
    param([string]$Url, [string]$Destination, [scriptblock]$Progress)
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Partial = $Destination + '.part'
    for ($Attempt = 0; $Attempt -lt 3; $Attempt++) {
        $Response = $null; $InputFile = $null; $OutputFile = $null
        try {
            $Done = if (Test-Path -LiteralPath $Partial) { (Get-Item -LiteralPath $Partial).Length } else { 0L }
            $Request = [Net.HttpWebRequest]::Create($Url)
            $Request.UserAgent = 'EasyPhoto/0.1.1'
            $Request.Timeout = 30000; $Request.ReadWriteTimeout = 90000
            if ($Done -gt 0) { $Request.AddRange([long]$Done) }
            $Response = $Request.GetResponse()
            if ([int]$Response.StatusCode -eq 206) {
                if ($Response.Headers['Content-Range'] -notmatch ('^bytes ' + $Done + '-\d+/(\d+)$')) { throw 'Сервер вернул неверный диапазон файла.' }
                $Total = [long]$Matches[1]
            } else { $Done = 0L; $Total = $Response.ContentLength }
            $Mode = if ($Done -gt 0) { [IO.FileMode]::Append } else { [IO.FileMode]::Create }
            $OutputFile = [IO.File]::Open($Partial, $Mode, [IO.FileAccess]::Write, [IO.FileShare]::Read)
            $InputFile = $Response.GetResponseStream()
            $Buffer = New-Object byte[] 1048576
            $Tick = Get-Date; $Previous = $Done
            while (($Count = $InputFile.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
                $OutputFile.Write($Buffer, 0, $Count); $Done += $Count
                $Seconds = ((Get-Date) - $Tick).TotalSeconds
                if ($Seconds -ge 1) {
                    if ($Progress) { & $Progress $Done $Total (($Done-$Previous)/$Seconds) }
                    $Previous = $Done; $Tick = Get-Date
                }
            }
            if ($Total -gt 0 -and $Done -ne $Total) { throw 'Соединение прервалось. Скачанная часть сохранена.' }
            $OutputFile.Dispose(); $OutputFile = $null
            Move-Item -LiteralPath $Partial -Destination $Destination -Force
            return
        } catch {
            if ($Attempt -eq 2) { throw }
        } finally {
            if ($InputFile) { $InputFile.Dispose() }
            if ($OutputFile) { $OutputFile.Dispose() }
            if ($Response) { $Response.Dispose() }
        }
    }
}
