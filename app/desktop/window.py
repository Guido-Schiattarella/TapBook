"""Control panel — the window.

It does graphically what is otherwise done from the terminal: starts and stops
the server, asks for the administrator password for the firewall (on Linux; on
Windows there is the Windows prompt), shows the address to open on the iPad
and the server messages. Only the server tells its state, through its events
(process.py): the window displays them.
"""
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

from .. import __version__
from ..system import updates
from .process import ServerProcess, check_password, password_needed
from .theme import Card, Fonts, GradientBar, Palette, RoundButton, auto_wrap

LOGO = Path(__file__).resolve().parent.parent / "view" / "static" / "img" / "logo.png"
ICON = LOGO.with_name("favicon.png")
STATES = {
    #            text                   dot colour
    "stopped": ("Spento", Palette.muted),
    "checking": ("Verifica della password…", Palette.warn),
    "starting": ("Avvio in corso…", Palette.warn),
    "running": ("Acceso", Palette.ok),
    "stopping": ("Arresto in corso…", Palette.warn),
    "error": ("Non avviato", Palette.danger),
}
STOP_TIMEOUT_MS = 30000
DIALOG_WIDTH = 460


def open_path(path: str):
    if os.name == "nt":
        os.startfile(path)                                  # noqa: S606 — cartella dei documenti
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


class Dialog(tk.Toplevel):
    """Modal dialog in the panel's style (title, text, buttons)."""

    def __init__(self, parent, fonts, title, text):
        super().__init__(parent, bg=Palette.bg)
        self.fonts, self.result = fonts, None
        self.title(title)
        self.minsize(DIALOG_WIDTH, 10)          # larghezza fissa; l'altezza segue i contenuti
        self.resizable(False, False)
        self.transient(parent)
        card = Card(self, fonts, title)
        card.pack(fill="both", expand=True, padx=16, pady=16)
        self.body = card.body
        # Fixed-width dialog: the text wraps within that width.
        tk.Label(self.body, text=text, font=fonts.body, fg=Palette.text_2, bg=Palette.surface,
                 justify="left", anchor="w", wraplength=DIALOG_WIDTH - 80).pack(fill="x")
        self.buttons = tk.Frame(self.body, bg=Palette.surface)
        self.bind("<Escape>", lambda e: self.close(None))
        self.protocol("WM_DELETE_WINDOW", lambda: self.close(None))

    def add_buttons(self, cancel_text, ok_text, ok_style="primary"):
        self.buttons.pack(fill="x", pady=(16, 0))
        self.ok = RoundButton(self.buttons, ok_text, self.confirm, self.fonts, ok_style)
        self.ok.pack(side="right")
        RoundButton(self.buttons, cancel_text, lambda: self.close(None), self.fonts, "soft").pack(side="right", padx=8)

    def confirm(self):
        self.close(True)

    def close(self, result):
        self.result = result
        self.grab_release()
        self.destroy()

    def run(self):
        self.update_idletasks()
        parent = self.master
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.wait_visibility()
        self.grab_set()
        self.wait_window()
        return self.result


class PasswordDialog(Dialog):
    """Administrator password (Linux). It is checked with sudo before starting the
    server; it stays in memory only and reaches the server through a pipe."""

    def __init__(self, parent, fonts):
        super().__init__(parent, fonts, "Password di amministratore",
                         "Il firewall del computer è attivo. Per far collegare l'iPad TapBook apre la porta "
                         "solo per la rete di casa e solo finché il server è acceso: inserisci la password "
                         "di amministratore. Non viene salvata.")
        self.var = tk.StringVar()
        frame = tk.Frame(self.body, bg=Palette.border, padx=1, pady=1)      # input border as on the web
        frame.pack(fill="x", pady=(14, 0))
        self.entry = tk.Entry(frame, textvariable=self.var, show="•", font=fonts.body, relief="flat", bd=8,
                              bg=Palette.surface_2, fg=Palette.text, insertbackground=Palette.text,
                              highlightthickness=0)
        self.entry.pack(fill="x")
        # Light-blue border while typing, like the web form fields.
        self.entry.bind("<FocusIn>", lambda e: frame.config(bg=Palette.accent))
        self.entry.bind("<FocusOut>", lambda e: frame.config(bg=Palette.border))
        self.error = tk.Label(self.body, text="", font=fonts.small, fg=Palette.danger, bg=Palette.surface, anchor="w")
        self.error.pack(fill="x", pady=(6, 0))
        self.add_buttons("Annulla", "Conferma")
        self.entry.bind("<Return>", lambda e: self.confirm())
        self.after(50, self.entry.focus_set)

    def confirm(self):
        password = self.var.get()
        if not password:
            return
        self.ok.configure_button(text="Verifica…", enabled=False)
        self.error.config(text="")

        def verify():
            ok = check_password(password)
            self.after(0, lambda: self._verified(ok, password))
        threading.Thread(target=verify, daemon=True).start()

    def _verified(self, ok, password):
        if ok:
            self.var.set("")
            self.close(password)
        else:
            self.ok.configure_button(text="Conferma", enabled=True)
            self.error.config(text="Password di amministratore errata.")
            self.entry.select_range(0, "end")
            self.entry.focus_set()


class ControlPanel:
    def __init__(self, root: tk.Tk, config, check_updates: bool = True):
        self.root, self.config = root, config
        self.fonts = Fonts(root)
        self.server = ServerProcess()
        self.state = "stopped"
        self.info = {}
        self.closing = False
        root.title("TapBook")
        root.configure(bg=Palette.bg)
        root.minsize(520, 600)
        root.geometry("560x700")
        if ICON.exists():
            self.icon = tk.PhotoImage(file=str(ICON))
            root.iconphoto(True, self.icon)
        self._build()
        self._show_state()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll)
        if check_updates:
            threading.Thread(target=self._check_updates, daemon=True).start()

    # --- layout ---------------------------------------------------------------------
    def _build(self):
        f = self.fonts
        header = GradientBar(self.root, height=96)
        header.pack(fill="x")
        if LOGO.exists():
            self.logo = tk.PhotoImage(file=str(LOGO)).subsample(5)
            header.create_image(26, 48, image=self.logo, anchor="w")
        header.create_text(92, 38, text="TapBook", font=f.title, fill="#ffffff", anchor="w")
        header.create_text(93, 64, text=f"Pannello del server · versione {__version__}", font=f.subtitle,
                           fill="#e3edff", anchor="w")

        body = tk.Frame(self.root, bg=Palette.bg)
        body.pack(fill="both", expand=True, padx=20, pady=16)

        # Update available (shown only when a newer Release exists)
        self.update_card = Card(body, f, "Aggiornamento disponibile")
        self.update_title = tk.Label(self.update_card.body, font=f.bold, fg=Palette.accent, bg=Palette.surface,
                                     anchor="w", justify="left")
        auto_wrap(self.update_title).pack(fill="x")
        self.update_notes = tk.Label(self.update_card.body, font=f.small, fg=Palette.text_2, bg=Palette.surface,
                                     anchor="w", justify="left")
        auto_wrap(self.update_notes).pack(fill="x", pady=(4, 0))
        row = tk.Frame(self.update_card.body, bg=Palette.surface)
        row.pack(fill="x", pady=(10, 0))
        RoundButton(row, "Scarica l'aggiornamento", self.open_update, f, "primary").pack(side="left")
        RoundButton(row, "Più tardi", self.hide_update, f, "soft").pack(side="left", padx=8)
        self.update_url = None

        # Server: state and main button
        card = Card(body, f, "Server")
        card.pack(fill="x")
        self.server_card = card
        row = tk.Frame(card.body, bg=Palette.surface)
        row.pack(fill="x")
        self.dot = tk.Canvas(row, width=14, height=14, bg=Palette.surface, highlightthickness=0)
        self.dot.pack(side="left")
        self.state_label = tk.Label(row, font=f.big, fg=Palette.text, bg=Palette.surface)
        self.state_label.pack(side="left", padx=(8, 0))
        self.main_button = RoundButton(row, "Avvia il server", self.toggle, f, "primary", width=170)
        self.main_button.pack(side="right")
        self.hint = tk.Label(card.body, font=f.small, fg=Palette.muted, bg=Palette.surface, anchor="w",
                             justify="left")
        auto_wrap(self.hint).pack(fill="x", pady=(10, 0))

        # Connection from the iPad
        card = Card(body, f, "Collegamento dall'iPad")
        card.pack(fill="x", pady=(14, 0))
        self.url_label = tk.Label(card.body, font=f.big, fg=Palette.accent, bg=Palette.surface, anchor="w")
        self.url_label.pack(fill="x")
        self.url_note = tk.Label(card.body, font=f.small, fg=Palette.muted, bg=Palette.surface, anchor="w",
                                 justify="left")
        auto_wrap(self.url_note).pack(fill="x", pady=(4, 0))
        buttons = tk.Frame(card.body, bg=Palette.surface)
        buttons.pack(fill="x", pady=(12, 0))
        self.copy_button = RoundButton(buttons, "Copia indirizzo", self.copy_url, f, "soft")
        self.copy_button.pack(side="left")
        self.open_button = RoundButton(buttons, "Apri su questo PC", self.open_local, f, "soft")
        self.open_button.pack(side="left", padx=8)

        # Information
        card = Card(body, f, "Informazioni")
        card.pack(fill="x", pady=(14, 0))
        grid = tk.Frame(card.body, bg=Palette.surface)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        self.rows = {}
        for i, (key, label) in enumerate((("folder", "Documenti"), ("firewall", "Firewall"),
                                          ("registration", "Registrazione"))):
            tk.Label(grid, text=label, font=f.bold, fg=Palette.text_2, bg=Palette.surface, anchor="nw"
                     ).grid(row=i, column=0, sticky="nw", pady=3, padx=(0, 14))
            value = tk.Label(grid, font=f.body, fg=Palette.text, bg=Palette.surface, anchor="w",
                             justify="left")
            auto_wrap(value).grid(row=i, column=1, sticky="we", pady=3)
            self.rows[key] = value
        self.rows["folder"].config(text=str(self.config.notes_root))
        self.rows["firewall"].config(text="—")
        self.rows["registration"].config(text="attiva" if self.config.allow_registration else "disattivata")
        RoundButton(card.body, "Apri la cartella dei documenti", self.open_folder, f, "ghost"
                    ).pack(anchor="w", pady=(8, 0))

        # Server messages
        card = Card(body, f, "Messaggi")
        card.pack(fill="both", expand=True, pady=(14, 0))
        self.log = tk.Text(card.body, height=7, font=f.mono, bg=Palette.surface_2, fg=Palette.text_2,
                           relief="flat", bd=8, wrap="word", highlightthickness=0, state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("warn", foreground="#a5790a")
        self.log.tag_configure("error", foreground=Palette.danger)

        tk.Label(self.root, text="Chiudendo la finestra il server si ferma e la porta del firewall si richiude.",
                 font=f.small, fg=Palette.muted, bg=Palette.bg).pack(pady=(0, 12))

    # --- state ------------------------------------------------------------------------
    def _show_state(self):
        text, color = STATES[self.state]
        self.state_label.config(text=text)
        self.dot.delete("all")
        self.dot.create_oval(2, 2, 12, 12, fill=color, outline=color)
        running = self.state == "running"
        busy = self.state in ("checking", "starting", "stopping")
        if self.state in ("running", "starting"):
            self.main_button.configure_button("Ferma il server", "danger", enabled=self.state == "running")
        else:
            self.main_button.configure_button("Avvia il server", "primary", enabled=not busy)
        hints = {
            "stopped": "Avvia il server per scrivere sui tuoi documenti dall'iPad.",
            "checking": "Controllo la password con sudo…",
            "starting": "Avvio del server e apertura della porta nel firewall…",
            "running": "Le note sono raggiungibili dall'iPad sulla rete di casa.",
            "stopping": "Salvo i documenti aperti e richiudo la porta del firewall…",
            "error": "Il server non è partito: i dettagli sono nei messaggi qui sotto.",
        }
        self.hint.config(text=hints[self.state])
        urls = self.info.get("ipad_urls") or []
        if running and urls:
            self.url_label.config(text=urls[0], fg=Palette.accent)
            note = "Aprilo in Safari sull'iPad, sulla stessa rete Wi-Fi."
            if self.info.get("https"):
                note += " La prima volta installa il certificato dalla pagina di accesso."
            if self.info.get("first_user"):
                note += " Nessun utente ancora: crea il primo account dalla pagina che si apre."
            self.url_note.config(text=note)
        elif running:
            self.url_label.config(text=self.info.get("local_url", ""), fg=Palette.accent)
            self.url_note.config(text="Server raggiungibile solo da questo computer (host = 127.0.0.1).")
        else:
            self.url_label.config(text="—", fg=Palette.muted)
            self.url_note.config(text="L'indirizzo compare quando il server è acceso.")
        self.copy_button.configure_button(enabled=running)
        self.open_button.configure_button(enabled=running)

    def _set_state(self, state):
        self.state = state
        self._show_state()

    def _log(self, text, level="info"):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n", level if level in ("warn", "error") else ())
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 500:
            self.log.delete("1.0", f"{lines - 500}.0")
        self.log.see("end")
        self.log.config(state="disabled")

    # --- actions ----------------------------------------------------------------------
    def toggle(self):
        if self.state == "running":
            self.stop()
        elif self.state in ("stopped", "error"):
            self.start()

    def start(self):
        password = None
        if password_needed(self.config):
            password = PasswordDialog(self.root, self.fonts).run()
            if password is None:
                self._set_state("stopped")
                return
        self.info = {}
        self.rows["firewall"].config(text="—")
        self._log("Avvio del server…")
        self._set_state("starting")
        try:
            self.server.start(password)
        except OSError as e:
            self._log(f"Impossibile avviare il server: {e}", "error")
            self._set_state("error")

    def stop(self):
        self._set_state("stopping")
        self._log("Arresto del server…")
        self.server.stop()
        self.root.after(STOP_TIMEOUT_MS, self._force_stop)

    def _force_stop(self):
        if self.server.running and self.state == "stopping":
            self._log("Il server non risponde: lo chiudo.", "warn")
            self.server.kill()

    # --- updates -------------------------------------------------------------------------
    def _check_updates(self):
        """Checks GitHub in a thread: the window never waits for the network."""
        release = updates.check(self.config)
        if release:
            self.root.after(0, lambda: self._show_update(release))

    def _show_update(self, release):
        self.update_url = release["url"]
        self.update_title.config(text=f"È disponibile TapBook {release['version']} (installata: {release['current']}).")
        self.update_notes.config(text=(release["notes"] + "\n\n" if release["notes"] else "") +
                                 "Scarica il pacchetto, chiudi TapBook e avvia di nuovo l'installer: "
                                 "documenti, account e impostazioni restano.")
        self.update_card.pack(fill="x", pady=(0, 14), before=self.server_card)
        # The window grows by the height of the box, so the rest is not squeezed.
        self.root.update_idletasks()
        height = self.root.winfo_height() + self.update_card.winfo_reqheight() + 14
        self.root.geometry(f"{self.root.winfo_width()}x{min(height, self.root.winfo_screenheight() - 60)}")

    def open_update(self):
        if self.update_url:
            webbrowser.open(self.update_url)

    def hide_update(self):
        self.update_card.pack_forget()

    def copy_url(self):
        url = self.url_label.cget("text")
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.copy_button.configure_button(text="Copiato ✓")
        self.root.after(1500, lambda: self.copy_button.configure_button(text="Copia indirizzo"))

    def open_local(self):
        if self.info.get("local_url"):
            webbrowser.open(self.info["local_url"])

    def open_folder(self):
        folder = self.config.notes_root
        folder.mkdir(parents=True, exist_ok=True)
        open_path(str(folder))

    # --- server events ----------------------------------------------------------------
    def _poll(self):
        while not self.server.events.empty():
            self._handle(self.server.events.get())
        self.root.after(100, self._poll)

    def _handle(self, event):
        kind = event.get("event")
        if kind == "started":
            self.info = event
            self._show_state()
        elif kind == "log":
            text, level = event.get("text", ""), event.get("level", "info")
            self._log(text, level)
            if text.startswith(("Firewall", "ATTENZIONE, firewall")) or "firewall" in text.lower():
                self.rows["firewall"].config(text=text.replace("Firewall: ", "", 1),
                                             fg=Palette.danger if level != "info" else Palette.text)
        elif kind == "ready":
            self._set_state("running")
            self._log("Server acceso.")
        elif kind == "stopped":
            self._log("Server fermato.")
        elif kind == "exit":
            failed = event.get("code") not in (0, None) and self.state != "stopping"
            self._set_state("error" if failed else "stopped")
            if self.closing:
                self.root.destroy()

    def on_close(self):
        if self.state in ("stopped", "error") or not self.server.running:
            self.root.destroy()
            return
        dialog = Dialog(self.root, self.fonts, "Il server è acceso",
                        "Chiudendo la finestra il server si ferma: i documenti aperti vengono salvati e la "
                        "porta del firewall si richiude.")
        dialog.add_buttons("Annulla", "Ferma e chiudi", "danger")
        if dialog.run():
            self.closing = True
            if self.state != "stopping":
                self.stop()
