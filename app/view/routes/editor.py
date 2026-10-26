"""VIEW — editor API: operations, notifications, images, backgrounds, closing."""
import io

from flask import abort, g, jsonify, request, send_file

from ..http import api, body, controllers, view_response


def _number(name):
    try:
        return float(request.form.get(name, ""))
    except ValueError:
        return None


def register(app):
    @app.post("/api/edit/op")
    @api
    def api_edit_op():
        """The view reports a change; the controller applies it to the model and
        answers with the events the model notified."""
        data = body()
        return jsonify(controllers().editing.apply(g.username, data.get("session"), data.get("op")))

    @app.get("/api/edit/listen")
    @api
    def api_edit_listen():
        """Request the view always keeps open: it answers when there are changes from
        other devices or from the computer, or when the save status changes."""
        return jsonify(controllers().editing.listen(g.username, request.args.get("session")))

    @app.post("/api/edit/image")
    @api
    def api_edit_image():
        """Photo from the iPad (multipart: session, page, x, y, w, file)."""
        f = request.files.get("file")
        if not f:
            abort(400)
        return jsonify(controllers().editing.add_image(
            g.username, request.form.get("session"), request.form.get("page"),
            _number("x"), _number("y"), _number("w"), f.read()))

    @app.get("/api/edit/picture")
    @api
    def api_edit_picture():
        path = controllers().editing.picture(g.username, request.args.get("session"), request.args.get("id", ""))
        return send_file(path, max_age=3600)

    @app.get("/api/edit/layout")
    @api
    def api_edit_layout():
        """Background (empty page with its layout) of a page added in this session."""
        pdf = controllers().editing.layout_page(g.username, request.args.get("session"), request.args.get("page"))
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", max_age=3600)

    @app.get("/api/edit/background")
    @api
    def api_edit_background():
        """One of the background PDFs of the open document (id: see backgrounds.py),
        downloaded only by devices that do not have it yet. It travels as a binary
        file sent in chunks: even a large PDF gets through a slow network."""
        path = controllers().editing.background(g.username, request.args.get("session"), request.args.get("id"))
        resp = send_file(path, mimetype="application/pdf", conditional=False)
        resp.headers["Cache-Control"] = "no-store"   # the editor keeps it itself (bgcache.js)
        return resp

    @app.post("/api/edit/close")
    @api
    def api_edit_close():
        return view_response(controllers().navigation.leave_editor(g.username, body().get("session")))
