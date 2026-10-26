"""Text boxes: size at creation, changeText (w/h/size/color), undo/redo, saved to PDF and read back."""
from _common import Checks, workspace
from app.control.errors import ControlError


def main():
    check = Checks("test_textbox")
    tmp, lib, ed = workspace()
    rel = lib.create_document("anna", "", "prova")
    o = ed.open("anna", rel)
    sid, pid = o["session"], o["pages"][0]["id"]
    ev = lambda r, name: [e for e in r["events"] if e["event"] == name]
    r = ed.apply("anna", sid, {"type": "addText", "page": pid, "x": 100, "y": 100, "color": "#1e5bd8", "size": 30})
    t = ev(r, "textAdded")[0]["text"]; tid = t["id"]
    check(t["size"] == 30 and t["h"] >= 48, f"size at creation {t}")
    r = ed.apply("anna", sid, {"type": "addText", "page": pid, "x": 100, "y": 300, "size": 9999})
    check(ev(r, "textAdded")[0]["text"]["size"] == 200, "size clamped")
    ed.apply("anna", sid, {"type": "discardText", "page": pid, "id": ev(r, "textAdded")[0]["text"]["id"]})
    ed.apply("anna", sid, {"type": "editText", "page": pid, "id": tid, "text": "Ciao mondo", "h": 50, "commit": True})
    tc = ev(ed.apply("anna", sid, {"type": "changeText", "page": pid, "id": tid, "w": 150, "h": 120}), "textChanged")[0]["text"]
    check(tc["w"] == 150 and tc["h"] == 120 and tc["text"] == "Ciao mondo", f"resize {tc}")
    tc = ev(ed.apply("anna", sid, {"type": "changeText", "page": pid, "id": tid, "size": 22, "h": 80, "color": "#d62d20"}), "textChanged")[0]["text"]
    check(tc["size"] == 22 and tc["color"] == "#d62d20" and tc["w"] == 150, f"size/color {tc}")
    tc = ev(ed.apply("anna", sid, {"type": "undo"}), "textChanged")[0]["text"]
    check(tc["size"] == 30 and tc["color"] == "#1e5bd8" and tc["h"] == 120, f"undo size {tc}")
    check(ev(ed.apply("anna", sid, {"type": "undo"}), "textChanged")[0]["text"]["w"] != 150, "undo resize")
    ed.apply("anna", sid, {"type": "redo"})
    tc = ev(ed.apply("anna", sid, {"type": "redo"}), "textChanged")[0]["text"]
    check(tc["size"] == 22 and tc["w"] == 150, "redo")
    for bad in [{"w": "x"}, {"size": float("nan")}, {"color": "red; x"}, {"h": True}]:
        try:
            ed.apply("anna", sid, {"type": "changeText", "page": pid, "id": tid, **bad})
            check(False, f"accepted {bad}")
        except ControlError:
            check.ok += 1
    check(ev(ed.apply("anna", sid, {"type": "changeText", "page": pid, "id": tid, "w": 1}), "textChanged")[0]["text"]["w"] == 20, "min width")
    ed.apply("anna", sid, {"type": "changeText", "page": pid, "id": tid, "w": 150})
    check(not ev(ed.apply("anna", sid, {"type": "changeText", "page": pid, "id": tid, "w": 150}), "textChanged"), "no-op change")
    ed.close("anna", sid)
    texts = ed.open("anna", rel)["pages"][0]["texts"]
    check(len(texts) == 1 and texts[0]["text"] == "Ciao mondo" and abs(texts[0]["size"] - 22) < 0.01
          and abs(texts[0]["w"] - 150) < 1 and texts[0]["color"] == "#d62d20", f"read back {texts}")
    check.done()


if __name__ == "__main__":
    main()
