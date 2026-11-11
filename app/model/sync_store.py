"""MODEL — what TapBook Sync needs on the server: the list of the user's files
with their fingerprints, and the uploads in progress.

What is synchronised: every folder and file of the user's folder except hidden
items (names starting with "."), the images folder kept by the app (pictures/
at the top) and links. These are the same rules the app uses everywhere, so the
trash (.cestino), the profile photo and the temporary files of a save in
progress never travel.

The fingerprint of a file is the SHA-256 of its content (the same "revision"
the editor uses). Computing it means reading the file, so it is remembered
together with size and modification time and recomputed only when they change
(data_dir/sync/<user>/hashes.json).

Uploads arrive in pieces and can be resumed: data_dir/sync/<user>/uploads/
<id>.part grows piece by piece, <id>.json says where it is going. When complete
and checked, the file is moved into place in a single step (os.replace), so
the app never sees half a file.
"""
import collections
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from .filesystem import PICTURES_DIR, UserFolder
from .files import atomic_write, is_link, replace
from .pdf_store import file_lock

UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
UPLOAD_EXPIRY = 24 * 3600         # an upload not completed within a day is thrown away
HASH_CHUNK = 1024 * 1024

_hash_locks: dict[str, threading.Lock] = {}
_hash_locks_guard = threading.Lock()


def _user_lock(key: str) -> threading.Lock:
    with _hash_locks_guard:
        return _hash_locks.setdefault(key, threading.Lock())


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def synced(name: str, at_root: bool) -> bool:
    """Is an item with this name part of the synchronised folder?"""
    return not name.startswith(".") and not (at_root and name == PICTURES_DIR)


class ChangeJournal:
    """The changes of one user's folder, numbered, so that a computer asks "what
    changed after number N?" and receives only those, not the whole list.

    It lives in memory: when the server restarts it gets a new `epoch` and the
    computers receive the complete list once. The folder is looked at (sizes and
    times only, see SyncStore.stamp) at most once per `refresh` interval, however
    many computers are waiting: they all share the same look."""
    KEEP = 20000                  # changes remembered; older cursors get the complete list

    def __init__(self):
        self.epoch = secrets.token_hex(6)
        self.seq = 0
        self.entries: dict | None = None
        self.stamp = None
        self.log = collections.deque()          # (number, path), numbers consecutive
        self.looked = 0.0
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)

    def refresh(self, store: "SyncStore", min_interval: float = 0.0):
        with self.lock:
            now = time.monotonic()
            if self.entries is not None and now - self.looked < min_interval:
                return
            self.looked = now
            stamp = store.stamp()
            if self.entries is not None and stamp == self.stamp:
                return
            entries = store.manifest()
            if self.entries is not None:
                for rel in sorted(entries.keys() | self.entries.keys()):
                    if entries.get(rel) != self.entries.get(rel):
                        self.seq += 1
                        self.log.append((self.seq, rel))
                while len(self.log) > self.KEEP:
                    self.log.popleft()
            self.entries, self.stamp = entries, stamp
            self.changed.notify_all()

    def cursor(self) -> str:
        return f"{self.epoch}:{self.seq}"

    def position(self, cursor) -> int | None:
        """The change number of a cursor of this journal, or None (another epoch,
        too old, damaged): then the complete list is needed."""
        if not isinstance(cursor, str) or ":" not in cursor:
            return None
        epoch, _, number = cursor.partition(":")
        if epoch != self.epoch or not number.isdigit():
            return None
        seq = int(number)
        if seq > self.seq or (self.log and seq < self.log[0][0] - 1) or (not self.log and seq != self.seq):
            return None
        return seq

    def since(self, seq: int) -> dict:
        """{path: entry, or None if it no longer exists} changed after `seq`."""
        changes = {}
        for number, rel in self.log:
            if number > seq:
                changes[rel] = self.entries.get(rel)
        return changes


class SyncStore:
    def __init__(self, folder: UserFolder, data_root: Path):
        self.folder = folder
        self.root = folder.root.resolve()
        self.data = data_root
        self.uploads = data_root / "uploads"

    # --- the list of files -------------------------------------------------------------------
    def _hash_cache(self) -> dict:
        try:
            data = json.loads((self.data / "hashes.json").read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_hash_cache(self, cache: dict):
        self.data.mkdir(parents=True, exist_ok=True)
        atomic_write(self.data / "hashes.json", json.dumps(cache, separators=(",", ":")).encode("utf-8"),
                     fsync=False)

    def stamp(self) -> str:
        """A short value that changes whenever something synchronised changes
        (names, sizes, modification times): checked often, it reads no content."""
        h = hashlib.sha256()
        for rel, kind, st in self._walk():
            h.update(f"{rel}\0{kind}\0{st.st_size if st else 0}\0{st.st_mtime_ns if st else 0}\n".encode())
        return h.hexdigest()[:32]

    def _walk(self):
        """(relative path, "d" | "f", stat) of every synchronised item."""
        for dirpath, dirnames, filenames in os.walk(self.root):
            here = Path(dirpath)
            at_root = here == self.root
            keep = []
            for d in sorted(dirnames):
                if synced(d, at_root) and not is_link(here / d):
                    keep.append(d)
                    yield (here / d).relative_to(self.root).as_posix(), "d", None
            dirnames[:] = keep
            for f in sorted(filenames):
                path = here / f
                if not synced(f, at_root) or is_link(path):
                    continue
                try:
                    st = path.stat()
                except OSError:
                    continue            # removed while walking
                yield path.relative_to(self.root).as_posix(), "f", st

    def manifest(self) -> dict:
        """{path: {"type": "dir"} | {"type": "file", "size", "mtime", "hash"}}"""
        with _user_lock(str(self.data)):
            cache = self._hash_cache()
            fresh, entries, changed = {}, {}, False
            for rel, kind, st in self._walk():
                if kind == "d":
                    entries[rel] = {"type": "dir"}
                    continue
                known = cache.get(rel)
                if isinstance(known, list) and len(known) == 3 and known[:2] == [st.st_size, st.st_mtime_ns]:
                    digest = known[2]
                else:
                    try:
                        digest = file_hash(self.root / rel)
                    except OSError:
                        continue
                    changed = True
                fresh[rel] = [st.st_size, st.st_mtime_ns, digest]
                entries[rel] = {"type": "file", "size": st.st_size, "mtime": st.st_mtime, "hash": digest}
            if changed or len(fresh) != len(cache):
                self._save_hash_cache(fresh)
            return entries

    def current_hash(self, path: Path) -> str | None:
        """Fingerprint of a file now (None if missing or a folder)."""
        if not path.is_file() or is_link(path):
            return None
        return file_hash(path)

    # --- uploads ------------------------------------------------------------------------------
    def _meta_path(self, upload_id: str) -> Path:
        if not isinstance(upload_id, str) or not UPLOAD_ID_RE.match(upload_id):
            raise FileNotFoundError(upload_id)
        return self.uploads / f"{upload_id}.json"

    def upload_info(self, upload_id: str) -> dict:
        meta_path = self._meta_path(upload_id)
        try:
            meta = json.loads(meta_path.read_text("utf-8"))
        except (OSError, ValueError):
            raise FileNotFoundError(upload_id) from None
        part = self.uploads / f"{upload_id}.part"
        meta["received"] = part.stat().st_size if part.exists() else 0
        meta["id"] = upload_id
        return meta

    def uploads_in_progress(self) -> list:
        if not self.uploads.is_dir():
            return []
        found = []
        for meta in self.uploads.glob("*.json"):
            try:
                found.append(self.upload_info(meta.stem))
            except FileNotFoundError:
                pass
        return found

    def start_upload(self, rel: str, size: int, digest: str, base, mtime, keep_previous=False) -> dict:
        """A new upload, or the one already in progress for the same file and
        content (resumed where it stopped)."""
        for info in self.uploads_in_progress():
            if info["path"] == rel and info["hash"] == digest and info["size"] == size:
                info.update(base=base, mtime=mtime, keep=bool(keep_previous))
                atomic_write(self._meta_path(info["id"]), json.dumps(
                    {k: info[k] for k in ("path", "size", "hash", "base", "mtime", "keep", "created")}).encode(),
                    fsync=False)
                return info
        self.uploads.mkdir(parents=True, exist_ok=True)
        upload_id = secrets.token_urlsafe(16)
        meta = {"path": rel, "size": size, "hash": digest, "base": base, "mtime": mtime,
                "keep": bool(keep_previous), "created": time.time()}
        atomic_write(self._meta_path(upload_id), json.dumps(meta).encode(), fsync=False)
        (self.uploads / f"{upload_id}.part").touch()
        return {**meta, "id": upload_id, "received": 0}

    def append(self, upload_id: str, offset: int, data: bytes) -> int:
        """Adds a piece; it must start exactly where the file ends (a piece sent
        twice is not written twice). Returns the bytes received so far."""
        info = self.upload_info(upload_id)
        part = self.uploads / f"{upload_id}.part"
        with _user_lock(str(part)):
            received = part.stat().st_size
            if offset != received:
                raise ValueError(received)
            if received + len(data) > info["size"]:
                raise OverflowError()
            with open(part, "ab") as fh:
                fh.write(data)
            return received + len(data)

    def finish_upload(self, upload_id: str, target: Path, expected_base) -> None:
        """Checks the complete file and puts it in place, if the file there is
        still the one the device knew (`expected_base`: its fingerprint, or None
        for a new file). Raises ValueError (incomplete or damaged) or
        FileExistsError (changed in the meantime)."""
        info = self.upload_info(upload_id)
        part = self.uploads / f"{upload_id}.part"
        if info["received"] != info["size"]:
            raise ValueError("incomplete")
        if file_hash(part) != info["hash"]:
            self.discard(upload_id)
            raise ValueError("damaged")
        with open(part, "rb+") as fh:
            os.fsync(fh.fileno())
        target.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(target):
            if target.is_dir() or is_link(target):
                raise FileExistsError(str(target))
            if self.current_hash(target) != expected_base:
                raise FileExistsError(str(target))
            if info.get("keep") and target.is_file():
                # A file moved and changed at the same time on the computer: the
                # version being replaced also stays in the trash (if the "move" was
                # really a different file, nothing is lost).
                shutil.copy2(target, self.folder.backup_path(self.folder.rel(target), "versione precedente"))
            # Copied next to the target first (same disk), then swapped in one step.
            tmp = target.parent / f".~sync-{upload_id}.tmp"
            try:
                os.replace(part, tmp) if part.stat().st_dev == target.parent.stat().st_dev \
                    else _copy(part, tmp)
                if isinstance(info.get("mtime"), (int, float)):
                    os.utime(tmp, (info["mtime"], info["mtime"]))
                replace(tmp, target)
            finally:
                if tmp.exists():
                    tmp.unlink()
        self.discard(upload_id)

    def discard(self, upload_id: str):
        for suffix in (".part", ".json"):
            (self.uploads / f"{upload_id}{suffix}").unlink(missing_ok=True)

    def expire_uploads(self, max_age: float = UPLOAD_EXPIRY):
        now = time.time()
        for info in self.uploads_in_progress():
            if now - float(info.get("created") or 0) > max_age:
                self.discard(info["id"])

    def pending_bytes(self) -> int:
        return sum(i["size"] for i in self.uploads_in_progress())


def _copy(src: Path, dst: Path):
    with open(src, "rb") as a, open(dst, "wb") as b:
        while chunk := a.read(HASH_CHUNK):
            b.write(chunk)
        b.flush()
        os.fsync(b.fileno())
    src.unlink()
