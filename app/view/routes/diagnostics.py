"""VIEW — errors of the interface reported by the browser (see app.js)."""
from flask import abort, g, jsonify, request

from ..http import api, body, controllers

MAX_REPORT_BYTES = 16 * 1024


def register(app):
    @app.post("/api/client-error")
    @api
    def api_client_error():
        if (request.content_length or 0) > MAX_REPORT_BYTES:
            abort(413)
        controllers().diagnostics.report_error(g.username, body())
        return jsonify(ok=True)
