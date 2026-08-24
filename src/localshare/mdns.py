"""Advertise `<name>.local` on the LAN through the OS mDNS responder.

macOS ships `dns-sd`, most Linux desktops ship Avahi. Both keep the record
alive only while the process runs, which is exactly the lifetime we want:
kill the process and the name disappears from the network.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from localshare.netinfo import mdns_host

MAX_STARTS = 5


@dataclass(frozen=True)
class Publisher:
    """A tool that can register a hostname -> IPv4 record."""

    binary: str
    kind: str

    def argv(self, hostname: str, ip: str, port: int) -> list[str]:
        host = mdns_host(hostname)
        if self.kind == "dns-sd":
            # -P registers a proxy service *and* an A record for <host>.
            return [
                self.binary,
                "-P",
                hostname,
                "_http._tcp",
                "local",
                str(port),
                host,
                ip,
            ]
        return [self.binary, "-a", "-R", host, ip]


def find_publisher() -> Publisher | None:
    dns_sd = shutil.which("dns-sd")
    if dns_sd:
        return Publisher(binary=dns_sd, kind="dns-sd")
    avahi = shutil.which("avahi-publish")
    if avahi:
        return Publisher(binary=avahi, kind="avahi-publish")
    return None


class Advertisement:
    """One long-lived responder process for one project name."""

    def __init__(self, publisher: Publisher, hostname: str, ip: str, port: int) -> None:
        self.publisher = publisher
        self.hostname = hostname
        self.ip = ip
        self.port = port
        self.starts = 0
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def exhausted(self) -> bool:
        """A responder that keeps dying will not start working on retry 20."""
        return self.starts >= MAX_STARTS

    def start(self) -> None:
        if self.alive or self.exhausted:
            return
        self.starts += 1
        self._process = subprocess.Popen(
            self.publisher.argv(self.hostname, self.ip, self.port),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
