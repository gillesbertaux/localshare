from __future__ import annotations

import json
import subprocess
from io import StringIO
from pathlib import Path

from localshare.cli import main
from localshare.errors import EXIT_OK, EXIT_PRECONDITION, EXIT_USAGE
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


def _run(tmp_path: Path, argv: list[str], runner: FakeRunner | None = None) -> tuple[int, str, str, FakeRunner]:
    runner = runner or FakeRunner()
    ts = Tailscale(binary="/usr/bin/true", runner=runner)
    stdout, stderr = StringIO(), StringIO()
    code = main(argv, cwd=tmp_path, tailscale=ts, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue(), runner


def _write_config(tmp_path: Path, *, public: bool = False) -> None:
    allow = "true" if public else "false"
    (tmp_path / "localshare.yaml").write_text(
        f"""
schema: 1
name: venue
target:
  port: 3000
allow:
  public: {allow}
""",
        encoding="utf-8",
    )


def test_missing_config(tmp_path: Path) -> None:
    code, _, err, _ = _run(tmp_path, ["validate"])
    assert code == EXIT_USAGE
    assert "not localshare-capable" in err


def test_validate_ok(tmp_path: Path) -> None:
    _write_config(tmp_path)
    code, out, _, _ = _run(tmp_path, ["validate"])
    assert code == EXIT_OK
    assert "name=venue" in out


def test_init_and_validate(tmp_path: Path) -> None:
    code, out, _, _ = _run(tmp_path, ["init", "--name", "shop", "--port", "5173"])
    assert code == EXIT_OK
    assert (tmp_path / "localshare.yaml").is_file()
    code, out, _, _ = _run(tmp_path, ["validate"])
    assert code == EXIT_OK
    assert "name=shop" in out


def test_up_serve(tmp_path: Path) -> None:
    _write_config(tmp_path)
    runner = FakeRunner()
    code, out, _, runner = _run(tmp_path, ["up"], runner)
    assert code == EXIT_OK
    assert ["serve", "reset"] in [c[1:] for c in runner.calls]
    assert ["funnel", "reset"] in [c[1:] for c in runner.calls]
    applied = [c[1:] for c in runner.calls if c[1] in {"serve", "funnel"} and "reset" not in c]
    assert ["serve", "--bg", "--yes", "--https=443", "3000"] in applied
    assert "https://mac.example.ts.net/" in out


def test_up_public_requires_yes(tmp_path: Path) -> None:
    _write_config(tmp_path, public=True)
    code, _, err, _ = _run(tmp_path, ["up", "--public"])
    assert code == EXIT_PRECONDITION
    assert "--yes" in err


def test_up_public_with_yes(tmp_path: Path) -> None:
    _write_config(tmp_path, public=True)
    runner = FakeRunner()
    code, out, _, runner = _run(tmp_path, ["up", "--public", "--yes"], runner)
    assert code == EXIT_OK
    applied = [c[1:] for c in runner.calls if c[1] == "funnel" and "reset" not in c]
    assert ["funnel", "--yes", "--https=443", "3000"] in applied
    assert "warning" in out


def test_url_json(tmp_path: Path) -> None:
    _write_config(tmp_path)
    code, out, _, _ = _run(tmp_path, ["--json", "url"])
    assert code == EXIT_OK
    payload = json.loads(out)
    assert payload["url"] == "https://mac.example.ts.net/"


def test_discovery_walks_up(tmp_path: Path) -> None:
    _write_config(tmp_path)
    nested = tmp_path / "app" / "src"
    nested.mkdir(parents=True)
    code, out, _, _ = _run(nested, ["validate"])
    assert code == EXIT_OK
    assert "venue" in out
