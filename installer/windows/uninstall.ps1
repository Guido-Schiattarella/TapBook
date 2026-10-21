# TapBook — uninstallation on Windows. Removes the application, shortcuts and the
# "Installed apps" entry. Documents (%USERPROFILE%\Note) are never touched; internal
# data (%LOCALAPPDATA%\TapBook: users, certificate) only after confirmation.
$ErrorActionPreference = 'Continue'
$Dest = Join-Path $env:LOCALAPPDATA 'Programs\TapBook'
$Data = Join-Path $env:LOCALAPPDATA 'TapBook'
Set-Location $env:TEMP                       # the app folder must be deletable

$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*-m app*" -and $_.ExecutablePath -like "$Dest*" }
if ($running) {
    Write-Host "TapBook is open: close its window (or stop the server) and run the uninstallation again." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
$answer = Read-Host "Uninstall TapBook? Documents in the Note folder are kept. [y/N]"
if ($answer -notmatch '^(y|yes)$') { Write-Host "Cancelled."; exit 0 }

Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\TapBook.lnk') -ErrorAction SilentlyContinue
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) 'TapBook.lnk') -ErrorAction SilentlyContinue
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TapBook' -Recurse -ErrorAction SilentlyContinue
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }

if (Test-Path $Data) {
    $answer = Read-Host "Also delete the internal data (accounts, certificate installed on the iPad)? [y/N]"
    if ($answer -match '^(y|yes)$') { Remove-Item -Recurse -Force $Data }
    else { Write-Host "Internal data kept in $Data (needed if TapBook is installed again)." }
}
Write-Host "TapBook has been uninstalled."
Read-Host "Press Enter to close"
