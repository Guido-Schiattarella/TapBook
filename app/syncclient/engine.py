"""TapBook Sync — the comparison between this computer and the server, and the
operations that align them.

Three lists are compared, item by item:
  local   what is in the folder now
  remote  what is on the server now
  base    how the two were the last time they were aligned (state-*.json)
The base tells who changed what: a file equal to the base on this computer but
different on the server was changed on the server (download it); the opposite
was changed here (upload it); missing on one side and unchanged on the other
was deleted there (delete it here too). Without the base a deletion could not
be told from a new file.

Safety rules:
  * a file changed on both sides is never overwritten: this computer's version
    is renamed "name (conflitto <computer> <date>).ext" and both are kept;
  * a change wins over a deletion (deleted here, changed on the iPad: it comes back);
  * deleted files do not disappear: on this computer they go to the hidden
    folder .tapbook-sync/cestino (kept CESTINO_DAYS days), on the server to the
    app's trash;
  * if many files are about to be deleted at once (more than DELETE_BRAKE),
    nothing is deleted until the user confirms in the window: a folder that was
    unplugged, emptied or moved by mistake does not empty the server;
  * a missing folder is an error, never "everything deleted";
  * a file just modified (still being written) waits for the next round;
  * every operation on the server names the version it knew: if meanwhile it
    changed there, it is refused and the next round sorts it out.
Moves and renames are recognised, so nothing is transferred again: on this
computer by the file's identity on disk (the inode, which a rename keeps; it also
recognises a whole folder renamed, moved on the server in one step, and a file
moved and changed at the same time), and by the fingerprint otherwise.

Windows does not tell "Appunti.pdf" from "appunti.pdf"; the server (Linux) does.
Two items whose names differ only in capitals are never mixed up: the same
content takes the server's name, a different one is kept as a conflict copy.
"""
import datetime as dt
import hashlib
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path

from ..security import PathError, clean_name
from .api import ApiError, Offline

HIDDEN = ".tapbook-sync"           # in the synchronised folder: local trash and downloads in progress
PICTURES_DIR = "pictures"          # kept by the app on the server, not synchronised
CESTINO_DAYS = 30
SETTLE_SECONDS = 2.0               # a file modified less than this ago is still being written
DELETE_BRAKE = (10, 0.30)          # more than 10 files and more than 30% of them: ask first
TEMP_PREFIXES = ("~$", ".~")       # Office lock files, temporary files
TEMP_SUFFIXES = (".tmp", ".part", ".crdownload", ".partial", ".swp")


class FolderMissing(Exception):
    pass


HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def clean_remote(entries) -> tuple[dict, list]:
    """The server's list, trusted only as far as it is valid: a damaged or hostile
    server could send paths like "../../.bashrc"; they are never used."""
    good, bad = {}, []
    if not isinstance(entries, dict):
        return good, bad
    for rel, e in entries.items():
        if not isinstance(rel, str) or not isinstance(e, dict) or not valid_rel(rel):
            bad.append(str(rel)[:80])
            continue
        if e.get("type") == "dir":
            good[rel] = {"type": "dir"}
        elif (e.get("type") == "file" and isinstance(e.get("hash"), str) and HASH_RE.match(e["hash"])
              and isinstance(e.get("size"), int) and not isinstance(e.get("size"), bool) and e["size"] >= 0):
            mtime = e.get("mtime")
            good[rel] = {"type": "file", "hash": e["hash"], "size": e["size"],
                         "mtime": mtime if isinstance(mtime, (int, float)) and 0 < mtime < 2 ** 33 else None}
        else:
            bad.append(rel)
    # A file inside something that is a file is not possible: drop it.
    for rel in list(good):
        parent = rel.rpartition("/")[0]
        if parent and good.get(parent, {"type": "dir"})["type"] != "dir":
            bad.append(rel)
            del good[rel]
    return good, bad


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def valid_rel(rel: str) -> bool:
    """A path the server accepts: names valid on Windows too, nothing hidden, no pictures/."""
    parts = rel.split("/")
    try:
        if [clean_name(p) for p in parts] != parts:
            return False
    except PathError:
        return False
    return parts[0].lower() != PICTURES_DIR


def _temporary(name: str) -> bool:
    lower = name.lower()
    return name.startswith(TEMP_PREFIXES) or lower.endswith(TEMP_SUFFIXES) or lower in ("thumbs.db", "desktop.ini")


def scan_local(root: Path):
    """({path: {"type": "dir", "ino", "dev"} | {"type": "file", "size", "mtime_ns", "ino", "dev"}},
    [skipped paths]). ino/dev: the item's identity on disk (kept by a rename)."""
    if not root.is_dir():
        raise FolderMissing(str(root))
    entries, skipped = {}, []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        rel_here = here.relative_to(root).as_posix()
        prefix = "" if rel_here == "." else rel_here + "/"
        keep = []
        for d in sorted(dirnames):
            path = here / d
            if d.startswith(".") or path.is_symlink() or (os.name == "nt" and _is_junction(path)):
                continue
            rel = prefix + d
            if not valid_rel(rel):
                skipped.append(rel + "/")
                continue
            keep.append(d)
            try:
                st = path.stat()
            except OSError:
                continue
            entries[rel] = {"type": "dir", "ino": st.st_ino, "dev": st.st_dev}
        dirnames[:] = keep
        for f in sorted(filenames):
            path = here / f
            if f.startswith(".") or _temporary(f) or path.is_symlink():
                continue
            rel = prefix + f
            if not valid_rel(rel):
                skipped.append(rel)
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            entries[rel] = {"type": "file", "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                            "ino": st.st_ino, "dev": st.st_dev}
    return entries, skipped


def _is_junction(path: Path) -> bool:
    return hasattr(path, "is_junction") and path.is_junction()


def local_stamp(root: Path) -> str:
    """Cheap value that changes when something in the folder changes (no content read)."""
    h = hashlib.sha256()
    try:
        entries, _ = scan_local(root)
    except FolderMissing:
        return "missing"
    for rel, e in entries.items():
        h.update(f"{rel}\0{e.get('size', -1)}\0{e.get('mtime_ns', 0)}\n".encode())
    return h.hexdigest()


def _inode(entry):
    """The identity on disk of a local item (or of the base entry), if known.
    Some file systems (FAT, exFAT on Windows) have none: 0."""
    if entry and entry.get("ino"):
        return entry["type"], entry.get("dev"), entry["ino"]
    return None


def _token(entry) -> str | None:
    if entry is None:
        return None
    return "dir" if entry["type"] == "dir" else entry["hash"]


def conflict_name(rel: str, device: str, existing) -> str:
    folder, _, name = rel.rpartition("/")
    stem, dot, ext = name.rpartition(".") if "." in name[1:] else (name, "", "")
    label = "".join(c for c in device if c.isalnum() or c in " -_")[:30].strip() or "PC"
    when = dt.datetime.now().strftime("%Y-%m-%d %H.%M")
    n = 1
    while True:
        extra = f" {n}" if n > 1 else ""
        candidate = f"{stem} (conflitto {label} {when}{extra}){dot}{ext}"
        full = f"{folder}/{candidate}" if folder else candidate
        if full not in existing:
            return full
        n += 1


class Engine:
    """One round: compare, decide, act. `report(text, level)` receives what happens."""

    def __init__(self, root: Path, conn, state: dict, device: str, report=print):
        self.root = Path(root)
        self.conn = conn
        self.base: dict = state.setdefault("base", {})
        self.state = state
        self.device = device
        self.report = report
        self.pending_deletions = 0         # held back by the brake, waiting for confirmation
        self.waiting = []                  # operations postponed (document open on the iPad…)
        self.errors = []
        self.unsettled = set()             # files still being written: looked at again shortly
        self.case_insensitive = os.name == "nt"   # "A.pdf" and "a.pdf" are the same file here

    # --- local hashes ---------------------------------------------------------------------------
    def _local_tokens(self, local: dict) -> tuple[dict, set]:
        """Fingerprint of every local file (from the base when size and time are the
        same); files still being written are set aside."""
        tokens, unsettled = {}, set()
        now = time.time_ns()
        for rel, e in local.items():
            if e["type"] == "dir":
                tokens[rel] = "dir"
                continue
            b = self.base.get(rel)
            if b and b.get("type") == "file" and b.get("size") == e["size"] and b.get("mtime_ns") == e["mtime_ns"]:
                tokens[rel] = b["hash"]
                continue
            if now - e["mtime_ns"] < SETTLE_SECONDS * 1e9:
                unsettled.add(rel)
                continue
            try:
                tokens[rel] = sha256_file(self.root / rel)
            except OSError:
                unsettled.add(rel)
        return tokens, unsettled

    # --- planning ---------------------------------------------------------------------------------
    def plan(self, local: dict, remote: dict, confirmed=False) -> list:
        remote, bad = clean_remote(remote)
        if bad:
            self.errors.append(f"Il server ha mandato {len(bad)} percorsi non validi, ignorati (es. «{bad[0]}»)")
        ltok, unsettled = self._local_tokens(local)
        self.unsettled = unsettled
        ops = []
        names = set(local) | set(remote)
        if self.case_insensitive:
            remote = self._without_case_clashes(remote)
        for rel in sorted(set(local) | set(remote) | set(self.base)):
            if rel in unsettled:
                continue
            l, r, b = ltok.get(rel), _token(remote.get(rel)), _token(self.base.get(rel))
            le, re_ = local.get(rel), remote.get(rel)
            if l == r:
                if l is None:
                    if rel in self.base:
                        ops.append({"op": "forget", "rel": rel})
                elif _token(self.base.get(rel)) != l or _inode(self.base[rel]) != _inode(le) or (
                        le["type"] == "file" and (self.base[rel].get("size"), self.base[rel].get("mtime_ns"))
                        != (le["size"], le["mtime_ns"])):
                    ops.append({"op": "record", "rel": rel, "token": l, "local": le})
                continue
            if l == b:                                  # changed on the server only
                if r is None:
                    ops.append({"op": "local_delete", "rel": rel, "local": le, "token": l})
                elif r == "dir":
                    if l is not None:                   # file here, folder there: the file is set aside
                        ops.append({"op": "conflict", "rel": rel, "local": le, "remote": re_, "names": names})
                    else:
                        ops.append({"op": "local_mkdir", "rel": rel})
                else:
                    ops.append({"op": "download", "rel": rel, "remote": re_, "local": le})
            elif r == b:                                # changed on this computer only
                if l is None:
                    ops.append({"op": "remote_delete", "rel": rel, "token": r, "base": self.base.get(rel)})
                elif l == "dir":
                    ops.append({"op": "remote_mkdir", "rel": rel})
                else:
                    ops.append({"op": "upload", "rel": rel, "token": l, "base": r if r != "dir" else None,
                                "local": le})
            else:                                       # changed on both sides
                if l is None:                           # deleted here, changed there: it comes back
                    ops.append({"op": "local_mkdir", "rel": rel} if r == "dir" else
                               {"op": "download", "rel": rel, "remote": re_, "local": None})
                elif r is None:                         # deleted there, changed here: it goes back
                    ops.append({"op": "remote_mkdir", "rel": rel} if l == "dir" else
                               {"op": "upload", "rel": rel, "token": l, "base": None, "local": le})
                elif l == "dir" or r == "dir":
                    self.waiting.append(f"{rel}: è una cartella da una parte e un file dall'altra")
                else:                                   # both changed: keep both
                    ops.append({"op": "conflict", "rel": rel, "local": le, "remote": re_, "names": names})
                    ops.append({"op": "download", "rel": rel, "remote": re_, "local": None})
        ops = self._find_moves(ops, ltok)
        return self._brake(ops, confirmed)

    def _without_case_clashes(self, remote: dict) -> dict:
        """Windows does not tell "Analisi.pdf" from "analisi.pdf": only the first is used."""
        seen, kept = {}, {}
        for rel in sorted(remote):
            key = rel.casefold()
            if key in seen:
                self.waiting.append(f"{rel}: sul server c'è anche «{seen[key]}», Windows non li distingue")
                continue
            seen[key] = rel
            kept[rel] = remote[rel]
        return kept

    @staticmethod
    def _find_moves(ops: list, ltok: dict) -> list:
        """A file that disappears in one place and appears in another was moved:
        move it, do not transfer it again. Here, the identity on disk says so even
        if the file was also changed (then the new content is uploaded after the
        move, and the server keeps the replaced version in its trash); otherwise
        the same content says so, in both directions."""
        result, used = [], set()
        by_inode = {_inode(o["base"]): o for o in ops if o["op"] == "remote_delete" and o["token"] not in (None, "dir")
                    and _inode(o.get("base"))}
        local_deletes = {o["token"]: o for o in ops if o["op"] == "local_delete" and o["token"] not in (None, "dir")}
        remote_deletes = {o["token"]: o for o in ops if o["op"] == "remote_delete" and o["token"] not in (None, "dir")}
        for o in ops:
            if o["op"] == "upload" and o["base"] is None and _inode(o["local"]) in by_inode \
                    and id(by_inode[_inode(o["local"])]) not in used:
                src = by_inode.pop(_inode(o["local"]))
                used.add(id(src))
                remote_deletes.pop(src["token"], None)
                changed = o["token"] != src["token"]
                result.append({"op": "remote_move", "rel": src["rel"], "to": o["rel"], "token": src["token"],
                               "local": o["local"], "changed": changed})
                if changed:
                    result.append({**o, "base": src["token"], "keep_previous": True})
            elif o["op"] == "download" and o["local"] is None and o["remote"]["hash"] in local_deletes:
                src = local_deletes.pop(o["remote"]["hash"])
                used.add(id(src))
                result.append({"op": "local_move", "rel": src["rel"], "to": o["rel"], "local": src["local"],
                               "remote": o["remote"]})
            elif o["op"] == "upload" and o["base"] is None and o["token"] in remote_deletes \
                    and id(remote_deletes[o["token"]]) not in used:
                src = remote_deletes.pop(o["token"])
                used.add(id(src))
                result.append({"op": "remote_move", "rel": src["rel"], "to": o["rel"], "token": o["token"],
                               "local": o["local"], "changed": False})
            else:
                result.append(o)
        return [o for o in result if id(o) not in used]

    # --- before planning: folders renamed here, names differing in capitals ------------------------
    def folder_moves(self, local: dict, remote: dict) -> list:
        """Folders renamed or moved on this computer (same identity on disk, new
        path): moved on the server in one step, with everything inside."""
        gone = {}
        for rel, b in self.base.items():
            if b.get("type") == "dir" and rel not in local and _inode(b) and remote.get(rel, {}).get("type") == "dir":
                gone[_inode(b)] = rel
        moves, taken = [], []
        for rel in sorted(local, key=lambda r: r.count("/")):
            e = local[rel]
            src = gone.get(_inode(e)) if e["type"] == "dir" and rel not in self.base and rel not in remote else None
            if not src or src == rel or rel.startswith(src + "/") or src.startswith(rel + "/"):
                continue
            if any(src.startswith(t + "/") or rel.startswith(d + "/") for t, d in taken):
                continue                      # inside a folder already being moved
            taken.append((src, rel))
            moves.append({"op": "folder_move", "rel": src, "to": rel, "local": e})
        return moves

    def _folder_move(self, o):
        self.conn.move(o["rel"], o["to"])
        src, dst = o["rel"], o["to"]
        for key in [k for k in self.base if k == src or k.startswith(src + "/")]:
            self.base[dst + key[len(src):]] = self.base.pop(key)
        self.base[dst] = {"type": "dir", "ino": o["local"].get("ino"), "dev": o["local"].get("dev")}
        self.report(f"Cartella spostata sul server: {src} → {dst}")
        return True

    def fix_case(self, local: dict, remote: dict) -> bool:
        """Windows: an item here and one on the server whose names differ only in
        capitals (never aligned before). Same content (or both folders): the one
        here takes the server's name. Different: the one here is set aside as a
        conflict copy. Returns True if something was renamed (scan again)."""
        if not self.case_insensitive:
            return False
        remote_by_key = {}
        for rel in remote:
            remote_by_key.setdefault(rel.casefold(), []).append(rel)
        names = set(local) | set(remote)
        renamed = False
        for rel in sorted(local, key=lambda r: r.count("/")):
            if rel in self.base or rel in remote:
                continue
            others = [r for r in remote_by_key.get(rel.casefold(), []) if r != rel and r not in local]
            if len(others) != 1 or others[0].rpartition("/")[0] != rel.rpartition("/")[0]:
                continue                      # different folders: their own folders are fixed first
            other, le, re_ = others[0], local[rel], remote[others[0]]
            same = le["type"] == re_["type"] == "dir" or (
                le["type"] == re_["type"] == "file" and le["size"] == re_["size"]
                and sha256_file(self._path(rel)) == re_["hash"])
            target = other if same else conflict_name(rel, self.device, names)
            os.replace(self._path(rel), self._path(target))
            if same:
                self.report(f"«{rel}» rinominato «{other}» come sul server (stesso contenuto, cambiano solo le maiuscole)")
            else:
                self.report(f"«{rel}» e «{other}» sul server differiscono solo per le maiuscole, che Windows non "
                            f"distingue: la versione di questo computer è stata tenuta come «{target}».", "warn")
            renamed = True
            break                             # one at a time: the paths below have changed
        return renamed

    def _brake(self, ops: list, confirmed: bool) -> list:
        deletions = [o for o in ops if o["op"] in ("local_delete", "remote_delete") and o.get("token") != "dir"]
        files = sum(1 for e in self.base.values() if e.get("type") == "file")
        limit, share = DELETE_BRAKE
        if len(deletions) > limit and len(deletions) > share * max(files, 1) and not confirmed:
            self.pending_deletions = len(deletions)
            held = {id(o) for o in ops if o["op"] in ("local_delete", "remote_delete")}
            return [o for o in ops if id(o) not in held]
        return ops

    # --- one complete round ----------------------------------------------------------------------------
    def refresh_remote(self) -> dict:
        """The server's list, kept in the state and updated with the changes only
        (the complete list the first time, or after the server restarted)."""
        answer = self.conn.changes(self.state.get("cursor"))
        remote = self.state.get("remote") if isinstance(self.state.get("remote"), dict) else {}
        if answer.get("full") or not isinstance(answer.get("changes"), dict):
            remote = dict(answer.get("entries") or {})
        else:
            for rel, entry in answer["changes"].items():
                if entry is None:
                    remote.pop(rel, None)
                else:
                    remote[rel] = entry
        self.state["remote"], self.state["cursor"] = remote, answer.get("cursor")
        return remote

    def sync(self, confirmed=False, step=None):
        """Compare and align. Returns (operations, paths skipped for their name)."""
        remote = self.refresh_remote()
        local, skipped = scan_local(self.root)
        for _ in range(100):                  # names differing only in capitals (Windows)
            if not self.fix_case(local, clean_remote(remote)[0]):
                break
            local, skipped = scan_local(self.root)
        moves = self.folder_moves(local, clean_remote(remote)[0])
        if moves:                             # whole folders first, then what is left
            self.execute(moves)
            remote = self.refresh_remote()
            local, skipped = scan_local(self.root)
        ops = self.plan(local, remote, confirmed)
        self.execute(ops, step)
        return moves + ops, skipped

    # --- execution -----------------------------------------------------------------------------------
    ORDER = {"folder_move": 0, "forget": 0, "record": 0, "local_mkdir": 1, "remote_mkdir": 1, "conflict": 2, "local_move": 3,
             "remote_move": 3, "download": 4, "upload": 4, "local_delete": 5, "remote_delete": 5}

    def execute(self, ops: list, progress=None) -> int:
        """Runs the operations; returns how many changed something."""
        def key(o):
            depth = o["rel"].count("/")
            # folders are created from the top, deleted from the bottom
            return (self.ORDER[o["op"]], -depth if o["op"].endswith("delete") else depth, o["rel"])
        done = 0
        for o in sorted(ops, key=key):
            try:
                if getattr(self, "_" + o["op"])(o):
                    done += 1
            except Offline:
                raise
            except ApiError as e:
                if e.status == 423:
                    self.waiting.append(f"{o['rel']}: aperto in modifica su un dispositivo, riprovo più tardi")
                elif e.status in (409, 404):
                    pass                        # changed meanwhile: the next round decides again
                elif e.status == 401:
                    raise
                else:
                    self.errors.append(f"{o['rel']}: {e}")
            except OSError as e:
                self.errors.append(f"{o['rel']}: {e.strerror or e}")
            if progress:
                progress()
        return done

    def _path(self, rel: str) -> Path:
        """Where `rel` is on disk; never outside the synchronised folder (not even
        through a link the user made inside it)."""
        path = self.root / rel
        root = self.root.resolve()
        resolved = path.parent.resolve()
        if resolved != root and root not in resolved.parents:
            raise OSError(f"percorso fuori dalla cartella sincronizzata: {rel}")
        return path

    def _stat_entry(self, rel: str, digest: str) -> dict:
        st = (self.root / rel).stat()
        if digest == "dir":
            return {"type": "dir", "ino": st.st_ino, "dev": st.st_dev}
        return {"type": "file", "hash": digest, "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "ino": st.st_ino, "dev": st.st_dev}

    def _unchanged(self, rel: str, local) -> bool:
        """Is the local item still as it was when the round started?"""
        path = self.root / rel
        if local is None:
            return not path.exists()
        if local["type"] == "dir":
            return path.is_dir()
        try:
            st = path.stat()
        except OSError:
            return False
        return st.st_size == local["size"] and st.st_mtime_ns == local["mtime_ns"]

    def _forget(self, o):
        self.base.pop(o["rel"], None)

    def _record(self, o):
        le = o["local"]
        if o["token"] == "dir":
            self.base[o["rel"]] = {"type": "dir", "ino": le.get("ino"), "dev": le.get("dev")}
        else:
            self.base[o["rel"]] = {"type": "file", "hash": o["token"], "size": le["size"], "mtime_ns": le["mtime_ns"],
                                   "ino": le.get("ino"), "dev": le.get("dev")}

    def _local_mkdir(self, o):
        self._path(o["rel"]).mkdir(parents=True, exist_ok=True)
        self.base[o["rel"]] = self._stat_entry(o["rel"], "dir")
        return True

    def _remote_mkdir(self, o):
        self.conn.mkdir(o["rel"])
        self.base[o["rel"]] = self._stat_entry(o["rel"], "dir")
        self.report(f"Cartella creata sul server: {o['rel']}")
        return True

    def _tmp(self) -> Path:
        folder = self.root / HIDDEN / "tmp"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _download(self, o):
        rel, remote = o["rel"], o["remote"]
        if not self._unchanged(rel, o["local"]):
            return False
        partial = self._tmp() / (remote["hash"][:32] + ".part")
        self.conn.download(rel, partial, remote["hash"], remote["size"])
        target = self._path(rel)
        if not self._unchanged(rel, o["local"]):        # changed while downloading: next round
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(partial, target)
        if isinstance(remote.get("mtime"), (int, float)):
            os.utime(target, (remote["mtime"], remote["mtime"]))
        self.base[rel] = self._stat_entry(rel, remote["hash"])
        self.report(f"Scaricato: {rel}")
        return True

    def _upload(self, o):
        rel, le = o["rel"], o["local"]
        if not self._unchanged(rel, le):
            return False
        path = self.root / rel
        self.conn.upload(path, rel, le["size"], o["token"], o["base"], le["mtime_ns"] / 1e9,
                         keep_previous=o.get("keep_previous", False))
        self.base[rel] = {"type": "file", "hash": o["token"], "size": le["size"], "mtime_ns": le["mtime_ns"],
                          "ino": le.get("ino"), "dev": le.get("dev")}
        self.report(f"Inviato al server: {rel}")
        return True

    def _conflict(self, o):
        """Both changed: this computer's version is set aside under another name
        (it will be uploaded as a new file), the server's version takes its place."""
        rel = o["rel"]
        if not self._unchanged(rel, o["local"]):
            return False
        aside = conflict_name(rel, self.device, o["names"])
        os.replace(self._path(rel), self._path(aside))
        self.base.pop(rel, None)
        if o["remote"]["type"] == "dir":            # a folder took its name on the server
            self._path(rel).mkdir()
            self.base[rel] = self._stat_entry(rel, "dir")
        self.report(f"Conflitto: «{rel}» è cambiato sia qui sia sul server. La versione di questo computer "
                    f"è stata tenuta come «{aside}».", "warn")
        return True

    def _local_move(self, o):
        src, dst = self._path(o["rel"]), self._path(o["to"])
        if not self._unchanged(o["rel"], o["local"]) or dst.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        self.base.pop(o["rel"], None)
        self.base[o["to"]] = self._stat_entry(o["to"], o["remote"]["hash"])
        self.report(f"Spostato: {o['rel']} → {o['to']}")
        return True

    def _remote_move(self, o):
        self.conn.move(o["rel"], o["to"], o["token"])
        self.base.pop(o["rel"], None)
        le = o["local"]
        # Moved and changed: the base is the moved version; size -1 makes the next
        # round look at the content again if the upload that follows fails.
        self.base[o["to"]] = {"type": "file", "hash": o["token"], "size": -1 if o.get("changed") else le["size"],
                              "mtime_ns": le["mtime_ns"], "ino": le.get("ino"), "dev": le.get("dev")}
        self.report(f"Spostato sul server: {o['rel']} → {o['to']}")
        return True

    def _local_delete(self, o):
        rel = o["rel"]
        path = self._path(rel)
        if o["token"] == "dir":
            if not path.is_dir():
                self.base.pop(rel, None)
                return False
            if any(p for p in path.iterdir()):
                return False                    # something new inside: it will be uploaded
            path.rmdir()
            self.base.pop(rel, None)
            return True
        if not self._unchanged(rel, o["local"]):
            return False
        # Not destroyed: into the hidden local trash, with its folders.
        trash = self.root / HIDDEN / "cestino" / dt.date.today().isoformat() / rel
        trash.parent.mkdir(parents=True, exist_ok=True)
        if trash.exists():
            trash = trash.with_name(f"{trash.stem} {int(time.time())}{trash.suffix}")
        shutil.move(str(path), str(trash))
        self.base.pop(rel, None)
        self.report(f"Eliminato (era stato eliminato sul server): {rel}")
        return True

    def _remote_delete(self, o):
        rel = o["rel"]
        if o["token"] == "dir":
            self.conn.delete(rel)
        else:
            self.conn.delete(rel, o["token"])
        self.base.pop(rel, None)
        self.report(f"Eliminato sul server (finisce nel cestino di TapBook): {rel}")
        return True

    # --- housekeeping -----------------------------------------------------------------------------------
    def clean_trash(self, days=CESTINO_DAYS):
        trash = self.root / HIDDEN / "cestino"
        if not trash.is_dir():
            return
        limit = dt.date.today() - dt.timedelta(days=days)
        for day in trash.iterdir():
            try:
                if dt.date.fromisoformat(day.name) < limit:
                    shutil.rmtree(day, ignore_errors=True)
            except ValueError:
                continue
        tmp = self.root / HIDDEN / "tmp"
        if tmp.is_dir():
            for f in tmp.iterdir():
                try:
                    if time.time() - f.stat().st_mtime > 7 * 86400:
                        f.unlink()
                except OSError:
                    pass


def nfc(rel: str) -> str:
    return unicodedata.normalize("NFC", rel)
