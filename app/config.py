"""Application configuration.

Values are read in this order of priority:
  1. environment variables (NOTES_*)
  2. config.ini in the project folder (or the file named by NOTES_CONFIG)
  3. the defaults below
"""
import configparser
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _default_data_dir() -> Path:
    """Internal data (session key, database, certificates). On Linux it lives in
    the project folder, protected with mode 700. On Windows Unix-style
    permissions do not apply, so the user's own data folder is used
    (%LOCALAPPDATA%\\TapBook), which Windows already keeps private."""
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "TapBook"
    return PROJECT_DIR / "instance"


DEFAULTS = {
    "notes_root": str(Path.home() / "Note"),
    "data_dir": str(_default_data_dir()),
    "host": "0.0.0.0",
    "port": "8000",
    "session_hours": "12",
    "max_upload_mb": "100",
    "allow_registration": "true",
    "edit_idle_minutes": "15",
    "https": "true",
    "firewall": "auto",
    "update_check": "true",
    "update_repository": "",
}


@dataclass(frozen=True)
class Config:
    notes_root: Path
    data_dir: Path
    host: str
    port: int
    session_hours: int
    max_upload_mb: int
    allow_registration: bool
    edit_idle_minutes: float
    https: bool
    firewall: str = "auto"
    update_check: bool = True
    update_repository: str = ""


def _path(value: str) -> Path:
    """Relative paths are relative to the project folder, not to the current directory."""
    p = Path(value).expanduser()
    return (p if p.is_absolute() else PROJECT_DIR / p).resolve()


def _flag(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "si", "sì", "on")


def _firewall_mode(value: str) -> str:
    """auto (default), on (even when no firewall is detected) or off."""
    value = value.strip().lower()
    if value in ("off", "false", "no", "0"):
        return "off"
    return "on" if value in ("on", "true", "yes", "si", "sì", "1") else "auto"


def load_config() -> Config:
    values = dict(DEFAULTS)
    ini_path = Path(os.environ.get("NOTES_CONFIG", PROJECT_DIR / "config.ini"))
    if ini_path.is_file():
        parser = configparser.ConfigParser()
        parser.read(ini_path, encoding="utf-8")
        for section in parser.sections():
            for key, value in parser.items(section):
                if key in values:
                    values[key] = value
    for key in values:
        env = os.environ.get("NOTES_" + key.upper())
        if env is not None:
            values[key] = env

    return Config(
        notes_root=_path(values["notes_root"]),
        data_dir=_path(values["data_dir"]),
        host=values["host"],
        port=int(values["port"]),
        session_hours=int(values["session_hours"]),
        max_upload_mb=int(values["max_upload_mb"]),
        edit_idle_minutes=float(values["edit_idle_minutes"]),
        https=_flag(values["https"]),
        allow_registration=_flag(values["allow_registration"]),
        firewall=_firewall_mode(values["firewall"]),
        update_check=_flag(values["update_check"]),
        update_repository=values["update_repository"].strip(),
    )
