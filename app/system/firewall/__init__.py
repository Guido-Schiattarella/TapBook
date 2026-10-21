"""Server port in the firewall, open only while the server is running.

Usage (app/server.py):

    guard = FirewallGuard(port, config.firewall, config.data_dir, say=reporter.say)
    for line in guard.open(server.prepare):   # starts listening and opens the port
        print(line)
    ...
    guard.close()                              # closes the port again

The administrator work is done by a separate helper, authorised at every start
with the administrator password (or confirmation), without installing anything:
  * Linux (linux.py + linux_helper.py): sudo, or pkexec without a terminal; rule
    in ufw/iptables, firewalld or nftables for the local network only;
  * Windows (windows.py + windows_helper.py): UAC prompt; Windows Defender
    Firewall rule for the local subnet only and for the server program only.
In both cases the helper closes the port when the server stops, even if it
stops abruptly (crash, killed process).
"""
import os
import sys

if sys.platform == "win32":
    from .windows import WindowsBackend as _Backend
else:
    from .linux import LinuxBackend as _Backend
from .linux import uninstall_old  # noqa: F401  (versioni precedenti, solo Linux)


def _print(text: str, level: str = "info"):
    print(f"  {text}", flush=True)


class FirewallGuard:
    """`say(text, level)` receives the messages to show (terminal or panel).
    `password`: the administrator password, if the control panel already asked
    for it (on Linux; on Windows the user confirms the Windows prompt)."""

    def __init__(self, port: int, mode: str, data_dir, say=_print, password: str | None = None):
        self.port, self.mode = port, mode
        self.backend = _Backend(port, mode, data_dir, say, password) if self._supported() else None

    @staticmethod
    def _supported() -> bool:
        return sys.platform == "win32" or sys.platform.startswith("linux")

    def open(self, listen) -> list[str]:
        """Starts the server listening (listen) and opens the port, in the right order
        for the system: on Linux the helper opens only for a process already
        listening; on Windows the rule must exist first, otherwise Windows shows its
        "Allow access?" prompt the first time the program starts listening."""
        if self.mode == "off":
            listen()
            return ["Firewall: gestione automatica disattivata (firewall = off)."]
        if self.backend is None:
            listen()
            return ["Firewall: gestione automatica disponibile solo su Linux e Windows."]
        if sys.platform != "win32" and os.geteuid() == 0:
            listen()
            return ["Firewall: server avviato come root, porta non gestita (avviarlo come utente normale)."]
        return self.backend.open(listen)

    def close(self):
        if self.backend is not None:
            self.backend.close()

