"""TapBook Sync — the background service.

It runs on its own (started at login, see `install_autostart`) and:
  * is told by the operating system when the folder changes (watcher.py); where
    that is not possible it looks every LOCAL_CHECK seconds (sizes and times only);
  * keeps a request open towards the server that answers as soon as something
    changes there (notes written on the iPad, a new document);
  * when either side changed, runs a round of the engine (engine.py), which asks
    the server only for what changed since the previous round;
  * writes what it is doing to status.json, which the window shows, and reads
    the window's requests from control.json (sync now, confirm deletions);
  * re-reads config.json when the window changes it (server, folder, pause).
Network problems are not errors: it waits and tries again.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import settings
from .api import ApiError, Connection, Offline, UntrustedCertificate
from .engine import Engine, FolderMissing, local_stamp
from .watcher import Watcher

LOCAL_CHECK = 2.0          # seconds between looks at the folder (when the system cannot watch it)
SAFETY_LOOK = 60.0         # with the system watching: a complete look anyway, in case an event was lost
QUIET = 0.5                # wait until the folder has been still this long (a copy in progress)
SETTLE = 1.0               # files still being written: looked at again after this
FULL_ROUND = 300           # a complete round anyway every 5 minutes
RETRY = 10                 # seconds before trying again after a network problem
RECENT = 40                # activity lines kept for the window
SERVICE_NAME = "tapbook-sync"


class SingleInstance:
    """Only one service at a time for the same user (a lock held by the process)."""

    def __init__(self):
        self.path = settings.config_dir() / "service.lock"
        self.fh = None

    def acquire(self) -> bool:
        self.fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False


def running() -> bool:
    """Is a service running for this user?"""
    probe = SingleInstance()
    if probe.acquire():
        probe.fh.close()
        return False
    return True


class Service:
    def __init__(self):
        self.recent = []
        self.status = {"state": "starting", "message": "Avvio…"}
        self.wake = threading.Event()
        self.remote_cursor = None
        self.watch_key = None
        self.last_engine = None
        self.local_dirty = 0.0               # when the folder last changed (from the Watcher)
        self.remote_dirty = False
        self.watching = False

    # --- status for the window ---------------------------------------------------------------------
    def say(self, text, level="info"):
        self.recent.append({"t": time.time(), "text": text, "level": level})
        del self.recent[:-RECENT]
        self.publish()

    def set(self, state, message, **extra):
        status = {"state": state, "message": message, **extra}
        if status != self.status:          # the same state is not written again every 2 seconds
            self.status = status
            self.publish()

    def publish(self):
        try:
            settings.write_json(settings.status_path(), {**self.status, "recent": self.recent, "pid": os.getpid(),
                                                         "updated": time.time()})
        except OSError:
            pass

    # --- watching the server and the folder ----------------------------------------------------------
    def _watch_remote(self):
        """Keeps a request open towards the server; wakes the main loop when
        something changes there."""
        cursor = None
        while True:
            key = self.watch_key
            if key is None:
                time.sleep(1)
                continue
            server, token = key
            try:
                answer = Connection(server, token).changes(cursor, wait=True)
                if key != self.watch_key:
                    continue
                if answer.get("full") or answer.get("changes"):
                    self.remote_dirty = True
                    self.wake.set()
                cursor = answer.get("cursor")
            except (Offline, ApiError, UntrustedCertificate, ValueError):
                cursor = None
                time.sleep(RETRY)

    def _local_changed(self):
        """Called by the Watcher when something changes in the folder."""
        self.local_dirty = time.monotonic()
        self.wake.set()

    # --- main loop ---------------------------------------------------------------------------------------
    def run(self):
        threading.Thread(target=self._watch_remote, daemon=True, name="server").start()
        last_local, last_round, last_look, control_seen = None, 0.0, 0.0, time.time()
        config_stamp, retry_at, watcher, watched = None, None, None, None
        cfg = settings.load()
        while True:
            # Settings changed by the window
            stamp = _mtime(settings.config_dir() / "config.json"), _mtime(settings.token_path())
            if stamp != config_stamp:
                config_stamp, cfg = stamp, settings.load()
                last_local, last_round = None, 0.0
            token = settings.load_token()
            control = settings.read_json(settings.control_path(), {})
            fresh = float(control.get("at") or 0) > control_seen
            if fresh:
                control_seen = float(control["at"])
            if not (cfg["server"] and cfg["folder"] and token):
                self.watch_key = None
                self.set("setup", "Da configurare: apri TapBook Sync e collega il server e la cartella.")
                self._sleep(LOCAL_CHECK)
                continue
            self.watch_key = (cfg["server"], token)
            if cfg["paused"]:
                self.set("paused", "In pausa.")
                self._sleep(LOCAL_CHECK)
                continue
            root = Path(cfg["folder"])
            if watched != root:               # (another) folder: the system watches it for us
                if watcher:
                    watcher.stop()
                watcher = Watcher(root, self._local_changed)
                self.watching = root.is_dir() and watcher.start()
                # Without the folder (disk unplugged) it is tried again when it is back;
                # if the system refuses to watch it, the folder is looked at every few seconds.
                watched = root if root.is_dir() else None
            now = time.monotonic()
            if self.local_dirty and now - self.local_dirty < QUIET:
                self._sleep(QUIET)            # changes still arriving (a copy in progress)
                continue
            local_changed = bool(self.local_dirty)
            if not local_changed and now - last_look >= (SAFETY_LOOK if self.watching else LOCAL_CHECK):
                last_look = now
                local_changed = local_stamp(root) != last_local
            due = (local_changed or self.remote_dirty or (retry_at is not None and now >= retry_at)
                   or time.time() - last_round > FULL_ROUND
                   or (fresh and (control.get("sync") or control.get("confirm"))))
            if not due:
                self._sleep(1.0 if retry_at else (SAFETY_LOOK if self.watching else LOCAL_CHECK))
                continue
            self.local_dirty, self.remote_dirty = 0.0, False
            self.wake.clear()
            confirmed = bool(fresh and control.get("confirm"))
            delay, again = self.round(cfg, token, root, confirmed)
            # Files still being written: another round as soon as they settle.
            retry_at = time.monotonic() + SETTLE if again else None
            last_local, last_round, last_look = local_stamp(root), time.time(), time.monotonic()
            if not root.is_dir():
                watched = None                # the folder went away: watched again when it is back
            self._sleep(delay)

    def _sleep(self, seconds):
        self.wake.wait(seconds)

    def round(self, cfg, token, root: Path, confirmed: bool) -> tuple[float, bool]:
        """One synchronisation; returns how long to wait before the next check and
        whether files were left for later (still being written)."""
        delay = self._round(cfg, token, root, confirmed)
        return delay, bool(self.last_engine and self.last_engine.unsettled)

    def _round(self, cfg, token, root: Path, confirmed: bool) -> float:
        state_file = settings.state_path(cfg)
        state = settings.read_json(state_file, {})
        conn = Connection(cfg["server"], token)
        engine = self.last_engine = Engine(root, conn, state, cfg["device"] or settings.default_device_name(),
                                           self.say)
        try:
            self.set("syncing", "Sincronizzazione in corso…")
            done = [0]

            def step():
                done[0] += 1
                if done[0] % 5 == 0:
                    self.set("syncing", f"Sincronizzazione in corso… ({done[0]} operazioni)")
            _, skipped = engine.sync(confirmed, step)
            engine.clean_trash()
        except FolderMissing:
            self.set("error", f"La cartella {root} non esiste più (disco scollegato o cartella spostata?). "
                              "Non viene cancellato niente sul server: ricollegala o scegline un'altra.")
            return RETRY
        except UntrustedCertificate:
            self.set("error", "Il certificato del server non è più quello confermato: ricollega il server "
                              "dalla finestra di TapBook Sync.")
            return RETRY * 3
        except Offline:
            self.set("offline", "Server non raggiungibile: riprovo tra poco.", last=self.status.get("last"))
            return RETRY
        except ApiError as e:
            if e.status == 401:
                self.set("error", "Questo computer non è più autorizzato (scollegato dal server o password "
                                  "cambiata): ricollegalo dalla finestra di TapBook Sync.")
                return RETRY * 3
            self.set("error", f"Il server ha risposto: {e}")
            return RETRY
        finally:
            try:
                settings.write_json(state_file, state)
            except OSError:
                pass
        notes = []
        if skipped:
            notes.append(f"{len(skipped)} elementi non sincronizzati per il nome (caratteri non ammessi, "
                         f"troppo lungo o riservato), per esempio «{skipped[0]}»")
        notes += engine.waiting[:5] + engine.errors[:5]
        if engine.pending_deletions:
            self.set("confirm", f"Stanno per essere eliminati {engine.pending_deletions} file. Per sicurezza "
                                "aspetto la tua conferma nella finestra di TapBook Sync.",
                     deletions=engine.pending_deletions, notes=notes, last=time.time())
            return LOCAL_CHECK
        if engine.errors:
            self.set("warn", "Sincronizzato, con alcuni problemi.", notes=notes, last=time.time())
        else:
            self.set("ok", "Tutto sincronizzato.", notes=notes, last=time.time())
        return LOCAL_CHECK


def _mtime(path: Path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def main():
    lock = SingleInstance()
    if not lock.acquire():
        print("TapBook Sync è già in esecuzione.")
        return
    service = Service()
    service.say("Servizio avviato.")
    try:
        service.run()
    except KeyboardInterrupt:
        pass


# --- automatic start -------------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

UNIT = """[Unit]
Description=TapBook Sync (sincronizzazione della cartella con TapBook Server)
After=network-online.target

[Service]
Type=simple
WorkingDirectory={project}
ExecStart={python} -m app.syncclient service
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""


def _python(windowless=False) -> str:
    folder = PROJECT_DIR / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    name = ("pythonw.exe" if windowless else "python.exe") if os.name == "nt" else "python"
    exe = folder / name
    return str(exe if exe.exists() else Path(sys.executable))


def _unit_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "systemd" / "user" / \
        f"{SERVICE_NAME}.service"


def _startup_script() -> Path:
    """Windows: a small script in the user's Startup folder."""
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "TapBook Sync.vbs"


def install_autostart(start=True):
    """The service starts at every login (and now, unless start is False)."""
    if os.name == "nt":
        script = _startup_script()
        script.parent.mkdir(parents=True, exist_ok=True)
        command = f'"{_python(True)}" -m app.syncclient service'
        script.write_text('Set s = CreateObject("WScript.Shell")\r\n'
                          f's.CurrentDirectory = "{PROJECT_DIR}"\r\n'
                          f's.Run "{command.replace(chr(34), chr(34) * 2)}", 0, False\r\n', encoding="utf-8")
        if start:
            start_detached()
        return
    unit = _unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(UNIT.format(project=PROJECT_DIR, python=_python()), encoding="utf-8")
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", SERVICE_NAME], check=True, capture_output=True)
        subprocess.run(["systemctl", "--user", "restart", SERVICE_NAME], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        # No systemd: the desktop's autostart (XDG), and start it now.
        unit.unlink(missing_ok=True)
        autostart = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"
        autostart.mkdir(parents=True, exist_ok=True)
        (autostart / "tapbook-sync.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=TapBook Sync\n"
            f"Exec=sh -c 'cd \"{PROJECT_DIR}\" && exec \"{_python()}\" -m app.syncclient service'\n"
            "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n", encoding="utf-8")
        start_detached()


def remove_autostart():
    if os.name == "nt":
        _startup_script().unlink(missing_ok=True)
        return
    subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE_NAME], capture_output=True)
    _unit_path().unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    (Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" /
     "tapbook-sync.desktop").unlink(missing_ok=True)


def start_detached():
    """Starts the service in the background if it is not running (e.g. from the window)."""
    if running():
        return
    kwargs = {"cwd": str(PROJECT_DIR), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200          # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    if os.name != "nt" and _unit_path().exists():
        if subprocess.run(["systemctl", "--user", "start", SERVICE_NAME], capture_output=True).returncode == 0:
            return
    subprocess.Popen([_python(True), "-m", "app.syncclient", "service"], **kwargs)
