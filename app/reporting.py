"""Server messages: plain text in the terminal, or JSON events for the
control panel (the TapBook window), which starts the server and reads its output.

Each JSON event is one line: {"event": "started" | "log" | "ready" | "stopped", ...}.
"""
import json
import sys
import threading


class TerminalReporter:
    def say(self, text: str, level: str = "info"):
        print(f"  {text}", flush=True)

    def started(self, info: dict):
        print("\n  Server TapBook avviato.")
        print(f"  Cartella documenti: {info['notes_root']}")
        print(f"  Registrazione dal web: {'attiva' if info['registration'] else 'disattivata'}")
        if info["first_user"]:
            print("  Nessun utente ancora: apri l'indirizzo qui sotto e crea il primo account.")
        print(f"  Su questo computer:  {info['local_url']}")
        for url in info["ipad_urls"]:
            print(f"  Dall'iPad (stessa rete Wi-Fi):  {url}")
        if info["https"]:
            print("  Connessione cifrata (HTTPS). Su ogni iPad, la prima volta: apri l'indirizzo,")
            print("  conferma l'avviso di Safari e tocca «Installa il certificato» nella pagina di accesso.")

    def ready(self):
        print("  Ctrl+C per fermare.\n", flush=True)

    def stopped(self):
        print("\n  Server fermato.", flush=True)


class JsonReporter:
    def __init__(self):
        self.lock = threading.Lock()

    def _emit(self, **event):
        with self.lock:
            sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def say(self, text: str, level: str = "info"):
        self._emit(event="log", text=text, level=level)

    def started(self, info: dict):
        self._emit(event="started", **info)

    def ready(self):
        self._emit(event="ready")

    def stopped(self):
        self._emit(event="stopped")


def level_of(line: str) -> str:
    return "warn" if line.startswith("ATTENZIONE") else "info"
