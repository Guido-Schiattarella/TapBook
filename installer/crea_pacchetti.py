"""Builds the packages to distribute: dist/TapBook-<version>-linux.tar.gz and
dist/TapBook-<version>-windows.zip.

    python3 installer/crea_pacchetti.py

They contain only the application with its installer: never the data of whoever
builds them (instance/: users, keys, certificates), config.ini, the Python
environment or the documents. Whoever receives them extracts the archive and runs
the installer:
  Linux    bash install.sh
  Windows  right-click "Install TapBook.cmd" > Run as administrator
"""
import io
import re
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = (ROOT / "app" / "__init__.py").read_text()
VERSION = re.search(r'__version__ = "(.+)"', INIT).group(1)
REPOSITORY = re.search(r'__repository__ = "(.*)"', INIT).group(1)
SKIP_DIRS = {"__pycache__"}

README = {
    "linux": """TapBook {v} - Linux

Installation: open a terminal in this folder and type
    bash install.sh
The installer asks for the administrator password, checks Python 3.10+, venv and
Tk and installs whatever is missing, then adds TapBook to the applications menu.
A progress bar shows each step; the full log is saved in
~/.local/share/tapbook/install.log.

Use: open TapBook from the applications menu, press "Avvia il server" (start the
server) and open on the iPad the address shown in the window (same Wi-Fi network).
If the firewall is active, the window asks for the administrator password to open
the port to the home network only, and only while the server is running.

Update: download the new package, close TapBook and run bash install.sh again
(documents, accounts and settings are kept).
Uninstall: ~/.local/share/tapbook/uninstall.sh (documents in ~/Note are kept).
""",
    "windows": """TapBook {v} - Windows

Installation: extract the whole archive, then right-click "Install TapBook.cmd"
and choose "Run as administrator" (Windows does not start it with a plain
double-click). If Python 3.10+ is missing it is installed automatically; then
TapBook appears in the Start menu and on the desktop. A progress bar shows each
step; the full log is saved in %LOCALAPPDATA%\\Programs\\TapBook\\install.log.

Use: open TapBook, press "Avvia il server" (start the server) and open on the iPad
the address shown in the window (same Wi-Fi network). With the Windows firewall
active, Windows asks for a confirmation to open the port to the home network only.

Update: download the new package, close TapBook and run "Install TapBook.cmd"
again as administrator (documents, accounts and settings are kept).
Uninstall: Settings > Apps > Installed apps > TapBook (documents in the Note
folder are kept).
""",
}
LINUX_START = "#!/usr/bin/env bash\n# TapBook: installation on Linux.\nexec bash \"$(dirname \"$0\")/installer/linux/install.sh\" \"$@\"\n"
WINDOWS_START = ("@echo off\r\n"
                 "rem TapBook: installation on Windows. Right-click this file and choose \"Run as administrator\".\r\n"
                 "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0installer\\windows\\install.ps1\"\r\n"
                 "echo.\r\necho Press any key to close this window.\r\npause >nul\r\n")


def files(system: str):
    """(path inside the archive, file on disk) of what goes into the package."""
    for path in sorted((ROOT / "app").rglob("*")):
        if path.is_file() and not SKIP_DIRS & set(path.parts) and path.suffix != ".pyc":
            yield path.relative_to(ROOT).as_posix(), path
    for name in ("requirements.txt", "config.example.ini", "LICENSE"):
        yield name, ROOT / name
    for path in sorted((ROOT / "installer" / system).iterdir()):
        if path.is_file() and (system != "windows" or path.name != "Install TapBook.cmd"):
            yield f"installer/{system}/{path.name}", path


def build_linux(out: Path):
    base = f"TapBook-{VERSION}"
    with tarfile.open(out, "w:gz") as tar:
        def add_bytes(name, data: bytes, mode=0o644):
            info = tarfile.TarInfo(f"{base}/{name}")
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        for name, path in files("linux"):
            mode = 0o755 if path.suffix == ".sh" else 0o644
            add_bytes(name, path.read_bytes(), mode)
        add_bytes("install.sh", LINUX_START.encode(), 0o755)
        add_bytes("README.txt", README["linux"].format(v=VERSION).encode())


def build_windows(out: Path):
    base = f"TapBook-{VERSION}"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in files("windows"):
            z.write(path, f"{base}/{name}")
        z.writestr(f"{base}/Install TapBook.cmd", WINDOWS_START)
        z.writestr(f"{base}/README.txt", README["windows"].format(v=VERSION).replace("\n", "\r\n"))


def main():
    if not REPOSITORY:
        print("ATTENZIONE: __repository__ in app/__init__.py è vuoto: chi installa questi pacchetti "
              "non verrà avvisato delle nuove versioni.")
    else:
        print(f"Versione {VERSION}: pubblicala come Release con tag v{VERSION} su https://github.com/{REPOSITORY}")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    linux, windows = dist / f"TapBook-{VERSION}-linux.tar.gz", dist / f"TapBook-{VERSION}-windows.zip"
    build_linux(linux)
    build_windows(windows)
    for f in (linux, windows):
        print(f"{f.relative_to(ROOT)}  ({f.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
