"""VIEW — HTML pages: HTTPS certificate, login, sign-up, the app page."""
from flask import abort, g, redirect, render_template, request, send_file, session, url_for

from ...control.errors import ControlError
from ...system.tls import ca_certificate
from ..http import (client_ip, controllers, form_token_ok, login_required, new_form_token, safe_next,
                    start_session)

# Document list, editor, trash, account and search are views of the same page:
# the controller decides which one to show in its answer to /api/open; the
# address only serves to reopen the same view on reload or with back/forward.
APP_PAGES = {"/": "index", "/edit": "edit_page", "/cestino": "trash_page",
             "/account": "account_page", "/cerca": "search_page"}


def register(app):
    # --- HTTPS certificate -----------------------------------------------------------
    @app.get("/certificato")
    def certificate():
        """Certificate of the local CA to install on the iPad (it is public: it holds
        no secrets). Safari recognises it and offers to install it as a profile."""
        config = controllers().config
        ca = ca_certificate(config.data_dir)
        if not config.https or ca is None:
            abort(404)
        return send_file(ca, mimetype="application/x-x509-ca-cert", as_attachment=True,
                         download_name="Note-PDF-certificato.crt", max_age=0)

    @app.get("/certificato/istruzioni")
    def certificate_help():
        if not controllers().config.https:
            abort(404)
        return render_template("certificate.html")

    # --- Login and sign-up -----------------------------------------------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        auth, config = controllers().auth, controllers().config
        if session.get("uid") and request.method == "GET":
            return redirect(url_for("index"))
        if auth.needs_first_user():
            return redirect(url_for("register"))  # first start: the first account is created
        error = None
        if request.method == "POST":
            if not form_token_ok():
                error = "Sessione del modulo scaduta, riprova."
            else:
                try:
                    user = auth.login(request.form.get("username", ""), request.form.get("password", ""),
                                      client_ip())
                    start_session(user)
                    return redirect(safe_next(url_for("index")))
                except ControlError as e:
                    error = e.message
        return render_template("login.html", error=error, csrf=new_form_token(),
                               allow_registration=auth.allow_registration,
                               https=config.https), (401 if error else 200)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        auth, config = controllers().auth, controllers().config
        if not auth.registration_open():
            abort(404)
        if session.get("uid") and request.method == "GET":
            return redirect(url_for("index"))
        first_user = auth.needs_first_user()
        error, username = None, ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip().lower()
            if not form_token_ok():
                error = "Sessione del modulo scaduta, riprova."
            else:
                try:
                    user = auth.register(username, request.form.get("password", ""),
                                         request.form.get("confirm", ""), client_ip())
                    start_session(user)
                    return redirect(url_for("index"))
                except ControlError as e:
                    error = e.message
        return render_template("register.html", error=error, csrf=new_form_token(),
                               username=username, first_user=first_user,
                               https=config.https), (400 if error else 200)

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # --- The application page -----------------------------------------------------
    @login_required
    def app_page():
        return render_template("app.html", username=g.username)

    for path, endpoint in APP_PAGES.items():
        app.add_url_rule(path, endpoint, app_page, methods=["GET"])
