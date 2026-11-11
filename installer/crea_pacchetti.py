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
The installer asks what to install:
  1) TapBook Server - the notes app, used from the iPad's browser. On a computer
     with a screen it gets its control panel; on a machine without one (a VPS)
     it becomes a background service that starts with the machine.
  2) TapBook Sync - keeps a folder of this computer aligned with a TapBook Server.
If it is already installed it asks whether to update it (settings untouched) or
to install it from scratch (all the questions again; documents and accounts are
kept). It always asks for the administrator password and installs whatever is
missing (Python 3.10+, venv, Tk). The full log is saved in install.log in the
installation folder (~/.local/share/tapbook or ~/.local/share/tapbook-sync).

TapBook Server: open it from the applications menu, press "Avvia il server" and
open on the iPad the address shown in the window. On a VPS: tapbook status,
tapbook user add <name>, tapbook logs -f (see "TapBook on a VPS" in the README).
TapBook Sync: open it from the applications menu, connect the server (address,
name, password) and choose the folder.

Uninstall: ~/.local/share/tapbook/uninstall.sh (server, documents in ~/Note are
kept) or ~/.local/share/tapbook-sync/uninstall.sh (sync, the folder is kept).
""",
    "windows": """TapBook {v} - Windows

Installation: extract the whole archive, then right-click "Install TapBook.cmd"
and choose "Run as administrator" (Windows does not start it with a plain
double-click). The installer asks what to install:
  1) TapBook Server - the notes app, used from the iPad's browser, with its
     control panel;
  2) TapBook Sync - keeps a folder of this computer aligned with a TapBook Server
     (for example on a VPS).
If it is already installed it asks whether to update it (settings untouched) or
to install it from scratch (all the questions again; documents and accounts are
kept). If Python 3.10+ is missing it is installed automatically. The full log is
saved in install.log in the installation folder.

TapBook Server: open it from the Start menu, press "Avvia il server" and open on
the iPad the address shown in the window. Accounts from the terminal:
%LOCALAPPDATA%\\Programs\\TapBook\\tapbook.cmd user add <name>
TapBook Sync: open it from the Start menu, connect the server (address, name,
password) and choose the folder; it then starts at every login.

Uninstall: Settings > Apps > Installed apps > TapBook Server / TapBook Sync
(documents and the synchronised folder are kept).
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
