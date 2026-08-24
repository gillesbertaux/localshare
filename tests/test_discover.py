from __future__ import annotations

from pathlib import Path

from localshare.config import find_project_root, load_config


def test_finds_from_nested_dir(tmp_path: Path) -> None:
    (tmp_path / "localshare.yaml").write_text(
        "schema: 1\nname: nest\ntarget:\n  port: 9\n",
        encoding="utf-8",
    )
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_project_root(nested) == tmp_path
    config = load_config(nested)
    assert config.name == "nest"


def test_local_overlay(tmp_path: Path) -> None:
    (tmp_path / "localshare.yaml").write_text(
        "schema: 1\nname: nest\ntarget:\n  port: 9\n",
        encoding="utf-8",
    )
    (tmp_path / "localshare.local.yaml").write_text(
        "target:\n  port: 4000\n",
        encoding="utf-8",
    )
    assert load_config(tmp_path).target.port == 4000
