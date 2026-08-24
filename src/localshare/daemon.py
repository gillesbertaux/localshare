"""The LAN daemon: one proxy, one mDNS advertisement per project.

The CLI never touches the network. It edits the registry and asks the daemon
to exist; the daemon polls the registry and reconciles.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import Any

from localshare import state
from localshare.errors import PreconditionError
from localshare.mdns import Advertisement, find_publisher
from localshare.netinfo import lan_ip, lan_url
from localshare.proxy import bind_proxy

DEFAULT_LAN_PORTS = (80, 7777)
POLL_INTERVAL_S = 1.0
STARTUP_TIMEOUT_S = 6.0


def candidate_ports(preferred: int | None) -> list[int]:
    if preferred is None:
        return list(DEFAULT_LAN_PORTS)
    if preferred in DEFAULT_LAN_PORTS:
        ordered = [preferred, *[p for p in DEFAULT_LAN_PORTS if p != preferred]]
        return ordered
    return [preferred, *DEFAULT_LAN_PORTS]


class DaemonController:
    """What the CLI is allowed to do to the daemon."""

    def ensure(self, preferred_port: int | None) -> dict[str, Any]:
        info = state.read_daemon_info()
        if info is not None:
            return info
        state.ensure_state_dir()
        log = open(state.daemon_log_path(), "ab", buffering=0)
        try:
            argv = [sys.executable, "-m", "localshare", "_daemon"]
            if preferred_port is not None:
                argv += ["--lan-port", str(preferred_port)]
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                cwd=str(state.ensure_state_dir()),
            )
        finally:
            log.close()
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            info = state.read_daemon_info()
            if info is not None:
                return info
            time.sleep(0.05)
        raise PreconditionError(
            f"LAN daemon did not start; see {state.daemon_log_path()}"
        )

    def stop(self) -> bool:
        return state.stop_daemon()

    def info(self) -> dict[str, Any] | None:
        return state.read_daemon_info()

    def refresh(self) -> dict[str, Any] | None:
        """Give a running daemon a moment to pick up a registry change."""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            info = state.read_daemon_info()
            if info is None:
                return None
            time.sleep(POLL_INTERVAL_S / 4)
            info = state.read_daemon_info()
            if info is not None:
                return info
        return state.read_daemon_info()


class _Daemon:
    def __init__(self, preferred_port: int | None) -> None:
        self.preferred_port = preferred_port
        self.routes: dict[str, int] = {}
        self.ads: dict[str, Advertisement] = {}
        self.ip: str | None = None
        self.stopping = False

    def _handle_signal(self, *_: object) -> None:
        self.stopping = True

    def run(self) -> int:
        entries = state.read_lan_entries()
        if not entries:
            state.clear_daemon_files()
            return 0

        publisher = find_publisher()
        if publisher is None:
            sys.stderr.write(
                "localshare: no mDNS publisher found (need dns-sd or avahi-publish)\n"
            )
            state.clear_daemon_files()
            return 1

        server = bind_proxy(lambda: self.routes, candidate_ports(self.preferred_port))
        self.ip = lan_ip()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        state.write_daemon_pid(os.getpid())
        server.serve_in_thread()

        last_seen = -1.0
        try:
            while not self.stopping:
                mtime = state.registry_mtime()
                current_ip = lan_ip()
                if mtime != last_seen or current_ip != self.ip:
                    self.ip = current_ip
                    entries = state.read_lan_entries()
                    if not entries:
                        break
                    self._reconcile(entries, publisher, server.port)
                    last_seen = mtime
                self._restart_dead_ads()
                time.sleep(POLL_INTERVAL_S)
        finally:
            for ad in self.ads.values():
                ad.stop()
            server.shutdown()
            server.server_close()
            state.clear_daemon_files()
        return 0

    def _reconcile(
        self,
        entries: dict[str, state.LanEntry],
        publisher: Any,
        proxy_port: int,
    ) -> None:
        self.routes = {name: entry.port for name, entry in entries.items()}

        for name in list(self.ads):
            entry = entries.get(name)
            ad = self.ads[name]
            stale = (
                entry is None
                or entry.hostname != ad.hostname
                or ad.ip != self.ip
                or ad.port != proxy_port
            )
            if stale:
                ad.stop()
                del self.ads[name]

        if self.ip is None:
            self._write_info(proxy_port, entries)
            return

        for name, entry in entries.items():
            if name in self.ads:
                continue
            ad = Advertisement(publisher, entry.hostname, self.ip, proxy_port)
            ad.start()
            self.ads[name] = ad

        self._write_info(proxy_port, entries)

    def _restart_dead_ads(self) -> None:
        for ad in self.ads.values():
            if not ad.alive:
                ad.start()

    def _write_info(self, proxy_port: int, entries: dict[str, state.LanEntry]) -> None:
        state.write_daemon_info(
            {
                "pid": os.getpid(),
                "port": proxy_port,
                "ip": self.ip,
                "started_at": time.time(),
                "projects": {
                    name: {
                        "hostname": entry.hostname,
                        "target_port": entry.port,
                        "url": lan_url(entry.hostname, proxy_port),
                    }
                    for name, entry in entries.items()
                },
            }
        )


def run_daemon(preferred_port: int | None = None) -> int:
    return _Daemon(preferred_port).run()
