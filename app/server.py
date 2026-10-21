"""Web server: listening, HTTPS, firewall, orderly shutdown.

Same on Linux and Windows; the system-specific parts live in app/system
(certificates, network addresses, firewall).
"""
import errno
import signal

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
LOCAL_ONLY = ("127.0.0.1", "localhost", "::1")


def _make_server(config: Config, c: Controllers, host: str, port: int):
    # VIEW: the meeting point between the iPad browser and the controllers.
    app = create_app(config, c.auth, c.library, c.navigation, c.editing, c.account)
    server = wsgi.Server((host, port), app, numthreads=THREADS, server_name="TapBook", timeout=TIMEOUT)
    if config.https:
        from .system.tls import REDIRECTED, RedirectingSSLAdapter, ensure_certificates
        tls = ensure_certificates(config.data_dir, all_addresses())
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


def _startup_info(config: Config, c: Controllers, host: str, port: int) -> dict:
    scheme = "https" if config.https else "http"
    ipad = [f"{scheme}://{a}:{port}" for a in local_addresses()] if host in ("0.0.0.0", "::") else []
    return {"notes_root": str(config.notes_root), "registration": config.allow_registration,
            "first_user": c.auth.needs_first_user(), "local_url": f"{scheme}://127.0.0.1:{port}",
            "ipad_urls": ipad, "https": config.https, "port": port}


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
        reporter=None, password: str | None = None):
    """Starts the server and keeps it running until Ctrl+C (or until the control
    panel asks it to stop). `reporter` writes the messages (terminal or JSON);
    `password` is the administrator password given by the panel for the firewall."""
    reporter = reporter or TerminalReporter()
    host = host or config.host
    port = port or config.port
    server = _make_server(config, c, host, port)
    reporter.started(_startup_info(config, c, host, port))
    _stop_on_signals()
    guard = FirewallGuard(port, config.firewall, config.data_dir, say=reporter.say, password=password)
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
        server.stop()
        c.editing.flush_all()               # save documents still open before exiting
