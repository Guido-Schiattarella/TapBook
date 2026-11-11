"""Where TapBook Sync keeps its things, readable only by the user:

  Linux    ~/.config/tapbook-sync/      (or $XDG_CONFIG_HOME/tapbook-sync)
  Windows  %APPDATA%\\TapBook Sync\\

  config.json   server address, account, folder, pause
  token         the device token received when pairing (it replaces the password,
                which is never saved); it can be revoked from the server
  ca.pem        certificate of the server trusted by the user (only for servers
                with the certificate created by TapBook)
  state-*.json  what was last aligned (one file per server + account + folder)
  status.json   what the service is doing (read by the window)
  control.json  requests of the window to the service (sync now, confirm deletions)
  service.lock  only one service at a time
"""
import hashlib
import json
import os
import socket
import tempfile
import time
from pathlib import Path


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        folder = base / "TapBook Sync"
    else:
        folder = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "tapbook-sync"
    folder.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(folder, 0o700)
    return folder


def write_json(path: Path, data, private=True):
    """Atomic write (temporary file, then replacement), mode 600."""
    fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        if private and os.name != "nt":
            os.chmod(tmp, 0o600)
        for _ in range(20):            # Windows: the reader may hold the file a moment
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                time.sleep(0.05)
        else:
            raise PermissionError(str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path, default=None):
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, type(default)) or default is None else default
    except (OSError, ValueError):
        return default


DEFAULTS = {"server": "", "folder": "", "username": "", "device": "", "paused": False}


def load() -> dict:
    data = read_json(config_dir() / "config.json", {})
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def save(settings: dict):
    write_json(config_dir() / "config.json", {k: settings.get(k, v) for k, v in DEFAULTS.items()})


def default_device_name() -> str:
    return (socket.gethostname() or "computer")[:64]


def default_folder() -> str:
    return str(Path.home() / "TapBook")


# --- device token ------------------------------------------------------------------------
def token_path() -> Path:
    return config_dir() / "token"


def load_token() -> str | None:
    try:
        token = token_path().read_text("ascii").strip()
        return token or None
    except (OSError, UnicodeDecodeError):
        return None


def save_token(token: str | None):
    path = token_path()
    if token is None:
        path.unlink(missing_ok=True)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(token)


def ca_path() -> Path:
    return config_dir() / "ca.pem"


# --- state, status, control ------------------------------------------------------------------
def state_path(settings: dict) -> Path:
    """The aligned state belongs to a server, an account and a folder: changing any
    of them starts from scratch (a merge, never a deletion)."""
    key = "\n".join((settings["server"].rstrip("/").lower(), settings["username"],
                     os.path.normcase(os.path.abspath(settings["folder"]))))
    return config_dir() / f"state-{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"


def status_path() -> Path:
    return config_dir() / "status.json"


def control_path() -> Path:
    return config_dir() / "control.json"


def send_control(**request):
    """The window asks the service something (it reads it within a second)."""
    data = read_json(control_path(), {})
    data.update(request, at=time.time())
    write_json(control_path(), data)


def normalize_server(address: str) -> str:
    address = (address or "").strip().rstrip("/")
    if address and "://" not in address:
        address = "https://" + address
    return address
