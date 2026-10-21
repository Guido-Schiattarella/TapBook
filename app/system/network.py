"""The computer's addresses on the local network (same on Linux and Windows)."""
import socket


def local_addresses() -> list[str]:
    """IP address of the computer on the local network (the one to use on the iPad).
    The interface of the main network is used, so Docker's or virtual machines'
    internal addresses do not show up."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent: this only selects the interface
            addr = s.getsockname()[0]
            if not addr.startswith("127."):
                return [addr]
    except OSError:
        pass
    try:  # no main network: show every known address
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
        return sorted({i[4][0] for i in infos if not i[4][0].startswith("127.")})
    except OSError:
        return []


def all_addresses() -> list[str]:
    """All IPv4 addresses of the computer (for the certificate: still valid if the network changes)."""
    addrs = set(local_addresses())
    try:
        addrs |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))
