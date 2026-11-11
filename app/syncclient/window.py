"""TapBook Sync — the window. It does not touch files: it sets the server, the
account and the folder, shows what the background service is doing
(status.json) and passes it the user's requests (pause, sync now, confirm a
large deletion). Closing it does not stop the synchronisation.
"""
import os
import subprocess
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog

from .. import __version__
from ..desktop.theme import Card, Fonts, GradientBar, Palette, RoundButton, auto_wrap
from . import settings
from .api import ApiError, Connection, Offline, UntrustedCertificate, check_with_ca, fetch_untrusted_ca
from .service import install_autostart, running, start_detached

LOGO = Path(__file__).resolve().parent.parent / "view" / "static" / "img" / "logo.png"
ICON = LOGO.with_name("favicon.png")
STATES = {
    "starting": ("Avvio…", Palette.warn),
    "setup": ("Da configurare", Palette.muted),
    "syncing": ("Sincronizzazione…", Palette.accent),
    "ok": ("Sincronizzato", Palette.ok),
    "warn": ("Sincronizzato con avvisi", Palette.warn),
    "paused": ("In pausa", Palette.muted),
    "offline": ("Server non raggiungibile", Palette.warn),
    "error": ("Errore", Palette.danger),
    "confirm": ("Conferma richiesta", Palette.danger),
    "stopped": ("Servizio fermo", Palette.danger),
}
DIALOG_WIDTH = 440


def open_path(path: str):
    if os.name == "nt":
        os.startfile(path)                                  # noqa: S606 — the synchronised folder
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def _entry(parent, fonts, var, show=None):
    frame = tk.Frame(parent, bg=Palette.border, padx=1, pady=1)
    entry = tk.Entry(frame, textvariable=var, show=show or "", font=fonts.body, relief="flat", bd=7,
                     bg=Palette.surface_2, fg=Palette.text, insertbackground=Palette.text, highlightthickness=0)
    entry.pack(fill="x")
    entry.bind("<FocusIn>", lambda e: frame.config(bg=Palette.accent))
    entry.bind("<FocusOut>", lambda e: frame.config(bg=Palette.border))
    return frame, entry


class PairDialog(tk.Toplevel):
    """Server address, name and password: the computer is paired (the password
    is sent once and never saved)."""

    def __init__(self, parent, fonts, cfg):
        super().__init__(parent, bg=Palette.bg)
        self.fonts, self.cfg, self.result = fonts, cfg, None
        self.title("Collega il server")
        self.minsize(DIALOG_WIDTH + 32, 10)
        self.resizable(False, False)
        self.transient(parent)
        card = Card(self, fonts, "Collega il server")
        card.pack(fill="both", expand=True, padx=16, pady=16)
        body = card.body
        auto_wrap(tk.Label(body, text="L'indirizzo è quello che apri nel browser per usare TapBook, per esempio "
                                      "https://192.168.1.20:8000 oppure https://note.example.org.",
                           font=fonts.small, fg=Palette.text_2, bg=Palette.surface, justify="left", anchor="w"
                           )).pack(fill="x")
        self.vars = {k: tk.StringVar(value=v) for k, v in (("server", cfg["server"]), ("username", cfg["username"]),
                                                          ("password", ""), ("device", cfg["device"] or
                                                                             settings.default_device_name()))}
        for key, label, show in (("server", "Indirizzo del server", None), ("username", "Nome utente", None),
                                 ("password", "Password", "•"), ("device", "Nome di questo computer", None)):
            tk.Label(body, text=label, font=fonts.bold, fg=Palette.text_2, bg=Palette.surface, anchor="w"
                     ).pack(fill="x", pady=(10, 3))
            frame, entry = _entry(body, fonts, self.vars[key], show)
            frame.pack(fill="x")
            entry.bind("<Return>", lambda e: self.confirm())
            if key == "server":
                self.first = entry
        self.error = tk.Label(body, text="", font=fonts.small, fg=Palette.danger, bg=Palette.surface, anchor="w",
                              justify="left")
        auto_wrap(self.error).pack(fill="x", pady=(8, 0))
        buttons = tk.Frame(body, bg=Palette.surface)
        buttons.pack(fill="x", pady=(12, 0))
        self.ok = RoundButton(buttons, "Collega", self.confirm, fonts, "primary")
        self.ok.pack(side="right")
        RoundButton(buttons, "Annulla", self.destroy, fonts, "soft").pack(side="right", padx=8)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(50, self.first.focus_set)

    def confirm(self):
        values = {k: v.get().strip() for k, v in self.vars.items()}
        values["password"] = self.vars["password"].get()
        values["server"] = settings.normalize_server(values["server"])
        if not values["server"] or not values["username"] or not values["password"]:
            self.error.config(text="Compila indirizzo, nome utente e password.")
            return
        self.ok.configure_button(text="Collego…", enabled=False)
        self.error.config(text="")
        threading.Thread(target=self._pair, args=(values,), daemon=True).start()

    def _pair(self, values, trusted=False):
        try:
            answer = Connection(values["server"]).pair(values["username"], values["password"], values["device"])
        except UntrustedCertificate:
            if trusted:
                return self._fail("Il certificato confermato non corrisponde al server.")
            return self.after(0, lambda: self._ask_trust(values))
        except Offline as e:
            return self._fail(f"Server non raggiungibile: {e}")
        except ApiError as e:
            return self._fail(str(e) if e.status != 404 else "Questo server non ha TapBook Sync: aggiornalo.")
        except ValueError as e:
            return self._fail(str(e))
        self.after(0, lambda: self._done(values, answer))

    def _ask_trust(self, values):
        try:
            pem, fingerprint = fetch_untrusted_ca(values["server"])
            ok = check_with_ca(values["server"], pem)
        except Offline as e:
            return self._fail(f"Server non raggiungibile: {e}")
        if not ok:
            return self._fail("Il certificato del server non contiene questo indirizzo: aspetta un minuto "
                              "(il server aggiunge da solo gli indirizzi nuovi) e riprova; sul server, "
                              "«tapbook status» mostra gli indirizzi validi (riga «Certificato per»).")
        question = tk.Toplevel(self, bg=Palette.bg)
        question.title("Certificato del server")
        question.minsize(DIALOG_WIDTH + 72, 10)
        question.transient(self)
        card = Card(question, self.fonts, "Ti fidi di questo server?")
        card.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(card.body, text="Il server usa un certificato creato da TapBook, non riconosciuto "
                                 "automaticamente. Confermalo solo se l'impronta qui sotto è la stessa che il server "
                                 "mostra con il comando «tapbook status» (riga «Impronta HTTPS»): verrà ricordato "
                                 "solo da TapBook Sync.",
                 font=self.fonts.small, fg=Palette.text_2, bg=Palette.surface, justify="left",
                 wraplength=DIALOG_WIDTH).pack(fill="x")
        tk.Label(card.body, text=fingerprint, font=self.fonts.mono, fg=Palette.text, bg=Palette.surface_2,
                 justify="left", wraplength=DIALOG_WIDTH).pack(fill="x", pady=(10, 0))
        buttons = tk.Frame(card.body, bg=Palette.surface)
        buttons.pack(fill="x", pady=(12, 0))

        def accept():
            settings.ca_path().write_text(pem, encoding="ascii")
            question.destroy()
            threading.Thread(target=self._pair, args=(values, True), daemon=True).start()

        def refuse():
            question.destroy()
            self._fail("Collegamento annullato: certificato non confermato.")
        RoundButton(buttons, "Mi fido", accept, self.fonts, "primary").pack(side="right")
        RoundButton(buttons, "Annulla", refuse, self.fonts, "soft").pack(side="right", padx=8)
        question.grab_set()

    def _fail(self, text):
        def show():
            self.error.config(text=text)
            self.ok.configure_button(text="Collega", enabled=True)
        self.after(0, show)

    def _done(self, values, answer):
        settings.save_token(answer["token"])
        self.result = {"server": values["server"], "username": answer["username"], "device": answer["device"]}
        self.destroy()


class SyncWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.fonts = Fonts(root)
        self.cfg = settings.load()
        root.title("TapBook Sync")
        root.configure(bg=Palette.bg)
        root.minsize(520, 640)
        root.geometry("560x720")
        if ICON.exists():
            self.icon = tk.PhotoImage(file=str(ICON))
            root.iconphoto(True, self.icon)
        self._build()
        self.refresh()
        root.after(300, self._ensure_service)
        root.after(1000, self._poll)

    def _build(self):
        f = self.fonts
        header = GradientBar(self.root, height=96)
        header.pack(fill="x")
        if LOGO.exists():
            self.logo = tk.PhotoImage(file=str(LOGO)).subsample(5)
            header.create_image(26, 48, image=self.logo, anchor="w")
        header.create_text(92, 38, text="TapBook Sync", font=f.title, fill="#ffffff", anchor="w")
        header.create_text(93, 64, text=f"Sincronizzazione della cartella · versione {__version__}",
                           font=f.subtitle, fill="#e3edff", anchor="w")
        body = tk.Frame(self.root, bg=Palette.bg)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        card = Card(body, f, "Stato")
        card.pack(fill="x")
        row = tk.Frame(card.body, bg=Palette.surface)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=14, height=14, bg=Palette.surface, highlightthickness=0)
        self.dot.pack(side="left")
        self.state_label = tk.Label(row, font=f.big, fg=Palette.text, bg=Palette.surface)
        self.state_label.pack(side="left", padx=(8, 0))
        self.pause_button = RoundButton(row, "Pausa", self.toggle_pause, f, "soft", width=110)
        self.pause_button.pack(side="right")
        self.message = tk.Label(card.body, font=f.small, fg=Palette.text_2, bg=Palette.surface, anchor="w",
                                justify="left")
        auto_wrap(self.message).pack(fill="x", pady=(8, 0))
        self.confirm_row = tk.Frame(card.body, bg=Palette.surface)
        RoundButton(self.confirm_row, "Elimina comunque", self.confirm_deletions, f, "danger").pack(side="left")
        RoundButton(self.confirm_row, "Metti in pausa", self.pause, f, "soft").pack(side="left", padx=8)
        buttons = tk.Frame(card.body, bg=Palette.surface)
        buttons.pack(fill="x", pady=(10, 0))
        self.sync_button = RoundButton(buttons, "Sincronizza ora", self.sync_now, f, "ghost")
        self.sync_button.pack(side="left")

        card = Card(body, f, "Server")
        card.pack(fill="x", pady=(14, 0))
        self.server_label = tk.Label(card.body, font=f.body, fg=Palette.text, bg=Palette.surface, anchor="w",
                                     justify="left")
        auto_wrap(self.server_label).pack(fill="x")
        buttons = tk.Frame(card.body, bg=Palette.surface)
        buttons.pack(fill="x", pady=(10, 0))
        self.pair_button = RoundButton(buttons, "Collega…", self.pair, f, "primary")
        self.pair_button.pack(side="left")
        self.unpair_button = RoundButton(buttons, "Scollega", self.unpair, f, "soft")
        self.unpair_button.pack(side="left", padx=8)
        self.web_button = RoundButton(buttons, "Apri TapBook", self.open_web, f, "ghost")
        self.web_button.pack(side="left")

        card = Card(body, f, "Cartella sincronizzata")
        card.pack(fill="x", pady=(14, 0))
        self.folder_label = tk.Label(card.body, font=f.body, fg=Palette.text, bg=Palette.surface, anchor="w",
                                     justify="left")
        auto_wrap(self.folder_label).pack(fill="x")
        buttons = tk.Frame(card.body, bg=Palette.surface)
        buttons.pack(fill="x", pady=(10, 0))
        RoundButton(buttons, "Scegli…", self.choose_folder, f, "soft").pack(side="left")
        self.open_folder_button = RoundButton(buttons, "Apri la cartella", self.open_folder, f, "ghost")
        self.open_folder_button.pack(side="left", padx=8)

        card = Card(body, f, "Attività")
        card.pack(fill="both", expand=True, pady=(14, 0))
        self.log = tk.Text(card.body, height=8, font=f.mono, bg=Palette.surface_2, fg=Palette.text_2,
                           relief="flat", bd=8, wrap="word", highlightthickness=0, state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("warn", foreground="#a5790a")
        self.log.tag_configure("error", foreground=Palette.danger)
        tk.Label(self.root, text="Chiudendo la finestra la sincronizzazione continua in background.",
                 font=f.small, fg=Palette.muted, bg=Palette.bg).pack(pady=(0, 12))

    # --- actions -----------------------------------------------------------------------------------
    def _save(self):
        settings.save(self.cfg)
        self.refresh()

    def pair(self):
        dialog = PairDialog(self.root, self.fonts, self.cfg)
        dialog.grab_set()
        self.root.wait_window(dialog)
        if dialog.result:
            self.cfg.update(dialog.result)
            if not self.cfg["folder"]:
                self.cfg["folder"] = settings.default_folder()
                Path(self.cfg["folder"]).mkdir(parents=True, exist_ok=True)
            self._save()
            self._ensure_service()

    def unpair(self):
        token = settings.load_token()
        if token and self.cfg["server"]:
            try:
                Connection(self.cfg["server"], token).unpair()
            except (Offline, ApiError, UntrustedCertificate, ValueError):
                pass                       # revoked on the server anyway with «tapbook device revoke»
        settings.save_token(None)
        self._save()

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="Cartella da sincronizzare",
                                         initialdir=self.cfg["folder"] or str(Path.home()), mustexist=False)
        if folder:
            self.cfg["folder"] = str(Path(folder))
            Path(folder).mkdir(parents=True, exist_ok=True)
            self._save()

    def toggle_pause(self):
        self.cfg["paused"] = not self.cfg["paused"]
        self._save()

    def pause(self):
        self.cfg["paused"] = True
        self._save()

    def sync_now(self):
        settings.send_control(sync=True, confirm=False)

    def confirm_deletions(self):
        settings.send_control(confirm=True, sync=True)

    def open_web(self):
        if self.cfg["server"]:
            webbrowser.open(self.cfg["server"])

    def open_folder(self):
        if self.cfg["folder"] and Path(self.cfg["folder"]).is_dir():
            open_path(self.cfg["folder"])

    def _ensure_service(self):
        if not running():
            try:
                install_autostart()
            except OSError:
                start_detached()

    # --- display -----------------------------------------------------------------------------------
    def refresh(self):
        cfg = self.cfg
        paired = bool(settings.load_token() and cfg["server"])
        if paired:
            self.server_label.config(text=f"{cfg['server']}\nCollegato come «{cfg['username']}» "
                                          f"(questo computer: {cfg['device'] or settings.default_device_name()})")
        else:
            self.server_label.config(text="Nessun server collegato.")
        self.pair_button.configure_button(text="Ricollega…" if paired else "Collega…")
        self.unpair_button.configure_button(enabled=paired)
        self.web_button.configure_button(enabled=bool(cfg["server"]))
        self.folder_label.config(text=cfg["folder"] or "Nessuna cartella scelta.")
        self.open_folder_button.configure_button(enabled=bool(cfg["folder"]))
        self.pause_button.configure_button(text="Riprendi" if cfg["paused"] else "Pausa")

    def _poll(self):
        status = settings.read_json(settings.status_path(), {})
        alive = running()
        state = status.get("state", "starting") if alive else "stopped"
        text, color = STATES.get(state, STATES["error"])
        self.state_label.config(text=text)
        self.dot.delete("all")
        self.dot.create_oval(2, 2, 12, 12, fill=color, outline=color)
        message = status.get("message", "") if alive else "Il servizio non è in esecuzione: lo avvio…"
        if status.get("last") and state in ("ok", "warn", "offline"):
            message += f"\nUltima sincronizzazione: {time.strftime('%H:%M:%S', time.localtime(status['last']))}"
        for note in status.get("notes") or []:
            message += f"\n• {note}"
        self.message.config(text=message)
        if state == "confirm":
            self.confirm_row.pack(fill="x", pady=(10, 0))
        else:
            self.confirm_row.pack_forget()
        lines = [(time.strftime("%H:%M:%S", time.localtime(r["t"])) + "  " + r["text"], r.get("level", "info"))
                 for r in status.get("recent") or []]
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        for line, level in reversed(lines):
            self.log.insert("end", line + "\n", level)
        self.log.config(state="disabled")
        if not alive:
            self._ensure_service()
        self.root.after(1000, self._poll)


def main(check=False):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk(className="TapBookSync")
    if check:
        root.withdraw()
        window = SyncWindow.__new__(SyncWindow)
        window.root, window.fonts, window.cfg = root, Fonts(root), settings.load()
        window._build()
        window.refresh()
        root.update()
        root.destroy()
        return
    SyncWindow(root)
    root.mainloop()
