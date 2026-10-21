"""MODEL — storage of the PDF documents on the file system.

This module reads and writes the PDFs; it decides nothing: it receives
already-validated data from the controller and returns raw data. Storage format:

* The PDF on disk is the single source of truth: it holds the original pages,
  the app's strokes and text boxes as standard PDF annotations (Ink and
  FreeText) — so any PDF reader on the computer shows them — plus an embedded
  attachment "notes-app-layer.json" with the complete data (ids, pressure,
  etc.) needed to resume editing.
* The app's annotations are recognised by their "subject" field starting with
  "notes-app:". To get the "clean" page shown in the editor it is enough to
  remove them: the original PDF content is never touched.
* Pages created by the app have their layout (lines, grid, dots) drawn into
  the page content (see layouts.py) and remember it in their dictionary
  (NotesAppLayout); the layout chosen for the next pages is in the attachment
  ("nextLayout").
* Deleted pages are put aside in a server-side cache (pagecache) so the
  session's undo/redo can bring them back.
"""
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pymupdf

from . import layouts
from .files import replace

LAYER_FILE = "notes-app-layer.json"
PAGE_ID_KEY = "NotesAppPageId"   # key in every page dictionary holding its id
PAGE_LAYOUT_KEY = "NotesAppLayout"  # layout the app created the page with
DOC_COLOR_KEY = "NotesAppColor"     # note colour chosen at creation (in the PDF catalog)
DOC_CREATED_KEY = "NotesAppCreated" # creation (or import) date of the note
COLOR_ID_RE = re.compile(r"^[a-z]{1,20}$")
SUBJECT_PREFIX = "notes-app:"
LAYER_VERSION = 1
A4 = (595.0, 842.0)

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SHAPE_RE = re.compile(r"^[a-z]{1,20}$")
MAX_STORED_POINTS = 20000      # same limits the controller applies to the view's data
MAX_STORED_TEXT = 20000
COORD_LIMIT = 1e6
PICTURE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\.(jpg|png)$")  # image file names

pymupdf.TOOLS.set_annot_stem("notes-app")

# One lock per file: two saves of the same document never overlap.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def file_lock(path: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(path), threading.Lock())


class RevisionMismatch(Exception):
    """The file on disk is no longer at the given revision (conditional save failed)."""


def revision_of(path: Path) -> str:
    """Fingerprint of the file content (SHA-256). It changes only when the content
    changes: if a program (backup, sync) touches the file without modifying it,
    the revision stays the same and no false conflict arises."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --- Note colour and creation date ------------------------------------------
# They live in the PDF catalog: they follow the file through every rename, move
# or trip to the trash, even when it is moved on the computer.
def read_doc_info(doc: pymupdf.Document) -> dict:
    cat = doc.pdf_catalog()
    kind, color = doc.xref_get_key(cat, DOC_COLOR_KEY)
    color = color.lstrip("/") if kind == "name" and COLOR_ID_RE.match(color.lstrip("/")) else None
    kind, created = doc.xref_get_key(cat, DOC_CREATED_KEY)
    try:
        created = dt.datetime.fromisoformat(created).timestamp() if kind == "string" else None
    except ValueError:
        created = None
    return {"color": color, "created": created}


def write_doc_info(doc: pymupdf.Document, color=None, created=None):
    cat = doc.pdf_catalog()
    if color and COLOR_ID_RE.match(color):
        doc.xref_set_key(cat, DOC_COLOR_KEY, "/" + color)
    if created:
        stamp = dt.datetime.fromtimestamp(created).isoformat(timespec="seconds")
        doc.xref_set_key(cat, DOC_CREATED_KEY, f"({stamp})")


_info_cache: dict[str, tuple] = {}
_info_lock = threading.Lock()


def doc_info(path: Path) -> dict:
    """Colour and creation date of a note, for the document list. The result stays
    in memory until the file changes. For PDFs without them (created before this
    feature or coming from elsewhere) the date is the PDF metadata's or, failing
    that, the file's."""
    st = path.stat()
    key, stamp = str(path), (st.st_mtime_ns, st.st_size)
    with _info_lock:
        hit = _info_cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    info = {"color": None, "created": None}
    try:
        with pymupdf.open(path) as doc:
            info = read_doc_info(doc)
            if info["created"] is None:
                m = re.match(r"D:(\d{14})", doc.metadata.get("creationDate") or "")
                if m:
                    info["created"] = dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S").timestamp()
    except Exception:
        pass
    if info["created"] is None:
        info["created"] = st.st_mtime
    with _info_lock:
        if len(_info_cache) > 5000:
            _info_cache.clear()
        _info_cache[key] = (stamp, info)
    return info


def mark_imported(data: bytes, created: float) -> bytes:
    """Imported PDF: the import date is written into it (white colour)."""
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        write_doc_info(doc, created=created)
        return doc.tobytes()


# --- Reading ---------------------------------------------------------------
def _read_layer(doc: pymupdf.Document):
    if LAYER_FILE in doc.embfile_names():
        try:
            return json.loads(doc.embfile_get(LAYER_FILE).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    return None


def _strip_app_content(doc: pymupdf.Document):
    """Removes the app's annotations and attachment from the document (in memory)."""
    for page in doc:
        for annot in list(page.annots() or []):
            if (annot.info.get("subject") or "").startswith(SUBJECT_PREFIX):
                page.delete_annot(annot)
    if LAYER_FILE in doc.embfile_names():
        doc.embfile_del(LAYER_FILE)


def _rgb_to_hex(rgb, default="#000000"):
    if not rgb or len(rgb) != 3:
        return default
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


# --- Embedded data: accepted only if well formed ------------------------------
# The JSON inside the PDF is usually written by the app, but a PDF coming from
# elsewhere could contain crafted data: every item is rebuilt field by field,
# with the same checks the controller applies to the view's data. If it is not
# valid, the data taken from the visible annotation is used instead.
def _finite(v, lo=-COORD_LIMIT, hi=COORD_LIMIT):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v) if lo <= v <= hi else None


def _clean_stroke(st, item_id):
    try:
        pts = st["points"]
        if not isinstance(pts, list) or not 0 < len(pts) <= MAX_STORED_POINTS:
            return None
        points = []
        for p in pts:
            x, y = _finite(p[0]), _finite(p[1])
            pr = _finite(p[2], 0, 1) if len(p) > 2 else 0.5
            if x is None or y is None or pr is None:
                return None
            points.append([x, y, pr])
        width = _finite(st.get("width", 2), 0.1, 100)
        color = st.get("color", "#000000")
        if st.get("tool", "pen") not in ("pen", "highlighter") or width is None \
                or not isinstance(color, str) or not HEX_COLOR_RE.match(color):
            return None
        out = {"id": item_id, "tool": st.get("tool", "pen"), "color": color.lower(), "width": width, "points": points}
        if st.get("shape") is not None:
            if not isinstance(st["shape"], str) or not SHAPE_RE.match(st["shape"]):
                return None
            out["shape"] = st["shape"]
        return out
    except (TypeError, KeyError, IndexError, AttributeError):
        return None


def _text_style(st):
    """Size and colour of a text box (from the embedded data, if valid)."""
    size = _finite(st.get("size"), 4, 200) if isinstance(st, dict) else None
    color = st.get("color") if isinstance(st, dict) else None
    return (size or 14.0), (color.lower() if isinstance(color, str) and HEX_COLOR_RE.match(color) else "#000000")


def _page_layer(page: pymupdf.Page, page_id, known: dict, layout=None, seen=None) -> dict:
    """Rebuilds a page's layer from the app annotations that are REALLY on that
    page. The embedded JSON (known) only enriches them (pressure, font size,
    ...): this way, even if the PDF was reordered or edited with another program,
    every stroke stays on the right page and nothing is lost."""
    strokes, texts, images = [], [], []
    m = page.rotation_matrix  # unrotated space -> visible space
    for annot in page.annots() or []:
        subject = annot.info.get("subject") or ""
        if not subject.startswith(SUBJECT_PREFIX):
            continue
        item_id = subject[len(SUBJECT_PREFIX):]
        if not ID_RE.match(item_id) or (seen is not None and item_id in seen):
            item_id = uuid.uuid4().hex[:16]      # invalid or repeated id: a new one is created
        if seen is not None:
            seen.add(item_id)
        stored = known.get(item_id)
        if not isinstance(stored, dict):
            stored = None
        if annot.type[0] == pymupdf.PDF_ANNOT_INK:
            clean = _clean_stroke(stored, item_id) if stored else None
            if clean:
                strokes.append(clean)
                continue
            pts = [[p.x, p.y, 0.5] for line in (annot.vertices or [])
                   for p in (pymupdf.Point(v) * m for v in line)]
            if pts:
                strokes.append({
                    "id": item_id,
                    "tool": "highlighter" if (annot.opacity or 1) < 1 else "pen",
                    "color": _rgb_to_hex(annot.colors.get("stroke")),
                    "width": (annot.border or {}).get("width") or 2,
                    "points": pts,
                })
        elif annot.type[0] == pymupdf.PDF_ANNOT_FREE_TEXT:
            r = annot.rect * m
            size, color = _text_style(stored)
            text = annot.info.get("content")
            if not isinstance(text, str):
                text = stored.get("text", "") if stored and isinstance(stored.get("text"), str) else ""
            texts.append({"id": item_id, "size": size, "color": color, "text": text[:MAX_STORED_TEXT],
                          "x": r.x0, "y": r.y0, "w": r.width, "h": r.height})
        elif annot.type[0] == pymupdf.PDF_ANNOT_STAMP:
            # App image: the file is in the document's pictures folder; the file name
            # is in the embedded data. Without it the image cannot be edited.
            if stored and isinstance(stored.get("file"), str) and PICTURE_RE.match(stored["file"]):
                r = annot.rect * m
                images.append({"id": item_id, "file": stored["file"],
                               "x": r.x0, "y": r.y0, "w": r.width, "h": r.height})
    return {
        "id": page_id or uuid.uuid4().hex[:16],
        "src": page.number, "render": page.number, "blank": False,
        "w": page.rect.width, "h": page.rect.height, "layout": layout,
        "strokes": strokes, "texts": texts, "images": images,
    }


def _get_page_id(doc: pymupdf.Document, page: pymupdf.Page):
    """Page id written inside the page itself: it follows the page even if another
    program adds, removes or reorders pages."""
    kind, value = doc.xref_get_key(page.xref, PAGE_ID_KEY)
    return value if kind == "string" and ID_RE.match(value) else None


def _set_page_id(doc: pymupdf.Document, page: pymupdf.Page, page_id: str):
    # The id ends up inside the PDF as a string: safe characters only (no brackets
    # or slashes that would change the structure of the file).
    if isinstance(page_id, str) and ID_RE.match(page_id):
        doc.xref_set_key(page.xref, PAGE_ID_KEY, f"({page_id})")


def _get_page_layout(doc: pymupdf.Document, page: pymupdf.Page):
    """Layout of the page if the app created it (None for the pages of an imported PDF)."""
    kind, value = doc.xref_get_key(page.xref, PAGE_LAYOUT_KEY)
    value = value.lstrip("/")
    return value if kind == "name" and layouts.exists(value) else None


def _set_page_layout(doc: pymupdf.Document, page: pymupdf.Page, layout):
    if layouts.exists(layout):
        doc.xref_set_key(page.xref, PAGE_LAYOUT_KEY, "/" + layout)


def load_document(path: Path):
    """Returns (clean_pdf_bytes, layer, revision) to send to the editor."""
    with file_lock(path):
        rev = revision_of(path)
        doc = pymupdf.open(path)
        try:
            stored = _read_layer(doc)
            if not isinstance(stored, dict):
                stored = {}
            listed = lambda v: v if isinstance(v, list) else []
            stored_pages = [p for p in listed(stored.get("pages")) if isinstance(p, dict)]
            known = {}
            for sp in stored_pages:
                for item in listed(sp.get("strokes")) + listed(sp.get("texts")) + listed(sp.get("images")):
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and ID_RE.match(item["id"]):
                        known[item["id"]] = item
            # Page ids: first the one written in the page itself; for PDFs saved by
            # earlier versions, the attachment's one if the number of pages
            # matches; otherwise a new id.
            fallback = ([sp.get("id") if isinstance(sp.get("id"), str) and ID_RE.match(sp.get("id")) else None
                         for sp in stored_pages]
                        if len(stored_pages) == doc.page_count else [None] * doc.page_count)
            page_ids, seen = [], set()
            for pg, fb in zip(doc, fallback):
                pid = _get_page_id(doc, pg) or fb
                if pid in seen:      # page duplicated by another program: new id
                    pid = None
                seen.add(pid)
                page_ids.append(pid)
            seen = set()
            pages = [_page_layer(pg, pid, known, _get_page_layout(doc, pg), seen)
                     for pg, pid in zip(doc, page_ids)]
            _strip_app_content(doc)
            clean = doc.tobytes(garbage=1, deflate=True)
        finally:
            doc.close()
    # The document id becomes the name of a page-cache folder: safe characters
    # only, otherwise a new one (never paths like "../..").
    doc_id = stored.get("docId")
    if not isinstance(doc_id, str) or not ID_RE.match(doc_id):
        doc_id = None
    # Layout of the next pages: the one chosen last time; for a new document,
    # the last page's one (i.e. the layout chosen at creation).
    next_layout = stored.get("nextLayout")
    if not layouts.exists(next_layout):
        next_layout = pages[-1]["layout"] if pages and pages[-1]["layout"] else layouts.DEFAULT
    return clean, {"version": LAYER_VERSION, "docId": doc_id or uuid.uuid4().hex,
                   "nextLayout": next_layout, "pages": pages}, rev


# --- Writing ---------------------------------------------------------------
def _hex_to_rgb(color):
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def smooth_polyline(points) -> list:
    """The same curve the editor draws (quadratic Béziers between midpoints),
    finely sampled: a PDF Ink annotation is made of straight segments, so this
    keeps the stroke smooth in the computer's PDF readers too."""
    if len(points) < 3:
        return list(points)
    out = [points[0]]
    start = points[0]
    for i in range(1, len(points) - 1):
        ctrl, nxt = points[i], points[i + 1]
        end = ((ctrl[0] + nxt[0]) / 2, (ctrl[1] + nxt[1]) / 2)
        length = (abs(ctrl[0] - start[0]) + abs(ctrl[1] - start[1])
                  + abs(end[0] - ctrl[0]) + abs(end[1] - ctrl[1]))
        steps = max(1, min(8, int(length / 1.5)))   # about one point every 1.5 PDF points
        for k in range(1, steps + 1):
            t = k / steps
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            out.append((a * start[0] + b * ctrl[0] + c * end[0], a * start[1] + b * ctrl[1] + c * end[1]))
        start = end
    out.append(points[-1])
    return out


def _add_annotations(page: pymupdf.Page, pdata: dict, pictures_dir: Path | None):
    # Coordinates arrive in the page's "visible" space (origin top left, like
    # pdf.js). For rotated pages they are mapped back to the unrotated space.
    m = page.derotation_matrix
    # Images first, so strokes and texts are drawn on top of them.
    for img in pdata.get("images", []):
        if pictures_dir is None or not PICTURE_RE.match(img["file"]):
            continue
        picture = pictures_dir / img["file"]
        if not picture.is_file():
            continue  # file deleted on the computer: the image is not written
        rect = pymupdf.Rect(img["x"], img["y"], img["x"] + img["w"], img["y"] + img["h"]) * m
        annot = page.add_stamp_annot(rect, stamp=picture.read_bytes())
        annot.set_info(subject=SUBJECT_PREFIX + img["id"], title="notes-app")
        annot.update()
    for s in pdata["strokes"]:
        xy = [(x, y) for x, y, _ in s["points"]]
        # Geometric shapes already have the right points (sharp corners): no smoothing.
        pts = [pymupdf.Point(x, y) * m for x, y in (xy if s.get("shape") else smooth_polyline(xy))]
        if len(pts) == 1:
            pts.append(pts[0] + (0.01, 0.01))
        annot = page.add_ink_annot([[(q.x, q.y) for q in pts]])
        annot.set_colors(stroke=_hex_to_rgb(s["color"]))
        annot.set_border(width=s["width"])
        if s["tool"] == "highlighter":
            annot.set_opacity(0.35)
            annot.set_blendmode(pymupdf.PDF_BM_Multiply)
        annot.set_info(subject=SUBJECT_PREFIX + s["id"], title="notes-app")
        annot.update()
    for t in pdata["texts"]:
        if not t["text"].strip():
            continue
        rect = pymupdf.Rect(t["x"], t["y"], t["x"] + t["w"], t["y"] + t["h"]) * m
        annot = page.add_freetext_annot(rect, t["text"], fontsize=t["size"], fontname="helv",
                                        text_color=_hex_to_rgb(t["color"]), rotate=page.rotation)
        annot.set_border(width=0)
        annot.set_info(subject=SUBJECT_PREFIX + t["id"], title="notes-app")
        annot.update()


def save_document(path: Path, layer: dict, base_revision: str, pagecache: Path,
                  base_bytes: bytes | None = None, backup_to: Path | None = None,
                  pictures_dir: Path | None = None):
    """Writes the layer into the PDF. Returns (new revision, written content).

    Normal: the file on disk must still be at revision `base_revision`
    (otherwise RevisionMismatch) and is the base for writing.
    Forced (base_bytes): start from the given PDF (the last one saved by the
    iPad) and replace the file on disk; if `backup_to` is given, the file is
    first copied there (backup of the computer's version).

    Saving is atomic: a temporary file is written in the same folder and then
    replaces the original, so the PDF on disk is always intact (either the
    previous version or the new one, never half of it). The starting PDF is read
    into memory: no file stays open during the replacement (on Windows an open
    file cannot be replaced).
    """
    with file_lock(path):
        if base_bytes is None:
            current = path.read_bytes()
            if hashlib.sha256(current).hexdigest() != base_revision:
                raise RevisionMismatch()
            doc = pymupdf.open(stream=current, filetype="pdf")
        else:
            if backup_to is not None and path.exists():
                shutil.copy2(path, backup_to)
            doc = pymupdf.open(stream=base_bytes, filetype="pdf")
        try:
            n = doc.page_count
            stored = _read_layer(doc) or {}
            prev_ids = [p.get("id") for p in stored.get("pages", [])]
            if len(prev_ids) != n:
                prev_ids = []
            _strip_app_content(doc)
            same_structure = [p["src"] for p in layer["pages"]] == list(range(n))
            if same_structure:
                out = doc  # no pages added/removed: the file is modified as it is
            else:
                out = _rebuild(doc, layer, pagecache, prev_ids)
                write_doc_info(out, **read_doc_info(doc))  # colour and date move to the new file
            for page, pdata in zip(out, layer["pages"]):
                _add_annotations(page, pdata, pictures_dir)
                _set_page_id(out, page, pdata["id"])
                _set_page_layout(out, page, pdata.get("layout"))
            out.embfile_add(LAYER_FILE, json.dumps(layer, separators=(",", ":")).encode("utf-8"),
                            filename=LAYER_FILE, desc="Dati modificabili di notes-app")
            fd, tmp = tempfile.mkstemp(prefix=".~", suffix=".pdf.tmp", dir=path.parent)
            os.close(fd)
            try:
                out.save(tmp, garbage=3, deflate=True)
                if out is not doc:
                    out.close()
                with open(tmp, "rb+") as fh:
                    os.fsync(fh.fileno())
                replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        finally:
            doc.close()
        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest(), data


def _rebuild(doc: pymupdf.Document, layer: dict, pagecache: Path,
             prev_ids: list) -> pymupdf.Document:
    """Rebuilds the document when pages were added, removed or reordered."""
    cache_dir = pagecache / layer["docId"]
    used = {p["src"] for p in layer["pages"] if p["src"] is not None}
    # 1. Pages that disappear go to the cache (clean) for a possible "undo".
    for i in range(doc.page_count):
        if i not in used and i < len(prev_ids) and prev_ids[i] and ID_RE.match(prev_ids[i]):
            cache_dir.mkdir(parents=True, exist_ok=True)
            single = pymupdf.open()
            single.insert_pdf(doc, from_page=i, to_page=i)
            single.save(cache_dir / f"{prev_ids[i]}.pdf")
            single.close()
    # 2. New document with the pages in the requested order.
    out = pymupdf.open()
    out.set_metadata(doc.metadata)
    for p in layer["pages"]:
        if p["src"] is not None:
            if p["src"] >= doc.page_count:
                raise ValueError("Pagina sorgente inesistente")
            out.insert_pdf(doc, from_page=p["src"], to_page=p["src"])
        elif not p["blank"] and (cache_dir / f"{p['id']}.pdf").is_file():
            cached = pymupdf.open(cache_dir / f"{p['id']}.pdf")
            out.insert_pdf(cached)
            cached.close()
        else:
            layouts.new_page(out, p["w"], p["h"], p.get("layout"))  # new page: draw its layout
    return out


def blank_pdf(pages=1, size=A4, layout=layouts.DEFAULT, color=None, created=None) -> bytes:
    """Content of a new PDF with pages of the chosen layout, note colour and
    creation date (UserFolder writes it afterwards)."""
    doc = pymupdf.open()
    write_doc_info(doc, color=color, created=created)
    for _ in range(pages):
        page = layouts.new_page(doc, size[0], size[1], layout)
        _set_page_layout(doc, page, layout)
    data = doc.tobytes()
    doc.close()
    return data


def is_valid_pdf(data: bytes) -> bool:
    """True if the bytes are a PDF that opens, with at least one page and no password."""
    if not data.startswith(b"%PDF-"):
        return False
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count > 0 and not doc.needs_pass
    except Exception:
        return False


def clean_pagecache(pagecache: Path, max_age_hours=24):
    if not pagecache.is_dir():
        return
    limit = time.time() - max_age_hours * 3600
    for f in pagecache.rglob("*.pdf"):
        if f.stat().st_mtime < limit:
            f.unlink(missing_ok=True)
