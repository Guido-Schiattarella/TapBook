"""MODEL — document open for editing.

Working copy of a PDF: pages, strokes and text boxes in memory.
Every change notifies the registered listeners (the controller) with an
event describing what changed; the controller forwards it to the view.
`save()` writes everything to the PDF on the file system through pdf_store.

Notified events (dictionaries):
  strokeAdded   {page, stroke, index}      strokeRemoved {page, id}
  strokeChanged {page, stroke}             (moved or recoloured with the lasso)
  textAdded     {page, text, index}        textRemoved   {page, id}
  textChanged   {page, text}
  imageAdded    {page, image, index}       imageRemoved  {page, id}
  imageChanged  {page, image}
  pagesChanged  {pages: [{id, w, h, render, layout, strokes, texts, images}, ...]}
  layoutChanged {layout}                   layout chosen for the next pages
  backgroundChanged {pages}   the PDF on disk was changed by another program
                              and the changes were merged: the view must
                              reload the background and redraw the pages

Merging external changes (merge_external): when the file on disk changed
while the document is open, three versions are compared:
  base   = the app's notes as they were at the last save (snapshot)
  disk   = the current file, with the other program's changes
  ours   = the data in memory, with the changes made from the iPad
Notes of other programs always stay (the app never touches them); the app's
notes deleted or changed by the other program are removed/updated here too;
everything else done from the iPad is kept.
"""
import copy
import uuid
from pathlib import Path

from . import pdf_store


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class PageStructureChanged(Exception):
    """Another program added, removed or reordered the pages: the notes cannot be
    reassigned to the right pages with certainty."""


class OpenDocument:
    def __init__(self, path: Path, pagecache: Path, pictures_dir: Path):
        self.path = path
        self.pagecache = pagecache
        self.pictures_dir = pictures_dir   # pictures/<document>: image files
        clean, layer, revision = pdf_store.load_document(path)
        self.base_pdf = clean           # PDF without notes: background for the view
        self.revision = revision        # version of the file on disk
        self.doc_id = layer["docId"]
        self.next_layout = layer["nextLayout"]   # layout of the pages that will be added
        self.pages = layer["pages"]     # pagine attuali, in ordine
        self.all_pages = {p["id"]: p for p in self.pages}  # deleted ones too (undo)
        self._listeners = []
        self.last_saved = path.read_bytes()   # the PDF as the last save left it
        self._take_snapshot()

    # --- notifications -----------------------------------------------------------------
    def subscribe(self, listener):
        self._listeners.append(listener)

    def unsubscribe(self, listener):
        self._listeners.remove(listener)

    def _notify(self, event: str, **data):
        for listener in list(self._listeners):
            listener({"event": event, **copy.deepcopy(data)})

    # --- reading ------------------------------------------------------------------------
    def page(self, page_id: str) -> dict:
        for p in self.pages:
            if p["id"] == page_id:
                return p
        raise LookupError("Pagina inesistente")

    def page_index(self, page_id: str) -> int:
        return self.pages.index(self.page(page_id))

    @staticmethod
    def _find(items, item_id, what):
        for i, item in enumerate(items):
            if item["id"] == item_id:
                return i, item
        raise LookupError(f"{what} inesistente")

    @staticmethod
    def view_page(p) -> dict:
        """What the view needs to draw a page."""
        return {"id": p["id"], "w": p["w"], "h": p["h"], "render": p.get("render"),
                "layout": p.get("layout"), "strokes": p["strokes"], "texts": p["texts"], "images": p.setdefault("images", [])}

    def view_pages(self):
        return [self.view_page(p) for p in self.pages]

    # --- strokes --------------------------------------------------------------------------
    def add_stroke(self, page_id, stroke, index=None):
        page = self.page(page_id)
        index = len(page["strokes"]) if index is None else index
        page["strokes"].insert(index, stroke)
        self._notify("strokeAdded", page=page_id, stroke=stroke, index=index)

    def remove_stroke(self, page_id, stroke_id):
        page = self.page(page_id)
        index, stroke = self._find(page["strokes"], stroke_id, "Tratto")
        del page["strokes"][index]
        self._notify("strokeRemoved", page=page_id, id=stroke_id)
        return stroke, index

    def has_stroke(self, page_id, stroke_id) -> bool:
        return any(s["id"] == stroke_id for s in self.page(page_id)["strokes"])

    def stroke(self, page_id, stroke_id) -> dict:
        return self._find(self.page(page_id)["strokes"], stroke_id, "Tratto")[1]

    def update_stroke(self, page_id, stroke_id, **changes):
        stroke = self.stroke(page_id, stroke_id)
        stroke.update(changes)
        self._notify("strokeChanged", page=page_id, stroke=stroke)

    # --- text boxes ---------------------------------------------------------------------------
    def text(self, page_id, text_id) -> dict:
        return self._find(self.page(page_id)["texts"], text_id, "Testo")[1]

    def add_text(self, page_id, text, index=None):
        page = self.page(page_id)
        index = len(page["texts"]) if index is None else index
        page["texts"].insert(index, text)
        self._notify("textAdded", page=page_id, text=text, index=index)

    def remove_text(self, page_id, text_id):
        page = self.page(page_id)
        index, text = self._find(page["texts"], text_id, "Testo")
        del page["texts"][index]
        self._notify("textRemoved", page=page_id, id=text_id)
        return text, index

    def update_text(self, page_id, text_id, **changes):
        text = self.text(page_id, text_id)
        text.update(changes)
        self._notify("textChanged", page=page_id, text=text)

    # --- images ---------------------------------------------------------------------------------
    def image(self, page_id, image_id) -> dict:
        return self._find(self.page(page_id).setdefault("images", []), image_id, "Immagine")[1]

    def add_image(self, page_id, image, index=None):
        images = self.page(page_id).setdefault("images", [])
        index = len(images) if index is None else index
        images.insert(index, image)
        self._notify("imageAdded", page=page_id, image=image, index=index)

    def remove_image(self, page_id, image_id):
        images = self.page(page_id).setdefault("images", [])
        index, image = self._find(images, image_id, "Immagine")
        del images[index]
        self._notify("imageRemoved", page=page_id, id=image_id)
        return image, index

    def update_image(self, page_id, image_id, **changes):
        image = self.image(page_id, image_id)
        image.update(changes)
        self._notify("imageChanged", page=page_id, image=image)

    def used_pictures(self) -> set:
        """Names of the image files used by the current pages."""
        return {img["file"] for p in self.pages for img in p.get("images", [])}

    def picture_path(self, image_id) -> Path:
        """File of a document image (also of a deleted page: undo needs it)."""
        for p in self.all_pages.values():
            for img in p.get("images", []):
                if img["id"] == image_id:
                    path = self.pictures_dir / img["file"]
                    if path.is_file():
                        return path
        raise LookupError("Immagine inesistente")

    # --- groups of items (lasso) --------------------------------------------------------------
    # Items no longer present (deleted in the meantime by another device or on
    # the computer) are skipped; the ones actually changed are returned.
    def move_items(self, page_id, strokes, texts, images, dx, dy) -> dict:
        page = self.page(page_id)
        done = {"strokes": [], "texts": [], "images": []}
        for s in page["strokes"]:
            if s["id"] in strokes:
                self.update_stroke(page_id, s["id"],
                                   points=[[x + dx, y + dy, pr] for x, y, pr in s["points"]])
                done["strokes"].append(s["id"])
        for t in page["texts"]:
            if t["id"] in texts:
                self.update_text(page_id, t["id"], x=t["x"] + dx, y=t["y"] + dy)
                done["texts"].append(t["id"])
        for img in page.setdefault("images", []):
            if img["id"] in images:
                self.update_image(page_id, img["id"], x=img["x"] + dx, y=img["y"] + dy)
                done["images"].append(img["id"])
        return done

    def colors_of(self, page_id, strokes, texts) -> dict:
        """Current colour of strokes and texts (so it can be restored)."""
        page = self.page(page_id)
        return {**{s["id"]: ("stroke", s["color"]) for s in page["strokes"] if s["id"] in strokes},
                **{t["id"]: ("text", t["color"]) for t in page["texts"] if t["id"] in texts}}

    def set_colors(self, page_id, colors: dict):
        """colors: id -> (kind, colour), as returned by colors_of."""
        page = self.page(page_id)
        for s in page["strokes"]:
            if colors.get(s["id"], ("",))[0] == "stroke":
                self.update_stroke(page_id, s["id"], color=colors[s["id"]][1])
        for t in page["texts"]:
            if colors.get(t["id"], ("",))[0] == "text":
                self.update_text(page_id, t["id"], color=colors[t["id"]][1])

    # --- pages --------------------------------------------------------------------------------
    def set_next_layout(self, layout: str):
        self.next_layout = layout
        self._notify("layoutChanged", layout=layout)

    def new_blank_page(self, like: dict, layout: str) -> dict:
        """New page, as large as `like`, with the given layout (drawn into the PDF
        when saving)."""
        page = {"id": new_id(), "src": None, "render": None, "blank": True, "layout": layout,
                "w": like["w"], "h": like["h"], "strokes": [], "texts": [], "images": []}
        self.all_pages[page["id"]] = page
        return page

    def insert_page(self, page: dict, index: int):
        self.pages.insert(index, page)
        self._notify("pagesChanged", pages=self.view_pages())

    def remove_page(self, page_id):
        index = self.page_index(page_id)
        page = self.pages.pop(index)
        self._notify("pagesChanged", pages=self.view_pages())
        return page, index

    # --- persistence ---------------------------------------------------------------------------
    def _take_snapshot(self):
        """Remembers the app's notes for every page of the file as they were at the
        last save: it is the "base" used to recognise what another program changed."""
        self.snapshot = [{"strokes": {s["id"] for s in p["strokes"]},
                          "texts": {t["id"]: t["text"] for t in p["texts"]},
                          "images": {i["id"] for i in p.get("images", [])}} for p in self.pages]

    def merge_external(self):
        """The file on disk changed: the other program's changes are merged with
        those in memory. Raises PageStructureChanged if the file's pages no
        longer match."""
        clean, disk, revision = pdf_store.load_document(self.path)
        disk_pages = disk["pages"]
        if len(disk_pages) != len(self.snapshot):
            raise PageStructureChanged()
        # Reordered pages? An app note appearing on a different page than at the
        # last save means the pages were moved.
        where = {}
        for i, base in enumerate(self.snapshot):
            for item_id in list(base["strokes"]) + list(base["texts"]) + list(base["images"]):
                where[item_id] = i
        for i, dp in enumerate(disk_pages):
            for item in dp["strokes"] + dp["texts"] + dp.get("images", []):
                if where.get(item["id"], i) != i:
                    raise PageStructureChanged()

        by_src = {p["src"]: p for p in self.pages if p["src"] is not None}
        for i, (base, dp) in enumerate(zip(self.snapshot, disk_pages)):
            page = by_src.get(i)
            if page is None:
                continue  # page deleted from the iPad: its deletion wins
            disk_strokes = {s["id"] for s in dp["strokes"]}
            disk_texts = {t["id"]: t["text"] for t in dp["texts"]}
            for stroke_id in base["strokes"] - disk_strokes:     # deleted by the other program
                if self.has_stroke(page["id"], stroke_id):
                    self.remove_stroke(page["id"], stroke_id)
            disk_images = {i["id"] for i in dp.get("images", [])}
            for image_id in base["images"] - disk_images:        # images deleted on the computer
                if any(i["id"] == image_id for i in page.get("images", [])):
                    self.remove_image(page["id"], image_id)
            for text_id, base_text in base["texts"].items():
                current = next((t for t in page["texts"] if t["id"] == text_id), None)
                if current is None:
                    continue
                if text_id not in disk_texts:                      # deleted by the other program
                    self.remove_text(page["id"], text_id)
                elif disk_texts[text_id] != base_text and current["text"] == base_text:
                    # changed only by the other program: its version counts
                    self.update_text(page["id"], text_id, text=disk_texts[text_id])

        # The file is now the new base: the background changes and the pages refer to it.
        self.base_pdf = clean
        self.revision = revision
        for p in self.all_pages.values():
            p["render"] = p["src"]
        self._take_snapshot_from_disk(disk_pages)
        self._notify("backgroundChanged", pages=self.view_pages())

    def _take_snapshot_from_disk(self, disk_pages):
        self.snapshot = [{"strokes": {s["id"] for s in dp["strokes"]},
                          "texts": {t["id"]: t["text"] for t in dp["texts"]},
                          "images": {i["id"] for i in dp.get("images", [])}} for dp in disk_pages]

    def _layer(self) -> dict:
        return {"docId": self.doc_id, "nextLayout": self.next_layout, "pages": [
            {**{k: p[k] for k in ("id", "src", "blank", "w", "h", "strokes", "texts")},
             "layout": p.get("layout"), "images": p.get("images", [])} for p in self.pages]}

    def save(self):
        """Writes the document to the PDF on disk. Raises pdf_store.RevisionMismatch
        if the file was changed by another program in the meantime."""
        self.revision, self.last_saved = pdf_store.save_document(
            self.path, self._layer(), self.revision, self.pagecache, pictures_dir=self.pictures_dir)
        self._after_save()

    def overwrite(self, backup_to: Path):
        """The iPad's version wins: the file on disk is replaced starting from the
        last PDF saved by the iPad; the computer's version is first copied to
        `backup_to`."""
        self.revision, self.last_saved = pdf_store.save_document(
            self.path, self._layer(), self.revision, self.pagecache,
            base_bytes=self.last_saved, backup_to=backup_to, pictures_dir=self.pictures_dir)
        self._after_save()

    def _after_save(self):
        # The file now has the pages in the saved order: update their position.
        # Pages no longer present lose src: if restored, they come from the cache.
        order = {p["id"]: i for i, p in enumerate(self.pages)}
        for p in self.all_pages.values():
            p["src"] = order.get(p["id"])
        self._take_snapshot()
