"""Security tests on the real web app (Flask test client, temporary data)."""
import io
import json
import os
import random
import re
import tempfile
from pathlib import Path
from _common import Checks, ROOT  # noqa: F401  (adds the project to the path)

tmp = Path(tempfile.mkdtemp())
os.environ.update(NOTES_DATA_DIR=str(tmp / "data"), NOTES_NOTES_ROOT=str(tmp / "notes"), NOTES_HTTPS="false")
import pymupdf  # noqa: E402
from app.bootstrap import build_controllers  # noqa: E402
from app.config import load_config  # noqa: E402
from app.view.web import create_app  # noqa: E402

H = {"X-Requested-With": "notes-app"}


def main():
    check = Checks("test_security")
    cfg = load_config(); c = build_controllers(cfg)
    app = create_app(cfg, c.auth, c.library, c.navigation, c.editing, c.account, c.diagnostics)
    app.testing = True
    for u, p in (("anna", "Password-Anna-1"), ("bruno", "Password-Bruno-1"), ("carla", "Password-Carla-1")):
        c.auth.create_user(u, p)
    pdf = pymupdf.open(); [pdf.new_page().insert_text((72, 72), f"pagina {i}") for i in range(3)]
    pdf_bytes = pdf.tobytes()

    def login(client, user, pw, ip="10.0.0.1"):
        page = client.get("/login", environ_base={"REMOTE_ADDR": ip}).get_data(as_text=True)
        token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
        return client.post("/login", data={"username": user, "password": pw, "csrf": token}, environ_base={"REMOTE_ADDR": ip})

    def post(client, url, body=None, headers=H):
        return client.post(url, data=json.dumps(body if body is not None else {}), content_type="application/json", headers=headers)

    # --- no login, CSRF, brute force, cookies, redirects --------------------------------
    anon = app.test_client()
    posts = [r.rule for r in app.url_map.iter_rules() if "POST" in r.methods and r.rule.startswith("/api/")]
    for url in posts:
        check(post(anon, url).status_code == 401, f"no login: POST {url}")
    for url in ["/api/edit/listen", "/api/edit/background?id=" + "0" * 32, "/api/doc/raw?path=a.pdf", "/api/account/avatar", "/api/edit/picture", "/api/layout/preview"]:
        check(anon.get(url).status_code in (401, 302), f"no login: GET {url}")
    a = app.test_client()
    check(a.post("/login", data={"username": "anna", "password": "Password-Anna-1"}).status_code != 302, "login without CSRF token refused")
    r = login(a, "anna", "Password-Anna-1")
    check(r.status_code == 302, "login")
    ck = r.headers.get("Set-Cookie", "")
    check("HttpOnly" in ck and "SameSite=Strict" in ck, "cookie HttpOnly, SameSite=Strict")
    for url in posts:
        check(post(a, url, headers={}).status_code == 403, f"CSRF: POST {url} without header")
    atk = app.test_client()
    for i in range(12):
        login(atk, "carla", f"sbagliata{i}", ip="10.9.9.9")
    check(login(atk, "carla", "Password-Carla-1", ip="10.9.9.9").status_code != 302, "brute force blocked")
    bc = app.test_client()
    pg = bc.get("/login?next=//evil.example/x", environ_base={"REMOTE_ADDR": "10.7.7.7"}).get_data(as_text=True)
    tok = re.search(r'name="csrf" value="([^"]+)"', pg).group(1)
    r = bc.post("/login?next=//evil.example/x", data={"username": "anna", "password": "Password-Anna-1", "csrf": tok}, environ_base={"REMOTE_ADDR": "10.7.7.7"})
    check("evil.example" not in r.headers.get("Location", ""), "no open redirect")

    # --- isolation ----------------------------------------------------------------------
    b = app.test_client(); login(b, "bruno", "Password-Bruno-1", ip="10.0.0.2")
    check(a.post("/api/library/upload", data={"path": "", "file": (io.BytesIO(pdf_bytes), "segreto.pdf")}, headers=H,
                 content_type="multipart/form-data").status_code == 200, "anna imports a PDF")
    oa = post(a, "/api/open", {"path": "segreto.pdf", "device": "tabanna00000000000000000"}).get_json()
    sid_a, pid_a = oa["session"], oa["pages"][0]["id"]
    bg_a = oa["pages"][0]["bg"]["id"]
    r = a.get(f"/api/edit/background?session={sid_a}&id={bg_a}")
    check(r.status_code == 200 and r.data.startswith(b"%PDF") and r.headers.get("Cache-Control") == "no-store", "anna downloads her background")
    for bad in ["../../etc/passwd", "0" * 32, "", bg_a + "x", "%2e%2e%2fmanifest"]:
        check(a.get(f"/api/edit/background?session={sid_a}&id={bad}").status_code == 404, f"background id refused: {bad!r}")
    post(a, "/api/edit/op", {"session": sid_a, "op": {"type": "addStroke", "page": pid_a, "stroke": {"id": "s1", "tool": "pen", "color": "#000000", "width": 1, "points": [[10, 10, .5], [50, 50, .5]]}}})
    for path in ["../anna/segreto.pdf", "/etc/passwd", "..\\anna\\segreto.pdf", "segreto.pdf/../../anna/segreto.pdf", "%2e%2e/anna/segreto.pdf", ".cestino/x"]:
        check(post(b, "/api/open", {"path": path}).status_code in (400, 404), f"bruno does not open {path!r}")
    check(b.get("/api/doc/raw?path=../anna/segreto.pdf").status_code in (400, 404), "bruno does not download anna's PDF")
    check(post(b, "/api/edit/op", {"session": sid_a, "op": {"type": "undo"}}).status_code == 410, "bruno cannot use anna's session")
    check(post(b, "/api/edit/close", {"session": sid_a}).status_code == 410, "bruno cannot close anna's session")
    check(b.get(f"/api/edit/listen?session={sid_a}").status_code == 410, "bruno cannot listen to anna")
    check(b.get(f"/api/edit/background?session={sid_a}&id={bg_a}").status_code == 410, "bruno cannot use anna's session for backgrounds")
    b.post("/api/library/upload", data={"path": "", "file": (io.BytesIO(pdf_bytes), "suo.pdf")}, headers=H, content_type="multipart/form-data")
    ob = post(b, "/api/open", {"path": "suo.pdf", "device": "tabanna00000000000000000"}).get_json()
    check(b.get(f"/api/edit/background?session={ob['session']}&id={bg_a}").status_code == 404, "bruno cannot get anna's background with his own session")
    check(post(a, "/api/edit/op", {"session": sid_a, "op": {"type": "undo"}}).status_code == 200, "same tab id from another user does not touch anna")
    post(a, "/api/edit/op", {"session": sid_a, "op": {"type": "redo"}})
    for dev in ["x", "../../a", "a" * 200, 12345, {"a": 1}, None, "<script>"]:
        check(post(a, "/api/open", {"path": "segreto.pdf", "device": dev}).status_code == 200, f"invalid tab id ignored: {str(dev)[:12]!r}")
    sid_b, pid_b = ob["session"], ob["pages"][0]["id"]
    r = post(b, "/api/edit/op", {"session": sid_b, "op": {"type": "erase", "page": pid_b, "path": [[10, 10]], "radius": 7, "ids": ["s1"]}})
    check(r.status_code == 200 and not [e for e in r.get_json()["events"] if e["event"] == "strokeRemoved"], "bruno cannot erase anna's strokes by naming them")
    r = post(b, "/api/edit/op", {"session": sid_b, "op": {"type": "erase", "page": pid_a, "path": [[10, 10]], "radius": 7, "ids": ["s1"]}})
    check(r.status_code == 200 and not [e for e in r.get_json()["events"] if e["event"] == "strokeRemoved"], "eraser on another document's page: ignored")
    check(any(s["id"] == "s1" for s in c.editing.clients[sid_a].room.doc.page(pid_a)["strokes"]), "anna's stroke still there")
    r = post(a, "/api/edit/op", {"session": sid_a, "op": {"type": "erase", "page": pid_a, "path": [[300, 300]], "radius": 7, "ids": ["s1"] * 6000}})
    check(r.status_code == 200 and not [e for e in r.get_json()["events"] if e["event"] == "strokeRemoved"], "huge id list ignored")
    r = post(a, "/api/edit/op", {"session": sid_a, "op": {"type": "addText", "page": pid_a, "x": 50, "y": 50, "size": 1e9}})
    t = [e for e in r.get_json()["events"] if e["event"] == "textAdded"][0]["text"]
    check(t["size"] == 200, "text size limited")
    for bad in [{"w": "1"}, {"h": float("inf")}, {"size": None}, {"color": "javascript:1"}, {"w": [1]}]:
        r = a.post("/api/edit/op", data=json.dumps({"session": sid_a, "op": {"type": "changeText", "page": pid_a, "id": t["id"], **bad}}, allow_nan=True), content_type="application/json", headers=H)
        check(r.status_code == 400, f"invalid changeText refused: {bad}")
    for name in ["../x", "a/b", "con", "nul.txt", "x" * 300, "a\x00b", ".nascosto", "  ", "a:b"]:
        check(post(a, "/api/library/newdoc", {"path": "", "name": name}).status_code == 400, f"invalid name refused: {name[:12]!r}")
    check(a.post("/api/library/upload", data={"path": "", "file": (io.BytesIO(b"<html><script>alert(1)</script>"), "x.pdf")}, headers=H, content_type="multipart/form-data").status_code == 400, "not a PDF refused")
    check(a.post("/api/library/upload", data={"path": "../bruno", "file": (io.BytesIO(pdf_bytes), "x.pdf")}, headers=H, content_type="multipart/form-data").status_code in (400, 404), "upload into another user's folder refused")
    check(a.post("/api/edit/image", data={"session": sid_a, "page": pid_a, "x": "10", "y": "10", "w": "100", "file": (io.BytesIO(b"GIF89a not really"), "x.png")}, headers=H, content_type="multipart/form-data").status_code == 400, "invalid image refused")
    check(a.post("/api/edit/op", data="x" * (26 * 1024 * 1024), content_type="application/json", headers=H).status_code == 413, "JSON too large")

    # --- client errors log ---------------------------------------------------------------
    log = tmp / "data" / "client-errors.log"
    check(post(a, "/api/client-error", "non un oggetto").status_code == 400, "non-object report refused")
    check(post(a, "/api/client-error", {"message": "z" * 20000}).status_code == 413, "report too large")
    for i in range(15):
        post(a, "/api/client-error", {"message": f"riga {i}\n2026-01-01T00:00:00  admin  falso", "page": "\x1b[31mrosso"})
    lines = log.read_text().splitlines()
    check(len(lines) == 10, "at most 10 reports per minute")
    check(all(l.split("  ")[1] == "anna" for l in lines), "no injected lines")
    check("\x1b" not in log.read_text(), "control characters removed")
    check(oct(log.stat().st_mode & 0o777) == "0o600", "log readable only by the owner")
    bgdir = tmp / "data" / "backgrounds"
    check(all(oct(p.stat().st_mode & 0o077) == "0o0" for p in [tmp / "data"]), "data folder private")

    # --- headers ---------------------------------------------------------------------------
    r = a.get("/")
    csp = r.headers.get("Content-Security-Policy", "")
    check("script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp, "strict CSP")
    check(r.headers.get("X-Content-Type-Options") == "nosniff", "nosniff")
    check(post(a, "/api/open", {"path": ""}).headers.get("Cache-Control") == "no-store", "JSON not cached")

    # --- fuzz of the editor operations -----------------------------------------------------
    rnd = random.Random(7)
    junk = [None, True, -1, 1e308, "x", "", [], {}, [1, 2], {"a": []}, "../../x", "<img src=x>", 10 ** 30, -0.0]
    types = ["addStroke", "erase", "addText", "editText", "moveText", "changeText", "removeText", "discardText", "changeImage",
             "removeImage", "addPage", "removePage", "setLayout", "select", "recognizeShape", "moveSelection",
             "recolorSelection", "removeSelection", "duplicateSelection", "undo", "redo", "__init__", "_save", "nonEsiste"]
    codes = {}
    for i in range(1500):
        op = {"type": rnd.choice(types + junk)}
        for key in ["page", "id", "x", "y", "w", "h", "size", "color", "text", "path", "points", "radius", "ids", "stroke", "polygon", "dx", "dy", "layout", "after", "commit", "tolerance"]:
            if rnd.random() < 0.4:
                op[key] = rnd.choice(junk + [pid_a, t["id"], [[1, 2]], [[1, 2, 3]] * 3])
        r = post(a, "/api/edit/op", {"session": sid_a, "op": op})
        codes[r.status_code] = codes.get(r.status_code, 0) + 1
    check(500 not in codes, f"fuzz: no error 500 ({codes})")
    check(post(a, "/api/edit/op", {"session": sid_a, "op": {"type": "undo"}}).status_code == 200, "editor still working after fuzz")
    c.editing.flush_all()
    check.done()


if __name__ == "__main__":
    main()
