"""Security helpers: password hashing and safe path resolution."""
import base64
import hashlib
import hmac
import os
import re
import threading
import unicodedata
from pathlib import Path

# --- Passwords ------------------------------------------------------------
# scrypt (standard library, memory-hard). Format stored in the database:
#   scrypt$<n>$<r>$<p>$<salt base64>$<hash base64>
# The parameters are stored with the hash so they can be raised in the future
# without invalidating existing passwords.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
SALT_BYTES = 16
KEY_BYTES = 32
# Each scrypt computation takes 32 MB: at most 4 at a time, so a burst of
# parallel logins cannot exhaust the computer's memory (the others wait their turn).
_SCRYPT_SLOTS = threading.BoundedSemaphore(4)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    with _SCRYPT_SLOTS:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                              maxmem=SCRYPT_MAXMEM, dklen=dklen)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    key = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, KEY_BYTES)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, key_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(key_b64)
        key = _scrypt(password, salt, int(n), int(r), int(p), len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key, expected)


# Dummy hash used when the user does not exist: the login response time stays
# the same and does not reveal which usernames exist.
DUMMY_HASH = hash_password("dummy-password-for-timing")


# --- Names and paths ------------------------------------------------------
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
# Characters not allowed in file/folder names created from the web (the same
# ones Windows rejects, so documents can be copied between Linux and Windows).
_FORBIDDEN_CHARS = set('/\\:*?"<>|')
# Windows device names: "CON", "nul.pdf", "COM1.txt"... are not files but
# devices, in any folder and with any extension.
_WINDOWS_DEVICES = re.compile(r"^(con|prn|aux|nul|com[0-9¹²³]|lpt[0-9¹²³]|conin\$|conout\$)(\.|$)", re.I)


def _windows_problem(name: str) -> bool:
    """A name Windows cannot use (or would silently turn into another name):
    device names, trailing dot or space (Windows strips them)."""
    return bool(_WINDOWS_DEVICES.match(name)) or name.endswith((".", " "))


class PathError(ValueError):
    """Invalid path, or a path outside the user's folder."""


MIN_PASSWORD = 8
MAX_PASSWORD = 256


def valid_username(username: str) -> bool:
    return bool(USERNAME_RE.match(username))


def password_problem(password: str, username: str = "") -> str | None:
    """Minimum password rules (used by both the command line and web sign-up).
    Returns the reason for rejecting it, or None if the password is fine."""
    if len(password) < MIN_PASSWORD:
        return f"La password deve avere almeno {MIN_PASSWORD} caratteri."
    if len(password) > MAX_PASSWORD:
        return "Password troppo lunga."
    if username and password.lower() == username.lower():
        return "La password non può essere uguale al nome utente."
    return None


def clean_name(name: str) -> str:
    """Validates the name of a single item (file or folder) and returns it normalized."""
    if not isinstance(name, str):
        raise PathError("Nome non valido")
    name = unicodedata.normalize("NFC", name).strip()
    if not name or len(name) > 120:
        raise PathError("Il nome deve avere tra 1 e 120 caratteri")
    if name in (".", "..") or name.startswith("."):
        raise PathError("Il nome non può iniziare con un punto")
    if any(c in _FORBIDDEN_CHARS or ord(c) < 32 for c in name):
        raise PathError("Il nome contiene caratteri non ammessi")
    if _windows_problem(name):
        raise PathError("Nome riservato dal sistema o che finisce con un punto o uno spazio")
    return name


def resolve_user_path(user_root: Path, rel: str) -> Path:
    """Turns a relative path coming from the browser into an absolute Path,
    making sure it stays inside the user's folder (path traversal defence).

    Checks, in order:
      * no null bytes or backslashes;
      * no '..', '.' or hidden (starting with '.') components;
      * on Windows, no ':' (drives like "C:" or hidden streams like
        "doc.pdf:x"), device names, trailing dots or spaces;
      * the resolved path (symlinks included) must stay inside user_root;
      * the resolved path must not go through hidden items either: on
        Windows a short name like "CESTIN~1" would lead into ".cestino".
    """
    if not isinstance(rel, str) or "\x00" in rel or "\\" in rel or len(rel) > 1024:
        raise PathError("Percorso non valido")
    parts = [p for p in rel.split("/") if p != ""]
    for part in parts:
        if part in (".", "..") or part.startswith("."):
            raise PathError("Percorso non valido")
        if os.name == "nt" and (any(c in _FORBIDDEN_CHARS or ord(c) < 32 for c in part) or _windows_problem(part)):
            raise PathError("Percorso non valido")
    root = user_root.resolve()
    candidate = root.joinpath(*parts) if parts else root
    resolved = candidate.resolve()  # follows any symlinks
    if resolved != root and root not in resolved.parents:
        raise PathError("Percorso fuori dalla cartella utente")
    if any(part.startswith(".") for part in resolved.relative_to(root).parts):
        raise PathError("Percorso non valido")
    return resolved


def to_rel(user_root: Path, path: Path) -> str:
    """Relative path (with '/') to show to the browser."""
    rel = path.resolve().relative_to(user_root.resolve())
    return "" if str(rel) == "." else rel.as_posix()
