"""CONTROL — TapBook Sync: a computer keeps a folder of its own aligned with the
user's folder on the server.

The server never reaches the computer: the TapBook Sync service asks what
changed (`changes`, a request that waits until something does) and tells what
changed on its side (upload, delete, move, new folder). Every change it asks for
names the version it knew (the file's fingerprint): if in the meantime the
file changed on the server (the iPad wrote on it), the change is refused with
a conflict and the service sorts it out on its side, keeping both versions.

Rules, the same as the app's:
  * only the user's own folder, through UserFolder (paths checked by the model);
  * names valid on Windows too (clean_name), no hidden items, no pictures/;
  * nothing is ever destroyed: a deleted file goes to the app's trash;
  * a document open in the editor is not deleted or moved (as from the web):
    the service tries again later;
  * files up to max_upload_mb, uploads in progress limited per user.

Pairing: the user types name and password once in TapBook Sync; the server
answers with a random token for that computer (only its SHA-256 is stored).
The token is revoked from the terminal (tapbook device revoke), and all of the
user's tokens are revoked when the password changes.
"""
import hashlib
import re
import secrets
import threading
import time
from pathlib import Path

from ..model.filesystem import PICTURES_DIR
from ..model.sync_store import ChangeJournal, SyncStore, synced
from ..security import PathError, clean_name
from .auth import Throttle
from .errors import AlreadyExists, AuthError, ControlError, InvalidInput, NotFound
from .errors import Conflict as _Conflict

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
WAIT_MAX = 25.0                # longest wait of a `changes` request
WAIT_STEP = 1.0                # how often the folder is looked at while waiting
MAX_UPLOADS = 64               # uploads in progress per user
MAX_CHUNK = 8 * 1024 * 1024    # one piece of an upload
MAX_DEVICE_NAME = 64
SEEN_EVERY = 300               # last_seen of a device written at most every 5 minutes
BAD_TOKENS_PER_IP = (20, 300)  # wrong tokens accepted from one address every 5 minutes
MAX_WAITING = 4                # `changes` requests waiting at the same time per user


class Conflict(_Conflict):
    """The file changed on the server since the device last saw it."""
    def __init__(self, message: str, **details):
        super().__init__(message, conflict=True, **details)


class Busy(ControlError):
    """The document is open in the editor: try again later."""
    status = 423

    def __init__(self, message: str):
        super().__init__(message, busy=True)


class TooLarge(ControlError):
    status = 413


class TooMany(ControlError):
    status = 429


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _hash(value, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not HASH_RE.match(value):
        raise InvalidInput("Impronta non valida")
    return value


class SyncController:
    def __init__(self, auth, library, editing, data_root: Path, max_bytes: int):
        self.auth = auth
        self.store = auth.store
        self.library = library
        self.editing = editing
        self.data_root = data_root
        self.max_bytes = max_bytes
        self._seen: dict[int, float] = {}
        self.bad_tokens = Throttle(*BAD_TOKENS_PER_IP)
        self._waiting: dict[str, int] = {}
        self._journals: dict[str, ChangeJournal] = {}
        self._closing = False
        self._lock = threading.Lock()

    def _sync_store(self, username: str) -> SyncStore:
        return SyncStore(self.library.folder(username), self.data_root / username)

    # --- pairing and devices ---------------------------------------------------------------------
    def pair(self, username, password, device_name, ip: str) -> dict:
        """Name and password (with the same limits and locks as the login page) →
        a token for this computer."""
        if not isinstance(device_name, str) or not device_name.strip():
            raise InvalidInput("Nome del dispositivo mancante")
        name = "".join(c for c in device_name.strip() if c.isprintable())[:MAX_DEVICE_NAME] or "computer"
        user = self.auth.login(username if isinstance(username, str) else "",
                               password if isinstance(password, str) else "", ip)
        token = secrets.token_urlsafe(32)
        self.store.add_device(user["id"], name, token_hash(token))
        return {"token": token, "username": user["username"], "device": name}

    def device_user(self, token, ip: str) -> dict:
        """The user of a device token, or AuthError. An address that keeps sending
        wrong tokens is stopped for a while."""
        if self.bad_tokens.blocked(ip):
            raise AuthError("Troppi tentativi. Riprova tra qualche minuto.")
        row = None
        if isinstance(token, str) and TOKEN_RE.match(token):
            row = self.store.device_by_token(token_hash(token))
        if row is None:
            self.bad_tokens.record(ip)
            raise AuthError("Dispositivo non autorizzato")
        now = time.monotonic()
        with self._lock:
            due = now - self._seen.get(row["device_id"], -SEEN_EVERY) >= SEEN_EVERY
            if due:
                self._seen[row["device_id"]] = now
        if due:
            self.store.touch_device(row["device_id"])
        return {"username": row["username"], "device_id": row["device_id"], "device": row["name"]}

    def unpair(self, device: dict):
        self.store.delete_device(device["device_id"])

    def list_devices(self, username=None) -> list:
        return self.store.list_devices(username)

    def revoke(self, device_id: int) -> bool:
        return self.store.delete_device(device_id)

    # --- paths ------------------------------------------------------------------------------------
    def _rel(self, rel) -> str:
        """A synchronised path: every part is a valid name (as for the app),
        nothing hidden, not the images folder."""
        if not isinstance(rel, str) or not rel or len(rel) > 1024:
            raise InvalidInput("Percorso non valido")
        parts = rel.split("/")
        try:
            clean = [clean_name(p) for p in parts]
        except PathError as e:
            raise InvalidInput(f"Nome non valido: {e}")
        if clean != parts or not synced(parts[0], True) or parts[0].lower() == PICTURES_DIR:
            raise InvalidInput("Percorso non valido")
        return rel

    def _path(self, username: str, rel: str) -> Path:
        try:
            return self.library.folder(username).resolve(self._rel(rel))
        except PathError as e:
            raise InvalidInput(str(e))

    def _not_open(self, username: str, rel: str):
        if self.editing.is_open(username, rel):
            raise Busy("Documento aperto in modifica su un dispositivo: riprovo più tardi")

    # --- what is on the server ---------------------------------------------------------------------
    def _journal(self, username: str) -> ChangeJournal:
        with self._lock:
            return self._journals.setdefault(username, ChangeJournal())

    def changes(self, username: str, cursor=None, wait=False) -> dict:
        """What changed after `cursor`: {"cursor", "full": false, "changes": {path:
        entry or null}}. With a cursor of another epoch or too old, the complete
        list: {"cursor", "full": true, "entries"}. With wait, if nothing changed it
        waits (up to WAIT_MAX) for something to change."""
        store, journal = self._sync_store(username), self._journal(username)
        journal.refresh(store)
        seq = journal.position(cursor)
        if seq is not None and wait and seq == journal.seq:
            # Each waiting request holds one of the server's threads: a few per user
            # at most (one per paired computer is the normal case).
            with self._lock:
                if self._waiting.get(username, 0) >= MAX_WAITING:
                    return {"cursor": journal.cursor(), "full": False, "changes": {}}
                self._waiting[username] = self._waiting.get(username, 0) + 1
            try:
                deadline = time.monotonic() + WAIT_MAX
                while time.monotonic() < deadline and journal.seq == seq and not self._closing:
                    # The folder is looked at once per WAIT_STEP for everybody waiting.
                    journal.refresh(store, WAIT_STEP)
                    with journal.changed:
                        if journal.seq == seq:
                            journal.changed.wait(WAIT_STEP)
            finally:
                with self._lock:
                    self._waiting[username] -= 1
                    if not self._waiting[username]:
                        del self._waiting[username]
        with journal.lock:
            if seq is None:
                return {"cursor": journal.cursor(), "full": True, "entries": dict(journal.entries),
                        "maxBytes": self.max_bytes}
            return {"cursor": journal.cursor(), "full": False, "changes": journal.since(seq),
                    "maxBytes": self.max_bytes}

    def shutdown(self):
        """The server is stopping: the requests waiting for changes answer at once
        (the computers simply ask again when the server is back)."""
        self._closing = True
        with self._lock:
            journals = list(self._journals.values())
        for journal in journals:
            with journal.changed:
                journal.changed.notify_all()

    def file_path(self, username: str, rel) -> Path:
        path = self._path(username, rel)
        if not path.is_file():
            raise NotFound("File non trovato")
        return path

    # --- changes from the computer --------------------------------------------------------------------
    def make_dir(self, username: str, rel) -> dict:
        path = self._path(username, rel)
        if path.is_file():
            raise Conflict("Esiste già un file con questo nome")
        path.mkdir(parents=True, exist_ok=True)
        return {"ok": True}

    def delete(self, username: str, rel, expected_hash=None) -> dict:
        """Moves to the trash. A file only if it is still the version the device
        knew; a folder only if nothing synchronised is left in it."""
        path = self._path(username, rel)
        rel = self._rel(rel)
        if not path.exists():
            return {"ok": True, "missing": True}
        self._not_open(username, rel)
        store = self._sync_store(username)
        if path.is_dir():
            if any(synced(p.name, False) for p in path.iterdir()):
                raise Conflict("La cartella sul server contiene ancora dei file")
        elif store.current_hash(path) != _hash(expected_hash):
            raise Conflict("Il file è cambiato sul server", hash=store.current_hash(path))
        try:
            self.library.folder(username).move_to_trash(rel)
        except FileNotFoundError:
            return {"ok": True, "missing": True}
        return {"ok": True}

    def move(self, username: str, rel, target, expected_hash=None) -> dict:
        """Renamed or moved on the computer: the same on the server, without
        uploading the content again."""
        src, dst = self._path(username, rel), self._path(username, target)
        rel, target = self._rel(rel), self._rel(target)
        if not src.exists():
            raise NotFound("Elemento non trovato sul server")
        self._not_open(username, rel)
        if src.is_file() and self._sync_store(username).current_hash(src) != _hash(expected_hash):
            raise Conflict("Il file è cambiato sul server")
        try:
            self.library.folder(username).move(rel, target)
        except FileExistsError:
            raise AlreadyExists("Esiste già un elemento con questo nome sul server")
        except FileNotFoundError:
            raise NotFound("Elemento non trovato sul server")
        return {"ok": True}

    # --- uploads ------------------------------------------------------------------------------------
    def upload_start(self, username: str, rel, size, digest, base=None, mtime=None, keep_previous=False) -> dict:
        path = self._path(username, rel)
        rel = self._rel(rel)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise InvalidInput("Dimensione non valida")
        if size > self.max_bytes:
            raise TooLarge(f"File troppo grande: il limite del server è {self.max_bytes // (1024 * 1024)} MB")
        digest, base = _hash(digest), _hash(base, allow_none=True)
        if not (isinstance(mtime, (int, float)) and not isinstance(mtime, bool) and 0 < mtime < 2 ** 33):
            mtime = None
        if path.is_dir():
            raise Conflict("Sul server c'è una cartella con questo nome")
        store = self._sync_store(username)
        store.expire_uploads()
        uploads = store.uploads_in_progress()
        if len(uploads) >= MAX_UPLOADS or store.pending_bytes() + size > 4 * max(self.max_bytes, MAX_CHUNK):
            if not any(u["path"] == rel and u["hash"] == digest for u in uploads):
                raise TooMany("Troppi caricamenti in corso: riprovo più tardi")
        info = store.start_upload(rel, size, digest, base, mtime, keep_previous is True)
        return {"id": info["id"], "received": info["received"]}

    def upload_chunk(self, username: str, upload_id, offset, data: bytes) -> dict:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0 or len(data) > MAX_CHUNK:
            raise InvalidInput("Parte non valida")
        store = self._sync_store(username)
        try:
            received = store.append(upload_id, offset, data)
        except FileNotFoundError:
            raise NotFound("Caricamento non trovato")
        except ValueError as e:
            raise Conflict("Posizione non valida", received=e.args[0])
        except OverflowError:
            raise InvalidInput("Il file è più grande di quanto dichiarato")
        return {"received": received}

    def upload_finish(self, username: str, upload_id) -> dict:
        store = self._sync_store(username)
        try:
            info = store.upload_info(upload_id)
        except FileNotFoundError:
            raise NotFound("Caricamento non trovato")
        path = self._path(username, info["path"])
        try:
            store.finish_upload(upload_id, path, info.get("base"))
        except FileExistsError:
            store.discard(upload_id)
            raise Conflict("Il file è cambiato sul server mentre lo caricavo")
        except ValueError as e:
            raise InvalidInput("Caricamento incompleto" if str(e) == "incomplete" else "Caricamento danneggiato")
        # A document open in the editor sees the new version on its next save
        # (merged with what is being written on the iPad, as for any change made
        # on the computer).
        return {"ok": True, "hash": info["hash"]}
