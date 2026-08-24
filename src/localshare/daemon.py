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
from localshare.mdns import Advertisement, Publisher, find_publisher
from localshare.netinfo import lan_ip, lan_url
from localshare.proxy import bind_proxy

DEFAULT_LAN_PORTS = (80, 7777)
POLL_INTERVAL_S = 1.0
STARTUP_TIMEOUT_S = 6.0
RELOAD_GRACE_S = 1.5

DaemonInfo = dict[str, Any]


def candidate_ports(preferred: int | None) -> list[int]:
    """Preferred port first, then the standard fallbacks, without repeats."""
    if preferred is None:
        return list(DEFAULT_LAN_PORTS)
    return [preferred, *(p for p in DEFAULT_LAN_PORTS if p != preferred)]


class DaemonController:
    """What the CLI is allowed to do to the daemon."""

    def ensure(self, preferred_port: int | None) -> DaemonInfo:
        info = state.read_daemon_info()
        if info is not None:
            return info
        self._spawn(preferred_port)
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

    def info(self) -> DaemonInfo | None:
        return state.read_daemon_info()

    def refresh(self) -> DaemonInfo | None:
        """Wait out one poll cycle so a running daemon has reconciled."""
        time.sleep(RELOAD_GRACE_S)
        return state.read_daemon_info()

    @staticmethod
    def _spawn(preferred_port: int | None) -> None:
        argv = [sys.executable, "-m", "localshare", "_daemon"]
        if preferred_port is not None:
            argv += ["--lan-port", str(preferred_port)]
        with open(state.daemon_log_path(), "ab", buffering=0) as log:
            subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                cwd=str(state.ensure_state_dir()),
            )


class _Daemon:
    def __init__(self, preferred_port: int | None) -> None:
        self.preferred_port = preferred_port
        self.routes: dict[str, int] = {}
        self.ads: dict[str, Advertisement] = {}
        self.given_up: set[str] = set()
        self.ip: str | None = None
        self.proxy_port = 0
        self.started_at = time.time()
        self.stopping = False

    def _handle_signal(self, *_: object) -> None:
        self.stopping = True

    def run(self) -> int:
        if not state.read_lan_entries():
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
        self.proxy_port = server.port
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        state.write_daemon_pid(os.getpid())
        server.serve_in_thread()

        last_reconciled = -1.0
        try:
            while not self.stopping:
                mtime = state.registry_mtime()
                current_ip = lan_ip()
                if mtime != last_reconciled or current_ip != self.ip:
                    self.ip = current_ip
                    entries = state.read_lan_entries()
                    if not entries:
                        break
                    self._reconcile(entries, publisher)
                    last_reconciled = mtime
                self._keep_ads_alive()
                time.sleep(POLL_INTERVAL_S)
        finally:
            for ad in self.ads.values():
                ad.stop()
            server.shutdown()
            server.server_close()
            state.clear_daemon_files()
        return 0

    def _reconcile(
        self, entries: dict[str, state.LanEntry], publisher: Publisher
    ) -> None:
        self.routes = {name: entry.port for name, entry in entries.items()}
        self._drop_stale_ads(entries)
        if self.ip is not None:
            for name, entry in entries.items():
                if name not in self.ads:
                    self.ads[name] = Advertisement(
                        publisher, entry.hostname, self.ip, self.proxy_port
                    )
        self._write_info(entries)

    def _keep_ads_alive(self) -> None:
        for name, ad in self.ads.items():
            if ad.alive:
                continue
            if ad.exhausted:
                if name not in self.given_up:
                    self.given_up.add(name)
                    sys.stderr.write(
                        f"localshare: gave up advertising {ad.hostname}.local after "
                        f"{ad.starts} attempts; is the name already taken?\n"
                    )
                continue
            ad.start()

    def _drop_stale_ads(self, entries: dict[str, state.LanEntry]) -> None:
        for name, ad in list(self.ads.items()):
            entry = entries.get(name)
            if entry is None or entry.hostname != ad.hostname or ad.ip != self.ip:
                ad.stop()
                del self.ads[name]
                self.given_up.discard(name)

    def _write_info(self, entries: dict[str, state.LanEntry]) -> None:
        state.write_daemon_info(
            {
                "pid": os.getpid(),
                "port": self.proxy_port,
                "ip": self.ip,
                "started_at": self.started_at,
                "projects": {
                    name: {
                        "hostname": entry.hostname,
                        "target_port": entry.port,
                        "url": lan_url(entry.hostname, self.proxy_port),
                    }
                    for name, entry in entries.items()
                },
            }
        )


def run_daemon(preferred_port: int | None = None) -> int:
    return _Daemon(preferred_port).run()
