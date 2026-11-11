"""MODEL — where the reader stopped in each document.

For every user, the page (and how far down it) last looked at in each document,
so that reopening a PDF, from any device, goes back to that point. Kept apart
from the PDF: turning pages must never rewrite the file.

File: <root>/<username>.json  {docId: {"page": index, "offset": fraction, "at": epoch}}
docId is the document's identifier inside the PDF (see pdf_store), so the
position survives renames and moves. Entries of documents not opened for a
long time are dropped (KEEP_DAYS).
"""
import json
import re
import threading
import time
from pathlib import Path

from .files import atomic_write

KEEP_DAYS = 365
MAX_ENTRIES = 5000
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
DOC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PositionStore:
    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()

    def _file(self, username: str) -> Path:
        if not USER_RE.match(username):
            raise ValueError("Nome utente non valido")
        return self.root / f"{username}.json"

    def _load(self, username: str) -> dict:
        try:
            data = json.loads(self._file(username).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, username: str, doc_id: str) -> dict | None:
        """{"page": index, "offset": fraction} or None if never opened."""
        entry = self._load(username).get(doc_id) if DOC_RE.match(str(doc_id)) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("page"), int):
            return None
        offset = entry.get("offset", 0.0)
        return {"page": max(0, entry["page"]),
                "offset": float(offset) if isinstance(offset, (int, float)) and 0 <= offset <= 1 else 0.0}

    def set(self, username: str, doc_id: str, page: int, offset: float = 0.0):
        if not DOC_RE.match(str(doc_id)):
            raise ValueError("Documento non valido")
        with self.lock:
            data = self._load(username)
            now = time.time()
            data[doc_id] = {"page": int(page), "offset": round(float(offset), 4), "at": int(now)}
            # Old entries go: documents not opened for KEEP_DAYS, and never more than MAX_ENTRIES.
            limit = now - KEEP_DAYS * 86400
            data = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("at", now) >= limit}
            if len(data) > MAX_ENTRIES:
                data = dict(sorted(data.items(), key=lambda kv: kv[1].get("at", 0))[-MAX_ENTRIES:])
            self.root.mkdir(parents=True, exist_ok=True)
            atomic_write(self._file(username), json.dumps(data, separators=(",", ":")).encode("utf-8"), fsync=False)

    def forget_user(self, username: str):
        """Account deleted: its positions go too."""
        try:
            self._file(username).unlink()
        except (OSError, ValueError):
            pass
