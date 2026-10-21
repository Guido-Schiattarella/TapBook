"""MODEL — storage of the users' folders and files on the file system.

Each `UserFolder` is confined to `<notes_root>/<username>`: every relative path
goes through `resolve_user_path`, so even if a controller made a mistake the
model could never read or write outside it (defence in depth against path
traversal).
"""
import datetime as dt
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from ..security import resolve_user_path, to_rel
from .files import atomic_write, is_link, replace

TRASH_DIR = ".cestino"
TRASH_INDEX = ".indice.json"   # where every trash item comes from (to restore it)
PICTURES_DIR = "pictures"   # document images: pictures/<document path without .pdf>/
AVATAR_FILE = ".profilo.jpg"   # profile photo (hidden: not listed among the documents)
DELETED_ACCOUNTS_DIR = ".account-eliminati"   # in notes_root: cartelle degli account eliminati
_STAMP_RE = re.compile(r"^(\d{8}-\d{6})_(.+)$")
_PICTURES_ENTRY_RE = re.compile(r"^\d{8}-\d{6}_" + PICTURES_DIR + "_")


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique(folder: Path, name: str) -> Path:
    """A free path in `folder`: name, or "name (2)", "name (3)", ... before the extension."""
    target = folder / name
    stem, suffix = (Path(name).stem, Path(name).suffix) if "." in name[1:] else (name, "")
    n = 2
    while target.exists() or is_link(target):
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def _size(path: Path) -> int:
    if is_link(path):
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not is_link(f))


def _remove(path: Path):
    """Really deletes a file or a folder (without following links)."""
    if is_link(path) and path.is_dir() and os.name == "nt":
        os.rmdir(path)            # junction or link to a folder: only the link is removed
    elif is_link(path) or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


class UserFolder:
    def __init__(self, notes_root: Path, username: str):
        self.root = notes_root / username
        self.root.mkdir(parents=True, exist_ok=True)
        # Private documents: the user's folder is accessible only to the owner of
        # the computer (not to other accounts of the operating system).
        if self.root.stat().st_mode & 0o077:
            os.chmod(self.root, 0o700)

    # --- paths -----------------------------------------------------------------
    def resolve(self, rel: str) -> Path:
        """Safe absolute path; raises PathError if it leaves the folder."""
        return resolve_user_path(self.root, rel or "")

    def rel(self, path: Path) -> str:
        return to_rel(self.root, path)

    def child(self, rel_parent: str, name: str) -> Path:
        """Item `name` inside the folder `rel_parent` (checked again)."""
        parent = self.resolve(rel_parent)
        return self.resolve(self.rel(parent) + "/" + name)

    def is_root(self, path: Path) -> bool:
        return path == self.root.resolve()

    # --- reading ---------------------------------------------------------------
    def list(self, rel: str):
        """Contents of a folder: subfolders and PDFs, without hidden files or symlinks."""
        folder = self.resolve(rel)
        if not folder.is_dir():
            raise FileNotFoundError(rel)
        entries = []
        at_root = self.is_root(folder)
        for entry in os.scandir(folder):
            if entry.name.startswith(".") or is_link(entry.path):
                continue
            if at_root and entry.name == PICTURES_DIR:
                continue  # images folder: managed by the app, not a document
            st = entry.stat()
            items = None
            if entry.is_dir():
                kind = "dir"
                try:   # how many documents and folders it contains (for the folder card)
                    items = sum(1 for e in os.scandir(entry.path) if not e.name.startswith(".")
                                and (e.is_dir() or e.name.lower().endswith(".pdf")))
                except OSError:
                    items = 0
            elif entry.name.lower().endswith(".pdf"):
                kind = "pdf"
            else:
                continue
            entries.append({"name": entry.name, "type": kind, "size": st.st_size,
                            "mtime": int(st.st_mtime), "items": items})
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return self.rel(folder), entries

    # --- writing ---------------------------------------------------------------
    def make_dir(self, rel_parent: str, name: str):
        self.child(rel_parent, name).mkdir()  # FileExistsError if it already exists

    def write_new_file(self, rel_parent: str, name: str, data: bytes) -> str:
        """Writes a new file (never overwriting) atomically."""
        target = self.child(rel_parent, name)
        if target.exists():
            raise FileExistsError(name)
        fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(tmp, target)  # fails if the file appeared in the meantime
            except FileExistsError:
                raise
            except OSError:
                # File system senza hard link (es. chiavette exFAT): rinomina semplice.
                if target.exists():
                    raise FileExistsError(name)
                replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return self.rel(target)

    def move_to_trash(self, rel: str):
        """Does not delete: moves to the user's hidden .cestino (trash) folder (a
        document goes there together with its images) and remembers where it came from."""
        src = self.resolve(rel)
        if self.is_root(src) or not src.exists():
            raise FileNotFoundError(rel)
        rel = self.rel(src)
        trash = self._trash()
        stamp = _stamp()
        pictures = self.pictures_dir(rel)
        pictures_entry = None
        if pictures.is_dir():  # the document's (or folder's) images follow it
            target = _unique(trash, f"{stamp}_{PICTURES_DIR}_{pictures.name}")
            shutil.move(str(pictures), str(target))
            pictures_entry = target.name
            self._prune_empty(pictures.parent)
        target = _unique(trash, f"{stamp}_{src.name}")
        shutil.move(str(src), str(target))
        self._index_add(target.name, rel, pictures_entry)

    def backup_path(self, rel: str, label: str) -> Path:
        """Path in the trash for a backup copy of the file, for example
        `.cestino/20261020-171500_Analisi (versione PC).pdf`. Restoring it puts it
        next to the document under that name."""
        src = self.resolve(rel)
        name = f"{src.stem} ({label}){src.suffix}"
        target = _unique(self._trash(), f"{_stamp()}_{name}")
        parent = self.rel(src.parent)
        self._index_add(target.name, f"{parent}/{name}" if parent else name, None)
        return target

    # --- trash -----------------------------------------------------------------------
    def _trash(self) -> Path:
        trash = self.root / TRASH_DIR
        trash.mkdir(exist_ok=True)
        return trash

    def _index(self) -> dict:
        try:
            data = json.loads((self.root / TRASH_DIR / TRASH_INDEX).read_text("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _index_save(self, index: dict):
        atomic_write(self._trash() / TRASH_INDEX, json.dumps(index, ensure_ascii=False).encode("utf-8"))

    def _index_add(self, entry: str, rel: str, pictures):
        index = self._index()
        index[entry] = {"from": rel, "pictures": pictures}
        self._index_save(index)

    def _trash_entry(self, entry) -> Path:
        """Trash item named by the view: only a plain, existing name."""
        if (not isinstance(entry, str) or not entry or "/" in entry or "\\" in entry
                or "\x00" in entry or entry.startswith(".") or _PICTURES_ENTRY_RE.match(entry)):
            raise FileNotFoundError(entry)
        path = self.root / TRASH_DIR / entry
        if not path.exists() or is_link(path):     # links are never touched
            raise FileNotFoundError(entry)
        return path

    def list_trash(self) -> list:
        """Items in the trash (document image folders are not listed: they follow
        their document)."""
        trash = self.root / TRASH_DIR
        if not trash.is_dir():
            return []
        index = self._index()
        items = []
        for path in trash.iterdir():
            entry = path.name
            if entry.startswith(".") or _PICTURES_ENTRY_RE.match(entry) or is_link(path):
                continue
            m = _STAMP_RE.match(entry)
            name = m.group(2) if m else entry
            try:
                deleted = dt.datetime.strptime(m.group(1), "%Y%m%d-%H%M%S").timestamp() if m \
                    else path.stat().st_mtime
            except ValueError:
                deleted = path.stat().st_mtime
            origin = index.get(entry, {}).get("from")
            items.append({"entry": entry, "name": Path(origin).name if origin else name,
                          "type": "dir" if path.is_dir() else ("pdf" if entry.lower().endswith(".pdf") else "file"),
                          "from": origin.rpartition("/")[0] if origin else None,
                          "deleted": int(deleted), "size": _size(path)})
        items.sort(key=lambda i: i["deleted"], reverse=True)
        return items

    def restore_from_trash(self, entry) -> str:
        """Puts the item back where it was (recreating missing folders); if an item
        with the same name is already there, adds a number. Returns the restored path."""
        path = self._trash_entry(entry)
        index = self._index()
        record = index.get(entry, {})
        origin = record.get("from")
        if not isinstance(origin, str) or not origin:
            m = _STAMP_RE.match(entry)
            origin = m.group(2) if m else entry
        parent_rel, _, name = origin.rpartition("/")
        try:
            parent = self.resolve(parent_rel)
        except ValueError:
            parent, name = self.root.resolve(), Path(origin).name
        if not self.is_root(parent) and (self.rel(parent).split("/")[0] == PICTURES_DIR):
            parent = self.root.resolve()          # never inside the images folder
        if self.is_root(parent) and name.lower() == PICTURES_DIR:
            name += " (ripristinato)"
        parent.mkdir(parents=True, exist_ok=True)
        target = _unique(parent, name)
        shutil.move(str(path), str(target))
        rel = self.rel(target)
        pictures = record.get("pictures")
        if isinstance(pictures, str) and _PICTURES_ENTRY_RE.match(pictures):
            src = self.root / TRASH_DIR / pictures
            if src.is_dir():
                dst = self.pictures_dir(rel)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.move(str(src), str(dst))
                else:   # a folder is already there: add the missing files
                    for f in src.iterdir():
                        if not (dst / f.name).exists():
                            shutil.move(str(f), str(dst / f.name))
                    _remove(src)
        index.pop(entry, None)
        self._index_save(index)
        return rel

    def delete_from_trash(self, entry):
        """Permanently deletes an item (and its images)."""
        path = self._trash_entry(entry)
        index = self._index()
        pictures = index.pop(entry, {}).get("pictures")
        _remove(path)
        if isinstance(pictures, str) and _PICTURES_ENTRY_RE.match(pictures):
            p = self.root / TRASH_DIR / pictures
            if p.exists():
                _remove(p)
        self._index_save(index)

    def empty_trash(self):
        """Empties the trash: everything in it is permanently deleted."""
        trash = self.root / TRASH_DIR
        if not trash.is_dir():
            return
        for path in list(trash.iterdir()):
            _remove(path)

    # --- profile -----------------------------------------------------------------------
    def avatar_path(self) -> Path | None:
        path = self.root / AVATAR_FILE
        return path if path.is_file() and not is_link(path) else None

    def save_avatar(self, data: bytes):
        atomic_write(self.root / AVATAR_FILE, data)

    def remove_avatar(self):
        (self.root / AVATAR_FILE).unlink(missing_ok=True)

    def documents(self):
        """All of the user's PDFs (subfolders included), without trash, hidden files,
        images folder and links: (relative path, Path, stat)."""
        root = self.root.resolve()
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".")
                                 and not (here == root and d == PICTURES_DIR)
                                 and not is_link(here / d))
            for f in sorted(filenames):
                path = here / f
                if f.startswith(".") or not f.lower().endswith(".pdf") or is_link(path):
                    continue
                yield path.relative_to(root).as_posix(), path, path.stat()

    def stats(self) -> dict:
        docs = list(self.documents())
        folders = sum(1 for _ in self._folders())
        return {"documents": len(docs), "folders": folders,
                "size": sum(st.st_size for _, _, st in docs), "trash": len(self.list_trash())}

    def _folders(self):
        root = self.root.resolve()
        for dirpath, dirnames, _ in os.walk(root):
            here = Path(dirpath)
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and not (here == root and d == PICTURES_DIR) and not is_link(here / d)]
            yield from dirnames

    @staticmethod
    def archive_account(notes_root: Path, username: str) -> Path | None:
        """Deleted account: its folder is not destroyed but moved to
        <notes_root>/.account-eliminati/<name>_<date>, recoverable from the computer.
        This frees the name for a new sign-up."""
        folder = notes_root / username
        if not folder.is_dir():
            return None
        archive = notes_root / DELETED_ACCOUNTS_DIR
        archive.mkdir(exist_ok=True)
        target = _unique(archive, f"{username}_{_stamp()}")
        shutil.move(str(folder), str(target))
        return target

    # --- document images -----------------------------------------------------------
    def pictures_dir(self, rel: str) -> Path:
        """Images folder: pictures/<path without .pdf> for a document, pictures/<path>
        for a folder. It mirrors the subfolders, so two documents with the same name
        in different folders do not get mixed up (e.g. pictures/Università/Analisi)."""
        path = self.resolve(rel)
        rel = self.rel(path)
        if rel.lower().endswith(".pdf"):
            rel = rel[:-4]
        return self.resolve(PICTURES_DIR + "/" + rel)

    def save_picture(self, rel_doc: str, name: str, data: bytes) -> Path:
        folder = self.pictures_dir(rel_doc)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        atomic_write(target, data, fsync=False)
        return target

    def rename(self, rel: str, new_name: str):
        """Renames a document or a folder; their images follow them."""
        src = self.resolve(rel)
        if self.is_root(src) or not src.exists():
            raise FileNotFoundError(rel)
        dst = self.child(self.rel(src.parent), new_name)
        # On Windows (case-insensitive names) "analisi" → "Analisi" is the same
        # file: renaming is allowed.
        if dst.exists() and not (dst.parent == src.parent and os.path.normcase(dst.name) == os.path.normcase(src.name)):
            raise FileExistsError(new_name)
        old_pictures = self.pictures_dir(rel)
        src.rename(dst)
        if old_pictures.is_dir():
            new_pictures = self.pictures_dir(self.rel(dst))
            new_pictures.parent.mkdir(parents=True, exist_ok=True)
            old_pictures.rename(new_pictures)
            self._prune_empty(old_pictures.parent)

    def trash_pictures(self, rel_doc: str, stamp: str, keep: set | None = None):
        """Moves the document's images to the trash: all of them, or all except
        those whose names are in `keep` (i.e. still used in the PDF).
        They are not listed in the web trash: emptying it deletes them."""
        folder = self.pictures_dir(rel_doc)
        if not folder.is_dir():
            return
        target = self.root / TRASH_DIR / f"{stamp}_{PICTURES_DIR}_{folder.name}"
        for f in list(folder.iterdir()):
            if f.name.startswith("."):
                continue
            if keep is not None and f.name in keep:
                continue
            target.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(target / f.name))
        if not any(folder.iterdir()):
            folder.rmdir()
            self._prune_empty(folder.parent)

    def _prune_empty(self, folder: Path):
        """Removes pictures folders left empty (up to and including pictures)."""
        pictures = self.root / PICTURES_DIR
        while folder != self.root and (folder == pictures or pictures in folder.parents):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                folder = folder.parent
            else:
                break

    # --- user folders (sign-up) ------------------------------------------------------
    @staticmethod
    def is_free(notes_root: Path, username: str) -> bool:
        """True unless a non-empty folder with that name already exists."""
        folder = notes_root / username
        return not folder.exists() or (folder.is_dir() and not any(folder.iterdir()))
