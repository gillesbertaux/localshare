from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from localshare import state
from localshare.cli import main
from localshare.errors import EXIT_OK, EXIT_PRECONDITION, EXIT_USAGE
from localshare.mdns import Publisher
from localshare.netinfo import lan_url
from localshare.tailscale import Tailscale


class FakeRunner:
    def __init__(self, dns: str = "mac.example.ts.net.") -> None:
        self.calls: list[list[str]] = []
        self.dns = dns
        self.backend = "Running"

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        stdout = ""
        rest = argv[1:]
        if rest[:2] == ["status", "--json"]:
            stdout = json.dumps(
                {
                    "BackendState": self.backend,
                    "Self": {"DNSName": self.dns},
                }
            )
        elif rest[:2] == ["serve", "status"] or rest[:2] == ["funnel", "status"]:
            stdout = "{}"
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


class FakeDaemon:
    """Stands in for the real daemon: no proxy, no mDNS, no subprocess."""

    def __init__(self, port: int = 80) -> None:
        self.port = port
        self.running = False
        self.ensure_calls: list[int | None] = []
        self.stop_calls = 0

    def _info(self) -> dict[str, Any] | None:
        if not self.running:
            return None
        entries = state.read_lan_entries()
        return {
            "pid": 4242,
            "port": self.port,
            "ip": "192.168.1.24",
            "projects": {
                name: {
                    "hostname": entry.hostname,
                    "target_port": entry.port,
                    "url": lan_url(entry.hostname, self.port),
                }
                for name, entry in entries.items()
            },
        }

    def ensure(self, preferred_port: int | None) -> dict[str, Any]:
        self.ensure_calls.append(preferred_port)
        if preferred_port:
            self.port = preferred_port
        self.running = True
        return self._info() or {}

    def stop(self) -> bool:
        self.stop_calls += 1
        was_running = self.running
        self.running = False
        return was_running

    def info(self) -> dict[str, Any] | None:
        return self._info()

    def refresh(self) -> dict[str, Any] | None:
        return self._info()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALSHARE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(
        "localshare.cli.find_publisher",
        lambda: Publisher(binary="/usr/bin/dns-sd", kind="dns-sd"),
    )


def _run(
    tmp_path: Path,
    argv: list[str],
    runner: FakeRunner | None = None,
    daemon: FakeDaemon | None = None,
) -> tuple[int, str, str, FakeRunner, FakeDaemon]:
    runner = runner or FakeRunner()
    daemon = daemon or FakeDaemon()
    ts = Tailscale(binary="/usr/bin/true", runner=runner)
    stdout, stderr = StringIO(), StringIO()
    code = main(
        argv,
        cwd=tmp_path,
        tailscale=ts,
        daemon=daemon,
        stdout=stdout,
        stderr=stderr,
    )
    return code, stdout.getvalue(), stderr.getvalue(), runner, daemon


def _write_config(
    tmp_path: Path,
    *,
    public: bool = False,
    lan: bool = False,
    reach: str = "tailnet",
    extra: str = "",
) -> None:
    (tmp_path / "localshare.yaml").write_text(
        f"""
schema: 1
name: venue
target:
  port: 3000
reach: {reach}
allow:
  lan: {str(lan).lower()}
  public: {str(public).lower()}
{extra}""",
        encoding="utf-8",
    )


def test_missing_config(tmp_path: Path) -> None:
    code, _, err, _, _ = _run(tmp_path, ["validate"])
    assert code == EXIT_USAGE
    assert "not localshare-capable" in err


def test_validate_ok(tmp_path: Path) -> None:
    _write_config(tmp_path)
    code, out, _, _, _ = _run(tmp_path, ["validate"])
    assert code == EXIT_OK
    assert "name=venue" in out


def test_init_and_validate(tmp_path: Path) -> None:
    code, _, _, _, _ = _run(tmp_path, ["init", "--name", "shop", "--port", "5173"])
    assert code == EXIT_OK
    assert (tmp_path / "localshare.yaml").is_file()
    code, out, _, _, _ = _run(tmp_path, ["validate"])
    assert code == EXIT_OK
    assert "name=shop" in out


def test_init_allow_lan(tmp_path: Path) -> None:
    code, _, _, _, _ = _run(
        tmp_path, ["init", "--name", "shop", "--port", "5173", "--allow-lan"]
    )
    assert code == EXIT_OK
    code, out, _, _, _ = _run(tmp_path, ["--json", "validate"])
    assert json.loads(out)["config"]["allow"]["lan"] is True


def test_up_serve(tmp_path: Path) -> None:
    _write_config(tmp_path)
    code, out, _, runner, _ = _run(tmp_path, ["up"])
    assert code == EXIT_OK
    assert ["serve", "reset"] in [c[1:] for c in runner.calls]
    applied = [c[1:] for c in runner.calls if c[1] in {"serve", "funnel"} and "reset" not in c]
    assert ["serve", "--bg", "--yes", "--https=443", "3000"] in applied
    assert "https://mac.example.ts.net/" in out


def test_up_public_requires_yes(tmp_path: Path) -> None:
    _write_config(tmp_path, public=True)
    code, _, err, _, _ = _run(tmp_path, ["up", "--public"])
    assert code == EXIT_PRECONDITION
    assert "--yes" in err


def test_up_public_with_yes(tmp_path: Path) -> None:
    _write_config(tmp_path, public=True)
    code, out, _, runner, _ = _run(tmp_path, ["up", "--public", "--yes"])
    assert code == EXIT_OK
    applied = [c[1:] for c in runner.calls if c[1] == "funnel" and "reset" not in c]
    assert ["funnel", "--yes", "--https=443", "3000"] in applied
    assert "warning" in out


def test_up_lan_registers_and_prints_local_url(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    code, out, _, runner, daemon = _run(tmp_path, ["up", "--lan"])
    assert code == EXIT_OK
    assert "http://venue.local/" in out
    assert state.read_lan_entries()["venue"].port == 3000
    assert daemon.ensure_calls == [None]
    assert runner.calls == []


def test_up_lan_requires_allow(tmp_path: Path) -> None:
    _write_config(tmp_path)
    code, _, err, _, daemon = _run(tmp_path, ["up", "--lan"])
    assert code == EXIT_PRECONDITION
    assert "allow.lan" in err
    assert state.read_lan_entries() == {}
    assert daemon.ensure_calls == []


def test_up_lan_reports_fallback_port(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    code, out, _, _, _ = _run(tmp_path, ["up", "--lan", "--lan-port", "7777"], daemon=FakeDaemon())
    assert code == EXIT_OK
    assert "http://venue.local:7777/" in out
    assert "port 80 unavailable" in out


def test_lan_reach_from_config(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True, reach="lan")
    code, out, _, runner, _ = _run(tmp_path, ["up"])
    assert code == EXIT_OK
    assert "reach   lan" in out
    assert runner.calls == []


def test_url_lan(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True, reach="lan")
    daemon = FakeDaemon()
    _run(tmp_path, ["up"], daemon=daemon)
    code, out, _, _, _ = _run(tmp_path, ["--json", "url"], daemon=daemon)
    assert code == EXIT_OK
    payload = json.loads(out)
    assert payload == {"name": "venue", "reach": "lan", "url": "http://venue.local/"}


def test_url_lan_when_not_up(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True, reach="lan")
    code, _, err, _, _ = _run(tmp_path, ["url"])
    assert code == EXIT_PRECONDITION
    assert "up --lan" in err


def test_url_json_tailnet(tmp_path: Path) -> None:
    _write_config(tmp_path)
    code, out, _, _, _ = _run(tmp_path, ["--json", "url"])
    assert code == EXIT_OK
    assert json.loads(out)["url"] == "https://mac.example.ts.net/"


def test_down_clears_both(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    daemon = FakeDaemon()
    _run(tmp_path, ["up", "--lan"], daemon=daemon)
    code, out, _, runner, daemon = _run(tmp_path, ["down"], daemon=daemon)
    assert code == EXIT_OK
    assert "removed venue.local" in out
    assert state.read_lan_entries() == {}
    assert daemon.stop_calls == 1
    assert ["serve", "reset"] in [c[1:] for c in runner.calls]


def test_down_lan_only_leaves_tailscale_alone(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    daemon = FakeDaemon()
    _run(tmp_path, ["up", "--lan"], daemon=daemon)
    code, _, _, runner, _ = _run(tmp_path, ["down", "--lan"], daemon=daemon)
    assert code == EXIT_OK
    assert runner.calls == []
    assert state.read_lan_entries() == {}


def test_down_keeps_daemon_for_other_projects(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    daemon = FakeDaemon()
    _run(tmp_path, ["up", "--lan"], daemon=daemon)
    state.put_lan_entry(
        state.LanEntry(
            name="other",
            hostname="other",
            port=4000,
            config_path="/tmp/other/localshare.yaml",
            updated_at=1.0,
        )
    )
    code, _, _, _, daemon = _run(tmp_path, ["down", "--lan"], daemon=daemon)
    assert code == EXIT_OK
    assert daemon.stop_calls == 0
    assert list(state.read_lan_entries()) == ["other"]


def test_status_shows_both_rungs(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    daemon = FakeDaemon()
    _run(tmp_path, ["up", "--lan"], daemon=daemon)
    code, out, _, _, _ = _run(tmp_path, ["--json", "status"], daemon=daemon)
    assert code == EXIT_OK
    payload = json.loads(out)
    assert payload["lan"]["registered"] is True
    assert payload["lan"]["url"] == "http://venue.local/"
    assert payload["tailscale"]["dns_name"] == "mac.example.ts.net."


def test_status_lan_off_by_default(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    code, out, _, _, _ = _run(tmp_path, ["status"])
    assert code == EXIT_OK
    assert "lan     off" in out


def test_doctor_reports_mdns_and_daemon(tmp_path: Path) -> None:
    code, out, _, _, _ = _run(tmp_path, ["--json", "doctor"])
    assert code == EXIT_OK
    payload = json.loads(out)
    assert payload["mdns_publisher"] == "/usr/bin/dns-sd"
    assert payload["lan_daemon"] is None


def test_daemon_subcommand(tmp_path: Path) -> None:
    _write_config(tmp_path, lan=True)
    daemon = FakeDaemon()
    _run(tmp_path, ["up", "--lan"], daemon=daemon)
    code, out, _, _, _ = _run(tmp_path, ["daemon"], daemon=daemon)
    assert code == EXIT_OK
    assert "venue -> http://venue.local/" in out
    code, out, _, _, daemon = _run(tmp_path, ["daemon", "--stop"], daemon=daemon)
    assert "daemon stopped" in out


def test_discovery_walks_up(tmp_path: Path) -> None:
    _write_config(tmp_path)
    nested = tmp_path / "app" / "src"
    nested.mkdir(parents=True)
    code, out, _, _, _ = _run(nested, ["validate"])
    assert code == EXIT_OK
    assert "venue" in out
