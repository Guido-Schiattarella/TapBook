"""Certificates for HTTPS on the home network.

On first start the app creates a small local certificate authority (CA) and,
with it, the server certificate valid for the computer's addresses. The CA
certificate is installed once on the iPad (it can be downloaded from the login
page): from then on Safari trusts the server and the connection is encrypted,
without warnings.

Files in <data_dir>/tls/:
  ca.crt / ca.key           the local CA (the key never leaves the computer)
  server.crt / server.key   server certificate, regenerated automatically when
                            the computer's address changes or expiry approaches
"""
import datetime as dt
import ipaddress
import os
import re
import socket
from pathlib import Path

from cheroot import errors
from cheroot.ssl.builtin import BuiltinSSLAdapter
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CA_DAYS = 3650
SERVER_DAYS = 397        # Apple does not accept server certificates valid for more than 398 days
RENEW_BEFORE_DAYS = 30


def _write_private(path: Path, data: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _key_bytes(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _create_ca(folder: Path):
    key = _new_key()
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, f"Note PDF - certificato locale ({socket.gethostname()})"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Note PDF"),
    ])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - dt.timedelta(days=1))
            .not_valid_after(_now() + dt.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_private(folder / "ca.key", _key_bytes(key))
    (folder / "ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _server_names(addresses):
    host = socket.gethostname()
    dns = sorted({"localhost", host, f"{host}.local"})
    ips = sorted({"127.0.0.1", *addresses})
    return dns, ips


def _needs_new_server_cert(folder: Path, dns, ips) -> bool:
    crt = folder / "server.crt"
    if not crt.exists() or not (folder / "server.key").exists():
        return True
    cert = x509.load_pem_x509_certificate(crt.read_bytes())
    if cert.not_valid_after_utc - _now() < dt.timedelta(days=RENEW_BEFORE_DAYS):
        return True
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    have_ips = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    have_dns = set(san.get_values_for_type(x509.DNSName))
    return not (set(ips) <= have_ips and set(dns) <= have_dns)


def _create_server_cert(folder: Path, dns, ips):
    ca_key = serialization.load_pem_private_key((folder / "ca.key").read_bytes(), password=None)
    ca_cert = x509.load_pem_x509_certificate((folder / "ca.crt").read_bytes())
    key = _new_key()
    san = x509.SubjectAlternativeName([x509.DNSName(d) for d in dns] +
                                      [x509.IPAddress(ipaddress.ip_address(i)) for i in ips])
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns[0] if dns else "localhost")]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_now() - dt.timedelta(days=1))
            .not_valid_after(_now() + dt.timedelta(days=SERVER_DAYS))
            .add_extension(san, critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_private(folder / "server.key", _key_bytes(key))
    (folder / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def ca_certificate(data_dir: Path) -> Path | None:
    """Public certificate of the local CA (to install on the iPad), if it exists."""
    ca = data_dir / "tls" / "ca.crt"
    return ca if ca.is_file() else None


def ensure_certificates(data_dir: Path, addresses) -> dict:
    """Prepares the CA and the server certificate if needed. Returns the paths and
    whether the server certificate was just (re)generated."""
    folder = data_dir / "tls"
    folder.mkdir(parents=True, exist_ok=True)
    os.chmod(folder, 0o700)
    created_ca = not (folder / "ca.crt").exists() or not (folder / "ca.key").exists()
    if created_ca:
        _create_ca(folder)
    dns, ips = _server_names(addresses)
    renewed = _needs_new_server_cert(folder, dns, ips)
    if renewed:
        _create_server_cert(folder, dns, ips)
    return {"ca": folder / "ca.crt", "cert": folder / "server.crt", "key": folder / "server.key",
            "new_ca": created_ca, "renewed": renewed}


# --- Redirect from http:// to https:// ---------------------------------------------
# If a device still opens the address with http:// (Safari history, a Home
# screen icon created before HTTPS), on the same port it gets a redirect to the
# same page over https://.
_TLS_HANDSHAKE = 0x16                      # first byte of a TLS connection
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")
_PATH_RE = re.compile(r"^/[\x21-\x7e]*$")  # visible characters only, no line breaks
REDIRECTED = "richiesta http:// reindirizzata a https://"


class RedirectingSSLAdapter(BuiltinSSLAdapter):
    def __init__(self, certificate, private_key, port):
        super().__init__(certificate, private_key)
        self.port = port

    def wrap(self, sock):
        try:
            sock.settimeout(10)
            first = sock.recv(1, socket.MSG_PEEK)
        except OSError as e:
            raise errors.FatalSSLAlert(*e.args) from e
        if first and first[0] != _TLS_HANDSHAKE:
            self._redirect(sock)
            raise errors.FatalSSLAlert(REDIRECTED)
        return super().wrap(sock)

    def _redirect(self, sock):
        data = b""
        try:
            while b"\r\n\r\n" not in data and len(data) < 8192:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            head = data.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            parts = head[0].split(" ")
            path = parts[1] if len(parts) >= 2 and _PATH_RE.match(parts[1]) else "/"
            host = next((line.split(":", 1)[1].strip() for line in head[1:]
                         if line.lower().startswith("host:")), "")
            if not _HOST_RE.match(host):
                host = f"127.0.0.1:{self.port}"
            location = f"https://{host}{path}"
            sock.sendall((f"HTTP/1.1 301 Moved Permanently\r\nLocation: {location}\r\n"
                          "Content-Length: 0\r\nConnection: close\r\n\r\n").encode("latin-1"))
        except OSError:
            pass
        finally:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
