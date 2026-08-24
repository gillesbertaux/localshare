"""Host/interface facts needed to advertise a name on the LAN."""

from __future__ import annotations

import socket

# TEST-NET-1: connecting a UDP socket sends no packets, it only asks the
# kernel which local address would be used to reach the outside world.
_PROBE_ADDR = ("192.0.2.1", 53)


def lan_ip() -> str | None:
    """The IPv4 address other devices on this network can reach."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(_PROBE_ADDR)
        address = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if not isinstance(address, str) or address.startswith("127."):
        return None
    return address


def mdns_host(hostname: str) -> str:
    return hostname if hostname.endswith(".local") else f"{hostname}.local"


def lan_url(hostname: str, port: int) -> str:
    host = mdns_host(hostname)
    if port == 80:
        return f"http://{host}/"
    return f"http://{host}:{port}/"
