"""TapBook Sync: a real server (subprocess) and the real client engine.
Both directions, moves, conflicts, the deletion brake, interrupted uploads,
certificates, and the attacks on the sync API."""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from _common import Checks, ROOT

tmp = Path(tempfile.mkdtemp())
os.environ["XDG_CONFIG_HOME"] = str(tmp / "clientconfig")     # the client's settings stay here
os.environ["APPDATA"] = str(tmp / "clientconfig")

from app.syncclient import api, settings  # noqa: E402
from app.syncclient.api import ApiError, Connection  # noqa: E402
from app.syncclient.engine import Engine, FolderMissing, scan_local  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, name, https=False, max_mb=100):
        self.dir = tmp / name
        self.notes = self.dir / "notes"
        self.port = free_port()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("NOTES_")}
        self.env.update(NOTES_DATA_DIR=str(self.dir / "data"), NOTES_NOTES_ROOT=str(self.notes),
                        NOTES_HTTPS="true" if https else "false", NOTES_HOST="127.0.0.1",
                        NOTES_PORT=str(self.port), NOTES_FIREWALL="off", NOTES_MAX_UPLOAD_MB=str(max_mb),
                        NOTES_ALLOW_REGISTRATION="false", NOTES_CONFIG=str(self.dir / "none.ini"))
        self.url = f"{'https' if https else 'http'}://127.0.0.1:{self.port}"
        self.proc = None

    def cli(self, *args, stdin=None):
        return subprocess.run([sys.executable, "-m", "app", *args], cwd=ROOT, env=self.env, input=stdin,
                              capture_output=True, text=True, timeout=120)

    def start(self):
        self.proc = subprocess.Popen([sys.executable, "-m", "app", "serve", "--service"], cwd=ROOT, env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=1).close()
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server not started")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=60)


def h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, data, age=10):
    """A file "settled" (modified `age` seconds ago, as if written earlier)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    t = time.time() - age
    os.utime(path, (t, t))


def main():
    check = Checks("test_sync")
    srv = Server("s1", max_mb=6)
    check(srv.cli("user", "add", "anna", stdin="Password-Anna-1\nPassword-Anna-1\n").returncode == 0, "user anna")
    check(srv.cli("user", "add", "bruno", stdin="Password-Bruno-1\nPassword-Bruno-1\n").returncode == 0, "user bruno")
    check(srv.cli("user", "add", "elena", stdin="Password-Elena-1\nPassword-Elena-1\n").returncode == 0, "user elena")
    srv.start()
    try:
        run_more(check, srv)
        run(check, srv)          # last: it ends by blocking this address with wrong tokens
    finally:
        srv.stop()
    run_watcher(check)
    run_https(check)
    run_open_document(check)
    check.done()


def run(check, srv):
    anon = Connection(srv.url)
    # --- pairing ------------------------------------------------------------------------------
    try:
        anon.pair("anna", "sbagliata", "pc"); check(False, "wrong password")
    except ApiError as e:
        check(e.status == 401, "pair: wrong password refused")
    paired = anon.pair("anna", "Password-Anna-1", "Portatile di Anna")
    token = paired["token"]
    check(len(token) == 43 and paired["username"] == "anna", "pair: token")
    conn = Connection(srv.url, token)
    check(conn.whoami()["username"] == "anna", "whoami")
    db = sqlite_rows(srv, "SELECT token_hash FROM devices")
    check(db and token not in json.dumps(db) and (h(token.encode()),) in db, "only the token's hash is stored")
    bruno = Connection(srv.url, anon.pair("bruno", "Password-Bruno-1", "pc-bruno")["token"])

    # --- attacks on the API ---------------------------------------------------------------------------
    for bad in (None, "", "x" * 43, token[:-1] + ("A" if token[-1] != "A" else "B")):
        try:
            Connection(srv.url, bad).changes(); check(False, "bad token")
        except ApiError as e:
            check(e.status == 401, f"bad token refused ({bad!r:.12})")
    # A cookie session is not a token: the web login does not open the sync API
    for path in ("../anna2/x.pdf", "/etc/passwd", ".cestino/x", "a/../../x", "pictures/x.png", "x/.hidden",
                 "a\\b", "a\x00b", "CON.pdf", "a:b.pdf", "a//b", "", "x" * 2000, "a/ b"):
        try:
            conn.download(path, tmp / "dl.bin", "0" * 64, 1); check(False, f"path {path!r}")
        except ApiError as e:
            check(e.status in (400, 404), f"download refused for {path[:20]!r}")
    for call in (lambda: conn.mkdir("../evil"), lambda: conn.delete("../bruno/x.pdf", "0" * 64),
                 lambda: conn.move("a.pdf", "../bruno/a.pdf", "0" * 64), lambda: conn.mkdir(".cestino"),
                 lambda: conn.request("POST", "/api/sync/upload", data={"path": "../x", "size": 1, "hash": "0" * 64}),
                 lambda: conn.request("POST", "/api/sync/upload", data={"path": "ok.pdf", "size": -1, "hash": "0" * 64}),
                 lambda: conn.request("POST", "/api/sync/upload", data={"path": "ok.pdf", "size": 1, "hash": "zz"}),
                 lambda: conn.request("PUT", "/api/sync/upload/../../x", {"offset": 0}, raw=b"x"),
                 lambda: conn.request("POST", "/api/sync/upload/AAAAAAAAAAAAAAAAAAAAAA/finish", data={})):
        try:
            call(); check(False, "attack accepted")
        except ApiError as e:
            check(e.status in (400, 404, 405), f"sync API attack refused ({e.status})")
    check(not (srv.notes / "evil").exists() and not (srv.notes / "anna" / ".cestino" / "x").exists(),
          "nothing written outside")
    # Bruno cannot see Anna's files
    (srv.notes / "anna").mkdir(parents=True, exist_ok=True)
    write(srv.notes / "anna" / "segreto.pdf", b"di anna")
    check("segreto.pdf" not in json.dumps(bruno.changes()["entries"]), "another user's files are not listed")
    try:
        bruno.download("segreto.pdf", tmp / "x.bin", h(b"di anna"), 7); check(False, "cross user")
    except ApiError as e:
        check(e.status == 404, "another user's file cannot be downloaded")
    (srv.notes / "anna" / "segreto.pdf").unlink()

    # --- first synchronisation: a merge --------------------------------------------------------------
    local = tmp / "local-anna"
    write(local / "Appunti.pdf", b"appunti v1")
    write(local / "Corsi" / "Analisi.pdf", b"analisi v1")
    write(local / ".nascosto", b"non va sul server")
    write(local / "~$bozza.docx", b"lock di office")
    write(local / "nome:strano.pdf", b"nome non valido su windows")
    (local / "Vuota").mkdir()
    write(srv.notes / "anna" / "Dal server.pdf", b"dal server v1")
    write(srv.notes / "anna" / ".cestino" / "vecchio.pdf", b"cestino del server")
    write(srv.notes / "anna" / "pictures" / "x" / "img.jpg", b"immagine dell'app")
    state, log = {}, []
    eng = lambda: Engine(local, conn, state, "PC Anna", lambda t, l="info": log.append(t))  # noqa: E731

    def sync(confirmed=False):
        e = eng()
        e.sync(confirmed)
        return e
    e = sync()
    server = srv.notes / "anna"
    check((server / "Appunti.pdf").read_bytes() == b"appunti v1", "upload: new file")
    check((server / "Corsi" / "Analisi.pdf").read_bytes() == b"analisi v1", "upload: in a subfolder")
    check((server / "Vuota").is_dir(), "empty folder created on the server")
    check((local / "Dal server.pdf").read_bytes() == b"dal server v1", "download: new file")
    check(not (server / ".nascosto").exists() and not (server / "~$bozza.docx").exists(), "hidden and temporary files stay local")
    check(not (local / ".cestino").exists() and not (local / "pictures").exists(), "server trash and images do not come down")
    check(not (server / "nome:strano.pdf").exists() and "nome:strano.pdf" in scan_local(local)[1], "invalid name skipped and reported")
    check(abs((server / "Appunti.pdf").stat().st_mtime - (local / "Appunti.pdf").stat().st_mtime) < 1, "modification time kept")
    sync()
    before = len(log)
    sync()
    check(len(log) == before, "nothing to do when aligned")

    # --- changes on one side ------------------------------------------------------------------------------
    write(local / "Appunti.pdf", b"appunti v2 modificati sul pc")
    sync()
    check((server / "Appunti.pdf").read_bytes() == b"appunti v2 modificati sul pc", "local change uploaded")
    write(server / "Dal server.pdf", b"scritto sull'ipad")
    sync()
    check((local / "Dal server.pdf").read_bytes() == b"scritto sull'ipad", "server change downloaded")

    # --- moves ----------------------------------------------------------------------------------------------
    big = os.urandom(5 * 1024 * 1024 + 123)            # several upload pieces
    write(local / "Grande.pdf", big)
    sync()
    check(h((server / "Grande.pdf").read_bytes()) == h(big), "5 MB file uploaded in pieces")
    (local / "Corsi" / "2026").mkdir()
    os.replace(local / "Grande.pdf", local / "Corsi" / "2026" / "Grande rinominato.pdf")
    log.clear()
    sync()
    check((server / "Corsi" / "2026" / "Grande rinominato.pdf").exists() and not (server / "Grande.pdf").exists(),
          "local move repeated on the server")
    check(any("Spostato sul server" in t for t in log) and not any("Inviato" in t for t in log),
          "moved, not uploaded again")
    os.replace(server / "Corsi" / "Analisi.pdf", server / "Analisi spostata.pdf")
    log.clear()
    sync()
    check((local / "Analisi spostata.pdf").exists() and not (local / "Corsi" / "Analisi.pdf").exists(),
          "server move repeated here")
    check(any(t.startswith("Spostato:") for t in log) and not any("Scaricato" in t for t in log),
          "moved, not downloaded again")

    # --- deletions ---------------------------------------------------------------------------------------------
    (local / "Analisi spostata.pdf").unlink()
    sync()
    trash = list((server / ".cestino").glob("*Analisi spostata.pdf"))
    check(not (server / "Analisi spostata.pdf").exists() and trash, "local deletion → server trash")
    (server / "Dal server.pdf").unlink()
    sync()
    check(not (local / "Dal server.pdf").exists(), "server deletion repeated here")
    check(list((local / ".tapbook-sync" / "cestino").rglob("Dal server.pdf")), "…into the local trash, not destroyed")
    shutil.rmtree(local / "Vuota")
    sync()
    check(not (server / "Vuota").exists(), "empty folder deleted")

    # --- conflicts ---------------------------------------------------------------------------------------------
    write(local / "Appunti.pdf", b"versione del pc")
    write(server / "Appunti.pdf", b"versione dell'ipad", age=5)
    sync()
    sync()
    copies = [p.name for p in local.glob("Appunti (conflitto PC Anna *).pdf")]
    check((local / "Appunti.pdf").read_bytes() == b"versione dell'ipad" and len(copies) == 1, "conflict: both kept here")
    check((server / copies[0]).read_bytes() == b"versione del pc", "conflict: the PC version reaches the server")
    write(server / "Appunti.pdf", b"cambiato sull'ipad dopo")
    (local / "Appunti.pdf").unlink()
    sync()
    check((local / "Appunti.pdf").read_bytes() == b"cambiato sull'ipad dopo", "change wins over deletion")

    # --- server-side protection: stale versions ---------------------------------------------------------
    try:
        conn.delete("Appunti.pdf", h(b"una versione vecchia")); check(False, "stale delete")
    except ApiError as e:
        check(e.status == 409 and (server / "Appunti.pdf").exists(), "delete of a changed file refused")
    up = conn.request("POST", "/api/sync/upload", data={"path": "Appunti.pdf", "size": 3, "hash": h(b"abc"),
                                                        "base": h(b"vecchia")})
    conn.request("PUT", f"/api/sync/upload/{up['id']}", {"offset": 0}, raw=b"abc")
    try:
        conn.request("POST", f"/api/sync/upload/{up['id']}/finish", data={}); check(False, "stale upload")
    except ApiError as e:
        check(e.status == 409 and (server / "Appunti.pdf").read_bytes() == b"cambiato sull'ipad dopo",
              "upload over a changed file refused")
    up = conn.request("POST", "/api/sync/upload", data={"path": "nuovo.pdf", "size": 3, "hash": h(b"xyz")})
    conn.request("PUT", f"/api/sync/upload/{up['id']}", {"offset": 0}, raw=b"abc")
    try:
        conn.request("POST", f"/api/sync/upload/{up['id']}/finish", data={}); check(False, "damaged")
    except ApiError as e:
        check(e.status == 400 and not (server / "nuovo.pdf").exists(), "damaged upload refused")
    up = conn.request("POST", "/api/sync/upload", data={"path": "ripresa.pdf", "size": 6, "hash": h(b"abcdef")})
    conn.request("PUT", f"/api/sync/upload/{up['id']}", {"offset": 0}, raw=b"abc")
    again = conn.request("POST", "/api/sync/upload", data={"path": "ripresa.pdf", "size": 6, "hash": h(b"abcdef")})
    check(again["id"] == up["id"] and again["received"] == 3, "interrupted upload resumes")
    try:
        conn.request("PUT", f"/api/sync/upload/{up['id']}", {"offset": 0}, raw=b"abc"); check(False, "dup piece")
    except ApiError as e:
        check(e.status == 409 and e.data.get("received") == 3, "a piece sent twice is not written twice")
    try:
        conn.request("PUT", f"/api/sync/upload/{up['id']}", {"offset": 3}, raw=b"defghi"); check(False, "overflow")
    except ApiError as e:
        check(e.status == 400, "more bytes than declared refused")
    conn.request("PUT", f"/api/sync/upload/{up['id']}", {"offset": 3}, raw=b"def")
    conn.request("POST", f"/api/sync/upload/{up['id']}/finish", data={})
    check((server / "ripresa.pdf").read_bytes() == b"abcdef", "resumed upload completed")
    try:
        conn.request("POST", "/api/sync/upload", data={"path": "enorme.pdf", "size": 7 * 1024 * 1024, "hash": "0" * 64})
        check(False, "too large")
    except ApiError as e:
        check(e.status == 413, "file over max_upload_mb refused")
    try:
        bruno.request("PUT", f"/api/sync/upload/{again['id']}", {"offset": 0}, raw=b"x"); check(False, "other's upload")
    except ApiError as e:
        check(e.status == 404, "another user's upload cannot be touched")
    sync()

    # --- deletion brake ------------------------------------------------------------------------------------------
    for i in range(30):
        write(local / "Molti" / f"file {i}.pdf", f"contenuto {i}")
    sync()
    check(len(list((server / "Molti").iterdir())) == 30, "30 files uploaded")
    shutil.rmtree(local / "Molti")
    e = sync()
    check(e.pending_deletions == 30 and len(list((server / "Molti").iterdir())) == 30,
          "mass deletion held back until confirmed")
    sync(confirmed=True)
    sync()
    check(not (server / "Molti").exists() or not list((server / "Molti").iterdir()), "deleted after confirmation")
    os.rename(local, tmp / "local-moved")
    try:
        sync(); check(False, "missing folder")
    except FolderMissing:
        check(any(server.iterdir()), "missing folder: error, nothing deleted on the server")
    os.rename(tmp / "local-moved", local)


    # --- a hostile server cannot make the client write outside the folder -------------------------------------------
    outside = tmp / "fuori"
    outside.mkdir()
    (local / "collegamento").symlink_to(outside, target_is_directory=True)
    fake = {"../../evil.txt": {"type": "file", "hash": h(b"x"), "size": 1, "mtime": 1},
            "a/../../evil2.txt": {"type": "file", "hash": h(b"x"), "size": 1},
            ".bashrc": {"type": "file", "hash": h(b"x"), "size": 1},
            "ok.pdf": {"type": "file", "hash": "../../../../etc/passwd", "size": 1},
            "collegamento/dentro.pdf": {"type": "file", "hash": h(b"x"), "size": 1}}
    hostile = Engine(local, conn, {}, "PC", lambda *a: None)
    ops = hostile.plan(scan_local(local)[0], fake)
    bad_rels = {o["rel"] for o in ops}
    check(not bad_rels & {"../../evil.txt", "a/../../evil2.txt", ".bashrc", "ok.pdf"} and hostile.errors,
          "hostile server: invalid paths and fingerprints ignored and reported")
    hostile.execute([o for o in ops if o["rel"] == "collegamento/dentro.pdf"])
    check(not any(outside.iterdir()) and not (tmp / "evil.txt").exists(), "hostile server: nothing written outside the folder")
    (local / "collegamento").unlink()

    # --- a device cannot hold all the server's threads ------------------------------------------------------------
    import threading
    cursor = conn.changes()["cursor"]
    times = []

    def waiter():
        t0 = time.time()
        conn.changes(cursor, wait=True)
        times.append(time.time() - t0)
    threads = [threading.Thread(target=waiter) for _ in range(7)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check(sum(1 for t in times if t < 5) >= 3, "at most 4 waiting requests per user, the others answered at once")

    # --- revocation ----------------------------------------------------------------------------------------------------
    r = srv.cli("device", "list")
    check("Portatile di Anna" in r.stdout and "pc-bruno" in r.stdout, "tapbook device list")
    bruno_id = next(line.split()[0] for line in r.stdout.splitlines() if "pc-bruno" in line)
    check(srv.cli("device", "revoke", bruno_id).returncode == 0, "tapbook device revoke")
    try:
        bruno.changes(); check(False, "revoked")
    except ApiError as e:
        check(e.status == 401, "revoked device refused")
    srv.cli("user", "passwd", "anna", stdin="Password-Anna-2\nPassword-Anna-2\n")
    try:
        conn.changes(); check(False, "password changed")
    except ApiError as e:
        check(e.status == 401, "password change unpairs the computers")
    # brute force on tokens from one address
    blocked = False
    for _ in range(25):
        try:
            Connection(srv.url, "y" * 43).changes()
        except ApiError as e:
            blocked = blocked or "Troppi" in str(e)
    check(blocked, "wrong tokens from one address are stopped")


def run_more(check, srv):
    """Only the changes from the server, waiting, moves by identity on disk,
    folders renamed, the first connection with both sides full, capitals."""
    conn = Connection(srv.url, Connection(srv.url).pair("elena", "Password-Elena-1", "PC Elena")["token"])
    server = srv.notes / "elena"
    local = tmp / "local-elena"
    state, log = {}, []

    def sync(case_insensitive=False):
        e = Engine(local, conn, state, "PC Elena", lambda t, l="info": log.append(t))
        e.case_insensitive = case_insensitive
        e.sync()
        return e

    # --- first connection: both sides already full ------------------------------------------------
    write(server / "Uguale.pdf", b"stesso contenuto")
    write(local / "Uguale.pdf", b"stesso contenuto")
    write(server / "Diverso.pdf", b"versione del server")
    write(local / "Diverso.pdf", b"versione del pc")
    write(server / "Solo server.pdf", b"s")
    write(local / "Solo pc.pdf", b"p")
    write(server / "Tipo" / "dentro.pdf", b"una cartella sul server")
    write(local / "Tipo", b"un file sul pc")
    e = sync()
    e2 = sync()
    copies = sorted(p.name for p in local.glob("Diverso (conflitto PC Elena *).pdf"))
    check(not any("Uguale" in t for t in log), "first connection, same name and content: nothing transferred")
    check((local / "Diverso.pdf").read_bytes() == b"versione del server" and len(copies) == 1
          and (server / copies[0]).read_bytes() == b"versione del pc", "first connection, same name, different content: both kept")
    check((local / "Solo server.pdf").exists() and (server / "Solo pc.pdf").exists(), "first connection: the two sides merged")
    check((local / "Tipo").is_file() and (server / "Tipo").is_dir() and any("Tipo" in w for w in e.waiting + e2.waiting),
          "first connection, file here and folder there: untouched and reported")
    check(not (server / ".cestino").exists() and not (local / ".tapbook-sync" / "cestino").exists(),
          "first connection: nothing deleted on either side")
    (local / "Tipo").unlink()
    sync()

    # --- only the changes from the server ---------------------------------------------------------
    cursor = state["cursor"]
    write(server / "Solo server.pdf", b"cambiato sull'ipad")
    answer = conn.changes(cursor)
    check(answer["full"] is False and list(answer["changes"]) == ["Solo server.pdf"],
          "the server sends only what changed, not the whole list")
    check(conn.changes("altra:5")["full"] is True and conn.changes(None)["full"] is True,
          "unknown cursor (server restarted): the complete list")
    sync()
    check((local / "Solo server.pdf").read_bytes() == b"cambiato sull'ipad", "change applied from the list of changes")
    import threading
    got = []
    t0 = time.time()
    waiter = threading.Thread(target=lambda: got.append(conn.changes(state["cursor"], wait=True)))
    waiter.start()
    time.sleep(1.0)
    write(server / "Arrivato.pdf", b"nuovo")
    waiter.join()
    check(got and "Arrivato.pdf" in got[0]["changes"] and time.time() - t0 < 4,
          "a waiting request answers as soon as something changes")
    sync()

    # --- moved and changed at the same time (identity on disk) ---------------------------------------
    write(local / "Lezione 1.pdf", b"prima versione della lezione")
    sync()
    (local / "Corso").mkdir(exist_ok=True)
    os.replace(local / "Lezione 1.pdf", local / "Corso" / "Lezione 1 rivista.pdf")
    with open(local / "Corso" / "Lezione 1 rivista.pdf", "ab") as fh:
        fh.write(b" + appunti aggiunti")
    old = time.time() - 10
    os.utime(local / "Corso" / "Lezione 1 rivista.pdf", (old, old))
    log.clear()
    sync()
    check((server / "Corso" / "Lezione 1 rivista.pdf").read_bytes() == b"prima versione della lezione + appunti aggiunti"
          and not (server / "Lezione 1.pdf").exists(), "moved and changed: moved on the server, new content uploaded")
    check(any("Spostato sul server" in t for t in log), "moved and changed: recognised as a move")
    kept = list((server / ".cestino").glob("*versione precedente*"))
    check(kept and kept[0].read_bytes() == b"prima versione della lezione", "the replaced version stays in the server trash")

    # --- a whole folder renamed: one step on the server ------------------------------------------------
    for i in range(6):
        write(local / "Analisi" / "Esercizi" / f"es {i}.pdf", f"esercizio {i}")
    sync()
    os.rename(local / "Analisi", local / "Analisi I")
    log.clear()
    sync()
    check(all((server / "Analisi I" / "Esercizi" / f"es {i}.pdf").exists() for i in range(6))
          and not (server / "Analisi").exists(), "folder renamed: renamed on the server")
    check(any("Cartella spostata sul server" in t for t in log) and not any("Inviato" in t for t in log)
          and sum("Spostato" in t for t in log) == 0, "folder renamed: one move, no file transferred again")
    log.clear()
    sync()
    check(not log, "after a folder move everything is aligned")

    # --- names differing only in capitals (as on Windows) ------------------------------------------------
    write(server / "Fisica.pdf", b"fisica")
    write(server / "Chimica.pdf", b"chimica del server")
    sync()
    os.replace(local / "Fisica.pdf", local / "fisica.pdf")       # as if created on Windows with other capitals
    state["base"].pop("Fisica.pdf", None)
    os.replace(local / "Chimica.pdf", local / "chimica.pdf")
    (local / "chimica.pdf").write_bytes(b"chimica del pc")
    os.utime(local / "chimica.pdf", (old, old))
    state["base"].pop("Chimica.pdf", None)
    log.clear()
    sync(case_insensitive=True)
    sync(case_insensitive=True)
    names = sorted(p.name for p in server.iterdir() if p.name.lower().startswith(("fisica", "chimica")))
    check((local / "Fisica.pdf").exists() and not (local / "fisica.pdf").exists() and "fisica.pdf" not in names,
          "capitals, same content: the name of the server is used, no duplicate")
    check((local / "Chimica.pdf").read_bytes() == b"chimica del server"
          and any(n.startswith("chimica (conflitto") for n in names), "capitals, different content: conflict copy, both kept")


def run_watcher(check):
    """The operating system tells about the changes (Linux: inotify)."""
    from app.syncclient.watcher import Watcher
    folder = tmp / "watched"
    folder.mkdir()
    events = []
    w = Watcher(folder, lambda: events.append(time.time()))
    started = w.start()
    check(started, "the system watches the folder")

    def wait_event(action):
        events.clear()
        action()
        for _ in range(40):
            if events:
                return True
            time.sleep(0.05)
        return False
    check(wait_event(lambda: (folder / "a.pdf").write_bytes(b"x")), "watch: new file noticed at once")
    check(wait_event(lambda: (folder / "Nuova").mkdir()), "watch: new folder noticed")
    time.sleep(0.2)
    check(wait_event(lambda: (folder / "Nuova" / "b.pdf").write_bytes(b"y")), "watch: file in a new folder noticed")
    check(wait_event(lambda: os.rename(folder / "a.pdf", folder / "c.pdf")), "watch: rename noticed")
    time.sleep(0.3)   # a rename is two events: the second must not count for the next check
    check(not wait_event(lambda: (folder / ".tapbook-sync").mkdir()), "watch: hidden items (own trash, downloads) ignored")
    w.stop()


def run_open_document(check):
    """A document open in the editor is not deleted or moved by the sync (as
    from the web); a new version uploaded meanwhile reaches the open editor."""
    import pymupdf
    os.environ.update(NOTES_DATA_DIR=str(tmp / "c" / "data"), NOTES_NOTES_ROOT=str(tmp / "c" / "notes"),
                      NOTES_HTTPS="false")
    from app.bootstrap import build_controllers
    from app.config import load_config
    from app.control.sync import Busy
    c = build_controllers(load_config())
    c.auth.create_user("dora", "Password-Dora-1")
    doc = pymupdf.open(); doc.new_page(); data = doc.tobytes()
    (tmp / "c" / "notes" / "dora" / "Lezione.pdf").write_bytes(data)
    opened = c.editing.open("dora", "Lezione.pdf")
    for call, what in ((lambda: c.sync.delete("dora", "Lezione.pdf", h(data)), "delete"),
                       (lambda: c.sync.move("dora", "Lezione.pdf", "Altro.pdf", h(data)), "move")):
        try:
            call(); check(False, what)
        except Busy:
            check((tmp / "c" / "notes" / "dora" / "Lezione.pdf").exists(), f"open document: {what} postponed (423)")
    c.editing.close("dora", opened["session"])
    check(c.sync.delete("dora", "Lezione.pdf", h(data))["ok"], "closed document: deleted")
    c.editing.flush_all()


def sqlite_rows(srv, sql):
    import sqlite3
    conn = sqlite3.connect(srv.dir / "data" / "tapbook.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def run_https(check):
    """A server with the certificate created by TapBook: the client asks to trust
    it once (fingerprint), then verifies it at every request."""
    srv = Server("s2", https=True)
    srv.cli("user", "add", "carla", stdin="Password-Carla-1\nPassword-Carla-1\n")
    srv.start()
    try:
        try:
            Connection(srv.url, cafile=Path(os.devnull)).pair("carla", "Password-Carla-1", "pc"); check(False, "untrusted")
        except api.UntrustedCertificate:
            check(True, "https: unknown certificate not trusted silently")
        pem, fingerprint = api.fetch_untrusted_ca(srv.url)
        ca = (srv.dir / "data" / "tls" / "ca.crt").read_text()
        check(pem.strip() == ca.strip() and len(fingerprint) == 95, "https: the CA offered is the server's, with fingerprint")
        check(api.check_with_ca(srv.url, pem), "https: the server certificate is signed by that CA")
        pin = tmp / "pinned.pem"
        pin.write_text(pem)
        token = Connection(srv.url, cafile=pin).pair("carla", "Password-Carla-1", "pc")["token"]
        check(Connection(srv.url, token, cafile=pin).whoami()["username"] == "carla", "https: works once trusted")
        other = Server("s3", https=True)
        other.start()
        try:
            try:
                Connection(other.url, token, cafile=pin).whoami(); check(False, "other server")
            except api.UntrustedCertificate:
                check(True, "https: another server with another certificate is refused")
        finally:
            other.stop()
    finally:
        srv.stop()


if __name__ == "__main__":
    main()
