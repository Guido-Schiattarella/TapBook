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


def _interface_addresses() -> set[str]:
    """IPv4 address of every network interface (Linux): also those of a VPN such
    as Tailscale or WireGuard, which are not the main network."""
    try:
        import fcntl
        import struct
    except ImportError:              # Windows: getaddrinfo already lists every interface
        return set()
    found = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _, name in socket.if_nameindex():
            try:
                packed = fcntl.ioctl(s.fileno(), 0x8915,     # SIOCGIFADDR
                                     struct.pack("256s", name.encode()[:15]))
                found.add(socket.inet_ntoa(packed[20:24]))
            except OSError:
                continue             # interface without an IPv4 address
    return found


def all_addresses() -> list[str]:
    """All IPv4 addresses of the computer (for the certificate: valid on every
    network the server is reached from, VPN included, and if the network changes)."""
    addrs = set(local_addresses()) | _interface_addresses()
    try:
        addrs |= {i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        pass
    return sorted(a for a in addrs if not a.startswith("127."))
