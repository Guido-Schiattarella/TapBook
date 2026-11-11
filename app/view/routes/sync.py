"""VIEW — the requests of TapBook Sync (the service on a computer that keeps a
folder aligned with the server). It is not a browser: it proves who it is with
the token received when it was paired (header "Authorization: Bearer …"),
never with the session cookie. A browser does not add that header by itself,
so another website cannot make these requests in the user's name (no CSRF).
"""
from functools import wraps

from flask import abort, g, jsonify, request, send_file

from ...control.errors import ControlError
from ...control.sync import MAX_CHUNK
from ..http import client_ip, controllers

MAX_JSON = 64 * 1024


def _json() -> dict:
    if (request.content_length or 0) > MAX_JSON:
        abort(413)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    return data


def _answer(view):
    """Controller errors become JSON answers with their status code."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except ControlError as e:
            return jsonify(error=e.message, **e.details), e.status
    return wrapper


def device_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        token = header[7:].strip() if header[:7].lower() == "bearer " else None
        g.device = controllers().sync.device_user(token, client_ip())
        g.username = g.device["username"]
        return view(*args, **kwargs)
    return _answer(wrapper)


def register(app):
    sync = lambda: controllers().sync  # noqa: E731

    @app.post("/api/sync/pair")
    @_answer
    def sync_pair():
        data = _json()
        return jsonify(sync().pair(data.get("username"), data.get("password"), data.get("device"), client_ip()))

    @app.get("/api/sync/whoami")
    @device_required
    def sync_whoami():
        from ... import __version__
        return jsonify(username=g.username, device=g.device["device"], version=__version__,
                       maxBytes=sync().max_bytes)

    @app.post("/api/sync/unpair")
    @device_required
    def sync_unpair():
        sync().unpair(g.device)
        return jsonify(ok=True)

    @app.get("/api/sync/changes")
    @device_required
    def sync_changes():
        return jsonify(sync().changes(g.username, request.args.get("cursor"), request.args.get("wait") == "1"))

    @app.get("/api/sync/file")
    @device_required
    def sync_file():
        path = sync().file_path(g.username, request.args.get("path"))
        # conditional: Range requests, so an interrupted download resumes.
        resp = send_file(path, mimetype="application/octet-stream", conditional=True, etag=False, max_age=0)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/api/sync/mkdir")
    @device_required
    def sync_mkdir():
        return jsonify(sync().make_dir(g.username, _json().get("path")))

    @app.post("/api/sync/delete")
    @device_required
    def sync_delete():
        data = _json()
        return jsonify(sync().delete(g.username, data.get("path"), data.get("hash")))

    @app.post("/api/sync/move")
    @device_required
    def sync_move():
        data = _json()
        return jsonify(sync().move(g.username, data.get("path"), data.get("to"), data.get("hash")))

    @app.post("/api/sync/upload")
    @device_required
    def sync_upload_start():
        data = _json()
        return jsonify(sync().upload_start(g.username, data.get("path"), data.get("size"), data.get("hash"),
                                           data.get("base"), data.get("mtime"), data.get("keepPrevious")))

    @app.put("/api/sync/upload/<upload_id>")
    @device_required
    def sync_upload_chunk(upload_id):
        try:
            offset = int(request.args.get("offset", ""))
        except ValueError:
            abort(400)
        if (request.content_length or 0) > MAX_CHUNK:
            abort(413)
        return jsonify(sync().upload_chunk(g.username, upload_id, offset, request.get_data(cache=False)))

    @app.post("/api/sync/upload/<upload_id>/finish")
    @device_required
    def sync_upload_finish(upload_id):
        return jsonify(sync().upload_finish(g.username, upload_id))
