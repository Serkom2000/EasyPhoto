$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework
$Root = Split-Path -Parent $PSScriptRoot
$Address = 'http://127.0.0.1:8787'
try { $Existing = Invoke-RestMethod "$Address/api/session" -TimeoutSec 1; if ($Existing.token) { Start-Process $Address; exit 0 } } catch {}
[xml]$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="EasyPhoto — ваша мастерская" Width="580" Height="440" ResizeMode="NoResize" WindowStartupLocation="CenterScreen" Background="#F7F8F4" FontFamily="Segoe UI" Foreground="#272D25">
 <Grid Margin="40"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions><TextBlock Text="easyphoto" Foreground="#526D3E" FontSize="28" FontWeight="Bold"/><StackPanel Grid.Row="1" VerticalAlignment="Center"><TextBlock x:Name="Heading" Text="Готовим мастерскую" FontSize="29" FontWeight="SemiBold"/><TextBlock x:Name="Detail" Text="Подключаем видеокарту и модели. Первый запуск может занять немного больше времени." TextWrapping="Wrap" FontSize="15" LineHeight="25" Foreground="#53604C" Margin="0,14,0,22"/><ProgressBar x:Name="Progress" Height="6" IsIndeterminate="True" Foreground="#526D3E" Background="#DFE6D7" BorderThickness="0"/></StackPanel><DockPanel Grid.Row="2"><TextBlock x:Name="Foot" MaxWidth="245" TextWrapping="Wrap" Margin="0,0,14,0" Text="Всё обрабатывается на вашем компьютере." VerticalAlignment="Center" FontSize="12" Foreground="#53604C"/><Button x:Name="Open" Width="165" HorizontalAlignment="Right" Content="Открыть студию" Visibility="Collapsed" DockPanel.Dock="Right" Padding="16,10" Background="#526D3E" Foreground="White" BorderThickness="0" Cursor="Hand"/></DockPanel></Grid>
</Window>
'@
$Window = [Windows.Markup.XamlReader]::Load((New-Object Xml.XmlNodeReader $Xaml))
foreach ($Name in @('Heading','Detail','Progress','Foot','Open')) { Set-Variable -Name $Name -Value $Window.FindName($Name) }
$Logs = Join-Path $Root 'data\logs'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$Args = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'start.ps1') + '" -NoBrowser'
$Worker = Start-Process powershell.exe -ArgumentList $Args -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Logs 'launcher-out.log') -RedirectStandardError (Join-Path $Logs 'launcher-error.log') -PassThru
$script:Ready = $false
$script:Checking = $false
$Open.Add_Click({ Start-Process $Address; $Window.WindowState = 'Minimized' })
$Timer = New-Object Windows.Threading.DispatcherTimer
$Timer.Interval = [TimeSpan]::FromSeconds(1)
$Timer.Add_Tick({
    if ($script:Ready -and $Worker.HasExited) { $Window.Close(); return }
    if ($script:Ready -or $script:Checking) { return }
    if ($Worker.HasExited) { $Heading.Text = 'Не удалось открыть мастерскую'; $Detail.Text = 'Подробности в data\logs\launcher-error.log. Проверьте драйвер NVIDIA и повторите запуск.'; $Progress.IsIndeterminate = $false; $Timer.Stop(); return }
    $script:Checking = $true
    try {
        $Session = Invoke-RestMethod "$Address/api/session" -TimeoutSec 1
        if ($Session.token) {
            $script:Ready = $true; $Heading.Text = 'Можно создавать'; $Detail.Text = 'Мастерская открыта в браузере. Здесь можно снова открыть студию. Закройте это окно, чтобы завершить EasyPhoto.'
            $Progress.IsIndeterminate = $false; $Progress.Value = 100; $Open.Visibility = 'Visible'
            $Foot.Text = 'Приятных экспериментов с фотографиями.'
            Start-Process $Address
        }
    } catch {} finally { $script:Checking = $false }
})
$Window.Add_Closing({param($sender,$e)
    if (-not $script:Ready -and -not $Worker.HasExited) { $e.Cancel = $true; $Foot.Text = 'Дождитесь подготовки. Это окно можно будет закрыть после запуска.'; return }
    if ($script:Ready -and -not $Worker.HasExited) {
        try { $Session = Invoke-RestMethod "$Address/api/session"; Invoke-RestMethod -Method Post -Uri "$Address/api/shutdown" -Headers @{'X-EasyPhoto-Token'=$Session.token} -ContentType 'application/json' -Body '{}' | Out-Null } catch {}
    }
})
$Timer.Start(); $Window.ShowDialog() | Out-Null; $Timer.Stop()
