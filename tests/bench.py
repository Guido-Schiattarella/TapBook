"""Speed of the main server operations (a document with 600 strokes).

    .venv/bin/python tests/bench.py [code folder]

With a folder (e.g. a copy of an earlier version), that code is measured: compare
the two in the same conditions (the computer's load changes the numbers)."""
import math
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))


def main():
    from app.control.editing import EditController
    from app.control.library import LibraryController
    tmp = Path(tempfile.mkdtemp()); (tmp / "notes" / "anna").mkdir(parents=True)
    lib = LibraryController(tmp / "notes")
    try:
        ed = EditController(lib, tmp / "cache", 15, tmp / "bg")
    except TypeError:                       # versions before the background store
        ed = EditController(lib, tmp / "cache", 15)
    rel = lib.create_document("anna", "", "bench")
    t0 = time.perf_counter(); o = ed.open("anna", rel)
    sid, pid = o["session"], o["pages"][0]["id"]; room = ed.clients[sid].room
    st = lambda i: {"id": f"s{i:05d}", "tool": "pen", "color": "#1d1d1f", "width": 1,
                    "points": [[40 + k * 4, 40 + (i % 180) * 4.4 + math.sin(k / 4) * 3, 0.5] for k in range(120)]}
    res, t = {}, []
    for i in range(600):
        t0 = time.perf_counter(); ed.apply("anna", sid, {"type": "addStroke", "page": pid, "stroke": st(i)}); t.append(time.perf_counter() - t0)
    room.timer and room.timer.cancel()
    res["nuovo tratto (ms, mediana)"] = statistics.median(t) * 1000
    t = []
    for _ in range(30):
        t0 = time.perf_counter(); ed.apply("anna", sid, {"type": "undo"}); ed.apply("anna", sid, {"type": "redo"}); t.append((time.perf_counter() - t0) / 2)
    room.timer and room.timer.cancel()
    res["annulla/ripristina (ms, mediana)"] = statistics.median(t) * 1000
    t = []
    for i in range(20):
        t0 = time.perf_counter(); ed.apply("anna", sid, {"type": "erase", "page": pid, "path": [[100 + i * 20, 40 + k * 3] for k in range(200)], "radius": 7}); t.append(time.perf_counter() - t0)
        ed.apply("anna", sid, {"type": "undo"})
    room.timer and room.timer.cancel()
    res["gomma (ms, mediana)"] = statistics.median(t) * 1000
    t0 = time.perf_counter(); ed.apply("anna", sid, {"type": "select", "page": pid, "polygon": [[50, 50], [400, 50], [400, 400], [50, 400]]}); res["lazzo (ms)"] = (time.perf_counter() - t0) * 1000
    room.state = "pending"; t0 = time.perf_counter(); ed._save(room); res["salvataggio (s)"] = time.perf_counter() - t0
    ed.apply("anna", sid, {"type": "addStroke", "page": pid, "stroke": st(5000)}); room.timer and room.timer.cancel()
    th = threading.Thread(target=ed._save, args=(room,)); th.start(); time.sleep(0.02); lat = []
    while th.is_alive() and len(lat) < 200:
        t0 = time.perf_counter(); ed.apply("anna", sid, {"type": "undo"}); ed.apply("anna", sid, {"type": "redo"}); lat.append(time.perf_counter() - t0)
    th.join(); room.timer and room.timer.cancel()
    res["annulla durante il salvataggio (ms, max)"] = max(lat) * 1000 if lat else float("nan")
    ed.close("anna", sid)
    t0 = time.perf_counter(); o = ed.open("anna", rel); res["apertura (ms)"] = (time.perf_counter() - t0) * 1000
    ed.close("anna", o["session"])
    t0 = time.perf_counter(); o = ed.open("anna", rel); res["riapertura (ms)"] = (time.perf_counter() - t0) * 1000
    ed.close("anna", o["session"])
    for k, v in res.items():
        print(f"   {k:42s} {v:10.2f}")


if __name__ == "__main__":
    main()
