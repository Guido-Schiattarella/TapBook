"""CONTROL — document list: navigation, new folders and documents, import,
rename, trash. It applies the rules (allowed names, valid PDFs only, no
overwriting) and delegates writing to the model. After every change it returns
the updated folder contents, which the view shows."""
import datetime as dt
import functools
import unicodedata
from pathlib import Path

from ..model import layouts, pdf_store, search_index
from ..model.filesystem import PICTURES_DIR, UserFolder
from ..security import PathError, clean_name
from .errors import AlreadyExists, InvalidInput, NotFound


# Note colours: id stored in the PDF, name, card background and dot colour.
# Pastels matching the light-blue interface; the default is white.
NOTE_COLORS = [
    ("white", "Bianco", "#ffffff", "#9fb0cc"),
    ("sky", "Azzurro", "#e4efff", "#3a7bfd"),
    ("aqua", "Acqua", "#dcf3f5", "#20a8b4"),
    ("mint", "Menta", "#e1f5e8", "#2fa36b"),
    ("lavender", "Lavanda", "#ebe7fd", "#7c66e0"),
    ("pink", "Rosa", "#fde5ee", "#e0598e"),
    ("peach", "Pesca", "#ffe9df", "#ee7d4f"),
    ("lemon", "Limone", "#fff5d4", "#d9a514"),
]
DEFAULT_COLOR = "white"

# Layout names shown to the user (the model draws them, here they get their names).
LAYOUT_LABELS = {
    "blank": "Bianca",
    "lined": "A righe",
    "squared": "A quadretti",
    "dotted": "A puntini",
    "cornell_lined": "Cornell a righe",
    "cornell_squared": "Cornell a quadretti",
}


def layout_catalog() -> list:
    return [{"id": l, "label": LAYOUT_LABELS.get(l, l)} for l in layouts.LAYOUTS]
_COLORS = {c[0]: {"id": c[0], "label": c[1], "bg": c[2], "dot": c[3]} for c in NOTE_COLORS}


def note_color(color_id) -> dict:
    return _COLORS.get(color_id) or _COLORS[DEFAULT_COLOR]


MAX_QUERY = 100
MAX_RESULTS = 200
SNIPPETS_PER_DOCUMENT = 3
SNIPPET_BEFORE, SNIPPET_AFTER = 45, 80


def _pdf_name(name: str) -> str:
    return name if name.lower().endswith(".pdf") else name + ".pdf"


@functools.lru_cache(maxsize=4096)
def _fold_char(c: str) -> str:
    """A character without accents and in lower case, always of length 1 (so that
    positions in the "folded" text match those in the original text)."""
    base = unicodedata.normalize("NFKD", c)[:1] or c
    return base.casefold()[:1] or c


def fold(text: str) -> str:
    """Text used for comparison: "Università" and "universita" are equal."""
    return "".join(_fold_char(c) for c in text)


def _snippet(text: str, pos: int, length: int) -> dict:
    start = max(0, pos - SNIPPET_BEFORE)
    end = min(len(text), pos + length + SNIPPET_AFTER)
    return {"before": ("…" if start > 0 else "") + text[start:pos],
            "match": text[pos:pos + length],
            "after": text[pos + length:end] + ("…" if end < len(text) else "")}


class LibraryController:
    def __init__(self, notes_root: Path):
        self.notes_root = notes_root

    def folder(self, username: str) -> UserFolder:
        return UserFolder(self.notes_root, username)

    def _call(self, fn, *args):
        """Turns model errors into domain errors."""
        try:
            return fn(*args)
        except PathError as e:
            raise InvalidInput(str(e))
        except FileNotFoundError:
            raise NotFound("Elemento non trovato")
        except FileExistsError:
            raise AlreadyExists("Esiste già un elemento con questo nome")

    # --- reading ------------------------------------------------------------------
    def list_folder(self, username: str, rel: str):
        """(normalized path, items) of the requested folder. Each document also
        carries the note colour and the creation date."""
        folder = self.folder(username)
        path, entries = self._call(folder.list, rel)
        base = folder.resolve(path)
        for e in entries:
            if e["type"] == "pdf":
                info = pdf_store.doc_info(base / e["name"])
                e["color"], e["created"] = note_color(info["color"]), int(info["created"])
        return path, entries

    def document_color(self, username: str, rel: str) -> dict:
        """Note colour (for the dot next to the title in the editor)."""
        path = self._call(self.folder(username).resolve, rel)
        return note_color(pdf_store.doc_info(path)["color"])

    def shell(self, username: str) -> dict:
        """Data shared by all pages (sidebar and top bar): user and top-level folders."""
        _, entries = self._call(self.folder(username).list, "")
        return {"user": self.user_summary(username),
                "folders": [e["name"] for e in entries if e["type"] == "dir"]}

    def kind(self, username: str, rel: str) -> str:
        """'dir' o 'pdf': serve a decidere quale vista mostrare."""
        path = self._call(self.folder(username).resolve, rel)
        if path.is_dir():
            return "dir"
        if path.is_file() and path.suffix.lower() == ".pdf":
            return "pdf"
        raise NotFound("Elemento non trovato")

    def raw_path(self, username: str, rel: str) -> Path:
        """The PDF exactly as it is on disk, for download."""
        rel = self.open_document(username, rel)
        return self.folder(username).resolve(rel)

    def open_document(self, username: str, rel: str) -> str:
        """Checks that the document exists and is one of the user's PDFs: the
        condition for opening the editor."""
        folder = self.folder(username)
        path = self._call(folder.resolve, rel)
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise NotFound("Documento non trovato")
        return folder.rel(path)

    def user_summary(self, username: str) -> dict:
        """Profile name and photo (the version changes when the photo changes)."""
        avatar = self.folder(username).avatar_path()
        return {"name": username, "avatar": avatar.stat().st_mtime_ns if avatar else None}

    # --- search --------------------------------------------------------------------
    def search(self, username: str, query) -> dict:
        """Searches all of the user's documents: in the name, in the folders and in
        the text (PDF content and text boxes; handwriting is not searchable).
        Documents with the word in the name come first, then those with more matching pages."""
        if not isinstance(query, str) or not query.strip():
            raise InvalidInput("Scrivi cosa cercare")
        query = " ".join(query.split())[:MAX_QUERY]
        q = fold(query)
        results = []
        for rel, path, st in self.folder(username).documents():
            name = Path(rel).stem
            folder = rel.rpartition("/")[0]
            pos = fold(name).find(q)
            name_match = _snippet(name, pos, len(q)) if pos >= 0 else None
            in_folder = q in fold(folder)
            matches, pages = [], 0
            if len(q) >= 2:
                for number, text in enumerate(search_index.page_texts(path, st)):
                    p = fold(text).find(q)
                    if p < 0:
                        continue
                    pages += 1
                    if len(matches) < SNIPPETS_PER_DOCUMENT:
                        matches.append({"page": number, **_snippet(text, p, len(q))})
            if name_match or in_folder or matches:
                results.append({"path": rel, "name": name, "folder": folder, "mtime": int(st.st_mtime),
                                "color": note_color(pdf_store.doc_info(path)["color"]),
                                "nameMatch": name_match, "folderMatch": in_folder,
                                "pages": pages, "matches": matches})
        results.sort(key=lambda r: (r["nameMatch"] is None, -r["pages"], -r["mtime"]))
        return {"query": query, "results": results[:MAX_RESULTS], "truncated": len(results) > MAX_RESULTS}

    # --- trash ----------------------------------------------------------------------
    def trash_list(self, username: str) -> list:
        return self.folder(username).list_trash()

    def trash_restore(self, username: str, entry) -> str:
        """Restores an item where it was; returns its path."""
        return self._call(self.folder(username).restore_from_trash, entry)

    def trash_delete(self, username: str, entry):
        self._call(self.folder(username).delete_from_trash, entry)

    def trash_empty(self, username: str):
        self.folder(username).empty_trash()

    # --- writing --------------------------------------------------------------------
    def _check_reserved(self, folder: UserFolder, rel_parent: str, name: str):
        """`pictures` in the top-level folder is reserved for images."""
        parent = self._call(folder.resolve, rel_parent)
        if folder.is_root(parent) and name.lower() == PICTURES_DIR:
            raise InvalidInput(f"Il nome «{PICTURES_DIR}» è riservato alle immagini dei documenti")

    def create_folder(self, username: str, rel: str, name):
        name = self._call(clean_name, name)
        self._check_reserved(self.folder(username), rel, name)
        self._call(self.folder(username).make_dir, rel, name)
        return self.list_folder(username, rel)

    @staticmethod
    def layout_catalog() -> list:
        return layout_catalog()

    def new_document_defaults(self) -> dict:
        """What the view proposes for a new notebook: name, layout of the first
        page and available layouts."""
        return {"name": dt.date.today().strftime("Nota %d-%m-%Y"), "layout": "lined",
                "layouts": layout_catalog(), "color": DEFAULT_COLOR, "colors": list(_COLORS.values())}

    def layout_preview(self, layout) -> bytes:
        if not layouts.exists(layout):
            raise NotFound("Layout sconosciuto")
        return layouts.preview_png(layout)

    def create_document(self, username: str, rel: str, name, layout=None, color=None) -> str:
        """New A4 PDF with one page of the chosen layout and the note colour;
        returns its path so it can be opened right away."""
        name = _pdf_name(self._call(clean_name, name))
        layout = layouts.DEFAULT if layout is None else layout
        if not layouts.exists(layout):
            raise InvalidInput("Layout sconosciuto")
        color = DEFAULT_COLOR if color is None else color
        if color not in _COLORS:
            raise InvalidInput("Colore sconosciuto")
        data = pdf_store.blank_pdf(layout=layout, color=color, created=dt.datetime.now().timestamp())
        return self._call(self.folder(username).write_new_file, rel, name, data)

    def import_pdf(self, username: str, rel: str, filename, data: bytes):
        name = self._call(clean_name, filename or "")
        if not name.lower().endswith(".pdf"):
            raise InvalidInput("Si possono caricare solo PDF")
        if not pdf_store.is_valid_pdf(data):
            raise InvalidInput("File PDF non valido o protetto da password")
        data = pdf_store.mark_imported(data, dt.datetime.now().timestamp())
        self._call(self.folder(username).write_new_file, rel, name, data)
        return self.list_folder(username, rel)

    def rename(self, username: str, rel: str, name):
        folder = self.folder(username)
        path = self._call(folder.resolve, rel)
        name = self._call(clean_name, name)
        if path.is_file():
            name = _pdf_name(name)  # a document stays a PDF
        self._check_reserved(folder, folder.rel(path.parent), name)
        self._call(folder.rename, rel, name)
        return self.list_folder(username, folder.rel(path.parent))

    def delete(self, username: str, rel: str):
        """Moves to the trash: a mistake can always be undone from the computer."""
        folder = self.folder(username)
        parent = folder.rel(self._call(folder.resolve, rel).parent)
        self._call(folder.move_to_trash, rel)
        return self.list_folder(username, parent)
