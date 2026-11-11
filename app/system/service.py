"""TapBook Server as a background service (Linux, systemd), for computers without
a screen such as a VPS: it starts when the machine starts and restarts on its
own if it stops abruptly.

It is a *user* service (~/.config/systemd/user/tapbook.service), like the rest
of the installation, which lives in the home folder: nothing runs as root.
"Lingering" keeps it running without anybody logged in.

    tapbook service enable     install, start now and at every boot
    tapbook service disable    stop and remove
    tapbook service start | stop | restart
    tapbook logs [-f]          messages of the service
"""
import getpass
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..config import PROJECT_DIR

NAME = "tapbook"
# Saving every open document when stopping may take as long as the save writer's
# limit (120 s, see model/save_worker.py): systemd waits for it before killing.
STOP_TIMEOUT = 150

UNIT = """[Unit]
Description=TapBook Server (PDF notes)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={project}
ExecStart={python} -m app serve --service
Restart=on-failure
RestartSec=5
TimeoutStopSec={stop}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


class ServiceError(Exception):
    pass


def supported() -> bool:
    return sys.platform.startswith("linux") and shutil.which("systemctl") is not None


def unit_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config_home / "systemd" / "user" / f"{NAME}.service"


def _python() -> str:
    venv = PROJECT_DIR / ".venv" / "bin" / "python"
    return str(venv if venv.exists() else Path(sys.executable))


def _user_env() -> dict:
    """systemctl --user needs the user's session bus: present when logged in over
    SSH or at the desktop, missing after «su - user». With lingering enabled the
    user's systemd runs anyway at /run/user/<uid>."""
    env = dict(os.environ)
    if not env.get("XDG_RUNTIME_DIR") and hasattr(os, "getuid"):
        runtime = Path(f"/run/user/{os.getuid()}")
        for _ in range(50):                  # just enabled: it takes a moment to appear
            if (runtime / "bus").exists():
                break
            time.sleep(0.1)
        env["XDG_RUNTIME_DIR"] = str(runtime)
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime / 'bus'}")
    return env


def _systemctl(*args, check=True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, env=_user_env())
    if check and proc.returncode != 0:
        raise ServiceError((proc.stderr or proc.stdout).strip() or f"systemctl {' '.join(args)} non riuscito")
    return proc


def installed() -> bool:
    return unit_path().is_file()


def state() -> str:
    """active, inactive, failed, activating… or "not-installed"."""
    if not supported() or not installed():
        return "not-installed"
    return _systemctl("is-active", NAME, check=False).stdout.strip() or "unknown"


def _linger_enabled(user: str) -> bool:
    proc = subprocess.run(["loginctl", "show-user", user, "--property=Linger", "--value"],
                          capture_output=True, text=True)
    return proc.stdout.strip() == "yes"


def _enable_linger(say):
    """Without lingering the service stops when the user logs out (on a VPS: when
    the SSH session ends). Allowed to the user itself on most systems; otherwise
    sudo asks for the administrator password."""
    user = getpass.getuser()
    if not shutil.which("loginctl") or _linger_enabled(user):
        return
    if subprocess.run(["loginctl", "enable-linger", user], capture_output=True).returncode == 0:
        return
    if shutil.which("sudo") and sys.stdin.isatty():
        say("Serve la password di amministratore per far girare il servizio anche senza accesso utente.")
        if subprocess.run(["sudo", "loginctl", "enable-linger", user]).returncode == 0:
            return
    say(f"ATTENZIONE: il servizio si fermerà quando esci dalla sessione. Per evitarlo: "
        f"sudo loginctl enable-linger {user}")


def enable(say=print):
    if not supported():
        raise ServiceError("Il servizio in background è disponibile solo su Linux con systemd.")
    path = unit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(UNIT.format(project=PROJECT_DIR, python=_python(), stop=STOP_TIMEOUT), encoding="utf-8")
    _enable_linger(say)                # first: it also starts the user's systemd if needed
    _systemctl("daemon-reload")
    _systemctl("enable", NAME)
    _systemctl("restart", NAME)        # restart: an update takes effect at once


def disable():
    if not supported() or not installed():
        return
    _systemctl("disable", "--now", NAME, check=False)
    unit_path().unlink(missing_ok=True)
    _systemctl("daemon-reload", check=False)


def control(action: str):
    if not installed():
        raise ServiceError("Il servizio non è installato: attivalo con  tapbook service enable")
    _systemctl(action, NAME)


def logs(lines: int = 100, follow: bool = False) -> int:
    """Shows the service messages (journalctl). Returns the exit code."""
    if not shutil.which("journalctl"):
        raise ServiceError("journalctl non disponibile su questo sistema.")
    args = ["journalctl", "--user", "-u", NAME, "-n", str(lines), "--no-pager", "-o", "short-iso"]
    if follow:
        args.append("-f")
    try:
        return subprocess.run(args, env=_user_env()).returncode
    except KeyboardInterrupt:
        return 0
