"""Two devices on the same document, each seeing the other's changes a little late:
no correct operation is rejected and both end with exactly the document on the
computer. Same tab reopening = no extra device. Eraser confirms the strokes the
view hid, within the margin."""
import collections
import io
import random
from _common import Checks, workspace
from PIL import Image
from app.control.errors import ControlError
from app.control.editing import SessionGone
from app.control.navigation import NavigationController


class View:
    def __init__(self, pages):
        self.pages = {p["id"]: {"strokes": {s["id"] for s in p["strokes"]}, "texts": {t["id"]: dict(t) for t in p["texts"]},
                                "images": {i["id"]: dict(i) for i in p.get("images", [])}} for p in pages}
        self.order = [p["id"] for p in pages]
        self.selection = None

    def apply(self, ev):
        e, pg = ev["event"], self.pages.get(ev.get("page"))
        if e in ("pagesChanged", "backgroundChanged"):
            for p in ev["pages"]:
                self.pages.setdefault(p["id"], {"strokes": set(p and {s["id"] for s in p["strokes"]}), "texts": {}, "images": {}})
            self.order = [p["id"] for p in ev["pages"]]
        elif e == "selection":
            self.selection = ev
        elif pg is None:
            return
        elif e == "strokeAdded": pg["strokes"].add(ev["stroke"]["id"])
        elif e == "strokeRemoved": pg["strokes"].discard(ev["id"])
        elif e in ("textAdded", "textChanged"): pg["texts"][ev["text"]["id"]] = dict(ev["text"])
        elif e == "textRemoved": pg["texts"].pop(ev["id"], None)
        elif e in ("imageAdded", "imageChanged"): pg["images"][ev["image"]["id"]] = dict(ev["image"])
        elif e == "imageRemoved": pg["images"].pop(ev["id"], None)


def png():
    b = io.BytesIO(); Image.new("RGB", (40, 30), (200, 50, 50)).save(b, "PNG"); return b.getvalue()


def collaborate(seed, steps=3000):
    rnd = random.Random(seed)
    tmp, lib, ed = workspace()
    rel = lib.create_document("anna", "", "collab")
    devs = {}
    for name in ("ipad", "zen"):
        o = ed.open("anna", rel, f"tab{name}000000000000000000"[:24])
        devs[name] = {"sid": o["session"], "view": View(o["pages"])}
    room = ed.clients[devs["ipad"]["sid"]].room
    img = png(); rejected = collections.Counter()

    def op(name, o):
        try:
            r = ed.apply("anna", devs[name]["sid"], o)
        except ControlError as e:
            rejected[(name, o["type"], e.message)] += 1; return
        for ev in r["events"]: devs[name]["view"].apply(ev)

    def deliver(name):
        c = ed.clients[devs[name]["sid"]]
        evs, c.outbox = c.outbox, []
        for ev in evs: devs[name]["view"].apply(ev)

    for step in range(steps):
        room.timer and room.timer.cancel()
        for name in devs:
            if rnd.random() < 0.35: deliver(name)
        name = "ipad" if rnd.random() < 0.6 else "zen"
        v = devs[name]["view"]; pid = rnd.choice(v.order); pg = v.pages[pid]
        x, y = rnd.uniform(20, 500), rnd.uniform(20, 700)
        kind = rnd.choice(["stroke", "stroke", "erase", "text", "editText", "moveText", "changeText", "removeText",
                           "lasso", "moveSel", "removeSel", "undo", "redo", "image", "moveImage", "removeImage",
                           "addPage", "removePage"])
        if kind == "stroke":
            op(name, {"type": "addStroke", "page": pid, "stroke": {"id": f"{name[0]}{step}", "tool": "pen", "color": "#000000", "width": 1, "points": [[x, y, .5], [x + 40, y + 10, .5]]}})
        elif kind == "erase" and pg["strokes"]:
            op(name, {"type": "erase", "page": pid, "path": [[x, y]], "radius": 7, "ids": [rnd.choice(sorted(pg["strokes"]))]})
        elif kind == "text":
            op(name, {"type": "addText", "page": pid, "x": x, "y": y, "size": 16})
        elif kind in ("editText", "moveText", "changeText", "removeText") and pg["texts"]:
            t = rnd.choice(list(pg["texts"].values())); o = {"type": kind, "page": pid, "id": t["id"]}
            if kind == "editText": o.update(text=f"ciao {step}", h=40, commit=rnd.random() < 0.5)
            if kind == "moveText": o.update(x=t["x"] + 3, y=t["y"] + 3)
            if kind == "changeText": o.update(w=t["w"] + 5, h=t["h"] + 5, size=18)
            op(name, o)
        elif kind == "lasso":
            op(name, {"type": "select", "page": pid, "polygon": [[x - 150, y - 150], [x + 150, y - 150], [x + 150, y + 150], [x - 150, y + 150]]})
        elif kind in ("moveSel", "removeSel") and v.selection:
            s = v.selection; base = {"page": s["page"], "strokes": s["strokes"], "texts": s["texts"], "images": s["images"]}
            op(name, {"type": "moveSelection", "dx": 4, "dy": 4, **base} if kind == "moveSel" else {"type": "removeSelection", **base})
            if kind == "removeSel": v.selection = None
        elif kind in ("undo", "redo"):
            op(name, {"type": kind})
        elif kind == "image" and name == "zen":
            try:
                r = ed.add_image("anna", devs[name]["sid"], pid, x, y, 120, img)
                for ev in r["events"]: v.apply(ev)
            except ControlError as e:
                rejected[(name, "add_image", e.message)] += 1
        elif kind == "moveImage" and pg["images"]:
            i = rnd.choice(list(pg["images"].values()))
            op(name, {"type": "changeImage", "page": pid, "id": i["id"], "x": i["x"] + 2, "y": i["y"] + 2, "w": i["w"], "h": i["h"]})
        elif kind == "removeImage" and pg["images"]:
            op(name, {"type": "removeImage", "page": pid, "id": rnd.choice(list(pg["images"]))})
        elif kind == "addPage" and len(v.order) < 4:
            op(name, {"type": "addPage", "after": pid})
        elif kind == "removePage" and len(v.order) > 1 and rnd.random() < 0.3:
            op(name, {"type": "removePage", "page": pid})
    for name in devs:
        deliver(name)
    truth = {p["id"]: ({s["id"] for s in p["strokes"]}, set(t["id"] for t in p["texts"]), {i["id"] for i in p.get("images", [])}) for p in room.doc.pages}
    views = []
    for name in devs:
        v = devs[name]["view"]
        views.append({pid: (v.pages[pid]["strokes"], set(v.pages[pid]["texts"]), set(v.pages[pid]["images"])) for pid in v.order} == truth)
    limits = {"Troppe immagini in questa pagina", "Troppi elementi in questa pagina"}
    return [k for k in rejected if k[2] not in limits], all(views)


def main():
    check = Checks("test_collaboration")
    for seed in (1, 2, 3):
        bad, converged = collaborate(seed)
        check(not bad, f"seed {seed}: operations rejected {bad}")
        check(converged, f"seed {seed}: devices differ from the document")
    # same tab reopening, eraser margin
    tmp, lib, ed = workspace()
    nav = NavigationController(lib, ed)
    rel = lib.create_document("anna", "", "doc")
    a = nav.open("anna", rel, None, "tabA0000000000000000000a")
    a2 = nav.open("anna", rel, None, "tabA0000000000000000000a")
    check(a2["devices"] == 1, "reload of the same tab: one device")
    try:
        ed.apply("anna", a["session"], {"type": "undo"}); check(False, "old session still alive")
    except SessionGone as e:
        check(e.details.get("reason") == "replaced", "old session replaced")
    b = nav.open("anna", rel, None, "tabB0000000000000000000b")
    check(b["devices"] == 2, "another tab counts")
    check(nav.open("anna", rel, None, "bad id")["devices"] == 3, "invalid tab id: just a device")
    sid, pid = a2["session"], a2["pages"][0]["id"]
    ed.apply("anna", sid, {"type": "addStroke", "page": pid, "stroke": {"id": "line1", "tool": "pen", "color": "#000000", "width": 1, "points": [[100, 100, .5], [200, 100, .5]]}})
    r = ed.apply("anna", sid, {"type": "erase", "page": pid, "path": [[150, 104.2]], "radius": 3})
    check(not [e for e in r["events"] if e["event"] == "strokeRemoved"], "strict miss")
    r = ed.apply("anna", sid, {"type": "erase", "page": pid, "path": [[150, 104.2]], "radius": 3, "ids": ["line1"]})
    check([e for e in r["events"] if e["event"] == "strokeRemoved"], "named stroke within margin erased")
    ed.apply("anna", sid, {"type": "undo"})
    r = ed.apply("anna", sid, {"type": "erase", "page": pid, "path": [[150, 140]], "radius": 3, "ids": ["line1"]})
    check(not [e for e in r["events"] if e["event"] == "strokeRemoved"], "named stroke far away kept")
    check.done()


if __name__ == "__main__":
    main()
