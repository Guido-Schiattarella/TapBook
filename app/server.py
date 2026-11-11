"""Web server: listening, HTTPS, firewall, orderly shutdown.

Same on Linux and Windows; the system-specific parts live in app/system
(certificates, network addresses, firewall).
"""
import errno
import logging
import signal
import threading
import time

from cheroot import wsgi

from .bootstrap import Controllers
from .config import Config
from .reporting import TerminalReporter, level_of
from .system.firewall import FirewallGuard
from .system.network import all_addresses, local_addresses
from .view.web import create_app

# timeout: how long to wait for a device that neither sends nor receives. 60 seconds
# (not 10) because an iPad on slow Wi-Fi, while downloading or uploading a large
# PDF, can pause for a few seconds without the connection being lost.
TIMEOUT = 60
THREADS = 32
ADDRESS_CHECK = 60      # seconds between checks of the computer's addresses (certificate)
LOCAL_ONLY = ("127.0.0.1", "localhost", "::1")


def _make_server(config: Config, c: Controllers, host: str, port: int):
    # VIEW: the meeting point between the iPad browser and the controllers.
    app = create_app(config, c.auth, c.library, c.navigation, c.editing, c.account, c.diagnostics, c.sync)
    server = wsgi.Server((host, port), app, numthreads=THREADS, server_name="TapBook", timeout=TIMEOUT)
    if config.https:
        from .system.tls import REDIRECTED, RedirectingSSLAdapter, ensure_certificates, own_certificate
        if config.tls_cert or config.tls_key:
            tls = own_certificate(config.tls_cert, config.tls_key)
        else:
            tls = ensure_certificates(config.data_dir, all_addresses())
            _follow_addresses(config.data_dir)
        # Anyone still opening the http:// address is sent to the same page over https://
        server.ssl_adapter = RedirectingSSLAdapter(str(tls["cert"]), str(tls["key"]), port)
        default_log = server.error_log

        def error_log(msg="", *args, **kwargs):
            # Connections closed by the device and redirects are normal: no noise.
            if REDIRECTED in msg or "peer dropped the TLS connection" in msg:
                return
            default_log(msg, *args, **kwargs)
        server.error_log = error_log
    return server


def _follow_addresses(data_dir):
    """An address that appears later (a VPN such as Tailscale started after
    TapBook, a new network) gets into the certificate within a minute: the
    certificate is renewed on disk and the server picks it up by itself (see
    RedirectingSSLAdapter). The certificate authority stays the same, so the
    devices that trust it keep trusting it."""
    from .system.tls import ensure_certificates

    def loop():
        while True:
            time.sleep(ADDRESS_CHECK)
            try:
                ensure_certificates(data_dir, all_addresses())
            except Exception:
                pass                  # tried again at the next check
    threading.Thread(target=loop, daemon=True, name="indirizzi").start()


def _startup_info(config: Config, c: Controllers, host: str, port: int) -> dict:
    scheme = "https" if config.https else "http"
    ipad = [f"{scheme}://{a}:{port}" for a in local_addresses()] if host in ("0.0.0.0", "::") else []
    return {"notes_root": str(config.notes_root), "registration": config.allow_registration,
            "first_user": c.auth.needs_first_user(), "local_url": f"{scheme}://127.0.0.1:{port}",
            "ipad_urls": ipad, "https": config.https, "port": port,
            "own_certificate": bool(config.tls_cert), "behind_proxy": config.behind_proxy}


def _stop_on_signals():
    """systemctl stop / kill (SIGTERM) and, on Windows, closing the window or
    Ctrl+Break (SIGBREAK) become a normal exit: the finally block closes the
    firewall port and saves the documents."""
    def stop(*_):
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)


def run(config: Config, c: Controllers, host: str | None = None, port: int | None = None,
        reporter=None, password: str | None = None, service: bool = False):
    """Starts the server and keeps it running until Ctrl+C (or until the control
    panel asks it to stop). `reporter` writes the messages (terminal or JSON);
    `password` is the administrator password given by the panel for the firewall;
    `service`: started by systemd (app/system/service.py), with nobody to type it."""
    reporter = reporter or TerminalReporter()
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    host = host or config.host
    port = port or config.port
    try:
        server = _make_server(config, c, host, port)
    except ValueError as e:             # own certificate missing or not valid
        reporter.say(f"ATTENZIONE: {e}", "error")
        raise SystemExit(1)
    reporter.started(_startup_info(config, c, host, port))
    if config.behind_proxy and host not in LOCAL_ONLY:
        reporter.say("ATTENZIONE: behind_proxy = true ma il server accetta connessioni da tutta la rete: chi "
                     "scavalca il proxy può fingere un altro indirizzo. Metti host = 127.0.0.1.", "warn")
    _stop_on_signals()
    firewall = config.firewall
    if service and firewall != "off":
        # Nobody can type the administrator password for a service: the port is
        # left to whoever manages the machine (or to a VPN, with no port open).
        reporter.say("ATTENZIONE: avviato come servizio, la porta non viene aperta nel firewall: aprila tu "
                     f"(porta {port}) oppure usa una VPN. Per non vedere questo avviso: firewall = off.", "warn")
        firewall = "off"
    guard = FirewallGuard(port, firewall, config.data_dir, say=reporter.say, password=password)
    try:
        if host in LOCAL_ONLY:
            server.prepare()                # reachable from this computer only: no firewall needed
        else:
            for line in guard.open(server.prepare):
                reporter.say(line, level_of(line))
        reporter.ready()
        server.serve()
    except KeyboardInterrupt:
        reporter.stopped()
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 10048) or "already in use" in str(e):
            reporter.say(f"ATTENZIONE: la porta {port} è già in uso: forse il server è già acceso (in un'altra "
                         "finestra o nel terminale), oppure la usa un altro programma.", "error")
        else:
            reporter.say(f"ATTENZIONE: impossibile avviare il server: {e}", "error")
        raise SystemExit(1)
    finally:
        guard.close()                       # the port is closed first
        c.sync.shutdown()                   # TapBook Sync requests waiting for changes answer now
        server.stop()
        c.editing.flush_all()               # save documents still open before exiting
