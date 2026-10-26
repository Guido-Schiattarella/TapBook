"""The app's own Ink writer produces the same annotations as pymupdf's (rotations, margins), faster."""
import math
import time
from _common import Checks
import pymupdf
from app.model.pdf_store import _InkWriter


def strokes(n):
    return [[(40 + k * 2.0 + i % 7, 60 + i * 1.3 + math.sin(k / 4) * 5) for k in range(60)] for i in range(n)]


def build(method, rotation, n=60, mediabox=None):
    doc = pymupdf.open(); page = doc.new_page(width=595, height=842)
    if mediabox: page.set_mediabox(mediabox)
    page.insert_text((100, 100), "esistente"); page.add_text_annot((20, 20), "nota di un altro programma")
    page.set_rotation(rotation)
    m = page.derotation_matrix; w = _InkWriter(page, m)
    for pts in strokes(n):
        a = page.add_ink_annot([[tuple(pymupdf.Point(x, y) * m) for x, y in pts]]) if method == "old" else w.add(pts)
        a.set_colors(stroke=(0, 0, 1)); a.set_border(width=1.5); a.set_info(subject="s", title="t"); a.update()
    return doc


def summary(doc):
    out = []
    for a in doc[0].annots():
        ink = [[c for p in sub for c in p] for sub in a.vertices] if a.type[0] == pymupdf.PDF_ANNOT_INK else None
        out.append((a.type[1], [round(v, 2) for v in a.rect], ink, doc.xref_get_key(a.xref, "NM"), round(a.border.get("width", 0), 3)))
    return out


def same(x, y):
    if x[:2] != y[:2] or x[3:] != y[3:] or (x[2] is None) != (y[2] is None):
        return False
    return x[2] is None or all(abs(u - v) <= 0.002 for su, sv in zip(x[2], y[2]) for u, v in zip(su, sv))


def main():
    check = Checks("test_ink_equiv")
    for rot in (0, 90, 180, 270):
        d1, d2 = build("old", rot), build("new", rot)
        s1, s2 = summary(d1), summary(d2)
        check(len(s1) == len(s2) and all(same(a, b) for a, b in zip(s1, s2)), f"rotation {rot}")
        check(d1[0].get_pixmap(dpi=72).samples == d2[0].get_pixmap(dpi=72).samples, f"render {rot}")
    d1, d2 = build("old", 0, mediabox=pymupdf.Rect(10, 20, 600, 860)), build("new", 0, mediabox=pymupdf.Rect(10, 20, 600, 860))
    check(d1[0].get_pixmap(dpi=72).samples == d2[0].get_pixmap(dpi=72).samples, "mediabox")
    t = time.perf_counter(); build("old", 0, n=1000); told = time.perf_counter() - t
    t = time.perf_counter(); build("new", 0, n=1000); tnew = time.perf_counter() - t
    check(tnew < told, "faster")
    check.done(f"(1000 tratti: libreria {told:.2f} s, nostra {tnew:.2f} s)")


if __name__ == "__main__":
    main()
