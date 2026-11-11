"""Texts of the terminal commands that describe the installation:
`tapbook status`, `tapbook config show` and `tapbook config export`.

They only read: the settings (config.py), the users (through AuthController)
and the background service (system/service.py).
"""
import os
import socket

from . import __version__
from .config import DEFAULTS, PROJECT_DIR, Config, config_path, raw_values

SOURCES = {"ini": "config.ini", "env": "variabile d'ambiente", "default": "predefinito"}
# Default values written in a form that works on another computer too
# (the real defaults are absolute paths of this one).
PORTABLE = {"notes_root": "~/Note", "data_dir": "./instance"}


def config_show() -> str:
    values = raw_values()
    width = max(map(len, values))
    lines = [f"File: {config_path()}" + ("" if config_path().is_file() else "  (non esiste: valori predefiniti)"), ""]
    for key, (value, source) in values.items():
        origin = SOURCES[source] + (f" NOTES_{key.upper()}" if source == "env" else "")
        lines.append(f"  {key:<{width}} = {value.strip() or '(vuoto)'}   [{origin}]")
    lines += ["", "La chiave delle sessioni e i certificati non sono impostazioni: restano in data_dir "
              "e non si copiano su un altro server."]
    return "\n".join(lines) + "\n"


def config_export() -> str:
    """A complete config.ini with the values in use, ready to copy to another server."""
    lines = [f"; TapBook {__version__}: configuration exported from {PROJECT_DIR}",
             "; Copy it to the TapBook folder of the other server as config.ini",
             "; (on Linux: ~/.local/share/tapbook/config.ini) and restart TapBook.",
             "; See config.example.ini for what each value means.", "", "[server]"]
    for key, (value, source) in raw_values().items():
        if source == "default":
            value = PORTABLE.get(key, DEFAULTS[key])
        lines.append(f"{key} = {value.strip()}")
    return "\n".join(lines) + "\n"


def _listening(host: str, port: int) -> bool:
    target = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with socket.create_connection((target, port), timeout=2):
            return True
    except OSError:
        return False


def status(config: Config) -> str:
    from .bootstrap import build_auth
    from .system import service
    users = build_auth(config).list_users()
    if config.behind_proxy:
        https = "gestito dal proxy davanti (behind_proxy = true)"
    elif not config.https:
        https = "disattivato (http)"
    elif config.tls_cert:
        https = f"certificato proprio ({config.tls_cert})"
    else:
        https = "certificato creato da TapBook (da installare su ogni dispositivo)"
    fingerprint = None
    ca = config.data_dir / "tls" / "ca.crt"
    if config.https and not config.tls_cert and not config.behind_proxy and ca.is_file():
        import hashlib
        import ssl
        digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(ca.read_text("ascii"))).hexdigest().upper()
        fingerprint = ":".join(digest[i:i + 2] for i in range(0, 64, 2))
    covers = None
    crt = config.data_dir / "tls" / "server.crt"
    if fingerprint and crt.is_file():
        from cryptography import x509
        san = x509.load_pem_x509_certificate(crt.read_bytes()).extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
        covers = ", ".join(sorted(str(ip) for ip in san.get_values_for_type(x509.IPAddress)
                                  if str(ip) != "127.0.0.1"))
    state = service.state()
    services = {"active": "attivo", "inactive": "fermo", "failed": "fermato per un errore (tapbook logs)",
                "activating": "in avvio", "not-installed": "non installato"}
    rows = [
        ("Versione", __version__),
        ("Cartella", str(PROJECT_DIR)),
        ("Impostazioni", str(config_path()) if config_path().is_file() else "valori predefiniti (nessun config.ini)"),
        ("Documenti", str(config.notes_root)),
        ("Dati interni", str(config.data_dir)),
        ("Indirizzo", f"{config.host}:{config.port}"),
        ("HTTPS", https),
        ("Registrazione", "dalla pagina di accesso" if config.allow_registration
                          else "chiusa: utenti solo con  tapbook user add"),
        ("Firewall", config.firewall),
        *([("Impronta HTTPS", fingerprint)] if fingerprint else []),
        *([("Certificato per", covers + "  (gli indirizzi nuovi entrano entro un minuto)")] if covers else []),
        ("Utenti", f"{len(users)}" + (f" ({', '.join(u['username'] for u in users[:10])}"
                                      f"{'…' if len(users) > 10 else ''})" if users else
                                      " — crea il primo con  tapbook user add <nome>")),
        ("Servizio", services.get(state, state) if service.supported() else "non disponibile su questo sistema"),
        ("Server", "in ascolto" if _listening(config.host, config.port) else "spento"),
    ]
    if os.name != "nt" and config.data_dir.exists() and config.data_dir.stat().st_mode & 0o077:
        rows.append(("ATTENZIONE", f"{config.data_dir} è leggibile da altri utenti del computer"))
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"  {label:<{width}}  {value}" for label, value in rows) + "\n"
