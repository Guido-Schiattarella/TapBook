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

from flask import Flask

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


def create_app(config, auth: AuthController, library: LibraryController,
               navigation: NavigationController, editing: EditController,
               account: AccountController, diagnostics: DiagnosticsController) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=_load_secret_key(config.data_dir),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_NAME="notes_session",
        SESSION_COOKIE_SECURE=config.https,   # with HTTPS the cookie never travels in clear text
        PERMANENT_SESSION_LIFETIME=dt.timedelta(hours=config.session_hours),
        MAX_CONTENT_LENGTH=config.max_upload_mb * 1024 * 1024,
    )
    app.extensions["tapbook"] = SimpleNamespace(config=config, auth=auth, library=library,
                                                navigation=navigation, editing=editing, account=account,
                                                diagnostics=diagnostics)
    app.after_request(security_headers)
    register_all(app)
    return app
