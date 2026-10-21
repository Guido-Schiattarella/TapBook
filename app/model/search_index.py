"""MODEL — document text for the search.

Extracts the text of every page of every PDF: the original content (for
example imported slides or handouts) plus the text boxes typed in the app.
Handwriting is not text and cannot be searched.
The extracted text stays in memory until the file changes (modification time
and size), so later searches are instant.
"""
import threading
from pathlib import Path

import pymupdf

from .pdf_store import SUBJECT_PREFIX

MAX_CACHED = 2000          # documenti tenuti in memoria
MAX_FILE_BYTES = 300 * 1024 * 1024

_cache: dict[str, tuple] = {}
_lock = threading.Lock()


def page_texts(path: Path, st) -> list[str]:
    """Text of every page of the PDF (empty list if the file cannot be read)."""
    key = str(path)
    stamp = (st.st_mtime_ns, st.st_size)
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
    texts = []
    if st.st_size <= MAX_FILE_BYTES:
        try:
            with pymupdf.open(path) as doc:
                for page in doc:
                    parts = [page.get_text("text")]
                    for annot in page.annots() or []:
                        if (annot.info.get("subject") or "").startswith(SUBJECT_PREFIX) \
                                and annot.type[0] == pymupdf.PDF_ANNOT_FREE_TEXT:
                            parts.append(annot.info.get("content") or "")
                    texts.append(" ".join(" ".join(parts).split()))
        except Exception:
            texts = []
    with _lock:
        if len(_cache) >= MAX_CACHED:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (stamp, texts)
    return texts
