"""Firewall on Linux: ufw/iptables, firewalld, nftables.

At every start, if the computer has an active firewall, the server runs the
helper (linux_helper.py) with sudo, which asks for the administrator password
(or with pkexec, in a window, if the server has no terminal). Nothing is
installed and no sudo rules are added.
"""
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .messages import describe

HELPER_SOURCE = Path(__file__).with_name("linux_helper.py")
SYSTEM_PYTHON = "/usr/bin/python3"
# What earlier TapBook versions installed (system helper with a passwordless
# sudo rule): it is reported and can be removed with firewall-uninstall.
OLD_HELPER = Path("/usr/local/lib/tapbook/tapbook-firewall")
# Services that load firewall rules at boot (systemd). A firewall loaded some
# other way (systems without systemd, custom scripts) is handled with firewall = on.
FIREWALL_SERVICES = ("ufw", "firewalld", "nftables", "iptables", "ip6tables",
                     "netfilter-persistent", "shorewall", "ferm", "csf")
PROMPT = "  Password di amministratore per aprire la porta nel firewall: "
STATES = ("OPEN", "NOFIREWALL", "NONET", "ERROR")


def active_firewalls() -> list[str]:
    """Active firewall services (read from systemd without privileges)."""
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return []
    out = subprocess.run([systemctl, "is-active", *FIREWALL_SERVICES], capture_output=True, text=True)
    return [name for name, state in zip(FIREWALL_SERVICES, out.stdout.split()) if state == "active"]


def _as_admin(args: list[str]) -> list[str] | None:
    """Command that runs the helper as administrator asking for the password: sudo
    in the terminal (-k: always asks, even if sudo remembers it from an earlier
    command), pkexec in a window when there is no terminal."""
    helper = [SYSTEM_PYTHON, "-I", str(HELPER_SOURCE), *args]
    if sys.stdin.isatty() and shutil.which("sudo"):
        return ["sudo", "-k", "-p", PROMPT, *helper]
    if shutil.which("pkexec"):
        return ["pkexec", *helper]
    return None


def uninstall_old() -> bool:
    """Removes the system helper and sudo rule of earlier versions, and any TapBook
    rules left in the firewall."""
    if not OLD_HELPER.exists():
        print("Nessuna installazione precedente da togliere.")
        return True
    cmd = _as_admin(["uninstall"])
    try:
        done = cmd is not None and subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False
    if done:
        print("Tolti il custode in /usr/local/lib/tapbook e la regola /etc/sudoers.d/tapbook.")
    return done


class LinuxBackend:
    def __init__(self, port: int, mode: str, data_dir, say, password: str | None = None):
        self.port, self.mode, self.say = port, mode, say
        self.password = password
        self.proc = None
        self.reader = None
        self.bad_password = False
        self.lines = queue.Queue()

    def open(self, listen) -> list[str]:
        # The server starts listening first: the helper opens only for a process that
        # is really listening on the port.
        listen()
        notes = []
        if OLD_HELPER.exists():
            notes = ["Nota: c'è ancora il custode installato dalla versione precedente (con una regola sudo "
                     "senza password): non serve più, toglilo con  python -m app firewall-uninstall"]
        active = active_firewalls()
        if not active and self.mode != "on":
            return notes + ["Firewall: nessun firewall attivo riconosciuto, non c'è niente da aprire "
                            "(se il PC ne ha uno caricato in altro modo, impostare firewall = on in config.ini)."]
        args = ["hold", "--port", str(self.port), "--pid", str(os.getpid())]
        if self.password is not None:
            # Password already asked by the control panel: sudo reads it from the pipe
            # (-S) and the helper inherits the same pipe, which stays open.
            cmd = ["sudo", "-S", "-k", "-p", "", SYSTEM_PYTHON, "-I", str(HELPER_SOURCE), *args]
        else:
            cmd = _as_admin(args)
        if cmd is None:
            return notes + ["ATTENZIONE: né sudo né pkexec disponibili, porta non aperta: l'iPad non "
                            "riuscirà a collegarsi finché il firewall è attivo."]
        self.say(f"Firewall attivo ({', '.join(active) or 'firewall = on'}): per far collegare l'iPad apro la "
                 f"porta {self.port} solo per la rete di casa e solo finché il server è acceso.")
        try:
            # No new session: sudo asks for the password in the server's terminal.
            # Standard input stays an open pipe: when the server ends, in any way,
            # it closes and the helper closes the port.
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True)
        except OSError as e:
            return notes + [f"ATTENZIONE: custode del firewall non avviato ({e})."]
        if self.password is not None:
            self.proc.stdin.write(self.password + "\n")
            self.proc.stdin.flush()
            self.password = None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        # Wait without a time limit: whoever starts the server is typing the password.
        while True:
            try:
                first = self.lines.get(timeout=1)
                break
            except queue.Empty:
                if self.bad_password and self.proc.poll() is None:
                    self.proc.kill()          # sudo would wait for another attempt
                    self.proc.wait()
                if self.proc.poll() is not None and self.lines.empty():
                    self.proc = None
                    return notes + ["ATTENZIONE: password non inserita o errata, porta non aperta: l'iPad non "
                                    "riuscirà a collegarsi. Riavvia il server per riprovare."]
        word, _, rest = first.partition(" ")
        return notes + [describe(self.port, word, rest)]

    def _read(self):
        """The helper's first line is the state at start; later lines (network
        changed, port closed, errors) are shown in the terminal. Before the state
        sudo messages may arrive ("try again"), already seen in the terminal."""
        first = True
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            word, _, rest = line.partition(" ")
            if first and word in STATES:
                self.lines.put(line)
                first = False
            elif first and ("Sorry" in line or "riprova" in line.lower() or "incorrect" in line):
                self.bad_password = True       # wrong password given by the panel
            elif not first:
                self.say(describe(self.port, word, rest))

    def close(self):
        """Makes the helper close the port and waits until it has finished."""
        if not self.proc:
            return
        proc, self.proc = self.proc, None
        clean = False
        if proc.poll() is None:
            proc.stdin.close()                # the helper notices and closes
            try:
                clean = proc.wait(timeout=10) == 0
            except subprocess.TimeoutExpired:
                try:
                    proc.terminate()          # sudo forwards it to the helper
                    clean = proc.wait(timeout=5) == 0
                except (OSError, subprocess.TimeoutExpired):
                    pass
        else:
            clean = proc.returncode == 0
        self.reader.join(timeout=2)           # the "port closed" message arrives before exiting
        if not clean:
            self.say(f"ATTENZIONE: il custode del firewall non ha confermato la chiusura della porta {self.port}. "
                     "Le sue regole spariscono comunque al riavvio del PC e al prossimo avvio del server.", "warn")
