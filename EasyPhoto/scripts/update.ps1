$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName System.Windows.Forms
$Root = Split-Path -Parent $PSScriptRoot
$PowerShellExe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
[xml]$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="Обновление EasyPhoto" Width="620" Height="480" ResizeMode="NoResize" WindowStartupLocation="CenterScreen" Background="#F7F8F4" Foreground="#272D25" FontFamily="Segoe UI">
 <Grid Margin="38"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions><TextBlock Text="easyphoto" Foreground="#526D3E" FontSize="28" FontWeight="Bold"/><StackPanel Grid.Row="1" VerticalAlignment="Center"><TextBlock x:Name="Heading" Text="Обновим мастерскую" FontSize="28" FontWeight="SemiBold"/><TextBlock x:Name="Detail" Text="Закройте EasyPhoto, затем нажмите «Проверить обновления». Скачаются только изменённые файлы программы. Модели, снимки и ваши настройки сохранятся." TextWrapping="Wrap" FontSize="15" LineHeight="25" Margin="0,14,0,20"/><TextBox x:Name="Folder" Padding="10" Margin="0,0,0,12"/><ProgressBar x:Name="Progress" Height="6" Minimum="0" Maximum="100" Foreground="#526D3E" Background="#DFE6D7" BorderThickness="0"/></StackPanel><DockPanel Grid.Row="2"><Button x:Name="Browse" Content="Выбрать папку" Padding="14,10" Background="#E5EBDD" BorderThickness="0"/><Button x:Name="Run" DockPanel.Dock="Right" Content="Проверить обновления" Padding="18,10" Background="#526D3E" Foreground="White" BorderThickness="0" HorizontalAlignment="Right"/></DockPanel></Grid>
</Window>
'@
$Window = [Windows.Markup.XamlReader]::Load((New-Object Xml.XmlNodeReader $Xaml))
foreach ($Name in @('Heading','Detail','Folder','Progress','Browse','Run')) { Set-Variable -Name $Name -Value $Window.FindName($Name) }
$Folder.Text = $Root
$script:Worker = $null
$script:State = $null
$Browse.Add_Click({
    $Dialog = New-Object Windows.Forms.FolderBrowserDialog
    $Dialog.SelectedPath = $Folder.Text
    if ($Dialog.ShowDialog() -eq 'OK') { $Folder.Text = $Dialog.SelectedPath }
    $Dialog.Dispose()
})
$Run.Add_Click({
    try {
        $Target = [IO.Path]::GetFullPath($Folder.Text)
        $Python = Join-Path $Target 'runtime\ComfyUI_windows_portable\python_embeded\python.exe'
        if (-not (Test-Path -LiteralPath $Python) -or -not (Test-Path -LiteralPath (Join-Path $Target 'app.py'))) { throw 'Выберите папку установленной EasyPhoto с runtime.' }
        # Covers v0.1 installations which predate the shared application lock.
        $Active = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -and ($_.Name -eq 'EasyPhoto.exe' -or $_.Name -eq 'python.exe') }
        if ($Active) { throw 'Закройте окно EasyPhoto и дождитесь остановки движка. Затем повторите проверку.' }
        $script:State = Join-Path ([IO.Path]::GetTempPath()) ('easyphoto-update-' + [Guid]::NewGuid().ToString('N') + '.json')
        $Arguments = '-I "' + (Join-Path $PSScriptRoot 'update_core.py') + '" --root "' + $Target + '" --state "' + $script:State + '"'
        $script:Worker = Start-Process -FilePath $Python -ArgumentList $Arguments -WorkingDirectory $Target -WindowStyle Hidden -PassThru
        $Run.IsEnabled = $false; $Browse.IsEnabled = $false; $Folder.IsEnabled = $false
        $Heading.Text = 'Проверяем обновления'; $Detail.Text = 'Соединяемся с GitHub…'; $Progress.IsIndeterminate = $true
    } catch { $Heading.Text = 'Пока не получилось'; $Detail.Text = $_.Exception.Message }
})
$Timer = New-Object Windows.Threading.DispatcherTimer
$Timer.Interval = [TimeSpan]::FromMilliseconds(500)
$Timer.Add_Tick({
    if (-not $script:Worker) { return }
    try {
        if (Test-Path -LiteralPath $script:State) {
            $StateValue = Get-Content -LiteralPath $script:State -Raw -Encoding UTF8 | ConvertFrom-Json
            $Heading.Text = $StateValue.phase; $Detail.Text = $StateValue.detail
            $Progress.IsIndeterminate = $false; $Progress.Value = $StateValue.percent
        }
        if ($script:Worker.HasExited) {
            if ($script:Worker.ExitCode -ne 0 -and (-not $StateValue -or $StateValue.status -ne 'error')) { $Heading.Text = 'Обновление остановлено'; $Detail.Text = 'Процесс завершился с ошибкой. Повторите проверку; незавершённое обновление будет восстановлено.' }
            $script:Worker = $null; $Run.IsEnabled = $true; $Browse.IsEnabled = $true; $Folder.IsEnabled = $true
        }
    } catch {}
})
$Window.Add_Closing({param($sender,$e) if ($script:Worker -and -not $script:Worker.HasExited) { $e.Cancel = $true; $Detail.Text = 'Дождитесь окончания обновления. Не выключайте компьютер.' }})
$Timer.Start(); $Window.ShowDialog() | Out-Null; $Timer.Stop()
