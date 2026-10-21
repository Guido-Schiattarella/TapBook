"""Control panel — the server as a separate process.

The panel does not contain the server: it starts it with
`python -m app serve --controlled` and reads its JSON events line by line. A
frozen window cannot freeze the server and vice versa, and the server always
shuts down in the same orderly way (firewall closed, documents saved), whether
started from the terminal or from the panel.

Communication with the server, entirely through its standard input/output:
  * first line written: the administrator password (empty if not needed);
  * "stop": orderly shutdown; closing the pipe shuts it down too;
  * lines read: JSON events (started, log, ready, stopped) or plain text.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from ..config import PROJECT_DIR

CREATE_NO_WINDOW = 0x08000000
LOCAL_ONLY = ("127.0.0.1", "localhost", "::1")


def _python_console() -> str:
    """Interpreter for the server: on Windows the panel runs with pythonw.exe (no
    black console window), but the server needs python.exe to write its messages."""
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


# --- administrator password (Linux) ---------------------------------------------------
def password_needed(config) -> bool:
    """On Linux the administrator password is needed to open the port in the
    firewall, if one is active. On Windows, Windows itself asks (UAC prompt)."""
    if not sys.platform.startswith("linux") or config.firewall == "off" or config.host in LOCAL_ONLY:
        return False
    if not shutil.which("sudo"):
        return False
    from ..system.firewall.linux import active_firewalls
    return config.firewall == "on" or bool(active_firewalls())


def check_password(password: str) -> bool:
    """Checks the password with sudo without running anything useful (`true`) and
    without sudo remembering it (-k). The password goes through a pipe, never on the command line."""
    try:
        out = subprocess.run(["sudo", "-S", "-k", "-p", "", "true"], input=password + "\n",
                             capture_output=True, text=True, timeout=20, start_new_session=True)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


# --- server process ----------------------------------------------------------------------
class ServerProcess:
    def __init__(self):
        self.proc = None
        self.events = queue.Queue()          # read by the window (main thread)

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, password: str | None = None):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        extra = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
        self.proc = subprocess.Popen(
            [_python_console(), "-m", "app", "serve", "--controlled"], cwd=PROJECT_DIR, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **extra)
        self.proc.stdin.write((password or "") + "\n")
        self.proc.stdin.flush()
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or "event" not in event:
                    raise ValueError
            except ValueError:
                # Plain text (e.g. "Database degli utenti creato") or an unexpected error.
                level = "error" if line.startswith(("Traceback", "Error", "Errore")) else "info"
                event = {"event": "log", "text": line, "level": level}
            self.events.put(event)
        self.events.put({"event": "exit", "code": proc.wait()})

    def stop(self):
        """Orderly shutdown: the server closes the firewall port and saves the documents."""
        if self.running:
            try:
                self.proc.stdin.write("stop\n")
                self.proc.stdin.flush()
                self.proc.stdin.close()
            except (OSError, ValueError):
                pass

    def kill(self):
        if self.running:
            self.proc.kill()
