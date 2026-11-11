"""TapBook Server on a machine of its own (VPS): sign-up closed, own certificate,
reverse proxy, terminal commands, background service."""
import datetime as dt
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from _common import Checks, ROOT

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

tmp = Path(tempfile.mkdtemp())
os.environ.update(NOTES_DATA_DIR=str(tmp / "data"), NOTES_NOTES_ROOT=str(tmp / "notes"), NOTES_HTTPS="false")
from app.bootstrap import build_controllers  # noqa: E402
from app.config import load_config  # noqa: E402
from app.view.web import create_app  # noqa: E402


def make_app(**env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        cfg = load_config()
    finally:
        for k, v in old.items():
            os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)
    c = build_controllers(cfg)
    app = create_app(cfg, c.auth, c.library, c.navigation, c.editing, c.account, c.diagnostics, c.sync)
    app.testing = True
    return app, c, cfg


def self_signed(folder: Path, name: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1"))]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (folder / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    return folder / "cert.pem", folder / "key.pem", cert.serial_number


def login(client, user, pw, **kw):
    page = client.get("/login", **kw).get_data(as_text=True)
    token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    return client.post("/login", data={"username": user, "password": pw, "csrf": token}, **kw)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    check = Checks("test_server_mode")

    # --- Sign-up closed: not even the first account from the web ----------------------
    app, c, _ = make_app(NOTES_ALLOW_REGISTRATION="false", NOTES_DATA_DIR=str(tmp / "d1"),
                         NOTES_NOTES_ROOT=str(tmp / "n1"))
    cl = app.test_client()
    r = cl.get("/login")
    check(r.status_code == 200 and "tapbook user add" in r.get_data(as_text=True), "closed, no users: login explains the terminal")
    check(cl.get("/register").status_code == 404, "closed, no users: GET /register 404")
    check(cl.post("/register", data={"username": "intruso", "password": "Password-Lunga-1",
                                     "confirm": "Password-Lunga-1"}).status_code == 404, "closed: POST /register 404")
    check(c.auth.store.count_users() == 0, "closed: no account created from the web")
    c.auth.create_user("anna", "Password-Anna-1")
    page = cl.get("/login").get_data(as_text=True)
    check("Registrati" not in page and "tapbook user add" not in page, "closed, with users: no sign-up link")
    check(login(cl, "anna", "Password-Anna-1").status_code == 302, "closed: terminal user logs in")

    # --- Sign-up open: first start as before --------------------------------------------
    app2, _, _ = make_app(NOTES_ALLOW_REGISTRATION="true", NOTES_DATA_DIR=str(tmp / "d2"),
                          NOTES_NOTES_ROOT=str(tmp / "n2"))
    r = app2.test_client().get("/login")
    check(r.status_code == 302 and "/register" in r.headers["Location"], "open, no users: first account from the web")

    # --- Proxy headers: ignored without behind_proxy -------------------------------------
    app3, c3, _ = make_app(NOTES_DATA_DIR=str(tmp / "d3"), NOTES_NOTES_ROOT=str(tmp / "n3"))
    c3.auth.create_user("carla", "Password-Carla-1")
    atk = app3.test_client()
    for i in range(12):        # a different fake address at every attempt
        login(atk, "carla", f"sbagliata{i}", headers={"X-Forwarded-For": f"203.0.113.{i}"},
              environ_base={"REMOTE_ADDR": "198.51.100.7"})
    r = login(atk, "carla", "Password-Carla-1", headers={"X-Forwarded-For": "203.0.113.99"},
              environ_base={"REMOTE_ADDR": "198.51.100.7"})
    check(r.status_code != 302, "no proxy: forged X-Forwarded-For does not dodge the limit")
    r = app3.test_client().get("/login", headers={"X-Forwarded-Proto": "https"})
    check("Secure" not in r.headers.get("Set-Cookie", ""), "no proxy: http cookie (https = false)")

    # --- Behind a proxy: device address and https from the proxy -------------------------
    app4, c4, _ = make_app(NOTES_BEHIND_PROXY="true", NOTES_DATA_DIR=str(tmp / "d4"), NOTES_NOTES_ROOT=str(tmp / "n4"))
    c4.auth.create_user("dario", "Password-Dario-1")
    px = {"environ_base": {"REMOTE_ADDR": "127.0.0.1"}}
    bad = app4.test_client()
    for i in range(12):
        login(bad, "nessuno", f"x{i}", headers={"X-Forwarded-For": "203.0.113.5", "X-Forwarded-Proto": "https"}, **px)
    good = app4.test_client()
    r = login(good, "dario", "Password-Dario-1", headers={"X-Forwarded-For": "203.0.113.6", "X-Forwarded-Proto": "https"}, **px)
    check(r.status_code == 302, "proxy: the limit hits the attacker's address, not everybody behind the proxy")
    check("Secure" in r.headers.get("Set-Cookie", ""), "proxy: Secure cookie")
    r = login(bad, "dario", "Password-Dario-1", headers={"X-Forwarded-For": "203.0.113.5", "X-Forwarded-Proto": "https"}, **px)
    check(r.status_code != 302, "proxy: the attacker's address stays blocked")
    check(app4.test_client().get("/certificato").status_code == 404, "proxy: no local certificate offered")
    plain = app4.test_client()            # proxy in plain HTTP (e.g. inside Tailscale): no X-Forwarded-Proto https
    r = login(plain, "dario", "Password-Dario-1", headers={"X-Forwarded-For": "203.0.113.7"}, **px)
    check(r.status_code == 302 and "Secure" not in r.headers.get("Set-Cookie", ""),
          "proxy over http: cookie without Secure, login works")
    check(plain.get("/", headers={"X-Forwarded-For": "203.0.113.7"}, **px).status_code == 200,
          "proxy over http: the session is kept")

    # --- Failed logins in the log, without forged lines -----------------------------------
    records = []
    handler = logging.Handler(); handler.emit = records.append
    logging.getLogger("tapbook.auth").addHandler(handler)
    logging.getLogger("tapbook.auth").setLevel(logging.INFO)
    login(app3.test_client(), "x\nAccesso riuscito", "y", environ_base={"REMOTE_ADDR": "192.0.2.1"})
    text = "\n".join(r.getMessage() for r in records)
    check("192.0.2.1" in text and "\n" not in text, "failed login logged on one line with the address")

    # --- Own certificate ------------------------------------------------------------------
    from app.system.tls import RedirectingSSLAdapter, own_certificate
    cert, key, serial1 = self_signed(tmp / "own", "tapbook.example")
    check(own_certificate(cert, key)["cert"] == cert, "own certificate accepted")
    for args, what in (((tmp / "missing.pem", key), "missing"), ((cert, None), "key not given")):
        try:
            own_certificate(*args); check(False, what)
        except ValueError:
            check(True, f"own certificate {what}: clear error")
    other_cert, other_key, _ = self_signed(tmp / "other", "altro")
    try:
        own_certificate(cert, other_key); check(False, "mismatch")
    except ValueError:
        check(True, "own certificate with the wrong key: clear error")

    # Real HTTPS server with the own certificate (subprocess, as installed)
    port = free_port()
    env = dict(os.environ, NOTES_DATA_DIR=str(tmp / "d5"), NOTES_NOTES_ROOT=str(tmp / "n5"), NOTES_HTTPS="true",
               NOTES_TLS_CERT=str(cert), NOTES_TLS_KEY=str(key), NOTES_HOST="127.0.0.1", NOTES_PORT=str(port),
               NOTES_FIREWALL="off")
    proc = subprocess.Popen([sys.executable, "-m", "app", "serve", "--service"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        ctx = ssl.create_default_context(cafile=str(cert))
        served = None
        for _ in range(100):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=2) as s, \
                        ctx.wrap_socket(s, server_hostname="localhost") as t:
                    served = x509.load_der_x509_certificate(t.getpeercert(binary_form=True)).serial_number
                    t.sendall(b"GET /certificato HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                    reply = t.recv(200).decode("latin-1")
                break
            except OSError:
                time.sleep(0.1)
        check(served == serial1, "HTTPS server uses the own certificate")
        check(" 404 " in reply.split("\r\n")[0], "own certificate: no local CA offered")
        check(not (tmp / "d5" / "tls").exists(), "own certificate: no local CA created")
    finally:
        proc.terminate()
        out = proc.communicate(timeout=30)[0]
    check(proc.returncode == 0 and "Server fermato" in out, "service stops cleanly on SIGTERM")

    # Wrong own certificate: the server does not start, with a clear message
    env.update(NOTES_TLS_KEY=str(other_key))
    r = subprocess.run([sys.executable, "-m", "app", "serve"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    check(r.returncode == 1 and "non validi" in r.stdout + r.stderr, "wrong own certificate: clear error, no start")

    # Renewed certificate picked up without restarting
    from cheroot import wsgi
    adapter = RedirectingSSLAdapter(str(cert), str(key), 0)
    adapter.RELOAD_CHECK = 0
    srv = wsgi.Server(("127.0.0.1", 0), lambda e, s: (s("200 OK", []), [b"ok"])[1], numthreads=2)
    srv.ssl_adapter = adapter
    srv.prepare()
    threading.Thread(target=srv.serve, daemon=True).start()
    rport = srv.bind_addr[1]

    def served_serial():
        nctx = ssl.create_default_context(); nctx.check_hostname = False; nctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection(("127.0.0.1", rport), timeout=5) as s, nctx.wrap_socket(s) as t:
            return x509.load_der_x509_certificate(t.getpeercert(binary_form=True)).serial_number
    check(served_serial() == serial1, "reload: first certificate")
    time.sleep(0.05)
    _, _, serial2 = self_signed(tmp / "own", "tapbook.example")      # renewal writes the same files
    check(served_serial() == serial2, "reload: renewed certificate used without restart")
    srv.stop()

    # --- Certificate created by TapBook: every address, VPN included ------------------------
    from app.system.network import _interface_addresses, all_addresses
    from app.system.tls import ensure_certificates
    check(_interface_addresses() <= set(all_addresses()) | {"127.0.0.1"}, "every interface address goes into the certificate")
    tls_dir = tmp / "tlsdata"
    first = ensure_certificates(tls_dir, ["10.0.0.5"])
    ca_before = (tls_dir / "tls" / "ca.crt").read_bytes()
    check(not ensure_certificates(tls_dir, ["10.0.0.5"])["renewed"], "same addresses: certificate kept")
    later = ensure_certificates(tls_dir, ["10.0.0.5", "100.82.69.126"])     # e.g. Tailscale started later
    san = x509.load_pem_x509_certificate(later["cert"].read_bytes()).extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value
    ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    check(later["renewed"] and {"10.0.0.5", "100.82.69.126"} <= ips, "a new address renews the certificate")
    check((tls_dir / "tls" / "ca.crt").read_bytes() == ca_before and first["new_ca"] and not later["new_ca"],
          "the certificate authority stays the same (devices keep trusting it)")

    # --- Terminal commands ----------------------------------------------------------------
    w = tmp / "cli"
    ini = w / "config.ini"
    w.mkdir()
    ini.write_text(f"[server]\nnotes_root = {w / 'Note'}\ndata_dir = {w / 'data'}\nport = 8123\n"
                   "allow_registration = false\nbehind_proxy = true\n", encoding="utf-8")
    cenv = {k: v for k, v in os.environ.items() if not k.startswith("NOTES_")}
    cenv["NOTES_CONFIG"] = str(ini)

    def cli(*args, stdin=None):
        return subprocess.run([sys.executable, "-m", "app", *args], cwd=ROOT, env=cenv, input=stdin,
                              capture_output=True, text=True, timeout=60)
    r = cli("user", "add", "elena", stdin="Password-Elena-1\nPassword-Elena-1\n")
    check(r.returncode == 0, "tapbook user add")
    check("elena" in cli("user", "list").stdout and "elena" in cli("list-users").stdout, "user list (new and old name)")
    r = cli("user", "passwd", "elena", stdin="Password-Elena-2\nPassword-Elena-2\n")
    check(r.returncode == 0, "tapbook user passwd")
    check(cli("user", "add", "elena", stdin="Password-Elena-3\nPassword-Elena-3\n").returncode != 0, "duplicate user refused")
    st = cli("status").stdout
    check("chiusa" in st and "proxy" in st and "8123" in st and "elena" in st, "tapbook status")
    show = cli("config", "show").stdout
    check(re.search(r"behind_proxy\s+= true\s+\[config.ini\]", show) and re.search(r"https\s+= true\s+\[predefinito\]", show),
          "config show: value and origin")
    export = cli("config", "export").stdout
    check("secret" not in export.lower() and "BEGIN" not in export, "config export: no secrets")
    ini2 = w / "copy.ini"
    ini2.write_text(export, encoding="utf-8")
    cenv2 = dict(cenv, NOTES_CONFIG=str(ini2))
    a = subprocess.run([sys.executable, "-c", "from app.config import load_config as l; print(l())"], cwd=ROOT,
                       env=cenv, capture_output=True, text=True).stdout
    b = subprocess.run([sys.executable, "-c", "from app.config import load_config as l; print(l())"], cwd=ROOT,
                       env=cenv2, capture_output=True, text=True).stdout
    check(a == b and a, "config export: the copy gives the same settings")
    r = cli("user", "del", "elena")
    check(r.returncode == 0 and (w / "Note" / "elena").is_dir(), "user del keeps the folder")

    # --- Background service unit ------------------------------------------------------------
    from app.system import service
    unit = service.UNIT.format(project=ROOT, python="/x/.venv/bin/python", stop=service.STOP_TIMEOUT)
    check("ExecStart=/x/.venv/bin/python -m app serve --service" in unit and "Restart=on-failure" in unit,
          "service unit: command and restart")
    check("TimeoutStopSec=150" in unit, "service unit: time to save before being stopped")
    check(str(service.unit_path()).endswith("systemd/user/tapbook.service"), "user service, not system-wide")
    check(service.state() in ("not-installed", "active", "inactive", "failed", "activating", "unknown"), "service state")
    check.done()


if __name__ == "__main__":
    main()
