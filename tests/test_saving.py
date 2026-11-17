import json
"""Saving: operations never wait for the PDF writing; pages changed during a save;
closing during a save; file changed on disk during a save; a stuck writer, Windows
mode and unexpected errors never leave the document unsaved or "in progress"."""
import math
import os
import subprocess
import threading
import time
from _common import Checks, workspace
import pymupdf
from app.model import pdf_store, save_worker
from app.model.document import OpenDocument


def subjects(path):
    return {a.info["subject"].split(":")[1] for p in pymupdf.open(path) for a in p.annots()}


def stroke(i, n=300):
    return {"id": f"s{i:05d}", "tool": "pen", "color": "#1d1d1f", "width": 1,
            "points": [[50 + k * 1.5, 50 + (i % 500) * 1.4 + math.sin(k / 5) * 3, 0.5] for k in range(n)]}


def main():
    check = Checks("test_saving")
    tmp, lib, ed = workspace()
    rel = lib.create_document("anna", "", "grande"); path = tmp / "notes" / "anna" / rel
    o = ed.open("anna", rel); sid, pid = o["session"], o["pages"][0]["id"]; room = ed.clients[sid].room
    def add(s):
        ed.apply("anna", sid, {"type": "addStroke", "page": pid, "stroke": s})
        room.timer and room.timer.cancel()
    for i in range(800):
        add(stroke(i))
    room.state = "pending"; t0 = time.perf_counter(); ed._save(room); full = time.perf_counter() - t0
    check(room.state == "saved", "saved")
    # --- incremental saves: only what changed is written -------------------------------------
    check(room.doc.incremental_saves == 0 and not room.doc.full_save_due, "first save of a new document was a full one")
    for i in range(5):
        add(stroke(5000 + i))
    room.state = "pending"; t0 = time.perf_counter(); ed._save(room); incr = time.perf_counter() - t0
    check(room.state == "saved" and room.doc.incremental_saves == 1 and incr < full / 3,
          f"incremental save of 5 strokes: {incr:.2f}s against {full:.2f}s for the full one")
    d = pymupdf.open(path); xref = d[0].annot_xrefs()[0][0]; kind, data = d.xref_get_key(xref, pdf_store.DATA_KEY); d.close()
    check(kind == "string" and json.loads(data)["points"], "every annotation carries its own data")
    ed.apply("anna", sid, {"type": "removeSelection", "page": pid, "strokes": ["s00001"], "texts": [], "images": []})
    ed.apply("anna", sid, {"type": "moveSelection", "page": pid, "strokes": ["s00002"], "texts": [], "images": [], "dx": 7, "dy": 3})
    ed.apply("anna", sid, {"type": "recolorSelection", "page": pid, "strokes": ["s00003"], "texts": [], "images": [], "color": "#d62d20"})
    r = ed.apply("anna", sid, {"type": "addText", "page": pid, "x": 40, "y": 40, "size": 18, "text": "nota"})
    tid = [e for e in r["events"] if e["event"] == "textAdded"][0]["text"]["id"]
    room.timer and room.timer.cancel(); room.state = "pending"; ed._save(room)
    ed.apply("anna", sid, {"type": "editText", "page": pid, "id": tid, "text": "nota cambiata", "h": 30, "commit": True})
    room.timer and room.timer.cancel(); room.state = "pending"; ed._save(room)
    check(room.doc.incremental_saves == 3, "three incremental saves in a row")
    _, disk, _ = pdf_store.load_document(path)            # full read, no cache
    on_disk = {s["id"]: s for s in disk["pages"][0]["strokes"]}
    model = {s["id"]: s for s in room.doc.pages[0]["strokes"]}
    same = set(on_disk) == set(model) and all(
        on_disk[k]["color"] == model[k]["color"] and len(on_disk[k]["points"]) == len(model[k]["points"])
        and all(abs(a - b) < 1e-6 for p, q in zip(on_disk[k]["points"], model[k]["points"]) for a, b in zip(p, q))
        for k in model)
    check(same and "s00001" not in on_disk and on_disk["s00003"]["color"] == "#d62d20"
          and on_disk["s00002"]["points"][0][0] == model["s00002"]["points"][0][0],
          "full read back after incremental saves equals the model (removed, moved, recoloured)")
    texts = disk["pages"][0]["texts"]
    check(len(texts) == 1 and texts[0]["text"] == "nota cambiata" and abs(texts[0]["size"] - 18) < 0.01, "text edited incrementally")
    size_before = path.stat().st_size
    for i in range(pdf_store.INCREMENTAL_LIMIT):
        add(stroke(6000 + i)); room.state = "pending"; ed._save(room)
    check(room.doc.incremental_saves < pdf_store.INCREMENTAL_LIMIT, "after the limit a full save compacts the file")
    ed.apply("anna", sid, {"type": "addPage", "after": pid}); room.timer and room.timer.cancel(); room.state = "pending"; ed._save(room)
    check(room.doc.incremental_saves == 0, "a page added: full save")
    ed.apply("anna", sid, {"type": "removePage", "page": room.doc.pages[1]["id"]}); room.timer and room.timer.cancel(); room.state = "pending"; ed._save(room)
    add(stroke(7000)); room.state = "pending"; ed._save(room)
    check(room.doc.incremental_saves == 1, "incremental again after the structure settled")
    # operations during a save
    add(stroke(9000))
    th = threading.Thread(target=ed._save, args=(room,)); th.start(); time.sleep(0.02)
    lat = []
    while th.is_alive() and len(lat) < 100:
        t0 = time.perf_counter(); ed.apply("anna", sid, {"type": "undo"}); ed.apply("anna", sid, {"type": "redo"}); lat.append(time.perf_counter() - t0)
    th.join(); room.timer and room.timer.cancel()
    check(lat and max(lat) < 0.05, f"latency during save {max(lat or [0])}")
    room.state = "pending"; ed._save(room)
    check({"s09000"} <= subjects(path), "stroke added during save is in the file")
    # a change while a save is on its way: that save is not overwritten, a new one
    # starts by itself as soon as it ends ("needs resave")
    orig_write = OpenDocument.write_save
    writing = threading.Event()
    OpenDocument.write_save = lambda self, job: (writing.set(), time.sleep(0.4), orig_write(self, job))[2]
    add(stroke(9010)); room.state = "pending"
    th = threading.Thread(target=ed._save, args=(room,)); th.start(); writing.wait(5)
    ed.apply("anna", sid, {"type": "addStroke", "page": pid, "stroke": stroke(9011)})   # restarts the countdown
    th.join()
    OpenDocument.write_save = orig_write
    due = room.timer is not None and room.timer.is_alive()
    room.timer.cancel()                      # run below by hand: no race with reading the file
    check(room.state == "pending" and due and not room.saving,
          "change during a save: after it the document is still to save, and a new save is due")
    on_disk = subjects(path)
    check("s09010" in on_disk and "s09011" not in on_disk, "the first save wrote what it had copied, untouched")
    ed._save(room)                           # the save that was due
    check(room.state == "saved" and "s09011" in subjects(path), "the following save wrote the new change")
    # pages added/removed during a slow write, then reopen
    pids = [p["id"] for p in room.doc.view_pages()]
    orig = OpenDocument.write_save
    OpenDocument.write_save = lambda self, job: (time.sleep(0.4), orig(self, job))[1]
    ed.apply("anna", sid, {"type": "addPage", "after": pid}); room.timer and room.timer.cancel()
    th = threading.Thread(target=lambda: (setattr(room, "state", "pending"), ed._save(room))); th.start(); time.sleep(0.1)
    ed.apply("anna", sid, {"type": "addPage", "after": pid})
    ed.apply("anna", sid, {"type": "removePage", "page": room.doc.pages[1]["id"]})
    th.join(); OpenDocument.write_save = orig
    room.timer and room.timer.cancel(); room.state = "pending"; ed._save(room)
    expected = [p["id"] for p in room.doc.pages]
    # file changed by another program during a write: merged
    add(stroke(9100))
    def external_then_write(self, job):
        d = pymupdf.open(path); d[0].insert_text((300, 800), "modifica esterna"); d.saveIncr(); d.close()
        return orig(self, job)
    OpenDocument.write_save = external_then_write
    room.state = "pending"; ed._save(room)
    OpenDocument.write_save = orig
    check(room.state == "saved", "merged after external change")
    d = pymupdf.open(path)
    check("modifica esterna" in d[0].get_text() and "s09100" in subjects(path), "external change and new stroke both kept")
    d.close()
    # closing during a slow write keeps everything
    OpenDocument.write_save = lambda self, job: (time.sleep(0.5), orig(self, job))[1]
    add(stroke(9200))
    th = threading.Thread(target=lambda: (setattr(room, "state", "pending"), ed._save(room))); th.start(); time.sleep(0.1)
    add(stroke(9201)); t0 = time.perf_counter(); ed.close("anna", sid); closing = time.perf_counter() - t0
    th.join(); OpenDocument.write_save = orig
    check(closing < 0.3, f"closing does not wait for the file ({closing:.2f}s)")
    # The room closes after the final (full) save: up to a minute on a slow machine
    # (e.g. a laptop in power-saving mode); the check is about what is kept, not speed.
    for _ in range(1200):
        if room.closed:
            break
        time.sleep(0.05)
    check(room.closed and {"s09200", "s09201"} <= subjects(path), "close during save keeps everything")
    d = pymupdf.open(path); stored = json.loads(d.embfile_get(pdf_store.LAYER_FILE)); d.close()
    check(room.doc.incremental_saves == 0 and {s["id"] for s in stored["pages"][0]["strokes"]} == {s["id"] for s in room.doc.pages[0]["strokes"]},
          "closing compacts the file: full save, layer file up to date")
    o = ed.open("anna", rel)
    check([p["id"] for p in o["pages"]] == expected, "pages after reopen")
    sid = o["session"]; room = ed.clients[sid].room
    # Reopened from the layer cache: the first save is incremental and really writes
    # (the saved layer must be a copy, not the live pages).
    add(stroke(9250)); room.state = "pending"; ed._save(room)
    check(room.doc.incremental_saves == 1 and "s09250" in subjects(path), "first save after reopening: incremental, stroke in the file")
    # stuck writer process: stopped, the server writes by itself
    add(stroke(9300))
    old = save_worker.WRITE_TIMEOUT; save_worker.WRITE_TIMEOUT = 0.001
    room.state = "pending"; ed._save(room); save_worker.WRITE_TIMEOUT = old
    check(room.state == "saved" and "s09300" in subjects(path), "stuck writer: saved anyway")
    check(save_worker._disabled and save_worker._executor is None, "writer stopped and not used again")
    time.sleep(0.3)
    kids = subprocess.run(["pgrep", "-P", str(os.getpid())], capture_output=True, text=True).stdout.split()
    alive = [k for k in kids if "spawn_main(tracker_fd" in open(f"/proc/{k}/cmdline").read()]
    check(not alive, f"no writer process left {alive}")
    # unexpected errors while preparing / recording a save
    orig_prep, orig_fin = OpenDocument.prepare_save, OpenDocument.finish_save
    OpenDocument.prepare_save = lambda self: (_ for _ in ()).throw(RuntimeError("guasto"))
    add(stroke(9400)); room.state = "pending"; ed._save(room)
    check(room.state == "error" and not room.saving and room.timer is not None, "prepare error: retried")
    OpenDocument.prepare_save = orig_prep; room.timer.cancel(); ed._save(room)
    check(room.state == "saved" and "s09400" in subjects(path), "saved after prepare error")
    OpenDocument.finish_save = lambda self, job, result: (_ for _ in ()).throw(RuntimeError("guasto"))
    add(stroke(9500)); room.state = "pending"; ed._save(room)
    check(room.state == "error" and not room.saving, "finish error: retried")
    OpenDocument.finish_save = orig_fin; room.timer.cancel(); ed._save(room)
    check(room.state == "saved", "saved after finish error")
    ed.close("anna", sid)
    check.done(f"(salvataggio di 800 tratti {full:.1f} s; attesa massima durante il salvataggio {max(lat) * 1000:.1f} ms)")


if __name__ == "__main__":
    main()
