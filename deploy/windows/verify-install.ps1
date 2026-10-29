param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Version,
    [Parameter(Mandatory)][string]$WorkDirectory
)

$ErrorActionPreference = 'Stop'
$installed = Join-Path $env:LOCALAPPDATA 'Programs/Codex Goal Monitor'
if (Test-Path $installed) { throw '既存のインストールがあります。' }
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if ((Get-Item $runKey).GetValue('Codex Goal Monitor')) { throw '既存の自動起動登録があります。' }
New-Item -ItemType Directory -Force $WorkDirectory | Out-Null
$settings = Join-Path (Resolve-Path $WorkDirectory) 'settings.json'
'{"webhook_url":"https://discord.com/api/webhooks/123/test","sender_label":"Installer","autostart":false}' | Set-Content -Encoding utf8 $settings
$binary = Join-Path $installed 'codex-goal-monitor.exe'
$uninstaller = Join-Path $installed 'unins000.exe'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'Codex Goal Monitor.lnk'
$uninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\org.akaakuhub.codex-goal-monitor_is1'

function Invoke-CheckedProcess([string]$File, [string[]]$Arguments) {
    $process = Start-Process $File -ArgumentList $Arguments -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "$File exit=$($process.ExitCode)" }
}

try {
    foreach ($installation in 1..2) {
        Invoke-CheckedProcess $Installer @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-')
        if (-not (Test-Path $shortcut)) { throw 'スタートメニューに登録されていません。' }
        if ((Get-ItemProperty $uninstallKey).DisplayVersion -ne $Version) { throw 'インストールのバージョンが一致しません。' }
        $output = Join-Path $WorkDirectory 'version.txt'
        $process = Start-Process $binary -ArgumentList '--version' -WindowStyle Hidden -RedirectStandardOutput $output -Wait -PassThru
        if ($process.ExitCode -ne 0 -or (Get-Content $output -Raw).Trim() -ne $Version) { throw 'インストールしたアプリを実行できません。' }
        if ($installation -eq 1) {
            Invoke-CheckedProcess $binary @('--headless', '--config', "`"$settings`"", '--autostart', 'on')
        }
        if (-not (Get-Item $runKey).GetValue('Codex Goal Monitor').Contains($binary)) { throw 'インストール先からの自動起動が登録されていません。' }
        if (-not (Get-Content $settings -Raw | ConvertFrom-Json).autostart) { throw '更新時に設定が失われました。' }
    }
    $monitor = Start-Process $binary -ArgumentList '--headless', '--config', "`"$settings`"" -WindowStyle Hidden -PassThru
    try {
        Start-Sleep -Seconds 2
        if ($monitor.HasExited) { throw 'インストール後の常駐起動に失敗しました。' }
    } finally {
        if (-not $monitor.HasExited) { Stop-Process -Id $monitor.Id }
    }
    $initialSettings = Join-Path (Resolve-Path $WorkDirectory) 'first run/settings.json'
    $tray = Start-Process $binary -ArgumentList '--config', "`"$initialSettings`"" -WindowStyle Hidden -PassThru
    try {
        Start-Sleep -Seconds 2
        if ($tray.HasExited) { throw '設定が未入力の状態でトレイが終了しました。' }
        if (-not (Test-Path $initialSettings)) { throw '初回起動時の設定ファイルがありません。' }
        $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($tray.Id)"
        if ($children | Where-Object Name -EQ 'mshta.exe') { throw 'HTAダイアログが起動しました。' }
    } finally {
        if (-not $tray.HasExited) { Stop-Process -Id $tray.Id }
    }
} finally {
    if (Test-Path $uninstaller) {
        Invoke-CheckedProcess $uninstaller @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
    }
}
if (Test-Path $binary) { throw 'アプリが削除されていません。' }
if (Test-Path $shortcut) { throw 'ショートカットが削除されていません。' }
if (Test-Path $uninstallKey) { throw 'アンインストール登録が削除されていません。' }
if ((Get-Item $runKey).GetValue('Codex Goal Monitor')) { throw '自動起動登録が削除されていません。' }
if (-not (Test-Path $settings)) { throw '設定ファイルが削除されました。' }
Write-Output 'PASS: install, upgrade, version, shortcut, HKCU, headless startup, first-run tray without dialogs, uninstall, settings preserved'
