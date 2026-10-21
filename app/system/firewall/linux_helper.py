#!/usr/bin/python3 -I
"""TapBook — firewall helper.

A program separate from the application that runs as root and does one thing
only: while the TapBook server is running, it opens the server port in the
computer's firewall for the local network only; when the server stops, it
closes it again.

Nothing is installed: at every start the server runs it with sudo (or pkexec,
without a terminal), which asks for the administrator password. Once
authorised, the helper lives as long as the server; no sudo rules or system
files are left behind.

Security rules:
  * it opens TCP only, only the given port (1024-65535), only for the network
    of the computer's main connection (e.g. 192.168.1.0/24), never for the Internet;
  * it opens only if the given process belongs to whoever entered the password
    and is really listening on that port;
  * the rules are runtime-only: they are never saved in the firewall
    configuration, so they also disappear when the computer restarts;
  * it closes as soon as the server ends, in any way (even a crash or a kill:
    the kernel follows it with a pidfd), as soon as it stops listening on the
    port, or when the helper receives a termination signal;
  * every few seconds it checks again: if the firewall was reloaded it puts the
    rule back, if the network changed it updates the rule;
  * on start it removes any TapBook rule left over from an abrupt shutdown.

It works with ufw and the other iptables-based firewalls (legacy or nft:
Shorewall, ferm, iptables-persistent…), firewalld and nftables setups (even
with nft built without JSON support): the rule is inserted at the top of every
input and prerouting chain, so no "block everything" rule overrides it.
Requires Linux 5.3+, Python 3.9+ and sudo (or pkexec).

It uses only the standard library and imports nothing from the rest of the project.

Commands:
  hold --port P --pid N    opens and keeps open while process N is listening
  close --port P           removes the TapBook rules for port P
  uninstall                removes what earlier versions installed
                           (helper in /usr/local/lib/tapbook and sudo rule)
"""
import ipaddress
import json
import os
import re
import select
import signal
import stat
import subprocess
import sys

# What earlier versions installed (only so that it can be removed: uninstall).
INSTALL_DIR = "/usr/local/lib/tapbook"
HELPER = INSTALL_DIR + "/tapbook-firewall"
SUDOERS = "/etc/sudoers.d/tapbook"
TAG = "tapbook:"                 # comment of the rules: tapbook:<port>:<network>
CHECK_SECONDS = 3
SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
ENV = {"PATH": SAFE_PATH, "LC_ALL": "C"}


class Stop(Exception):
    pass


def say(*words):
    print(*words, flush=True)


def tool(name):
    """Path of a system program, only if it belongs to root and nobody else can modify it."""
    for d in SAFE_PATH.split(":"):
        path = os.path.join(d, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if st.st_uid == 0 and not st.st_mode & 0o022:
            return path
    return None


def run(*cmd, data=None):
    return subprocess.run(cmd, input=data, capture_output=True, text=True, env=ENV, timeout=20)


# --- checks on the server process --------------------------------------------------
def caller_uid():
    # Set by sudo and pkexec (after the password): the user cannot forge them.
    for var in ("SUDO_UID", "PKEXEC_UID"):
        if os.environ.get(var, "").isdigit():
            return int(os.environ[var])
    return None


def process_uid(pid):
    with open(f"/proc/{pid}/status") as fh:
        for line in fh:
            if line.startswith("Uid:"):
                return int(line.split()[1])
    return None


def listening(pid, port):
    """True if the process has a TCP socket listening on the port."""
    inodes = set()
    try:
        for fd in os.listdir(f"/proc/{pid}/fd"):
            try:
                link = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
    except OSError:
        return False
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table) as fh:
                next(fh)
                for line in fh:
                    f = line.split()
                    if f[3] == "0A" and int(f[1].rsplit(":", 1)[1], 16) == port and f[9] in inodes:
                        return True
        except OSError:
            continue
    return False


# --- local network ---------------------------------------------------------------------
def lan_networks():
    """Private IPv4 networks of the interfaces with the default route (the home
    Wi-Fi or cable): only from there can the server be reached."""
    ip = tool("ip")
    if not ip:
        return []
    try:
        routes = json.loads(run(ip, "-j", "-4", "route", "show", "default").stdout or "[]")
    except ValueError:
        return []
    nets = set()
    for dev in {r.get("dev") for r in routes if r.get("dev")}:
        try:
            info = json.loads(run(ip, "-j", "-4", "addr", "show", "dev", dev).stdout or "[]")
        except ValueError:
            continue
        for iface in info:
            for a in iface.get("addr_info", []):
                try:
                    net = ipaddress.ip_network(f"{a['local']}/{a['prefixlen']}", strict=False)
                except (KeyError, ValueError):
                    continue
                if (net.is_private and not net.is_loopback and not net.is_link_local
                        and 8 <= net.prefixlen <= 30):
                    nets.add(net)
    return sorted(nets)


# --- rules -----------------------------------------------------------------------------
# Chains the rule is inserted into: every "filter" chain hooked on input or,
# earlier still, on packet arrival (prerouting), in every ip/inet nftables
# table: an "accept" rule only applies within its own chain, so it must go into
# every chain that might block.
HOOKS = ("input", "prerouting")
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


# Tables created by iptables (iptables-nft too, used by ufw) are changed with
# iptables: rules written with nft would make them unreadable for ufw.
def iptables_managed(chain):
    return chain["family"] == "ip" and chain["table"] in ("filter", "raw", "mangle", "nat", "security") \
        and chain["name"].isupper()


def nft_ruleset():
    """(nft, JSON available, chains, rules) read from the kernel. If nft was built
    without JSON support, the text of "nft -a list ruleset" is parsed instead."""
    nft = tool("nft")
    if not nft:
        return None, False, [], []
    out = run(nft, "-j", "list", "ruleset")
    if out.returncode == 0:
        try:
            items = json.loads(out.stdout).get("nftables", [])
            return (nft, True, [i["chain"] for i in items if "chain" in i],
                    [i["rule"] for i in items if "rule" in i])
        except ValueError:
            pass
    out = run(nft, "-a", "list", "ruleset")
    if out.returncode:
        return nft, False, [], []
    chains, rules, table, chain = [], [], None, None
    for line in out.stdout.splitlines():
        s = line.strip()
        if m := re.match(r"table (\w+) (\S+) \{", s):
            table, chain = (m.group(1), m.group(2)), None
        elif (m := re.match(r"chain (\S+) \{", s)) and table:
            chain = {"family": table[0], "table": table[1], "name": m.group(1)}
            chains.append(chain)
        elif (m := re.match(r"type (\w+) hook (\w+)", s)) and chain:
            chain.update(type=m.group(1), hook=m.group(2))
        elif chain and (m := re.search(r'comment "([^"]*)".*# handle (\d+)', s)):
            rules.append({"family": chain["family"], "table": chain["table"], "chain": chain["name"],
                          "comment": m.group(1), "handle": int(m.group(2))})
    return nft, False, chains, rules


def nft_apply(nft, use_json, commands):
    if not commands:
        return
    if use_json:
        out = run(nft, "-j", "-f", "-", data=json.dumps({"nftables": commands}))
        if out.returncode:
            say("ERROR nft", out.stderr.strip().replace("\n", " ")[:300])
        return
    for c in commands:                 # nft without JSON: one command at a time
        verb = next(iter(c))
        r = c[verb]["rule"]
        if not all(NAME_RE.match(str(r[k])) for k in ("family", "table", "chain")):
            continue                   # odd names: never risk building a wrong command
        if verb == "delete":
            args = ["delete", "rule", r["family"], r["table"], r["chain"], "handle", str(r["handle"])]
        else:
            args = ["insert", "rule", r["family"], r["table"], r["chain"], "ip", "saddr", r["net"],
                    "tcp", "dport", str(r["port"]), "accept", "comment", f'"{r["comment"]}"']
        out = run(nft, *args)
        if out.returncode:
            say("ERROR nft", out.stderr.strip().replace("\n", " ")[:300])


def iptables_rules(ipt):
    out = run(ipt, "-w", "-S", "INPUT")
    return out.stdout.splitlines() if out.returncode == 0 else None


def ipt_spec(port, net):
    return ["-s", str(net), "-p", "tcp", "-m", "tcp", "--dport", str(port),
            "-m", "comment", "--comment", f"{TAG}{port}:{net}", "-j", "ACCEPT"]


def sync(port, nets):
    """Brings the rules to the desired state: one rule per network at the top of
    every chain that might block, no extra TapBook rule (port=None removes them
    all). Returns the number of chains opened."""
    prefix = f"{TAG}{port}:" if port else TAG
    want = {f"{TAG}{port}:{n}": n for n in nets} if port else {}
    nft, use_json, chains, rules = nft_ruleset()
    opened, commands = 0, []

    for ch in chains:
        if ch.get("hook") not in HOOKS or ch.get("type") != "filter" or ch["family"] not in ("ip", "inet"):
            continue
        if iptables_managed(ch):
            continue
        key = (ch["family"], ch["table"], ch["name"])
        where = {"family": key[0], "table": key[1], "chain": key[2]}
        have = {r.get("comment"): r["handle"] for r in rules
                if (r["family"], r["table"], r["chain"]) == key and str(r.get("comment", "")).startswith(prefix)}
        for comment, handle in have.items():
            if comment not in want:
                commands.append({"delete": {"rule": {**where, "handle": handle}}})
        for comment, net in want.items():
            if comment not in have:
                rule = {**where, "comment": comment, "expr": [
                    {"match": {"op": "==", "left": {"payload": {"protocol": "ip", "field": "saddr"}},
                               "right": {"prefix": {"addr": str(net.network_address), "len": net.prefixlen}}}},
                    {"match": {"op": "==", "left": {"payload": {"protocol": "tcp", "field": "dport"}}, "right": port}},
                    {"accept": None}]}
                if not use_json:
                    rule.update(net=str(net), port=port)
                commands.append({"insert": {"rule": rule}})
        opened += bool(want) and ch.get("hook") == "input"
    nft_apply(nft, use_json, commands)

    # iptables INPUT chain (ufw, older firewalld, iptables-services, Shorewall…):
    # with iptables-nft it is visible in nft too; with iptables-legacy it is not,
    # so it is read with iptables itself.
    ipt = tool("iptables")
    has_ipt_chain = any(iptables_managed(c) and c["name"] == "INPUT" and c["table"] == "filter" for c in chains)
    if ipt and (has_ipt_chain or "legacy" in run(ipt, "-V").stdout):
        lines = iptables_rules(ipt)
        if lines is not None:
            have = {}
            for line in lines:
                m = re.search(r'--comment "?(' + re.escape(prefix) + r'[0-9a-f.:/]+)"?', line)
                if m:
                    have[m.group(1)] = line
            for comment in have:
                if comment not in want:
                    p, net = comment[len(TAG):].split(":", 1)
                    run(ipt, "-w", "-D", "INPUT", *ipt_spec(int(p), net))
            for comment, net in want.items():
                if comment not in have:
                    out = run(ipt, "-w", "-I", "INPUT", "1", *ipt_spec(port, net))
                    if out.returncode:
                        say("ERROR iptables", out.stderr.strip()[:300])
            opened += bool(want)
    return opened


# --- commands --------------------------------------------------------------------------
def hold(port, pid):
    uid = caller_uid()
    if uid is None:
        sys.exit("ERROR va avviato tramite sudo o pkexec")
    try:
        if process_uid(pid) != uid:
            sys.exit("ERROR il processo non appartiene a chi lo ha chiesto")
        pidfd = os.pidfd_open(pid)
    except (OSError, TypeError):
        sys.exit("ERROR processo inesistente")
    if not listening(pid, port):
        sys.exit("ERROR il processo non è in ascolto sulla porta")

    def on_signal(*_):
        raise Stop
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, on_signal)
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    # If standard input is the pipe opened by the server, its closing (server
    # stopped in any way) is another signal to close, independent of the
    # signals sudo forwards.
    watch = [pidfd]
    if stat.S_ISFIFO(os.fstat(0).st_mode):
        watch.append(0)
    last = None
    try:
        sync(port, [])                      # rules left over from an abrupt shutdown
        while True:
            nets = lan_networks()
            opened = sync(port, nets)
            state = (tuple(map(str, nets)), opened)
            if state != last:
                if nets and opened:
                    say("OPEN", " ".join(map(str, nets)))
                elif nets:
                    say("NOFIREWALL")
                else:
                    say("NONET")
                last = state
            ready, _, _ = select.select(watch, [], [], CHECK_SECONDS)
            if pidfd in ready or (0 in ready and not os.read(0, 4096)) or not listening(pid, port):
                break
    except Stop:
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            sync(port, [])
            say("CLOSED")
        except Exception as e:            # noqa: BLE001 — still try to report it
            say("ERROR chiusura", e)
            sys.exit(1)


def uninstall():
    """Removes what earlier TapBook versions installed (helper in
    /usr/local/lib/tapbook and passwordless sudo rule) and any leftover rules."""
    if os.geteuid() != 0:
        sys.exit("Serve l'amministratore (sudo o pkexec).")
    sync(None, [])
    for path in (SUDOERS, HELPER):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    try:
        os.rmdir(INSTALL_DIR)
    except OSError:
        pass
    say("UNINSTALLED")


def main(argv):
    def port_arg(v):
        p = int(v)
        if not 1024 <= p <= 65535:
            raise ValueError
        return p
    try:
        cmd, args = argv[0], argv[1:]
        if cmd == "hold" and len(args) == 4 and args[0] == "--port" and args[2] == "--pid":
            hold(port_arg(args[1]), int(args[3]))
        elif cmd == "close" and len(args) == 2 and args[0] == "--port":
            sync(port_arg(args[1]), [])
            say("CLOSED")
        elif cmd == "uninstall" and not args:
            uninstall()
        else:
            raise ValueError
    except (IndexError, ValueError):
        sys.exit("uso: linux_helper.py hold --port P --pid N | close --port P | uninstall")


if __name__ == "__main__":
    main(sys.argv[1:])
