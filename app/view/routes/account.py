"""VIEW — account API: profile photo, password change, deletion."""
from flask import abort, g, jsonify, request, send_file, session, url_for

from ..http import api, body, client_ip, controllers, view_response


def register(app):
    @app.post("/api/account/open")
    @api
    def api_account_open():
        return view_response(controllers().account.account_view(g.user))

    @app.get("/api/account/avatar")
    @api
    def api_account_avatar():
        return send_file(controllers().account.avatar_path(g.username), mimetype="image/jpeg", max_age=0)

    @app.post("/api/account/avatar")
    @api
    def api_account_avatar_set():
        f = request.files.get("file")
        if not f:
            abort(400)
        return view_response(controllers().account.set_avatar(g.user, f.read()))

    @app.post("/api/account/avatar/delete")
    @api
    def api_account_avatar_delete():
        return view_response(controllers().account.remove_avatar(g.user))

    @app.post("/api/account/password")
    @api
    def api_account_password():
        data = body()
        result, fingerprint = controllers().account.change_password(
            g.user, data.get("current"), data.get("new"), data.get("confirm"), client_ip())
        session["fp"] = fingerprint   # this session stays valid, the others do not
        return view_response(result)

    @app.post("/api/account/delete")
    @api
    def api_account_delete():
        data = body()
        controllers().account.delete_account(g.user, data.get("password"), data.get("confirm"), client_ip())
        session.clear()
        return jsonify(redirect=url_for("login"))
