# TapBook — installation on Windows.
#
#   Right-click "Install TapBook.cmd" > Run as administrator
#   (or: powershell -ExecutionPolicy Bypass -File install.ps1)
#
# 1. looks for Python 3.10+ with Tk; if missing, installs it (winget, or the
#    official python.org installer, whose signature is checked);
# 2. copies the application to %LOCALAPPDATA%\Programs\TapBook;
# 3. prepares the app's Python environment and installs the libraries one by one;
# 4. checks that the control panel really starts (an installation that ends
#    without errors is an installation whose window opens);
# 5. creates the Start menu and desktop shortcuts, with the logo, and the entry in
#    "Installed apps" to uninstall it.
# A progress bar shows how far the installation has got, with what is happening
# underneath; the full output of every command goes to install.log in the
# installation folder. Data (users, certificate) lives in %LOCALAPPDATA%\TapBook
# and documents in %USERPROFILE%\Note: running the installation again updates the
# app without touching them.

# External programs (python, pip, winget) are checked through $LASTEXITCODE: with 'Stop'
# PowerShell 5 would treat even a plain warning printed by pip as an error.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$Src = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Dest = Join-Path $env:LOCALAPPDATA 'Programs\TapBook'
$Log = Join-Path $Dest 'install.log'
$PythonInstaller = 'https://www.python.org/ftp/python/3.13.0/python-3.13.0-amd64.exe'

# --- progress bar and log ---------------------------------------------------------------
function Write-Log($text) { Add-Content -Path $Log -Value $text -Encoding UTF8 -ErrorAction SilentlyContinue }
# One bar line per stage, the details below it.
function Progress($pct, $text) {
    $width = 30
    $filled = [int][math]::Floor($pct * $width / 100)
    $bar = ([string][char]0x2588) * $filled + ([string][char]0x2591) * ($width - $filled)
    Write-Host ""
    Write-Host -NoNewline "  "
    Write-Host -NoNewline $bar -ForegroundColor Cyan
    Write-Host (" {0,3}%  {1}" -f $pct, $text)
    Write-Log ""
    Write-Log "== $text ($pct%)"
}
function Info($text) { Write-Host "      $text" -ForegroundColor DarkGray; Write-Log $text }
function Fail($text) {
    Write-Host ""
    Write-Host "  Error: $text" -ForegroundColor Red
    if (Test-Path $Log) { Write-Host "  Full log: $Log" }
    Write-Log "Error: $text"
    exit 1
}
# Runs a program: all of its output goes to the log, the lines matching $Filter
# are shown on screen. Returns the program's exit code.
function Invoke-Logged([string]$Filter, [string]$Exe, [string[]]$Arguments) {
    Write-Log "> $Exe $($Arguments -join ' ')"
    & $Exe @Arguments 2>&1 | ForEach-Object {
        $line = "$_"
        Write-Log $line
        if ($line -match $Filter) {
            $line = $line -replace '^Requirement already satisfied: (\S+) .*', 'Already installed: $1'
            Write-Host "      $line" -ForegroundColor DarkGray
        }
    }
    return $LASTEXITCODE
}

if (-not (Test-Path (Join-Path $Src 'app\__main__.py'))) {
    Write-Host "  Error: application files not found next to the installer ($Src). Extract the whole archive first." -ForegroundColor Red
    exit 1
}
$Version = (Select-String -Path (Join-Path $Src 'app\__init__.py') -Pattern '^__version__ = "(.*)"').Matches[0].Groups[1].Value
Write-Host ""
Write-Host "  TapBook $Version - installation" -ForegroundColor Blue

# Update: the app must not be running while its files are being replaced.
$running = Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*-m app*" -and $_.ExecutablePath -like "$Dest*" }
if ($running) {
    Write-Host "  Error: TapBook is open: close its window (or stop the server) and run the installation again." -ForegroundColor Red
    exit 1
}
New-Item -ItemType Directory -Force -Path $Dest -ErrorAction Stop | Out-Null
Set-Content -Path $Log -Value "TapBook $Version installation, $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8

# --- 0. administrator ------------------------------------------------------------------
# The installer is started with "Run as administrator": it confirms the installation
# and that the computer can be administered, which TapBook also needs to open its
# port in the firewall. Started without it, Windows asks here for the administrator
# password (or a confirmation); the elevated command does nothing.
# The app itself is installed in the folders of the account signed in to Windows.
Progress 0 'Administrator'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$adminRole = [Security.Principal.WindowsBuiltInRole]::Administrator
$isAdmin = (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole($adminRole)
if ($isAdmin) {
    # Elevated with the credentials of another account, the installation would end
    # up in that account's folders and TapBook would not appear for whoever is
    # signed in.
    $signedIn = (Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue).UserName
    if ($signedIn -and $signedIn -ine $identity.Name) {
        Fail ("the installer is running as a different account from the one signed in to Windows, " +
              "so TapBook would be installed for that account. Close this window and double-click " +
              "'Install TapBook.cmd' instead: Windows will ask for the administrator password.")
    }
    Info 'Running as administrator.'
} else {
    Info 'Windows asks for the administrator password (or a confirmation).'
    try {
        $proc = Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -ArgumentList '/c', 'exit 0' `
            -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop
        if ($proc.ExitCode -ne 0) { throw "code $($proc.ExitCode)" }
    } catch {
        Fail 'administrator confirmation cancelled: installation cancelled.'
    }
    Info 'Administrator confirmed.'
}

# --- 1. Python ------------------------------------------------------------------------
$Check = "import sys, tkinter, venv; sys.exit(sys.version_info < (3, 10))"
function Find-Python {
    $candidates = @()
    foreach ($cmd in @('py', 'python')) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) { $candidates += , @($found.Source) }
    }
    # Right after an installation, this window's PATH is not up to date yet.
    $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                                 "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object { , @($_.FullName) }
    foreach ($c in $candidates) {
        $exe = $c[0]
        $extra = @()
        if ((Split-Path -Leaf $exe) -ieq 'py.exe') { $extra = @('-3') }
        # The fake "python" of the Microsoft Store (WindowsApps) opens the Store: skip it.
        if ($exe -like '*\WindowsApps\*') { continue }
        & $exe @extra -c $Check 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return , (@($exe) + $extra) }
    }
    return $null
}

Progress 10 'Checking Python'
$Python = Find-Python
if (-not $Python) {
    Info 'Python 3.10 or newer not found: installing it.'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Progress 15 'Installing Python (winget)'
        # Screen: only lines with words (winget also prints spinners and progress bars).
        Invoke-Logged '^(?!.*[▀-▟]).*\p{L}{3,}' $winget.Source @(
            'install', '--id', 'Python.Python.3.13', '-e', '--scope', 'user', '--silent',
            '--accept-package-agreements', '--accept-source-agreements') | Out-Null
    }
    $Python = Find-Python
    if (-not $Python) {
        Progress 15 'Installing Python (python.org)'
        $setup = Join-Path $env:TEMP 'python-setup.exe'
        Info "Downloading $PythonInstaller"
        try { Invoke-WebRequest -Uri $PythonInstaller -OutFile $setup -UseBasicParsing -ErrorAction Stop }
        catch { Fail 'Python could not be downloaded (an Internet connection is required).' }
        $sig = Get-AuthenticodeSignature $setup
        if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            Remove-Item $setup -Force
            Fail 'the downloaded Python installer has no valid signature from the Python Software Foundation.'
        }
        Info 'Signature of the Python Software Foundation verified. Installing...'
        Start-Process -FilePath $setup -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_tcltk=1', 'Include_launcher=1' -Wait
        Remove-Item $setup -Force
        $Python = Find-Python
    }
    if (-not $Python) { Fail 'Python could not be installed: install it from https://www.python.org/downloads/ and run the installation again.' }
}
$PyExe = $Python[0]
$PyArgs = @($Python | Select-Object -Skip 1)
$PyVersion = & $PyExe @PyArgs -c "import platform; print(platform.python_version())"
Info "Python $PyVersion with Tk found ($PyExe)."

# --- 2. application files -------------------------------------------------------------
Progress 25 "Copying the application to $Dest"
if (Test-Path "$Dest\app") { Remove-Item -Recurse -Force "$Dest\app" }       # update: the code is replaced
Copy-Item -Recurse (Join-Path $Src 'app') "$Dest\app" -ErrorAction Stop
Get-ChildItem "$Dest\app" -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Copy-Item (Join-Path $Src 'requirements.txt'), (Join-Path $Src 'config.example.ini') $Dest -Force
if ((Test-Path (Join-Path $Src 'config.ini')) -and -not (Test-Path "$Dest\config.ini")) {
    Copy-Item (Join-Path $Src 'config.ini') $Dest
    Info 'Settings (config.ini) copied.'
}
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') $Dest -Force
# Files extracted from a downloaded archive carry the "from the Internet" mark: the
# installed copy is trusted, so the mark is removed.
Get-ChildItem "$Dest\app" -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
Unblock-File -Path "$Dest\*.ps1", "$Dest\*.txt", "$Dest\*.ini" -ErrorAction SilentlyContinue
Info "$((Get-ChildItem "$Dest\app" -Recurse -File).Count) application files copied."

# --- 3. Python environment -------------------------------------------------------------
Progress 35 'Preparing the Python environment'
$VenvPy = "$Dest\.venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    Info 'Existing environment kept (update).'
} else {
    $code = Invoke-Logged '.' $PyExe ($PyArgs + @('-m', 'venv', "$Dest\.venv"))
    if ($code -or -not (Test-Path $VenvPy)) { Fail 'the Python environment could not be created.' }
    Info "Environment created in $Dest\.venv"
}
$PipShow = '^(Collecting|Downloading|Installing|Successfully|Requirement already satisfied: \S+==|ERROR|error)'
$Pip = @('-m', 'pip', 'install', '--disable-pip-version-check', '--progress-bar', 'off')
$code = Invoke-Logged $PipShow $VenvPy ($Pip + @('--upgrade', 'pip'))
if ($code) { Fail 'pip could not be updated (an Internet connection is required).' }

# One library at a time: the bar moves forward with each of them.
$Packages = @(Get-Content "$Dest\requirements.txt" | ForEach-Object { ($_ -replace '#.*', '').Trim() } | Where-Object { $_ })
for ($i = 0; $i -lt $Packages.Count; $i++) {
    $pkg = $Packages[$i]
    $name = ($pkg -split '==')[0]
    Progress ([int](40 + 40 * $i / $Packages.Count)) "Installing the libraries ($($i + 1)/$($Packages.Count)): $name"
    $code = Invoke-Logged $PipShow $VenvPy ($Pip + @($pkg))
    if ($code) { Fail "the library $name could not be installed (an Internet connection is required)." }
}

# --- 4. startup check -------------------------------------------------------------------
Progress 80 'Checking that TapBook starts'
Push-Location $Dest
Invoke-Logged '^Error' $VenvPy @('-m', 'compileall', '-q', "$Dest\app") | Out-Null     # faster first start
$code = Invoke-Logged '.' $VenvPy @('-c', 'import app, flask, cheroot, pymupdf, PIL, cryptography, tkinter')
if ($code) { Pop-Location; Fail 'the libraries were not installed correctly.' }
Info 'Libraries loaded correctly.'
$code = Invoke-Logged '.' $VenvPy @('-m', 'app', 'desktop', '--check')
Pop-Location
if ($code) { Fail 'the TapBook window does not start (details in the log).' }
Info 'The control panel opens correctly.'

# --- 5. shortcuts and uninstall entry --------------------------------------------------
Progress 90 'Creating the Start menu and desktop shortcuts'
$Icon = "$Dest\app\view\static\img\tapbook.ico"
$Shell = New-Object -ComObject WScript.Shell
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\TapBook.lnk'
$Desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'TapBook.lnk'
foreach ($path in @($StartMenu, $Desktop)) {
    $lnk = $Shell.CreateShortcut($path)
    $lnk.TargetPath = "$Dest\.venv\Scripts\pythonw.exe"       # pythonw: no black console window
    $lnk.Arguments = '-m app desktop'
    $lnk.WorkingDirectory = $Dest
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = 'TapBook: start and stop the notes server'
    $lnk.Save()
    Info "Shortcut: $path"
}
$Key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TapBook'
New-Item -Path $Key -Force | Out-Null
$size = [int]((Get-ChildItem $Dest -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
$values = @{
    DisplayName = 'TapBook'; DisplayVersion = $Version; Publisher = 'TapBook'; DisplayIcon = $Icon
    InstallLocation = $Dest; EstimatedSize = $size; NoModify = 1; NoRepair = 1
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Dest\uninstall.ps1`""
}
foreach ($name in $values.Keys) {
    $type = if ($values[$name] -is [int]) { 'DWord' } else { 'String' }
    New-ItemProperty -Path $Key -Name $name -Value $values[$name] -PropertyType $type -Force | Out-Null
}
Info 'Entry added to Settings > Apps > Installed apps.'

Progress 100 'Done'
Write-Host ""
Write-Host "  TapBook is installed." -ForegroundColor Blue
Write-Host "  Open it from the Start menu or the desktop icon. Documents: the Note folder in the home folder."
Write-Host "  To uninstall it: Settings > Apps > Installed apps > TapBook."
Write-Host "  Installation log: $Log"
Write-Host ""
