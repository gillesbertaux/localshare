"""On-disk state shared between the CLI and the LAN daemon.

The registry is the list of projects currently exposed on the LAN. The CLI
only ever edits the registry; the daemon reconciles reality against it.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import signal
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REGISTRY_VERSION = 1


def state_dir() -> Path:
    override = os.environ.get("LOCALSHARE_STATE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "localshare"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return base / "localshare"


def registry_path() -> Path:
    return state_dir() / "registry.json"


def daemon_pid_path() -> Path:
    return state_dir() / "daemon.pid"


def daemon_info_path() -> Path:
    return state_dir() / "daemon.json"


def daemon_log_path() -> Path:
    return state_dir() / "daemon.log"


def _lock_path() -> Path:
    return state_dir() / "registry.lock"


def ensure_state_dir() -> Path:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@dataclass
class LanEntry:
    """One project's claim on a `<name>.local` name."""

    name: str
    hostname: str
    port: int
    config_path: str
    updated_at: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LanEntry":
        return cls(
            name=str(data["name"]),
            hostname=str(data.get("hostname") or data["name"]),
            port=int(data["port"]),
            config_path=str(data.get("config_path", "")),
            updated_at=float(data.get("updated_at", 0.0)),
        )


@contextmanager
def _locked() -> Iterator[None]:
    ensure_state_dir()
    handle = os.open(_lock_path(), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def _read_unlocked() -> dict[str, LanEntry]:
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != REGISTRY_VERSION:
        return {}
    entries = raw.get("lan")
    if not isinstance(entries, list):
        return {}
    out: dict[str, LanEntry] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        try:
            entry = LanEntry.from_dict(item)
        except (KeyError, TypeError, ValueError):
            continue
        out[entry.name] = entry
    return out


def _write_unlocked(entries: dict[str, LanEntry]) -> None:
    ensure_state_dir()
    payload = {
        "version": REGISTRY_VERSION,
        "lan": [asdict(entry) for entry in sorted(entries.values(), key=lambda e: e.name)],
    }
    path = registry_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_lan_entries() -> dict[str, LanEntry]:
    with _locked():
        return _read_unlocked()


def put_lan_entry(entry: LanEntry) -> dict[str, LanEntry]:
    with _locked():
        entries = _read_unlocked()
        entries[entry.name] = entry
        _write_unlocked(entries)
        return entries


def drop_lan_entry(name: str) -> tuple[bool, dict[str, LanEntry]]:
    with _locked():
        entries = _read_unlocked()
        existed = entries.pop(name, None) is not None
        _write_unlocked(entries)
        return existed, entries


def registry_mtime() -> float:
    try:
        return registry_path().stat().st_mtime
    except OSError:
        return 0.0


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return exc.errno == errno.EPERM
    return True


def read_daemon_pid() -> int | None:
    try:
        pid = int(daemon_pid_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def write_daemon_pid(pid: int) -> None:
    ensure_state_dir()
    daemon_pid_path().write_text(f"{pid}\n", encoding="utf-8")


def clear_daemon_files() -> None:
    for path in (daemon_pid_path(), daemon_info_path()):
        try:
            path.unlink()
        except OSError:
            pass


def read_daemon_info() -> dict[str, Any] | None:
    try:
        data = json.loads(daemon_info_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int) or not pid_alive(pid):
        return None
    return data


def write_daemon_info(info: dict[str, Any]) -> None:
    ensure_state_dir()
    path = daemon_info_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def stop_daemon(timeout: float = 5.0) -> bool:
    pid = read_daemon_pid()
    if pid is None:
        clear_daemon_files()
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        clear_daemon_files()
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            break
        time.sleep(0.05)
    clear_daemon_files()
    return True
