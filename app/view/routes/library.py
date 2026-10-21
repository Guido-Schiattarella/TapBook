"""VIEW — document list API: navigation, folders, new documents, import,
search, trash, layout previews."""
import io

from flask import abort, g, request, send_file

from ..http import api, body, controllers, view_response


def register(app):
    # --- Navigation and document list ---------------------------------------------
    @app.post("/api/open")
    @api
    def api_open():
        """The view asks to open a path: the controller answers with the data and
        the view to switch to (list or editor)."""
        data = body()
        return view_response(controllers().navigation.open(g.username, data.get("path", ""), data.get("page")))

    @app.post("/api/library/mkdir")
    @api
    def api_mkdir():
        data = body()
        c = controllers()
        listing = c.library.create_folder(g.username, data.get("path", ""), data.get("name"))
        return view_response(c.navigation.library_view(g.username, listing))

    @app.post("/api/library/newdoc")
    @api
    def api_newdoc():
        data = body()
        return view_response(controllers().navigation.create_document(
            g.username, data.get("path", ""), data.get("name"), data.get("layout"), data.get("color")))

    @app.post("/api/library/upload")
    @api
    def api_upload():
        f = request.files.get("file")
        if not f:
            abort(400)
        c = controllers()
        listing = c.library.import_pdf(g.username, request.form.get("path", ""), f.filename, f.read())
        return view_response(c.navigation.library_view(g.username, listing))

    @app.post("/api/library/rename")
    @api
    def api_rename():
        data = body()
        return view_response(controllers().navigation.rename(g.username, data.get("path", ""), data.get("name")))

    @app.post("/api/library/delete")
    @api
    def api_delete():
        return view_response(controllers().navigation.delete(g.username, body().get("path", "")))

    @app.get("/api/layout/preview")
    @api
    def api_layout_preview():
        """Preview of a layout (PNG drawn by the model) for the selection menus."""
        png = controllers().library.layout_preview(request.args.get("id"))
        return send_file(io.BytesIO(png), mimetype="image/png", max_age=86400)

    @app.get("/api/doc/raw")
    @api
    def api_doc_raw():
        path = controllers().library.raw_path(g.username, request.args.get("path", ""))
        return send_file(path, mimetype="application/pdf", as_attachment=True,
                         download_name=path.name, max_age=0)

    # --- Search and trash --------------------------------------------------------------
    @app.post("/api/search")
    @api
    def api_search():
        return view_response(controllers().navigation.search_view(g.username, body().get("query")))

    @app.post("/api/trash/open")
    @api
    def api_trash_open():
        return view_response(controllers().navigation.trash_view(g.username))

    @app.post("/api/trash/restore")
    @api
    def api_trash_restore():
        return view_response(controllers().navigation.trash_restore(g.username, body().get("entry")))

    @app.post("/api/trash/delete")
    @api
    def api_trash_delete():
        return view_response(controllers().navigation.trash_delete(g.username, body().get("entry")))

    @app.post("/api/trash/empty")
    @api
    def api_trash_empty():
        return view_response(controllers().navigation.trash_empty(g.username))
