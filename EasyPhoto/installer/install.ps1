$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName PresentationFramework, System.Windows.Forms
$Source = Split-Path -Parent $PSScriptRoot
[xml]$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="Установка EasyPhoto" Width="820" Height="570" ResizeMode="NoResize" WindowStartupLocation="CenterScreen" Background="#F7F8F4" FontFamily="Segoe UI" Foreground="#272D25">
 <Window.Resources><Style TargetType="Button"><Setter Property="Padding" Value="22,12"/><Setter Property="Cursor" Value="Hand"/><Setter Property="FontSize" Value="14"/><Setter Property="BorderThickness" Value="0"/><Setter Property="Background" Value="#526D3E"/><Setter Property="Foreground" Value="White"/><Setter Property="Template"><Setter.Value><ControlTemplate TargetType="Button"><Border Background="{TemplateBinding Background}" CornerRadius="8" Padding="{TemplateBinding Padding}"><ContentPresenter HorizontalAlignment="Center"/></Border><ControlTemplate.Triggers><Trigger Property="IsMouseOver" Value="True"><Setter Property="Opacity" Value="0.85"/></Trigger><Trigger Property="IsEnabled" Value="False"><Setter Property="Opacity" Value="0.55"/></Trigger><Trigger Property="IsKeyboardFocused" Value="True"><Setter Property="BorderThickness" Value="2"/></Trigger></ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter></Style></Window.Resources>
 <Grid><Grid.ColumnDefinitions><ColumnDefinition Width="235"/><ColumnDefinition/></Grid.ColumnDefinitions>
  <Border Background="#E9EEDf" Padding="30,40"><Grid><StackPanel><TextBlock Text="easyphoto" FontSize="28" FontWeight="Bold" Foreground="#405A30"/><TextBlock Text="Ваша фотомастерская" Margin="0,9,0,0" FontSize="14"/><TextBlock Text="От идеи&#10;к кадру." Margin="0,60,0,18" FontSize="30" FontWeight="SemiBold" TextWrapping="Wrap"/><TextBlock Text="Создавайте новое.&#10;Меняйте любимые кадры.&#10;Без сложных настроек." FontSize="14" LineHeight="24" TextWrapping="Wrap"/></StackPanel><TextBlock Text="Фотографии остаются&#10;на вашем компьютере." VerticalAlignment="Bottom" FontSize="12" Foreground="#4E6045"/></Grid></Border>
  <Grid Grid.Column="1" Margin="36,40"><Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
   <TextBlock x:Name="Heading" Text="Начнём с установки" FontSize="27" FontWeight="SemiBold"/>
   <TextBlock Grid.Row="1" x:Name="Intro" Text="Модели уже в комплекте. Движок, Python и библиотеки скачаются и установятся автоматически." TextWrapping="Wrap" FontSize="14" LineHeight="23" Margin="0,14,0,26" Foreground="#53604C"/>
   <StackPanel Grid.Row="2"><TextBlock Text="Папка для EasyPhoto" FontSize="13" Margin="0,0,0,8"/><DockPanel><Button x:Name="Browse" DockPanel.Dock="Right" Content="Выбрать" Background="#E5EBDf" Foreground="#34462C" Padding="14,10" Margin="8,0,0,0"/><TextBox x:Name="Folder" FontSize="13" Padding="10" VerticalContentAlignment="Center" BorderBrush="#CAD4C0"/></DockPanel><TextBlock x:Name="Note" Text="Нужно 18 ГБ свободного места, интернет для установки и видеокарта NVIDIA с установленным драйвером." TextWrapping="Wrap" FontSize="12" Foreground="#53604C" LineHeight="20" Margin="0,12,0,28"/><TextBlock x:Name="Phase" Text="Один раз установить — и дальше только создавать." TextWrapping="Wrap" FontSize="15" FontWeight="SemiBold"/><ProgressBar x:Name="Progress" Height="7" Minimum="0" Maximum="100" Value="0" Foreground="#526D3E" Background="#DFE6D7" BorderThickness="0" Margin="0,16,0,12"/><TextBlock x:Name="Detail" Text="Установка не затронет системный Python и другие программы." FontSize="12" TextWrapping="Wrap" LineHeight="20" Foreground="#53604C"/></StackPanel>
   <DockPanel Grid.Row="3" Margin="0,22,0,0"><Button x:Name="Log" Content="Журнал" Background="Transparent" Foreground="#526D3E" Padding="0,12" Visibility="Collapsed" DockPanel.Dock="Left"/><Button x:Name="Action" Content="Установить EasyPhoto" HorizontalAlignment="Right"/></DockPanel>
  </Grid>
 </Grid>
</Window>
'@
$Window = [Windows.Markup.XamlReader]::Load((New-Object Xml.XmlNodeReader $Xaml))
foreach ($Name in @('Heading','Intro','Folder','Browse','Note','Phase','Progress','Detail','Action','Log')) { Set-Variable -Name $Name -Value $Window.FindName($Name) }
$Folder.Text = Join-Path $env:LOCALAPPDATA 'EasyPhoto'
$script:Worker = $null; $script:Installed = $false
$State = Join-Path ([IO.Path]::GetTempPath()) ('EasyPhoto-setup-' + [guid]::NewGuid().ToString() + '.json')
$Browse.Add_Click({$Dialog = New-Object System.Windows.Forms.FolderBrowserDialog; $Dialog.Description = 'Выберите папку для EasyPhoto'; if ($Dialog.ShowDialog() -eq 'OK') { $Folder.Text = Join-Path $Dialog.SelectedPath 'EasyPhoto' }})
$Log.Add_Click({ if (Test-Path "$State.log") { Start-Process notepad.exe -ArgumentList ('"' + "$State.log" + '"') } else { Start-Process notepad.exe -ArgumentList ('"' + $State + '"') } })
$Action.Add_Click({
    if ($script:Worker -and -not $script:Worker.HasExited) { return }
    if ($script:Installed) { Start-Process -FilePath (Join-Path $Folder.Text 'EasyPhoto.exe') -WorkingDirectory $Folder.Text; $Window.Close(); return }
    if ($Folder.Text -match '["\r\n]' -or -not [IO.Path]::IsPathRooted($Folder.Text)) { $Detail.Text = 'Выберите полный путь к папке с помощью кнопки «Выбрать».'; return }
    Remove-Item -LiteralPath $State -Force -ErrorAction SilentlyContinue
    $Log.Visibility = 'Collapsed'; $Phase.Text = 'Начинаем установку'; $Detail.Text = 'Проверяем папку и файлы комплекта.'
    $Folder.IsEnabled = $false; $Browse.IsEnabled = $false; $Action.IsEnabled = $false; $Action.Content = 'Устанавливаем…'; $Progress.IsIndeterminate = $true
    $Args = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot 'worker.ps1') + '" -Source "' + $Source + '" -Target "' + $Folder.Text.TrimEnd('\') + '" -State "' + $State + '"'
    $script:Worker = Start-Process powershell.exe -ArgumentList $Args -WindowStyle Hidden -PassThru
})
$Timer = New-Object Windows.Threading.DispatcherTimer
$Timer.Interval = [TimeSpan]::FromMilliseconds(400)
$Timer.Add_Tick({
    if (Test-Path -LiteralPath $State) {
        try {
            $Status = Get-Content -Raw -Encoding UTF8 -LiteralPath $State | ConvertFrom-Json
            $Phase.Text = $Status.phase; $Detail.Text = $Status.detail
            $Progress.IsIndeterminate = $Status.status -eq 'working' -and $Status.phase -ne 'Скачиваем движок'
            $Progress.Value = $Status.percent
            if ($Status.status -eq 'done') { $script:Installed = $true; $Action.IsEnabled = $true; $Action.Content = 'Открыть мастерскую'; $Heading.Text = 'Добро пожаловать'; $Timer.Stop() }
            if ($Status.status -eq 'working') { $Action.IsEnabled = $false; $Action.Content = 'Устанавливаем…'; $Folder.IsEnabled = $false; $Browse.IsEnabled = $false }
            if ($Status.status -eq 'error' -and $script:Worker -and $script:Worker.HasExited) { $Folder.IsEnabled = $true; $Browse.IsEnabled = $true; $Action.IsEnabled = $true; $Action.Content = 'Повторить установку'; $Log.Visibility = 'Visible' }
        } catch {}
    }
    if ($script:Worker -and $script:Worker.HasExited -and -not (Test-Path -LiteralPath $State)) { $Detail.Text = 'Не удалось запустить установку. Проверьте доступ к выбранной папке.'; $Action.IsEnabled = $true; $Folder.IsEnabled = $true; $Browse.IsEnabled = $true }
})
$Window.Add_Closing({param($sender,$e) if ($script:Worker -and -not $script:Worker.HasExited) { $e.Cancel = $true; $Note.Text = 'Дождитесь завершения текущего этапа. После ошибки можно повторить установку или закрыть окно.' }})
$Timer.Start(); $Window.ShowDialog() | Out-Null; $Timer.Stop()
