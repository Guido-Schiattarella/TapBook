"""Backgrounds stored per page: what a device has to download in each situation,
fingerprints that survive the app's saves, and only the right document's backgrounds."""
import io
import os
import time
from pathlib import Path
from _common import Checks, workspace
import pymupdf
from PIL import Image
from app.control.errors import ControlError
from app.model import backgrounds, pdf_store


def text_pdf(n=24):
    """Pages sharing their fonts (like lecture notes or slides)."""
    d = pymupdf.open()
    for i in range(n):
        p = d.new_page()
        p.insert_text((72, 72), f"Pagina {i + 1}", fontsize=24, fontname="tiro")
        p.insert_text((72, 120), "Testo di esempio " * 8, fontsize=11, fontname="helv")
    return d.tobytes(garbage=3, deflate=True)


def image_pdf(n=6):
    """Scanned pages (one image each)."""
    d = pymupdf.open()
    for i in range(n):
        b = io.BytesIO(); Image.effect_noise((400, 560), 40 + i).convert("RGB").save(b, "JPEG", quality=70)
        d.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=b.getvalue())
    return d.tobytes(garbage=3, deflate=True)


def scenario(check, name, data):
    tmp, lib, ed = workspace("anna", "bruno")
    lib.import_pdf("anna", "", "doc.pdf", data)
    path = tmp / "notes" / "anna" / "doc.pdf"

    def open_():
        o = ed.open("anna", "doc.pdf"); return o, o["session"]

    def refs(o):
        return [p["bg"] for p in o["pages"]]

    o, sid = open_(); first = o["backgrounds"]; n = len(o["pages"])
    check(len(first) == 1 and all(r and r["id"] in first for r in refs(o)), f"{name}: first opening, one background")
    ed.close("anna", sid); o, sid = open_()
    check(o["backgrounds"] == first, f"{name}: reopened untouched: same background")
    pids = [p["id"] for p in o["pages"]]
    ed.apply("anna", sid, {"type": "addStroke", "page": pids[0], "stroke": {"id": "s1", "tool": "pen", "color": "#000000", "width": 1, "points": [[10, 10, .5], [60, 60, .5]]}})
    ed.apply("anna", sid, {"type": "addPage", "after": pids[0]})
    ed.apply("anna", sid, {"type": "removePage", "page": pids[2]})
    ed.close("anna", sid); o, sid = open_()
    check(o["backgrounds"] == first, f"{name}: strokes, page added and removed with the app: same background")
    check(o["pages"][1]["bg"] is None and o["pages"][1]["layout"], f"{name}: added page drawn from its layout")
    # pages moved: undo of a removal puts a page back elsewhere in the order
    ed.apply("anna", sid, {"type": "removePage", "page": o["pages"][-1]["id"]})
    ed.apply("anna", sid, {"type": "undo"})
    ed.close("anna", sid); o, sid = open_()
    check(o["backgrounds"] == first, f"{name}: still the same background")
    ed.close("anna", sid)
    d = pymupdf.open(path); d[3].insert_text((60, 60), "modificata fuori"); d.saveIncr(); d.close()
    o, sid = open_()
    new_ids = set(o["backgrounds"]) - set(first)
    check(len(new_ids) == 1, f"{name}: external change: one new background")
    delta = new_ids.pop()
    in_delta = [i for i, r in enumerate(refs(o)) if r and r["id"] == delta]
    check(3 in in_delta and len(in_delta) < n, f"{name}: the new background holds the changed page {in_delta}")
    check(o["backgrounds"][delta] < sum(first.values()), f"{name}: and is smaller than the whole")
    check(ed.background("anna", sid, delta).is_file(), f"{name}: downloadable from its document")
    for bad in ["../x", "0" * 32, "z" * 32, None, 123, delta.upper()]:
        try:
            ed.background("anna", sid, bad); check(False, f"accepted {bad!r}")
        except ControlError:
            check.ok += 1
    lib.import_pdf("bruno", "", "suo.pdf", data)
    ob = ed.open("bruno", "suo.pdf")
    try:
        ed.background("bruno", ob["session"], delta); check(False, "bruno downloads anna's background")
    except ControlError:
        check.ok += 1
    ed.close("bruno", ob["session"])
    # file changed while open: only the new pages' background
    room = ed.clients[sid].room
    d = pymupdf.open(path); d[5].insert_text((80, 80), "altra modifica"); d.saveIncr(); d.close()
    ed.apply("anna", sid, {"type": "addStroke", "page": o["pages"][0]["id"], "stroke": {"id": "s2", "tool": "pen", "color": "#000000", "width": 1, "points": [[20, 20, .5], [70, 70, .5]]}})
    room.timer and room.timer.cancel(); room.state = "pending"; ed._save(room)
    ev = [e for e in ed.clients[sid].outbox if e["event"] == "backgroundChanged"]
    check(ev and len(set(ev[-1]["backgrounds"]) - set(first) - {delta}) == 1, f"{name}: changed while open: one new background")
    ed.close("anna", sid)
    for k in range(8):
        d = pymupdf.open(path); d[k % n].insert_text((100, 100 + k * 10), f"giro {k}"); d.saveIncr(); d.close()
        o, sid = open_(); ed.close("anna", sid)
    o, sid = open_(); ed.close("anna", sid)
    check(len(o["backgrounds"]) <= backgrounds.MAX_BACKGROUNDS, f"{name}: backgrounds kept few ({len(o['backgrounds'])})")
    folder = tmp / "backgrounds" / "anna"
    files = sum(len(list(f.glob("*.pdf"))) for f in folder.iterdir())
    check(files == len(o["backgrounds"]), f"{name}: no unused background file on the computer")
    for f in folder.iterdir():
        os.utime(f / "manifest.json", (time.time() - 40 * 86400,) * 2)
    backgrounds.expire(tmp / "backgrounds")
    check(not any(folder.iterdir()), f"{name}: backgrounds of documents not opened for 30 days removed")


def notebook(check):
    """A notebook made in TapBook: all layout pages, nothing to download."""
    tmp, lib, ed = workspace()
    rel = lib.create_document("anna", "", "quaderno", "lined")
    o = ed.open("anna", rel); sid = o["session"]
    ed.apply("anna", sid, {"type": "addPage", "after": o["pages"][0]["id"]})
    ed.close("anna", sid)
    o = ed.open("anna", rel)
    check(o["backgrounds"] == {} and all(p["bg"] is None for p in o["pages"]), "notebook made in TapBook: nothing to download")
    ed.close("anna", o["session"])


def main():
    check = Checks("test_backgrounds")
    scenario(check, "testo", text_pdf())
    scenario(check, "scansioni", image_pdf())
    notebook(check)
    check.done()


if __name__ == "__main__":
    main()
