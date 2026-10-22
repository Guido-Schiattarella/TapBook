"""CONTROL — document editing, also from several devices at once.

Every open document has a "room" (Room) on the computer holding the document model.
Every device that opens it is a "client" of the room:
  1. a device's view sends the controller an operation (stroke, eraser, lasso,
     text, image, page, layout, undo/redo);
  2. the controller validates it, decides what to do (for eraser and lasso it
     works out which items the gesture touched) and tells the model to apply it;
  3. the model notifies the controller of what changed (events);
  4. the controller sends the events back to the view that made the operation
     (in the response) and queues them for the other devices, which receive them
     on the request that always stays open towards the computer (/api/edit/listen);
  5. after 1 second without operations the controller tells the model to save
     the PDF; if the file was changed on the computer in the meantime, the
     changes are merged (merge_external) or, if the pages changed, the version
     in use wins and the computer's version goes to the trash.
Each device has its own undo/redo history: it undoes only its own changes.
"""
import collections
import copy
import datetime as dt
import math
import re
import secrets
import threading
import time
from pathlib import Path

from ..model import layouts, pdf_store, save_worker
from ..model.document import OpenDocument, PageStructureChanged, new_id
from ..model.pictures import InvalidPicture, prepare_picture
from . import geometry, shapes
from .errors import ControlError, InvalidInput

AUTOSAVE_DELAY = 1.0          # seconds of inactivity before saving
RETRY_DELAY = 3.0             # retry after a write error
HISTORY_LIMIT = 500           # undo steps kept per device
LISTEN_WAIT_MAX = 25.0        # maximum duration of a /listen request
IDLE_CHECK_SECONDS = 30       # how often idle devices are looked for
MERGE_ATTEMPTS = 3            # if the file changes again during the merge, try again

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_STROKES_PER_PAGE = 20000
MAX_POINTS_PER_STROKE = 20000
MAX_TEXT_LEN = 20000
TEXT_SIZE_MIN, TEXT_SIZE_MAX = 4.0, 200.0   # font size of text boxes (as read back from the PDF)
TEXT_W_MIN = 20.0                         # narrowest text box (PDF points)
MAX_PAGES = 2000
MAX_IMAGE_BYTES = 30 * 1024 * 1024   # photos coming from the iPad
MAX_IMAGES_PER_PAGE = 50
MAX_TEXTS_PER_PAGE = 2000
MAX_GESTURE_POINTS = 10000           # points of an eraser path or a lasso outline
ERASER_RADIUS = 7.0                  # default eraser radius (PDF points)
ERASER_RADIUS_RANGE = (1.0, 60.0)    # allowed radii (the view offers Fine, Medium, Large)
# The view hides right away the strokes the eraser seems to touch and names them in
# the operation; the controller still checks each one against the path, with this
# margin (PDF points) for the small differences between the two computations.
# Without it a stroke "touched" on the iPad but just missed here would reappear.
ERASE_TOLERANCE = 1.5
MAX_ERASE_IDS = 5000
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")   # browser tab identifier
DUPLICATE_OFFSET = 15.0              # offset of the copies made with the lasso

# Kinds of page items and the model methods that add/remove them.
ITEM_KINDS = {"strokes": ("add_stroke", "remove_stroke"),
              "texts": ("add_text", "remove_text"),
              "images": ("add_image", "remove_image")}


class SessionGone(ControlError):
    """The device is no longer connected to the document. The reason tells the
    view what to do:
      idle      no changes for too long → the view reopens by itself from the current version
      unknown   server restarted or unknown session → the view reopens by itself
      replaced  the same browser tab opened the document again (e.g. page reload)"""
    status = 410

    def __init__(self, reason: str):
        super().__init__("Sessione di modifica chiusa: il documento viene riaperto.", reason=reason)


# --- Validation of the data sent by the view (never trust the browser) -----------------
def _num(v, lo=-1e6, hi=1e6):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        raise InvalidInput("Numero non valido")
    return max(lo, min(hi, float(v)))


def _id(v):
    if not isinstance(v, str) or not ID_RE.match(v):
        raise InvalidInput("Id non valido")
    return v


def _color(v):
    if not isinstance(v, str) or not COLOR_RE.match(v):
        raise InvalidInput("Colore non valido")
    return v.lower()


def validate_stroke(s) -> dict:
    if not isinstance(s, dict):
        raise InvalidInput("Tratto non valido")
    pts = s.get("points")
    if not isinstance(pts, list) or not pts or len(pts) > MAX_POINTS_PER_STROKE:
        raise InvalidInput("Tratto non valido")
    tool = s.get("tool", "pen")
    if tool not in ("pen", "highlighter"):
        raise InvalidInput("Strumento non valido")
    points = [[_num(p[0]), _num(p[1]), _num(p[2] if len(p) > 2 else 0.5, 0, 1)]
              for p in pts if isinstance(p, list) and len(p) >= 2]
    if not points:
        raise InvalidInput("Tratto non valido")
    stroke = {"id": _id(s.get("id")), "tool": tool, "color": _color(s.get("color", "#000000")),
              "width": _num(s.get("width", 2), 0.1, 100), "points": points}
    if s.get("shape") is not None:          # stroke turned into a geometric shape
        if s["shape"] not in shapes.SHAPE_KINDS:
            raise InvalidInput("Forma non valida")
        stroke["shape"] = s["shape"]
    return stroke


def _text_value(v) -> str:
    if not isinstance(v, str) or len(v) > MAX_TEXT_LEN:
        raise InvalidInput("Testo non valido")
    return v


def _gesture(v) -> list:
    """Eraser path or lasso outline: [[x, y], ...]."""
    if not isinstance(v, list) or not v or len(v) > MAX_GESTURE_POINTS:
        raise InvalidInput("Gesto non valido")
    return [(_num(p[0]), _num(p[1])) for p in v if isinstance(p, list) and len(p) >= 2]


def _id_set(v) -> set:
    if v is None:
        return set()
    if not isinstance(v, list) or len(v) > MAX_STROKES_PER_PAGE:
        raise InvalidInput("Selezione non valida")
    return {_id(i) for i in v}


def _remove_items(doc, pid, ids: dict) -> list:
    """Removes the given items from the page (those still present).
    Returns [(kind, item, position)] so they can be put back."""
    page, removed = doc.page(pid), []
    for kind, (_, remove) in ITEM_KINDS.items():
        for item in list(page.setdefault(kind, [])):
            if item["id"] in ids.get(kind, ()):
                removed.append((kind, *getattr(doc, remove)(pid, item["id"])))
    return removed


def _restore_items(doc, pid, removed: list):
    """Puts the items removed by _remove_items back in their original positions
    (in reverse order: each position refers to the page at that moment)."""
    page = doc.page(pid)
    for kind, item, index in reversed(removed):
        getattr(doc, ITEM_KINDS[kind][0])(pid, item, min(index, len(page[kind])))


def _ids_of(removed: list) -> dict:
    ids = {kind: set() for kind in ITEM_KINDS}
    for kind, item, _ in removed:
        ids[kind].add(item["id"])
    return ids


# --- Room (shared document) and client (device) ---------------------------------------
class Room:
    def __init__(self, username: str, rel: str, doc: OpenDocument):
        self.username, self.rel, self.doc = username, rel, doc
        self.clients: dict[str, "Client"] = {}
        self.state = "saved"                 # saved | pending | saving | error
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.timer = None
        self.closed = False
        # Writing the PDF happens outside `lock` (see EditController._save):
        # save_lock is held only while writing, and the result waits in
        # pending_save until it is recorded with `lock` held.
        self.save_lock = threading.Lock()
        self.saving = False
        self.pending_save = None

    def broadcast(self, events, exclude=None):
        """Queues the events for all devices (except `exclude`)."""
        if not events:
            return
        for client in self.clients.values():
            if client is not exclude:
                client.outbox.extend(events)
        self.changed.notify_all()


class Client:
    def __init__(self, room: Room, device=None):
        self.id = secrets.token_urlsafe(16)
        self.room = room
        self.device = device                 # browser tab it belongs to (see open)
        self.done, self.undone = [], []      # this device's history
        self.text_before = {}                # text at the start of the edit in progress
        self.outbox = []                     # events to deliver to this device
        self.last_used = time.time()         # last change made by this device
        self.sent_state = None               # last save status reported


class EditController:
    def __init__(self, library, pagecache_root: Path, idle_minutes: float = 15):
        self.library = library
        self.pagecache_root = pagecache_root
        self.idle_seconds = idle_minutes * 60
        self.rooms: dict[tuple, Room] = {}
        self.clients: dict[str, Client] = {}
        self.closed = collections.OrderedDict()   # closed client id -> reason
        self.lock = threading.Lock()
        pdf_store.clean_pagecache(pagecache_root)  # pages deleted more than 24 hours ago
        # Periodic check: a device that does not change the document for
        # idle_minutes is disconnected; when nobody is left the document is saved
        # and closed. This way "open" means "in use right now".
        threading.Thread(target=self._idle_loop, daemon=True, name="chiusura-inattivi").start()

    # --- opening and closing ------------------------------------------------------------
    def open(self, username: str, rel: str, device=None) -> dict:
        """Connects a device to the document. If it is already open on another
        device, it joins the same room and sees the current state right away.
        device: identifier of the browser tab (it survives a page reload). The
        same tab opening the document again (reload, reopening) replaces its
        previous connection instead of counting as one more device."""
        device = device if isinstance(device, str) and DEVICE_RE.match(device) else None
        rel = self.library.open_document(username, rel)  # NotFound if it is not one of the user's PDFs
        key = (username, rel)
        while True:
            with self.lock:
                room = self.rooms.get(key)
            if room is None:
                folder = self.library.folder(username)
                doc = OpenDocument(folder.resolve(rel), self.pagecache_root / username,
                                   folder.pictures_dir(rel))
                with self.lock:
                    if key in self.rooms:
                        continue  # opened by another device in the meantime
                    room = self.rooms[key] = Room(username, rel, doc)
            with room.lock:
                if room.closed:
                    continue      # it was closing: a new one is created
                client = Client(room, device)
                room.clients[client.id] = client
                if device:
                    for old in [c for c in room.clients.values() if c is not client and c.device == device]:
                        self._detach(old, "replaced")
                client.sent_state = room.state
                # The background PDF is not sent here: the view downloads it separately, as a
                # binary file in chunks (GET /api/edit/background), with the progress bar.
                result = {"session": client.id, "path": rel,
                          "pages": room.doc.view_pages(), "canUndo": False, "canRedo": False,
                          "status": self._public_state(room), "devices": len(room.clients),
                          "layout": room.doc.next_layout, "layouts": self.library.layout_catalog(),
                          "eraserRadius": ERASER_RADIUS}
                room.broadcast([{"event": "devices", "count": len(room.clients)}], exclude=client)
            with self.lock:
                self.clients[client.id] = client
            return result

    def close(self, username: str, client_id: str) -> str:
        """The view leaves the editor: if it was the last device, save right away.
        Returns the document's folder."""
        client = self._get(username, client_id)
        self._detach(client, "closed")
        return client.room.rel.rpartition("/")[0]

    def is_open(self, username: str, rel: str) -> bool:
        """True if the document `rel`, or a document inside the folder `rel`, is open."""
        with self.lock:
            return any(u == username and (r == rel or not rel or r.startswith(rel + "/"))
                       for u, r in self.rooms)

    def close_user(self, username: str):
        """Account deleted: its open documents are saved and closed."""
        for client in list(self.clients.values()):
            if client.room.username == username:
                self._detach(client, "closed")

    def flush_all(self):
        """On server shutdown: saves all open documents, then stops the process
        that writes the PDFs."""
        for client in list(self.clients.values()):
            self._detach(client, "shutdown")
        save_worker.shutdown()

    # --- operations from the view ----------------------------------------------------------
    def apply(self, username: str, client_id: str, op) -> dict:
        client = self._get(username, client_id)
        if not isinstance(op, dict) or not isinstance(op.get("type"), str) or not op["type"].isalpha():
            raise InvalidInput("Operazione non valida")
        handler = getattr(self, "_op_" + op["type"], None)
        if handler is None:
            raise InvalidInput("Operazione sconosciuta")
        return self._run(client, lambda: handler(client, op))

    def _run(self, client: Client, action) -> dict:
        """Runs a change on the model while collecting its notifications: they go to
        the device that made it (response) and to the others (queue). An operation
        can also return events only for its author (e.g. the lasso selection)."""
        room = client.room
        with room.lock:
            mine = []
            room.doc.subscribe(mine.append)       # the model notifies the controller
            try:
                private = action() or []
            except LookupError as e:
                raise InvalidInput(str(e))
            finally:
                room.doc.unsubscribe(mine.append)
            client.last_used = time.time()
            room.broadcast(mine, exclude=client)   # the other devices see the change
            if mine:
                self._schedule_save(room)
            return self._reply(client, mine + private)

    def add_image(self, username: str, client_id: str, page_id, x, y, max_w, data: bytes) -> dict:
        """New image: the file goes into pictures/<document>/ on the computer, and the
        page gets a reference to it (movable and removable like strokes)."""
        client = self._get(username, client_id)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise InvalidInput("Immagine troppo grande o vuota")
        try:
            picture, ext, px_w, px_h = prepare_picture(data)   # the model prepares the file
        except InvalidPicture as e:
            raise InvalidInput(str(e))
        room = client.room
        with room.lock:
            try:
                page = room.doc.page(_id(page_id))
            except LookupError as e:
                raise InvalidInput(str(e))
            if len(page.get("images", [])) >= MAX_IMAGES_PER_PAGE:
                raise InvalidInput("Troppe immagini in questa pagina")
            image_id = new_id()
            name = f"{image_id}.{ext}"
            self.library.folder(username).save_picture(room.rel, name, picture)
            # Size: at most the given width (or 60% of the page), image proportions
            # kept, centred on the given point.
            w = min(_num(max_w, 20, page["w"]) if max_w is not None else page["w"] * 0.6, page["w"] * 0.9)
            h = w * px_h / px_w
            if h > page["h"] * 0.9:
                h = page["h"] * 0.9
                w = h * px_w / px_h
            cx, cy = _num(x, 0, page["w"]), _num(y, 0, page["h"])
            image = {"id": image_id, "file": name, "w": w, "h": h,
                     "x": min(max(0.0, cx - w / 2), page["w"] - w),
                     "y": min(max(0.0, cy - h / 2), page["h"] - h)}
            doc, pid = room.doc, page["id"]
            return self._run(client, lambda: self._push(
                client, undo=lambda: doc.remove_image(pid, image_id),
                redo=lambda: doc.add_image(pid, image)))

    def picture(self, username: str, client_id: str, image_id: str) -> Path:
        """File of a document image (to show it in the view)."""
        client = self._get(username, client_id)
        with client.room.lock:
            try:
                return client.room.doc.picture_path(_id(image_id))
            except LookupError:
                raise InvalidInput("Immagine non trovata")

    def layout_page(self, username: str, client_id: str, page_id) -> bytes:
        """Background of a page added in this session and not yet in the original
        PDF: an empty page with its layout, drawn by the model."""
        client = self._get(username, client_id)
        with client.room.lock:
            try:
                page = client.room.doc.page(_id(page_id))
            except LookupError as e:
                raise InvalidInput(str(e))
            layout, w, h = page.get("layout") or layouts.DEFAULT, page["w"], page["h"]
        return layouts.page_pdf(layout, w, h)

    def listen(self, username: str, client_id: str) -> dict:
        """Request the view always keeps open: it answers as soon as there are
        changes from other devices or from the computer, or when the save status
        changes (at most after LISTEN_WAIT_MAX seconds)."""
        client = self._get(username, client_id)
        room = client.room
        with room.changed:
            room.changed.wait_for(
                lambda: client.outbox or client.sent_state != self._public_state(room)
                or client.id not in room.clients,
                timeout=LISTEN_WAIT_MAX)
            if client.id not in room.clients:
                raise SessionGone(self.closed.get(client.id, "unknown"))
            return self._reply(client, [])

    def background(self, username: str, client_id: str) -> bytes:
        """Current background PDF: on opening and after merging changes made on the computer."""
        client = self._get(username, client_id)
        with client.room.lock:
            return client.room.doc.base_pdf

    def _reply(self, client: Client, mine: list) -> dict:
        """Response for a device: first the news from the others, then its own."""
        room = client.room
        events, client.outbox = client.outbox + mine, []
        client.sent_state = self._public_state(room)
        return {"events": events, "canUndo": bool(client.done), "canRedo": bool(client.undone),
                "status": client.sent_state, "devices": len(room.clients)}

    # --- single operations -----------------------------------------------------------------
    def _push(self, client, undo, redo, execute=True, tag=None):
        if execute:
            redo()
        client.done.append({"undo": undo, "redo": redo, "tag": tag})
        del client.done[:-HISTORY_LIMIT]
        client.undone.clear()

    # A history step may refer to a note that has since been deleted (by another
    # device or on the computer): that step is skipped.
    def _op_undo(self, client, op):
        while client.done:
            cmd = client.done.pop()
            try:
                cmd["undo"]()
            except LookupError:
                continue
            client.undone.append(cmd)
            return

    def _op_redo(self, client, op):
        while client.undone:
            cmd = client.undone.pop()
            try:
                cmd["redo"]()
            except LookupError:
                continue
            client.done.append(cmd)
            return

    def _op_addStroke(self, client, op):
        doc, pid = client.room.doc, _id(op.get("page"))
        stroke = validate_stroke(op.get("stroke"))
        if doc.has_stroke(pid, stroke["id"]):
            raise InvalidInput("Tratto già presente")
        if len(doc.page(pid)["strokes"]) >= MAX_STROKES_PER_PAGE:
            raise InvalidInput("Troppi tratti in questa pagina")
        self._push(client, undo=lambda: doc.remove_stroke(pid, stroke["id"]),
                   redo=lambda: doc.add_stroke(pid, stroke))

    def _op_erase(self, client, op):
        """Eraser: the view sends the path drawn with the Pencil and the eraser size;
        the controller decides which strokes it touched and tells the model to remove them."""
        doc, pid = client.room.doc, _id(op.get("page"))
        radius = _num(op.get("radius", ERASER_RADIUS), *ERASER_RADIUS_RANGE)
        strokes = doc.page(pid)["strokes"]
        path = _gesture(op.get("path"))
        hit = set(geometry.strokes_touched(strokes, path, radius))
        # Strokes the view already hid: confirmed if they are within the margin.
        named = op.get("ids")
        if isinstance(named, list) and len(named) <= MAX_ERASE_IDS:
            named = {x for x in named if isinstance(x, str)} - hit
            candidates = [st for st in strokes if st["id"] in named]
            hit.update(geometry.strokes_touched(candidates, path, radius + ERASE_TOLERANCE))
        removed = _remove_items(doc, pid, {"strokes": hit})
        if removed:
            self._push(client, undo=lambda: _restore_items(doc, pid, removed),
                       redo=lambda: _remove_items(doc, pid, _ids_of(removed)), execute=False)

    def _op_addText(self, client, op):
        """New text box at the tapped point: the controller decides position and size."""
        doc, pid = client.room.doc, _id(op.get("page"))
        page = doc.page(pid)
        if len(page["texts"]) >= MAX_TEXTS_PER_PAGE:
            raise InvalidInput("Troppe caselle di testo in questa pagina")
        x, y = _num(op.get("x"), 0, page["w"]), _num(op.get("y"), 0, page["h"])
        size = _num(op.get("size", 16), TEXT_SIZE_MIN, TEXT_SIZE_MAX)
        t = {"id": new_id(), "x": x, "y": max(0.0, y - size * 0.6), "w": min(260.0, page["w"] - x - 10),
             "h": max(30.0, size * 1.6), "size": size, "color": _color(op.get("color", "#000000")), "text": ""}
        if t["w"] < 60:
            t["x"], t["w"] = max(0.0, page["w"] - 270), 260.0
        self._push(client, undo=lambda: doc.remove_text(pid, t["id"]),
                   redo=lambda: doc.add_text(pid, t), tag=("addText", t["id"]))

    def _op_editText(self, client, op):
        """Typed text. It becomes an undo step only when the edit ends (commit)."""
        doc, pid, tid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        current = doc.text(pid, tid)
        key = (pid, tid)
        if key not in client.text_before:
            client.text_before[key] = {"text": current["text"], "h": current["h"]}
        doc.update_text(pid, tid, text=_text_value(op.get("text")),
                        h=_num(op.get("h", current["h"]), 10, 5000))
        if op.get("commit"):
            before = client.text_before.pop(key)
            after = {"text": current["text"], "h": current["h"]}
            if before != after:
                self._push(client, undo=lambda: doc.update_text(pid, tid, **before),
                           redo=lambda: doc.update_text(pid, tid, **after), execute=False)

    def _op_moveText(self, client, op):
        doc, pid, tid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        t = doc.text(pid, tid)
        before = {"x": t["x"], "y": t["y"]}
        after = {"x": _num(op.get("x"), -5000, 20000), "y": _num(op.get("y"), -5000, 20000)}
        if before != after:
            self._push(client, undo=lambda: doc.update_text(pid, tid, **before),
                       redo=lambda: doc.update_text(pid, tid, **after))

    def _op_changeText(self, client, op):
        """Box resized, or new font size or colour: one undo step. Only the fields
        present in the operation change."""
        doc, pid, tid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        t = doc.text(pid, tid)
        after = {}
        if "w" in op:
            after["w"] = _num(op["w"], TEXT_W_MIN, 20000)
        if "h" in op:
            after["h"] = _num(op["h"], 10, 5000)
        if "size" in op:
            after["size"] = _num(op["size"], TEXT_SIZE_MIN, TEXT_SIZE_MAX)
        if "color" in op:
            after["color"] = _color(op["color"])
        before = {k: t[k] for k in after}
        if before != after:
            # A text edit in progress keeps its starting height for "undo" in step.
            key = (pid, tid)
            if key in client.text_before and "h" in after:
                client.text_before[key]["h"] = after["h"]
            self._push(client, undo=lambda: doc.update_text(pid, tid, **before),
                       redo=lambda: doc.update_text(pid, tid, **after))

    def _op_removeText(self, client, op):
        doc, pid, tid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        client.text_before.pop((pid, tid), None)
        if not any(x["id"] == tid for x in doc.page(pid)["texts"]):
            return  # already removed (e.g. empty box removed when leaving the field)
        t = doc.text(pid, tid)
        index = doc.page(pid)["texts"].index(t)
        self._push(client, undo=lambda: doc.add_text(pid, t, index),
                   redo=lambda: doc.remove_text(pid, tid))

    def _op_discardText(self, client, op):
        """A text box left empty is removed. If it had just been created, its
        creation is removed from the history too (no useless step remains)."""
        doc, pid, tid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        before = client.text_before.pop((pid, tid), None)
        if client.done and client.done[-1]["tag"] == ("addText", tid):
            client.done.pop()
            doc.remove_text(pid, tid)
            return
        if before:
            doc.update_text(pid, tid, **before)
        self._op_removeText(client, op)

    def _op_changeImage(self, client, op):
        """Moving or resizing an image."""
        doc, pid, iid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        page = doc.page(pid)
        img = doc.image(pid, iid)
        before = {k: img[k] for k in ("x", "y", "w", "h")}
        after = {"x": _num(op.get("x"), -5000, 20000), "y": _num(op.get("y"), -5000, 20000),
                 "w": _num(op.get("w"), 10, page["w"] * 2), "h": _num(op.get("h"), 10, page["h"] * 2)}
        if before != after:
            self._push(client, undo=lambda: doc.update_image(pid, iid, **before),
                       redo=lambda: doc.update_image(pid, iid, **after))

    def _op_removeImage(self, client, op):
        doc, pid, iid = client.room.doc, _id(op.get("page")), _id(op.get("id"))
        if not any(i["id"] == iid for i in doc.page(pid).get("images", [])):
            return
        img = doc.image(pid, iid)
        index = doc.page(pid)["images"].index(img)
        # The file stays in the folder while the document is open (undo needs it);
        # on close, files no longer used go to the trash.
        self._push(client, undo=lambda: doc.add_image(pid, img, index),
                   redo=lambda: doc.remove_image(pid, iid))

    def _op_addPage(self, client, op):
        doc = client.room.doc
        if len(doc.pages) >= MAX_PAGES:
            raise InvalidInput("Troppe pagine")
        index = doc.page_index(_id(op.get("after"))) + 1
        # The new page gets the layout chosen at that moment for the document.
        page = doc.new_blank_page(doc.pages[index - 1], doc.next_layout)

        def redo():
            doc.insert_page(page, min(index, len(doc.pages)))

        self._push(client, undo=lambda: doc.remove_page(page["id"]), redo=redo)

    def _op_removePage(self, client, op):
        doc, pid = client.room.doc, _id(op.get("page"))
        if len(doc.pages) <= 1:
            raise InvalidInput("Il documento deve avere almeno una pagina")
        page = doc.page(pid)
        index = doc.page_index(pid)
        self._push(client, undo=lambda: doc.insert_page(page, min(index, len(doc.pages))),
                   redo=lambda: doc.remove_page(pid))

    def _op_setLayout(self, client, op):
        """Layout of the pages that will be added (existing ones do not change).
        It is a document setting: it is not part of the undo history."""
        layout = op.get("layout")
        if not layouts.exists(layout):
            raise InvalidInput("Layout sconosciuto")
        if layout != client.room.doc.next_layout:
            client.room.doc.set_next_layout(layout)

    # --- lasso ------------------------------------------------------------------------------
    # The view sends the drawn outline; the controller picks the enclosed items and
    # answers (to that device only) with the selection. Later operations name the
    # selected items and each becomes a single undo step.
    def _op_select(self, client, op):
        doc, pid = client.room.doc, _id(op.get("page"))
        polygon = _gesture(op.get("polygon"))
        if len(polygon) < 3:
            raise InvalidInput("Contorno troppo corto")
        return [{"event": "selection", "page": pid, **geometry.lasso_select(doc.page(pid), polygon)}]

    # --- geometric shapes ---------------------------------------------------------------------
    def _op_recognizeShape(self, client, op):
        """The view asks which shape the stroke just drawn is (the document is not
        changed): the controller recognises it and answers, to that device only, with
        the clean shape. End points and corners snap to those of existing shapes within `tolerance`."""
        doc, pid = client.room.doc, _id(op.get("page"))
        points = _gesture(op.get("points"))
        tolerance = _num(op.get("tolerance", 8), 1, 60)
        kind, pts = shapes.recognize(points, shapes.snap_targets(doc.page(pid)["strokes"]), tolerance)
        return [{"event": "shape", "page": pid, "kind": kind,
                 "points": [[round(x, 2), round(y, 2), 0.5] for x, y in pts] if pts else None}]

    def _selection(self, client, op):
        doc, pid = client.room.doc, _id(op.get("page"))
        doc.page(pid)  # LookupError if the page no longer exists
        return doc, pid, {kind: _id_set(op.get(kind)) for kind in ITEM_KINDS}

    def _op_moveSelection(self, client, op):
        doc, pid, sel = self._selection(client, op)
        dx, dy = _num(op.get("dx"), -20000, 20000), _num(op.get("dy"), -20000, 20000)
        if dx == 0 and dy == 0:
            return
        moved = doc.move_items(pid, sel["strokes"], sel["texts"], sel["images"], dx, dy)
        if any(moved.values()):
            ids = [set(moved[k]) for k in ("strokes", "texts", "images")]
            self._push(client, undo=lambda: doc.move_items(pid, *ids, -dx, -dy),
                       redo=lambda: doc.move_items(pid, *ids, dx, dy), execute=False)

    def _op_recolorSelection(self, client, op):
        """New colour for the selected strokes and texts (images stay as they are)."""
        doc, pid, sel = self._selection(client, op)
        color = _color(op.get("color"))
        before = doc.colors_of(pid, sel["strokes"], sel["texts"])
        if all(c == color for _, c in before.values()):
            return
        after = {item_id: (kind, color) for item_id, (kind, _) in before.items()}
        self._push(client, undo=lambda: doc.set_colors(pid, before),
                   redo=lambda: doc.set_colors(pid, after))

    def _op_removeSelection(self, client, op):
        doc, pid, sel = self._selection(client, op)
        removed = _remove_items(doc, pid, sel)
        if removed:
            self._push(client, undo=lambda: _restore_items(doc, pid, removed),
                       redo=lambda: _remove_items(doc, pid, _ids_of(removed)), execute=False)

    def _op_duplicateSelection(self, client, op):
        """Copy of the selected items, slightly down and to the right; the selection
        moves to the copies."""
        doc, pid, sel = self._selection(client, op)
        page, d = doc.page(pid), DUPLICATE_OFFSET
        copies = {
            "strokes": [{**copy.deepcopy(s), "id": new_id(),
                         "points": [[x + d, y + d, pr] for x, y, pr in s["points"]]}
                        for s in page["strokes"] if s["id"] in sel["strokes"]],
            "texts": [{**t, "id": new_id(), "x": t["x"] + d, "y": t["y"] + d}
                      for t in page["texts"] if t["id"] in sel["texts"]],
            "images": [{**i, "id": new_id(), "x": i["x"] + d, "y": i["y"] + d}
                       for i in page.get("images", []) if i["id"] in sel["images"]],
        }
        if not any(copies.values()):
            return
        if (len(page["strokes"]) + len(copies["strokes"]) > MAX_STROKES_PER_PAGE
                or len(page["texts"]) + len(copies["texts"]) > MAX_TEXTS_PER_PAGE
                or len(page.get("images", [])) + len(copies["images"]) > MAX_IMAGES_PER_PAGE):
            raise InvalidInput("Troppi elementi in questa pagina")
        ids = {kind: {item["id"] for item in items} for kind, items in copies.items()}

        def redo():
            for kind, items in copies.items():
                for item in items:
                    getattr(doc, ITEM_KINDS[kind][0])(pid, item)

        self._push(client, undo=lambda: _remove_items(doc, pid, ids), redo=redo)
        return [{"event": "selection", "page": pid, **{k: sorted(v) for k, v in ids.items()}}]

    # --- autosave ---------------------------------------------------------------------------
    def _schedule_save(self, room):
        """Every change (from any device) restarts the 1-second countdown."""
        room.state = "pending"
        self._start_timer(room, AUTOSAVE_DELAY)

    def _start_timer(self, room, delay):
        if room.timer:
            room.timer.cancel()
        room.timer = threading.Timer(delay, self._save, (room,))
        room.timer.daemon = True
        room.timer.start()

    def _save(self, room):
        """Autosave (timer thread). The PDF is written WITHOUT holding the room's
        lock: strokes, undo and the other operations of the devices go on at
        once instead of waiting for the file (which can take up to a second on
        large documents). Only copying the notes and recording the result
        happen with the lock held."""
        with room.lock:
            if room.closed or room.saving or room.state not in ("pending", "error"):
                return
            room.state = "saving"
            room.saving = True
            job = room.doc.prepare_save()
        with room.save_lock:
            try:
                room.pending_save = (job, room.doc.write_save(job), None)
            except Exception as e:     # handled by _finish_save, with the lock held
                room.pending_save = (job, None, e)
        with room.lock:
            self._finish_save(room)

    def _finish_save(self, room):
        """Records the result of a background write (with room.lock held). If
        another thread already did it, there is nothing left to do."""
        outcome, room.pending_save = room.pending_save, None
        if outcome is None:
            return
        room.saving = False
        job, result, error = outcome
        changed_meanwhile = room.state == "pending"     # changes arrived during the writing
        if isinstance(error, (pdf_store.RevisionMismatch, PageStructureChanged)):
            # The file changed on disk: merge and save again, as a whole.
            room.state = "pending"
            self._save_now(room)
            return
        if error is not None:
            room.state = "error"               # e.g. disk full: try again shortly
            self._start_timer(room, RETRY_DELAY)
        else:
            room.doc.finish_save(job, result)
            if not changed_meanwhile:
                room.state = "saved"
        if changed_meanwhile:
            self._start_timer(room, AUTOSAVE_DELAY)   # the changes made meanwhile get their own save
        room.changed.notify_all()

    def _save_now(self, room):
        """Saves right away, with room.lock held (last device leaving, or after a
        merge). A background write still running is waited for and recorded first:
        it does not need the lock while writing, so waiting cannot block it."""
        while room.saving and room.pending_save is None:
            with room.save_lock:      # the writer holds it while writing
                pass
            if room.saving and room.pending_save is None:
                time.sleep(0.005)     # prepared but not started writing yet
        self._finish_save(room)
        if room.state not in ("pending", "error"):
            return
        room.state = "saving"
        merged = []
        room.doc.subscribe(merged.append)    # news from the merge → to every device
        try:
            for _ in range(MERGE_ATTEMPTS):
                try:
                    room.doc.save()
                    break
                except pdf_store.RevisionMismatch:
                    # The file changed on disk: merge the changes and try again.
                    room.doc.merge_external()
            else:
                raise pdf_store.RevisionMismatch()
            room.state = "saved"
        except (pdf_store.RevisionMismatch, PageStructureChanged):
            # The pages changed on the computer while the document is in use:
            # the version in use wins, the computer's version goes to the trash.
            merged.append(self._in_use_wins(room))
            room.state = "saved"
        except Exception:
            room.state = "error"           # e.g. disk full: try again shortly
            self._start_timer(room, RETRY_DELAY)
        finally:
            room.doc.unsubscribe(merged.append)
        room.broadcast(merged)
        room.changed.notify_all()

    def _in_use_wins(self, room) -> dict:
        folder = self.library.folder(room.username)
        backup = folder.backup_path(room.rel, "versione PC")
        room.doc.overwrite(backup)
        return {"event": "notice",
                "message": ("Il PDF era stato modificato sul PC mentre lo stavi usando qui: è stata tenuta "
                            f"questa versione. Quella del PC è nel cestino come «{backup.name}».")}

    @staticmethod
    def _public_state(room) -> str:
        return {"saving": "pending"}.get(room.state, room.state)

    # --- devices and rooms ----------------------------------------------------------------------
    def _get(self, username, client_id) -> Client:
        client = self.clients.get(client_id) if isinstance(client_id, str) else None
        if not client or client.room.username != username:
            reason = self.closed.get(client_id, "unknown") if isinstance(client_id, str) else "unknown"
            raise SessionGone(reason)
        return client

    def _detach(self, client: Client, reason: str):
        """Disconnects a device. If it was the last one, the document is saved and closed."""
        room = client.room
        with room.lock:
            if client.id not in room.clients:
                return
            last = len(room.clients) == 1
            if last and reason == "idle" and room.state == "error":
                return  # save failed (e.g. disk full): do not close, try again
            del room.clients[client.id]
            if last:
                if room.timer:
                    room.timer.cancel()
                self._save_now(room)
                room.closed = True
                self._trash_unused_pictures(room)
            else:
                room.broadcast([{"event": "devices", "count": len(room.clients)}])
            room.changed.notify_all()
        with self.lock:
            self.clients.pop(client.id, None)
            self.closed[client.id] = reason
            while len(self.closed) > 1000:
                self.closed.popitem(last=False)
            if last and self.rooms.get((room.username, room.rel)) is room:
                del self.rooms[(room.username, room.rel)]

    def _trash_unused_pictures(self, room):
        """When the document is closed, images no longer used (deleted and not
        restored) go to the trash."""
        try:
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            self.library.folder(room.username).trash_pictures(room.rel, stamp, keep=room.doc.used_pictures())
        except OSError:
            pass  # not critical: they stay in the folder

    def _idle_loop(self):
        while True:
            time.sleep(IDLE_CHECK_SECONDS)
            limit = time.time() - self.idle_seconds
            for client in list(self.clients.values()):
                if client.last_used < limit:
                    try:
                        self._detach(client, "idle")
                    except Exception:
                        pass  # will be retried on the next round
