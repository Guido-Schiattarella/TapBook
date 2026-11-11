"""The requests of TapBook Sync to the server (only the standard library).

Every request has a time limit: a connection that stops answering (Wi-Fi or
hotspot losing packets) is abandoned and retried, instead of waiting for minutes.

Certificates: a server with a certificate valid for its name (e.g. Let's Encrypt)
is trusted as any website. A server with the certificate created by TapBook is
trusted after the user confirmed it once, when pairing (trust_server): its
certificate authority (/certificato) is saved in ca.pem and used from then on.
"""
import hashlib
import http.client
import json
import os
import socket
import ssl
import urllib.parse
from pathlib import Path

from . import settings

TIMEOUT = 60                  # seconds without an answer before giving up
WAIT_TIMEOUT = 60             # the `changes` request waits up to 25 s on the server
CHUNK = 4 * 1024 * 1024       # upload pieces
READ_BLOCK = 256 * 1024


class Offline(Exception):
    """The server cannot be reached (network, server off, time limit)."""


class ApiError(Exception):
    def __init__(self, status: int, data: dict):
        super().__init__(data.get("error") or f"Errore {status}")
        self.status, self.data = status, data


class UntrustedCertificate(Exception):
    """The server's certificate is not recognised: the user must confirm it."""


def _context(cafile: Path | None = None) -> ssl.SSLContext:
    """The system's certificates, plus the one confirmed by the user (if any)."""
    context = ssl.create_default_context()
    if cafile and cafile.is_file():
        context.load_verify_locations(cafile=str(cafile))
    return context


class Connection:
    def __init__(self, server: str, token: str | None = None, cafile: Path | None = None):
        url = urllib.parse.urlsplit(settings.normalize_server(server))
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ValueError("Indirizzo del server non valido")
        self.scheme, self.host = url.scheme, url.hostname
        self.port = url.port or (443 if url.scheme == "https" else 80)
        self.base = url.path.rstrip("/")
        self.token = token
        self.cafile = cafile if cafile is not None else settings.ca_path()

    # --- low level ------------------------------------------------------------------------
    def _open(self, timeout) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=timeout,
                                               context=_context(self.cafile))
        return http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def _send(self, method, path, params=None, body=None, headers=None, timeout=TIMEOUT):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        headers = dict(headers or {})
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        conn = self._open(timeout)
        try:
            conn.request(method, url, body=body, headers=headers)
            return conn, conn.getresponse()
        except ssl.SSLCertVerificationError as e:
            conn.close()
            raise UntrustedCertificate(str(e)) from e
        except (OSError, http.client.HTTPException) as e:
            conn.close()
            raise Offline(str(e) or type(e).__name__) from e

    def request(self, method, path, params=None, data=None, raw=None, timeout=TIMEOUT) -> dict:
        body, headers = None, {}
        if data is not None:
            body, headers = json.dumps(data).encode(), {"Content-Type": "application/json"}
        elif raw is not None:
            body, headers = raw, {"Content-Type": "application/octet-stream"}
        conn, resp = self._send(method, path, params, body, headers, timeout)
        try:
            payload = resp.read()
        except (OSError, http.client.HTTPException) as e:
            raise Offline(str(e)) from e
        finally:
            conn.close()
        try:
            answer = json.loads(payload) if payload else {}
        except ValueError:
            answer = {}
        if not isinstance(answer, dict):
            answer = {}
        if resp.status >= 400:
            raise ApiError(resp.status, answer)
        return answer

    # --- account ----------------------------------------------------------------------------
    def pair(self, username, password, device) -> dict:
        return self.request("POST", "/api/sync/pair", data={"username": username, "password": password,
                                                            "device": device})

    def whoami(self) -> dict:
        return self.request("GET", "/api/sync/whoami")

    def unpair(self):
        return self.request("POST", "/api/sync/unpair", data={})

    # --- files ------------------------------------------------------------------------------
    def changes(self, cursor=None, wait=False) -> dict:
        """What changed on the server after `cursor` (see control/sync.py): only the
        changes, or the complete list ("full") the first time or after a restart."""
        params = {"wait": "1" if wait else "0"}
        if cursor:
            params["cursor"] = cursor
        return self.request("GET", "/api/sync/changes", params, timeout=WAIT_TIMEOUT if wait else TIMEOUT)

    def mkdir(self, rel):
        return self.request("POST", "/api/sync/mkdir", data={"path": rel})

    def delete(self, rel, digest=None):
        return self.request("POST", "/api/sync/delete", data={"path": rel, "hash": digest})

    def move(self, rel, target, digest=None):
        return self.request("POST", "/api/sync/move", data={"path": rel, "to": target, "hash": digest})

    def download(self, rel: str, dest: Path, digest: str, size: int, progress=None):
        """Downloads into `dest`, resuming a partial file already there; the content
        must have the expected fingerprint (otherwise it is thrown away)."""
        have = dest.stat().st_size if dest.exists() else 0
        if have > size:
            dest.unlink()
            have = 0
        if have < size or size == 0:
            headers = {"Range": f"bytes={have}-"} if have else {}
            conn, resp = self._send("GET", "/api/sync/file", {"path": rel}, headers=headers)
            try:
                if resp.status >= 400:
                    try:
                        data = json.loads(resp.read() or b"{}")
                    except ValueError:
                        data = {}
                    raise ApiError(resp.status, data if isinstance(data, dict) else {})
                mode = "ab" if resp.status == 206 else "wb"
                with open(dest, mode) as fh:
                    while block := resp.read(READ_BLOCK):
                        fh.write(block)
                        if progress:
                            progress(len(block))
            except (OSError, http.client.HTTPException) as e:
                if isinstance(e, ApiError):
                    raise
                raise Offline(str(e)) from e
            finally:
                conn.close()
        h = hashlib.sha256()
        with open(dest, "rb") as fh:
            while block := fh.read(READ_BLOCK):
                h.update(block)
        if h.hexdigest() != digest:
            dest.unlink(missing_ok=True)
            raise ApiError(0, {"error": "File scaricato danneggiato o cambiato durante lo scaricamento"})

    def upload(self, source: Path, rel: str, size: int, digest: str, base, mtime, progress=None,
               keep_previous=False):
        """Uploads in pieces; an interrupted upload resumes where it stopped.
        keep_previous: the server keeps the version it replaces in its trash."""
        start = self.request("POST", "/api/sync/upload", data={"path": rel, "size": size, "hash": digest,
                                                               "base": base, "mtime": mtime,
                                                               "keepPrevious": bool(keep_previous)})
        upload_id, offset = start["id"], int(start["received"])
        with open(source, "rb") as fh:
            fh.seek(offset)
            while offset < size:
                block = fh.read(min(CHUNK, size - offset))
                if not block:
                    break                     # file shorter than declared: the server will say so
                try:
                    offset = int(self.request("PUT", f"/api/sync/upload/{upload_id}", {"offset": offset},
                                              raw=block)["received"])
                except ApiError as e:
                    if e.status == 409 and "received" in e.data:      # resume from where the server is
                        offset = int(e.data["received"])
                        fh.seek(offset)
                        continue
                    raise
                if progress:
                    progress(len(block))
        return self.request("POST", f"/api/sync/upload/{upload_id}/finish", data={})


# --- certificates --------------------------------------------------------------------------
def fetch_untrusted_ca(server: str) -> tuple[str, str]:
    """For a server whose certificate is not recognised: the certificate to trust
    (TapBook's certificate authority from /certificato, or else the server's own
    certificate) and its SHA-256 fingerprint to show to the user."""
    conn = Connection(server, cafile=Path(os.devnull))
    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    pem = None
    try:
        c = http.client.HTTPSConnection(conn.host, conn.port, timeout=TIMEOUT, context=insecure)
        c.request("GET", conn.base + "/certificato")
        resp = c.getresponse()
        data = resp.read(64 * 1024)
        c.close()
        if resp.status == 200:
            text = data.decode("ascii", "replace")
            if "BEGIN CERTIFICATE" in text:
                pem = text
            else:
                pem = ssl.DER_cert_to_PEM_cert(data)
    except (OSError, http.client.HTTPException, ValueError):
        pem = None
    if pem is None:
        try:
            with socket.create_connection((conn.host, conn.port), timeout=TIMEOUT) as s, \
                    insecure.wrap_socket(s, server_hostname=conn.host) as t:
                pem = ssl.DER_cert_to_PEM_cert(t.getpeercert(binary_form=True))
        except OSError as e:
            raise Offline(str(e)) from e
    der = ssl.PEM_cert_to_DER_cert(pem)
    fingerprint = hashlib.sha256(der).hexdigest().upper()
    return pem, ":".join(fingerprint[i:i + 2] for i in range(0, len(fingerprint), 2))


def check_with_ca(server: str, pem: str) -> bool:
    """Does the server really present a certificate signed by `pem` (with the right name)?"""
    tmp = settings.config_dir() / "ca-check.pem"
    tmp.write_text(pem, encoding="ascii")
    try:
        conn = Connection(server, cafile=tmp)
        c = conn._open(TIMEOUT)
        c.connect()
        c.close()
        return True
    except (ssl.SSLError, ssl.CertificateError):
        return False
    except OSError as e:
        raise Offline(str(e)) from e
    finally:
        tmp.unlink(missing_ok=True)
