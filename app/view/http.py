"""VIEW — HTTP tools shared by all routes.

Only the security measures tied to the HTTP protocol: session, anti-CSRF
token, security headers, safe redirects, reading JSON requests. No business
rules: those live in the controllers.
"""
import re
import secrets
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from ..control.errors import ControlError

API_HEADER = ("X-Requested-With", "notes-app")
MAX_JSON_BYTES = 25 * 1024 * 1024   # JSON requests (the longest stroke is ~1 MB); files have their own limit
# Destination after login: only a path of this site, made of visible
# characters (no "//", backslashes, spaces or control characters, which some
# browsers ignore and would turn into the address of another site).
SAFE_NEXT_RE = re.compile(r"^/(?![/\\])[\x21-\x7e]*$")
CSP = ("default-src 'self'; img-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; "
       "worker-src 'self' blob:; script-src 'self' 'wasm-unsafe-eval'; object-src 'none'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


def controllers():
    """The app's controllers and configuration (registered by create_app)."""
    return current_app.extensions["tapbook"]


def client_ip() -> str:
    return request.remote_addr or "?"


# --- Session ----------------------------------------------------------------------------
def start_session(user):
    session.clear()  # new session after login (no session fixation)
    session.permanent = True
    session["uid"], session["username"], session["fp"] = user["id"], user["username"], user["fp"]


def new_form_token() -> str:
    session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def form_token_ok() -> bool:
    return secrets.compare_digest(request.form.get("csrf", ""), session.get("csrf", "-"))


def safe_next(default: str) -> str:
    nxt = request.args.get("next", "")
    # Internal redirects only (no open redirect to other sites).
    return nxt if SAFE_NEXT_RE.match(nxt) and "\\" not in nxt else default


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        user = controllers().auth.session_user(session.get("uid"), session.get("username"), session.get("fp"))
        if not user:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify(error="Sessione scaduta"), 401
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        g.user = user
        g.username = user["username"]
        return view(*args, **kwargs)
    return wrapper


# --- API JSON ----------------------------------------------------------------------------
def api(view):
    """JSON route. Requests that change data must carry a custom header that
    another site cannot send (CSRF protection, together with the
    SameSite=Strict cookie). Controller errors become JSON responses with the
    matching HTTP status code."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if request.method != "GET" and request.headers.get(API_HEADER[0]) != API_HEADER[1]:
            return jsonify(error="Richiesta non valida"), 403
        try:
            return view(*args, **kwargs)
        except ControlError as e:
            return jsonify(error=e.message, **e.details), e.status
    return login_required(wrapper)


def body() -> dict:
    if (request.content_length or 0) > MAX_JSON_BYTES:
        abort(413)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    return data


def view_response(result: dict):
    """Response with the view to show (the editor's PDF is downloaded separately)."""
    return jsonify(result)


# --- Headers -----------------------------------------------------------------------------
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy", CSP)
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), payment=(), usb=()")
    # User pages and data never stay in the browser cache (for example after
    # logging out on a shared iPad); static files, previews and images do.
    if resp.mimetype in ("application/json", "text/html") and "Cache-Control" not in resp.headers:
        resp.headers["Cache-Control"] = "no-store"
    return resp
