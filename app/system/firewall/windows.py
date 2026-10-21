"""Firewall on Windows: Windows Defender Firewall.

At every start, if the firewall is active, the server launches the helper
(windows_helper.py) as administrator: Windows shows its prompt (UAC), asking
for the administrator password if the user is not one. Nothing is installed.
The helper adds the rule before the server starts listening, so Windows does
not show its "Allow access?" prompt (which would open the program on every
port); it removes the rule when the server stops.

The server reads nothing written by the helper: it checks by itself, without
privileges, that the rule exists (netsh) and asks for the shutdown with an event.
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from .messages import describe

HELPER_SOURCE = Path(__file__).with_name("windows_helper.py")
CREATE_NO_WINDOW = 0x08000000
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0
ERROR_CANCELLED = 1223
START_TIMEOUT = 30


def _run(*cmd) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)


def firewall_active() -> bool:
    """At least one Windows Defender Firewall profile is active (read without
    privileges). If it cannot be determined, it is assumed active."""
    out = _run("powershell", "-NoProfile", "-NonInteractive", "-Command",
               "@(Get-NetFirewallProfile | Where-Object { $_.Enabled }).Count")
    try:
        return int(out.stdout.strip()) > 0
    except ValueError:
        return True


def blocking_rules(program: str) -> int:
    """Rules blocking the server program inbound (created by Windows if "Cancel"
    was once answered to its prompt): they take precedence over any allow rule."""
    quoted = program.replace("'", "''")
    out = _run("powershell", "-NoProfile", "-NonInteractive", "-Command",
               f"@(Get-NetFirewallApplicationFilter -Program '{quoted}' -ErrorAction SilentlyContinue | "
               "Get-NetFirewallRule | Where-Object { $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' "
               "-and $_.Action -eq 'Block' }).Count")
    try:
        return int(out.stdout.strip())
    except ValueError:
        return 0


def _rule_exists(port: int) -> bool:
    return _run("netsh", "advfirewall", "firewall", "show", "rule", f"name=TapBook-porta-{port}").returncode == 0


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def _api():
    k, sh = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("shell32", use_last_error=True)
    H, D, B = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    k.CreateEventW.argtypes, k.CreateEventW.restype = [ctypes.c_void_p, B, B, wintypes.LPCWSTR], H
    k.SetEvent.argtypes, k.SetEvent.restype = [H], B
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [H, D], D
    k.GetExitCodeProcess.argtypes, k.GetExitCodeProcess.restype = [H, ctypes.POINTER(D)], B
    k.CloseHandle.argtypes, k.CloseHandle.restype = [H], B
    k.GetCurrentProcess.restype = H
    k.QueryFullProcessImageNameW.argtypes = [H, D, wintypes.LPWSTR, ctypes.POINTER(D)]
    k.QueryFullProcessImageNameW.restype = B
    sh.ShellExecuteExW.argtypes, sh.ShellExecuteExW.restype = [ctypes.POINTER(_ShellExecuteInfo)], B
    return k, sh


def _own_program(kernel32) -> str:
    """Executable of this process (with a virtual environment it is the real
    Python, not the .venv\\Scripts launcher)."""
    size = wintypes.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    kernel32.QueryFullProcessImageNameW(kernel32.GetCurrentProcess(), 0, buf, ctypes.byref(size))
    return buf.value or sys.executable


class WindowsBackend:
    def __init__(self, port: int, mode: str, data_dir, say, password: str | None = None):
        self.port, self.mode, self.say = port, mode, say          # no password needed: UAC prompt
        self.kernel32 = self.shell32 = None
        self.helper = self.event = None

    def open(self, listen) -> list[str]:
        if not firewall_active() and self.mode != "on":
            listen()
            return ["Firewall: Windows Defender Firewall non attivo, non c'è niente da aprire."]
        self.kernel32, self.shell32 = _api()
        program = _own_program(self.kernel32)
        notes = []
        if blocking_rules(program):
            notes = [f"ATTENZIONE: Windows ha una regola che blocca {Path(program).name} (forse si è risposto "
                     "«Annulla» al suo avviso): l'iPad non riuscirà a collegarsi finché non la si toglie da "
                     "«Windows Defender Firewall → Consenti app» (togliere la spunta di blocco su Python)."]
        self.say(f"Firewall di Windows attivo: per far collegare l'iPad apro la porta {self.port} solo per la "
                 "rete di casa e solo finché il server è acceso. Conferma la richiesta di Windows.")
        name = f"Local\\TapBook-firewall-{os.getpid()}"
        self.event = self.kernel32.CreateEventW(None, True, False, name)
        params = subprocess.list2cmdline(["-I", str(HELPER_SOURCE), "hold", "--port", str(self.port),
                                          "--pid", str(os.getpid()), "--event", name])
        info = _ShellExecuteInfo(cbSize=ctypes.sizeof(_ShellExecuteInfo), fMask=SEE_MASK_NOCLOSEPROCESS,
                                 lpVerb="runas", lpFile=sys.executable, lpParameters=params, nShow=SW_HIDE)
        if not self.shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
            cancelled = ctypes.get_last_error() == ERROR_CANCELLED
            listen()
            return notes + [("ATTENZIONE: richiesta di Windows annullata" if cancelled else
                             "ATTENZIONE: custode del firewall non avviato") +
                            ", porta non aperta: l'iPad non riuscirà a collegarsi. Riavvia il server per riprovare."]
        self.helper = info.hProcess
        # The rule must exist before the server starts listening.
        deadline = time.monotonic() + START_TIMEOUT
        while not _rule_exists(self.port):
            if time.monotonic() > deadline or self.kernel32.WaitForSingleObject(self.helper, 0) == 0:
                listen()
                return notes + ["ATTENZIONE: il custode del firewall non ha aperto la porta."]
            time.sleep(0.3)
        listen()
        return notes + [describe(self.port, "OPEN", "(subnet locale)")]

    def close(self):
        """Asks the helper to remove the rule and waits until it has finished."""
        if self.helper is None:
            return
        self.kernel32.SetEvent(self.event)
        finished = self.kernel32.WaitForSingleObject(self.helper, 15000) == 0
        self.kernel32.CloseHandle(self.helper)
        self.kernel32.CloseHandle(self.event)
        self.helper = self.event = None
        if finished and not _rule_exists(self.port):
            self.say(describe(self.port, "CLOSED"))
        else:
            self.say(f"ATTENZIONE: la regola del firewall per la porta {self.port} non risulta tolta: "
                     "verrà tolta al prossimo avvio del server (si chiama TapBook-porta-…).", "warn")
