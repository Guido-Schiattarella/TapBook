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
from app.model import save_worker
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
    add(stroke(9201)); ed.close("anna", sid); th.join(); OpenDocument.write_save = orig
    check({"s09200", "s09201"} <= subjects(path), "close during save keeps everything")
    o = ed.open("anna", rel)
    check([p["id"] for p in o["pages"]] == expected, "pages after reopen")
    sid = o["session"]; room = ed.clients[sid].room
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
