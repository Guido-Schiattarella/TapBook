"""VIEW — the meeting point between the interface (HTML/JavaScript in the iPad
browser) and the controllers on the computer.

This creates the web application: session cookie settings, security headers
and route registration (view/routes). The routes:
  1. receive the view's request (parameters, form, JSON, session);
  2. pass it to the controller;
  3. return the controller's answer: an HTML page or JSON data (including the
     view to show).
They hold no business rules and never access files or the database directly.
"""
import datetime as dt
import os
import secrets
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, request
from flask.sessions import SecureCookieSessionInterface
from werkzeug.middleware.proxy_fix import ProxyFix

from ..control.account import AccountController
from ..control.auth import AuthController
from ..control.diagnostics import DiagnosticsController
from ..control.editing import EditController
from ..control.library import LibraryController
from ..control.navigation import NavigationController
from .http import security_headers
from .routes import register_all


def _load_secret_key(data_dir: Path) -> bytes:
    """Key that signs the session cookies. It is stored on disk (mode 600) so that
    users do not have to log in again when the server restarts."""
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / "secret_key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(secrets.token_bytes(32))
    return key_file.read_bytes()


class ProxySessionInterface(SecureCookieSessionInterface):
    """Behind a proxy the session cookie is Secure only when the device really
    reached the proxy over HTTPS (X-Forwarded-Proto): with a proxy in plain HTTP
    (for example inside a VPN such as Tailscale, which already encrypts) a Secure
    cookie would be thrown away by the browser and no login would work."""
    def get_cookie_secure(self, app):
        return request.is_secure


def create_app(config, auth: AuthController, library: LibraryController,
               navigation: NavigationController, editing: EditController,
               account: AccountController, diagnostics: DiagnosticsController, sync=None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_load_secret_key(config.data_dir),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_NAME="notes_session",
        # With HTTPS the cookie never travels in clear text (behind a proxy: see
        # ProxySessionInterface).
        SESSION_COOKIE_SECURE=config.https,
        PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=config.session_hours),
        MAX_CONTENT_LENGTH=config.max_upload_mb * 1024 * 1024,
    )
    app.extensions["tapbook"] = SimpleNamespace(config=config, auth=auth, library=library,
                                                navigation=navigation, editing=editing, account=account,
                                                diagnostics=diagnostics, sync=sync)
    if config.behind_proxy:
        # Address and protocol of the device, as seen by the proxy in front (one
        # proxy only). Without behind_proxy these headers are ignored: anybody
        # could write them to dodge the per-address login limit.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.session_interface = ProxySessionInterface()
    app.after_request(security_headers)
    register_all(app)
    return app
