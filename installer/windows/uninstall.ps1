# TapBook — uninstallation on Windows.
#   uninstall.ps1           TapBook Server: application, shortcuts, "Installed apps" entry.
#                           Documents (%USERPROFILE%\Note) are never touched; internal data
#                           (%LOCALAPPDATA%\TapBook: users, certificate) only after confirmation.
#   uninstall.ps1 -Client   TapBook Sync: also stops it and removes its automatic start. The
#                           synchronised folder is never touched; the settings (%APPDATA%\TapBook
#                           Sync: server address, this computer's access) only after confirmation.
param([switch]$Client)
$ErrorActionPreference = 'Continue'
Set-Location $env:TEMP                       # the app folder must be deletable

if ($Client) {
    $AppName = 'TapBook Sync'
    $Dest = Join-Path $env:LOCALAPPDATA 'Programs\TapBook Sync'
    $Data = Join-Path $env:APPDATA 'TapBook Sync'
    $Key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TapBook Sync'
    $DataQuestion = "Also delete the settings (server address, this computer's access)? [y/N]"
    $Kept = 'the synchronised folder and the files on the server are kept'
} else {
    $AppName = 'TapBook Server'
    $Dest = Join-Path $env:LOCALAPPDATA 'Programs\TapBook'
    $Data = Join-Path $env:LOCALAPPDATA 'TapBook'
    $Key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TapBook'
    $DataQuestion = 'Also delete the internal data (accounts, certificate installed on the iPad)? [y/N]'
    $Kept = 'documents in the Note folder are kept'
}

# "$Dest\*": TapBook Sync lives in "TapBook Sync", next to "TapBook".
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*-m app*" -and $_.ExecutablePath -like "$Dest\*" }
if ($running -and -not $Client) {
    Write-Host "TapBook Server is open: close its window (or stop the server) and run the uninstallation again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
$answer = Read-Host "Uninstall $AppName? ($Kept) [y/N]"
if ($answer -notmatch '^(y|yes)$') { Write-Host "Cancelled."; exit 0 }

if ($Client) {
    $running | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\TapBook Sync.vbs') -ErrorAction SilentlyContinue
}
$Programs = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$DesktopDir = [Environment]::GetFolderPath('Desktop')
$names = if ($Client) { @('TapBook Sync.lnk') } else { @('TapBook Server.lnk', 'TapBook.lnk') }
foreach ($n in $names) {
    Remove-Item (Join-Path $Programs $n), (Join-Path $DesktopDir $n) -ErrorAction SilentlyContinue
}
Remove-Item $Key -Recurse -ErrorAction SilentlyContinue
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }

if (Test-Path $Data) {
    $answer = Read-Host $DataQuestion
    if ($answer -match '^(y|yes)$') { Remove-Item -Recurse -Force $Data }
    else { Write-Host "Kept in $Data (used if $AppName is installed again)." }
}
Write-Host "$AppName has been uninstalled."
if ($Client) { Write-Host "On the server you can also remove this computer: tapbook device list / revoke." }
Read-Host "Press Enter to close"
