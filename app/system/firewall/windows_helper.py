"""TapBook — firewall helper on Windows.

It runs as administrator (started by the server with the UAC prompt at every
start) and does one thing only: while the TapBook server is running, a Windows
Defender Firewall rule allows reaching its port only from the local subnet and
only for the server program; when the server stops the rule is removed.

Security rules:
  * TCP only, only the given port (1024-65535), only "localsubnet" (the home
    network, never the Internet), only for the executable of the server process;
  * the process must start listening on the port within 2 minutes; when it
    stops listening or ends (in any way: the helper waits on the process itself)
    the rule is removed;
  * the server can ask for the shutdown through a Windows event (the helper
    writes no files: an administrator writing into user paths could be tricked
    into modifying other files);
  * every few seconds it checks that the rule is still there;
  * on start it removes any TapBook rule left over from an abrupt shutdown.

It uses only the standard library (ctypes for the Windows functions) and
imports nothing from the rest of the project.

Command:  windows_helper.py hold --port P --pid N --event NAME
"""
import ctypes
import socket
import struct
import subprocess
import sys
import time
from ctypes import wintypes

CHECK_SECONDS = 3
LISTEN_GRACE = 120              # seconds given to the server to start listening
SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 0x102
CREATE_NO_WINDOW = 0x08000000


def rule_name(port: int) -> str:
    return f"TapBook-porta-{port}"


def _api():
    """Windows functions with declared types (handles are 64-bit)."""
    k, ip = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("iphlpapi")
    H, D, B = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    k.OpenProcess.argtypes, k.OpenProcess.restype = [D, B, D], H
    k.OpenEventW.argtypes, k.OpenEventW.restype = [D, B, wintypes.LPCWSTR], H
    k.WaitForMultipleObjects.argtypes, k.WaitForMultipleObjects.restype = [D, ctypes.POINTER(H), B, D], D
    k.QueryFullProcessImageNameW.argtypes = [H, D, wintypes.LPWSTR, ctypes.POINTER(D)]
    k.QueryFullProcessImageNameW.restype = B
    k.CloseHandle.argtypes, k.CloseHandle.restype = [H], B
    ip.GetExtendedTcpTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(D), B, wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    ip.GetExtendedTcpTable.restype = D
    return k, ip


def netsh(*args) -> int:
    return subprocess.run(["netsh", "advfirewall", "firewall", *args], capture_output=True,
                          creationflags=CREATE_NO_WINDOW).returncode


def rule_exists(port: int) -> bool:
    return netsh("show", "rule", f"name={rule_name(port)}") == 0


def add_rule(port: int, program: str):
    netsh("add", "rule", f"name={rule_name(port)}", "dir=in", "action=allow", "protocol=TCP",
          f"localport={port}", "remoteip=localsubnet", f"program={program}", "profile=any", "enable=yes")


def delete_rules(port: int):
    netsh("delete", "rule", f"name={rule_name(port)}")


def process_image(kernel32, handle) -> str:
    size = wintypes.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        raise OSError("percorso del programma non leggibile")
    return buf.value


def listening(iphlpapi, pid: int, port: int) -> bool:
    """True if the process has an IPv4 TCP socket listening on the port
    (Windows connection table, GetExtendedTcpTable)."""
    size = wintypes.DWORD(0)
    for _ in range(5):
        buf = ctypes.create_string_buffer(max(size.value, 4))
        # AF_INET = 2, TCP_TABLE_OWNER_PID_LISTENER = 3
        res = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 3, 0)
        if res == 0:
            break
        if res != 122:              # ERROR_INSUFFICIENT_BUFFER: retry with the right size
            return False
    else:
        return False
    (count,) = struct.unpack_from("<I", buf, 0)
    for i in range(count):
        _state, _laddr, lport, _raddr, _rport, owner = struct.unpack_from("<6I", buf, 4 + 24 * i)
        if owner == pid and socket.ntohs(lport & 0xFFFF) == port:
            return True
    return False


def hold(port: int, pid: int, event_name: str):
    kernel32, iphlpapi = _api()
    if not ctypes.windll.shell32.IsUserAnAdmin():
        sys.exit("serve l'amministratore")
    process = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        sys.exit("processo inesistente")
    event = kernel32.OpenEventW(SYNCHRONIZE, False, event_name)
    if not event:
        sys.exit("evento di chiusura inesistente")
    handles = (wintypes.HANDLE * 2)(process, event)
    program = process_image(kernel32, process)
    delete_rules(port)                       # rules left over from an abrupt shutdown
    try:
        add_rule(port, program)
        started, seen = time.monotonic(), False
        while True:
            res = kernel32.WaitForMultipleObjects(2, handles, False, CHECK_SECONDS * 1000)
            if res != WAIT_TIMEOUT:         # process ended or shutdown requested by the server
                break
            if listening(iphlpapi, pid, port):
                seen = True
            elif seen or time.monotonic() - started > LISTEN_GRACE:
                break                       # it stopped listening, or never started
            if not rule_exists(port):
                add_rule(port, program)     # removed by someone else: put it back
    finally:
        delete_rules(port)
        kernel32.CloseHandle(event)
        kernel32.CloseHandle(process)


def main(argv):
    try:
        if len(argv) != 7 or argv[0] != "hold" or argv[1] != "--port" or argv[3] != "--pid" or argv[5] != "--event":
            raise ValueError
        port, pid, event = int(argv[2]), int(argv[4]), argv[6]
        if not 1024 <= port <= 65535 or not event.startswith("Local\\TapBook-firewall-"):
            raise ValueError
    except ValueError:
        sys.exit("uso: windows_helper.py hold --port P --pid N --event Local\\TapBook-firewall-…")
    hold(port, pid, event)


if __name__ == "__main__":
    main(sys.argv[1:])
