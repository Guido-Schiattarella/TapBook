"""Copy and paste, text boxes and images moved to another page, reading position
remembered: controller operations and their undo/redo, limits and bad input."""
import io

from _common import Checks, workspace
from app.control.errors import ControlError

def png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buf, "PNG")
    return buf.getvalue()


def main():
    check = Checks("test_editor_extras")
    tmp, lib, ed = workspace()
    rel = lib.create_document("anna", "", "prova")
    o = ed.open("anna", rel)
    sid, p1 = o["session"], o["pages"][0]["id"]
    ev = lambda r, name: [e for e in r["events"] if e["event"] == name]
    op = lambda **kw: ed.apply("anna", sid, kw)
    doc = ed.rooms[("anna", rel)].doc
    p2 = ev(op(type="addPage", after=p1), "pagesChanged")[0]["pages"][1]["id"]

    # --- text box dropped on another page -------------------------------------------------
    tid = ev(op(type="addText", page=p1, x=50, y=50, size=16), "textAdded")[0]["text"]["id"]
    op(type="editText", page=p1, id=tid, text="ciao", h=30, commit=True)
    r = op(type="moveText", page=p1, id=tid, x=10, y=20, toPage=p2)
    check([e["event"] for e in r["events"]] == ["textRemoved", "textAdded"], "move to another page: removed + added")
    check(not doc.pages[0]["texts"] and doc.pages[1]["texts"][0]["x"] == 10 and doc.pages[1]["texts"][0]["text"] == "ciao",
          "box is on the other page, text kept")
    op(type="undo")
    check(doc.pages[0]["texts"][0]["id"] == tid and doc.pages[0]["texts"][0]["x"] == 50 and not doc.pages[1]["texts"], "undo brings it back")
    op(type="redo")
    check(not doc.pages[0]["texts"] and doc.pages[1]["texts"][0]["id"] == tid, "redo moves it again")
    for bad in ({"toPage": "zz zz"}, {"toPage": 5}, {"x": "a"}):
        try:
            op(**{"type": "moveText", "page": p2, "id": tid, "x": 1, "y": 1, **bad})
            check(False, f"accepted {bad}")
        except ControlError:
            check.ok += 1
    check(not ev(op(type="moveText", page=p2, id=tid, x=1, y=1, toPage="missingpage00"), "textRemoved"),
          "unknown target page: nothing happens")
    check(doc.pages[1]["texts"][0]["id"] == tid, "box still there after the unknown target")
    r = op(type="moveText", page=p2, id=tid, x=7, y=8, toPage=p2)
    check(ev(r, "textChanged") and doc.pages[1]["texts"][0]["x"] == 7, "toPage = same page: a normal move")

    # --- image dropped on another page --------------------------------------------------------
    r = ed.add_image("anna", sid, p1, 30, 40, 100, png())
    iid = ev(r, "imageAdded")[0]["image"]["id"]
    r = op(type="changeImage", page=p1, id=iid, x=5, y=6, w=80, h=80, toPage=p2)
    check([e["event"] for e in r["events"]] == ["imageRemoved", "imageAdded"], "image moved to the other page")
    check(not doc.pages[0]["images"] and doc.pages[1]["images"][0]["w"] == 80, "image is there with its new size")
    op(type="undo")
    check(doc.pages[0]["images"][0]["id"] == iid and not doc.pages[1]["images"], "undo image move")
    op(type="redo")

    # --- copy and paste ---------------------------------------------------------------------------
    st = {"id": "s1", "tool": "pen", "color": "#1d1d1f", "width": 2, "points": [[10, 10, .5], [50, 50, .5]]}
    op(type="addStroke", page=p1, stroke=st)
    text = {"x": 1, "y": 2, "w": 100, "h": 30, "size": 12, "color": "#d62d20", "text": "x"}
    r = op(type="paste", page=p1, strokes=[st], texts=[text], images=[{"id": iid, "x": 0, "y": 0, "w": 50, "h": 50}], dx=5, dy=5)
    kinds = [e["event"] for e in r["events"]]
    check(kinds == ["strokeAdded", "textAdded", "imageAdded", "selection"], f"paste events {kinds}")
    sel = ev(r, "selection")[0]
    check(len(sel["strokes"]) == 1 and len(sel["texts"]) == 1 and len(sel["images"]) == 1, "pasted items become the selection")
    pasted = [s for s in doc.pages[0]["strokes"] if s["id"] != "s1"][0]
    check(pasted["id"] in sel["strokes"] and pasted["points"][0][:2] == [15, 15], "stroke copied with a new id and shifted")
    check(doc.pages[0]["texts"][0]["x"] == 6 and doc.pages[0]["texts"][0]["text"] == "x", "text pasted and shifted")
    img2 = doc.pages[0]["images"][0]
    check(img2["id"] != iid and img2["file"] == doc.pages[1]["images"][0]["file"] and img2["w"] == 50, "image copy shares the file")
    op(type="undo")
    check(len(doc.pages[0]["strokes"]) == 1 and not doc.pages[0]["texts"] and not doc.pages[0]["images"], "undo removes everything pasted")
    op(type="redo")
    check(len(doc.pages[0]["strokes"]) == 2 and len(doc.pages[0]["texts"]) == 1, "redo pastes again")
    r = op(type="paste", page=p2, strokes=[], texts=[], images=[{"id": "fromotherdoc1"}])
    check(ev(r, "notice") and not ev(r, "imageAdded") and not ev(r, "selection"), "image of another document: notice, nothing pasted")
    r = op(type="paste", page=p2, strokes=[st], texts=[], images=[{"id": "fromotherdoc1"}])
    check(ev(r, "strokeAdded") and ev(r, "notice"), "mixed: the rest is pasted, the image reported")
    for bad in ({"strokes": "x"}, {"strokes": [{"points": []}]}, {"texts": [3]}, {"texts": [{"color": "red"}]},
                {"images": [{"id": "a b"}]}, {"strokes": [{**st, "tool": "bomb"}]}, {"dx": float("inf")},
                {"texts": [{"text": "a" * 30000}]}):
        try:
            op(type="paste", page=p1, **{"strokes": [], "texts": [], "images": [], **bad})
            check(False, f"accepted {bad}")
        except ControlError:
            check.ok += 1
    try:
        op(type="paste", page=p1, strokes=[st] * 5001)
        check(False, "accepted 5001 items")
    except ControlError:
        check.ok += 1
    try:
        op(type="paste", page=p1, texts=[text] * 2001)
        check(False, "accepted more texts than a page may hold")
    except ControlError:
        check.ok += 1

    # --- text box created with pasted text ---------------------------------------------------------
    r = op(type="addText", page=p1, x=20, y=20, size=16, text="riga uno\nriga due\nriga tre")
    t = ev(r, "textAdded")[0]["text"]
    check(t["text"].count("\n") == 2 and t["h"] >= 3 * 16 * 1.25 and t["w"] >= 260, f"pasted text: box sized to the text {t['w']}x{t['h']}")
    op(type="discardText", page=p1, id=t["id"])
    r = op(type="addText", page=p1, x=20, y=20, size=16, text="x" * 200)
    check(ev(r, "textAdded")[0]["text"]["w"] <= 520, "a long line widens the box within a limit")
    try:
        op(type="addText", page=p1, x=20, y=20, text="a" * 30000)
        check(False, "accepted a text beyond the limit")
    except ControlError:
        check.ok += 1

    # --- reading position --------------------------------------------------------------------------
    check("startPage" not in o, "first opening: no remembered position")
    ed.set_position("anna", sid, 1, 0.25)
    for bad in (("x", 0), (99, 0), (-1, 0), (True, 0), (1, "y")):
        try:
            ed.set_position("anna", sid, *bad)
            check(False, f"accepted position {bad}")
        except ControlError:
            check.ok += 1
    ed.set_position("anna", sid, 1, 7)          # offset beyond 1 is clamped, not an error
    ed.close("anna", sid)
    o2 = ed.open("anna", rel)
    check(o2.get("startPage") == 1 and o2.get("startOffset") == 1.0, f"reopens at the remembered page {o2.get('startPage')}, {o2.get('startOffset')}")
    (tmp / "notes" / "bruno").mkdir()
    other = ed.open("bruno", lib.create_document("bruno", "", "sua"))
    check("startPage" not in other, "another user: no position")
    ed.close("bruno", other["session"])
    # Renamed: the position follows the document (keyed by its id, not its name).
    ed.close("anna", o2["session"])
    check(not ed.is_open("anna", rel, wait=20), "after closing, the document is free once written")
    lib.rename("anna", rel, "rinominato")
    o3 = ed.open("anna", "rinominato.pdf")
    check(o3.get("startPage") == 1, "position survives a rename")
    # Page gone: the position is not used.
    s3 = o3["session"]
    ed.apply("anna", s3, {"type": "removePage", "page": o3["pages"][1]["id"]})
    ed.close("anna", s3)
    check("startPage" not in ed.open("anna", "rinominato.pdf"), "removed page: opens at the start")
    ed.positions.forget_user("anna")
    check(ed.positions.get("anna", doc.doc_id) is None, "forget_user drops the file")
    try:
        ed.positions.set("../x", doc.doc_id, 0)
        check(False, "accepted a path as user name")
    except ValueError:
        check.ok += 1
    check.done()


if __name__ == "__main__":
    main()
