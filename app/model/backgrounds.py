"""MODEL — backgrounds of the open documents, stored so that devices download them
only once.

The background of a document is the PDF without the app's notes: what the
devices draw under the strokes. A device keeps the backgrounds it downloaded
(see the view's bgcache.js) and downloads one only if it does not have it yet.

So the backgrounds must not change unless the pages themselves change. Every page
of the file gets a fingerprint of what makes up its appearance (content, resources
such as fonts and images, size, rotation, annotations of other programs), and the
store remembers in which stored background, and at which position, each page with
that fingerprint already is:

  * the app saving the notes does not change the fingerprints (the notes are
    not part of the background): nothing to download;
  * pages added, removed or moved with the app: the pages are already in a
    stored background, only the map changes; pages added with the app are layout
    pages (blank, lined…), drawn from the small layout page (layouts.py) and
    never part of a background;
  * the file changed by another program: only the pages that changed (or are
    new) go into a new, small background, added to the others (a "delta").

The first background of a document holds all its pages together, so resources
shared by the pages (fonts) are stored and downloaded once. When a document has
gathered too many deltas, a new complete background replaces them (when nobody
has it open).

Files: <root>/<docId>/manifest.json and <root>/<docId>/<backgroundId>.pdf. The
background id is the SHA-256 of its bytes (32 hex characters): a device can
recognise it and nobody can make up a valid one. Backgrounds of documents not
opened for EXPIRE_DAYS are deleted.
"""
import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path

import pymupdf

from . import layouts
from .files import atomic_write

BG_ID_RE = re.compile(r"^[0-9a-f]{32}$")
DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DECODE_LIMIT = 256 * 1024    # compressed data up to this size is decoded before the fingerprint
MAX_BACKGROUNDS = 6          # beyond this many backgrounds for a document, a complete one is rebuilt
EXPIRE_DAYS = 30
SUBJECT_PREFIX = "notes-app:"
_REF_RE = re.compile(rb"(\d+) 0 R")
_LENGTH_RE = re.compile(rb"/Length\s*\d+(\s+0\s+R)?")
_STREAM_KEYS_RE = re.compile(rb"/(Length|DL)\s*\d+(\s+0\s+R)?|/Filter\s*(/FlateDecode|\[\s*/FlateDecode\s*\])|/DecodeParms\s*(<<[^>]*>>|null)")
_SKIP_KEYS = (b"/Parent", b"/P ", b"/Popup", b"/IRT")   # links back up the tree: not part of the appearance
_locks = {}
_locks_guard = threading.Lock()


def _doc_lock(key) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


# --- fingerprints -------------------------------------------------------------------
class _Hasher:
    """Fingerprints of PDF objects that do not depend on how the file is numbered
    inside: an object refers to another by number ("12 0 R"), and saving the file
    may renumber everything; each reference is replaced by the fingerprint of the
    object it points to."""

    def __init__(self, doc: pymupdf.Document):
        self.doc = doc
        self.memo = {}

    def obj(self, xref: int) -> bytes:
        if xref in self.memo:
            return self.memo[xref]
        self.memo[xref] = b"cycle"              # an object reachable from itself
        h = hashlib.sha256()
        try:
            text = self.doc.xref_object(xref, compressed=True).encode("latin-1", "replace")
        except Exception:
            text = b""
        for key in _SKIP_KEYS:
            text = re.sub(re.escape(key) + rb"\s*\d+ 0 R", b"", text)
        data = None
        if self.doc.xref_is_stream(xref):
            # Generic compression (or none) is decoded and its description removed: the
            # fingerprint is the same however the file was compressed when saved.
            # Images (JPEG, JPEG 2000…) are compared as they are, without decoding.
            # Large data (images, big drawings) is compared as stored: decoding it would be
            # slow, and the app never recompresses data that is already compressed.
            filt = self.doc.xref_get_key(xref, "Filter")[1]
            raw = self.doc.xref_stream_raw(xref) or b""
            image = self.doc.xref_get_key(xref, "Subtype")[1] == "/Image"
            if not image and len(raw) <= DECODE_LIMIT and filt in ("null", "/FlateDecode", "[/FlateDecode]"):
                try:
                    data = self.doc.xref_stream(xref)
                except Exception:
                    data = None
                if data is not None:
                    text = _STREAM_KEYS_RE.sub(b"", text)
            if data is None:
                text = _LENGTH_RE.sub(b"", text)
                data = raw
        h.update(_REF_RE.sub(lambda m: b"<" + self.obj(int(m.group(1))).hex().encode() + b">", text))
        if data is not None:
            h.update(data)
        self.memo[xref] = h.digest()
        return self.memo[xref]

    def page(self, page: pymupdf.Page) -> str:
        h = hashlib.sha256()
        h.update(repr((tuple(round(v, 2) for v in page.mediabox), tuple(round(v, 2) for v in page.cropbox),
                       page.rotation)).encode())
        for xref in page.get_contents():                # the page's drawing instructions
            h.update(self.obj(xref))
        res = self.doc.xref_get_key(page.xref, "Resources")
        if res[0] == "xref":
            h.update(self.obj(int(res[1].split()[0])))
        elif res[0] == "dict":
            h.update(_REF_RE.sub(lambda m: b"<" + self.obj(int(m.group(1))).hex().encode() + b">",
                                 res[1].encode("latin-1", "replace")))
        for annot in page.annots() or []:              # annotations of other programs (the app's are removed)
            if not (annot.info.get("subject") or "").startswith(SUBJECT_PREFIX):
                h.update(self.obj(annot.xref))
        return h.hexdigest()[:32]


def page_fingerprints(doc: pymupdf.Document) -> list:
    hasher = _Hasher(doc)
    return [hasher.page(p) for p in doc]


_layout_memo = {}


def layout_fingerprint(layout, w, h):
    """Fingerprint of an untouched page of that layout, as the app creates it."""
    key = (layout, round(w, 2), round(h, 2))
    if key not in _layout_memo:
        doc = pymupdf.open(stream=layouts.page_pdf(layout, w, h), filetype="pdf")
        try:
            _layout_memo[key] = page_fingerprints(doc)[0]
        finally:
            doc.close()
    return _layout_memo[key]


# --- store ---------------------------------------------------------------------------
class BackgroundStore:
    """Backgrounds of one user's documents."""

    def __init__(self, root: Path):
        self.root = root

    def _dir(self, doc_id: str) -> Path:
        if not isinstance(doc_id, str) or not DOC_ID_RE.match(doc_id):
            raise LookupError("Documento inesistente")
        return self.root / doc_id

    def _manifest(self, folder: Path) -> dict:
        try:
            data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"backgrounds": []}
        bgs = [b for b in data.get("backgrounds", []) if isinstance(b, dict) and BG_ID_RE.match(str(b.get("id")))
               and isinstance(b.get("pages"), list) and (folder / f"{b['id']}.pdf").is_file()]
        return {"backgrounds": bgs, "revision": data.get("revision"), "refs": data.get("refs")}

    def _save_manifest(self, folder: Path, manifest: dict):
        atomic_write(folder / "manifest.json", json.dumps(manifest, separators=(",", ":")).encode("utf-8"))

    def _add(self, folder: Path, manifest: dict, data: bytes, fingerprints: list) -> str:
        bg_id = hashlib.sha256(data).hexdigest()[:32]
        target = folder / f"{bg_id}.pdf"
        if not target.exists():
            atomic_write(target, data)
        manifest["backgrounds"] = [b for b in manifest["backgrounds"] if b["id"] != bg_id]
        manifest["backgrounds"].append({"id": bg_id, "pages": fingerprints, "size": len(data)})
        return bg_id

    def prepare(self, doc_id: str, clean: bytes, page_layouts: list, revision: str, tidy: bool) -> list:
        """Background reference of every page of the clean document, in order:
        {"id": background id, "page": index in it}, or None for an untouched
        layout page (drawn from the layout). Stores what is missing.
        page_layouts: (layout, w, h) of each page, or None for pages not made by the app.
        tidy: nobody has the document open, so backgrounds no longer needed can go."""
        folder = self._dir(doc_id)
        with _doc_lock(str(folder)):
            folder.mkdir(parents=True, exist_ok=True)
            manifest = self._manifest(folder)
            if manifest.get("revision") == revision and isinstance(manifest.get("refs"), list) \
                    and len(manifest["refs"]) == len(page_layouts) and self._refs_valid(manifest):
                refs = manifest["refs"]          # same file as last time: nothing to compute
            else:
                refs = self._compute(folder, manifest, clean, page_layouts, tidy)
                manifest["revision"], manifest["refs"] = revision, refs
            if tidy:
                # Every background file the pages no longer use goes (listed or not).
                used = {r["id"] for r in refs if r}
                manifest["backgrounds"] = [b for b in manifest["backgrounds"] if b["id"] in used]
                for f in folder.glob("*.pdf"):
                    if f.stem not in used:
                        f.unlink(missing_ok=True)
            self._save_manifest(folder, manifest)     # also marks the document as recently used
            return refs

    @staticmethod
    def _refs_valid(manifest) -> bool:
        ids = {b["id"] for b in manifest["backgrounds"]}
        return all(r is None or (isinstance(r, dict) and r.get("id") in ids) for r in manifest["refs"])

    def _compute(self, folder, manifest, clean, page_layouts, tidy):
        doc = pymupdf.open(stream=clean, filetype="pdf")
        try:
            fps = page_fingerprints(doc)
            known = {}
            for b in manifest["backgrounds"]:
                for i, fp in enumerate(b["pages"]):
                    known.setdefault(fp, {"id": b["id"], "page": i})
            refs, missing = [], []
            for i, (fp, lay) in enumerate(zip(fps, page_layouts)):
                if lay and layouts.exists(lay[0]) and fp == layout_fingerprint(*lay):
                    refs.append(None)                   # untouched layout page: drawn from the layout
                elif fp in known:
                    refs.append(known[fp])
                else:
                    refs.append("missing")
                    missing.append(i)
            if not missing:
                return refs
            complete = (not manifest["backgrounds"]
                        or (tidy and len(manifest["backgrounds"]) >= MAX_BACKGROUNDS))
            if complete:
                # All the pages together (shared fonts once): replaces the others.
                wanted = [i for i, r in enumerate(refs) if r is not None]
                if tidy:
                    manifest["backgrounds"] = []
            else:
                wanted = missing                          # a delta: only the new pages
            out = pymupdf.open()
            try:
                for i in wanted:
                    out.insert_pdf(doc, from_page=i, to_page=i)
                data = out.tobytes(garbage=3, deflate=True)
            finally:
                out.close()
            bg_id = self._add(folder, manifest, data, [fps[i] for i in wanted])
            for k, i in enumerate(wanted):
                refs[i] = {"id": bg_id, "page": k}
            return refs
        finally:
            doc.close()

    def path(self, doc_id: str, bg_id) -> Path:
        """File of a background of this document (LookupError if it is not one of its backgrounds)."""
        folder = self._dir(doc_id)
        if not isinstance(bg_id, str) or not BG_ID_RE.match(bg_id):
            raise LookupError("Sfondo inesistente")
        if not any(b["id"] == bg_id for b in self._manifest(folder)["backgrounds"]):
            raise LookupError("Sfondo inesistente")
        return folder / f"{bg_id}.pdf"

    def sizes(self, doc_id: str) -> dict:
        return {b["id"]: b.get("size", 0) for b in self._manifest(self._dir(doc_id))["backgrounds"]}


def expire(root: Path, days: int = EXPIRE_DAYS):
    """Deletes the backgrounds of documents not opened for `days` days."""
    if not root.is_dir():
        return
    limit = time.time() - days * 86400
    for user in root.iterdir():
        if not user.is_dir() or user.is_symlink():
            continue
        for folder in user.iterdir():
            manifest = folder / "manifest.json"
            try:
                if folder.is_dir() and not folder.is_symlink() and (
                        not manifest.exists() or manifest.stat().st_mtime < limit):
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                pass
