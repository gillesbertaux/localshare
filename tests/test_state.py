from __future__ import annotations

from pathlib import Path

import pytest

from localshare import state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALSHARE_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def _entry(name: str, port: int) -> state.LanEntry:
    return state.LanEntry(
        name=name,
        hostname=name,
        port=port,
        config_path=f"/tmp/{name}/localshare.yaml",
        updated_at=1.0,
    )


def test_registry_roundtrip() -> None:
    assert state.read_lan_entries() == {}
    state.put_lan_entry(_entry("venue", 3000))
    state.put_lan_entry(_entry("shop", 5173))
    entries = state.read_lan_entries()
    assert sorted(entries) == ["shop", "venue"]
    assert entries["venue"].port == 3000


def test_put_is_idempotent_per_name() -> None:
    state.put_lan_entry(_entry("venue", 3000))
    state.put_lan_entry(_entry("venue", 4000))
    entries = state.read_lan_entries()
    assert len(entries) == 1
    assert entries["venue"].port == 4000


def test_drop_reports_existence() -> None:
    state.put_lan_entry(_entry("venue", 3000))
    existed, remaining = state.drop_lan_entry("venue")
    assert existed is True
    assert remaining == {}
    existed, _ = state.drop_lan_entry("venue")
    assert existed is False


def test_corrupt_registry_is_ignored() -> None:
    state.ensure_state_dir()
    state.registry_path().write_text("{not json", encoding="utf-8")
    assert state.read_lan_entries() == {}


def test_daemon_info_requires_live_pid() -> None:
    state.write_daemon_info({"pid": 999_999_999, "port": 80})
    assert state.read_daemon_info() is None


def test_daemon_info_with_own_pid() -> None:
    import os

    state.write_daemon_info({"pid": os.getpid(), "port": 7777})
    info = state.read_daemon_info()
    assert info is not None
    assert info["port"] == 7777
