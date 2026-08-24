from __future__ import annotations

from pathlib import Path

import pytest

from localshare.compile import compile_up, public_url
from localshare.config import parse_config
from localshare.errors import ConfigError, PreconditionError


def cfg(tmp_path: Path, text: str):
    path = tmp_path / "localshare.yaml"
    path.write_text(text, encoding="utf-8")
    import yaml

    return parse_config(yaml.safe_load(text), path)


MINIMAL = """
schema: 1
name: venue
target:
  port: 3000
"""


def test_minimal_defaults(tmp_path: Path) -> None:
    config = cfg(tmp_path, MINIMAL)
    assert config.name == "venue"
    assert config.reach == "tailnet"
    assert config.allow.public is False
    assert config.tailscale.https_port == 443
    assert config.security.exclusive is True


def test_rejects_bad_name(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="DNS label"):
        cfg(tmp_path, "schema: 1\nname: Venue\ntarget:\n  port: 1\n")


def test_requires_exactly_one_target(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="exactly one"):
        cfg(tmp_path, "schema: 1\nname: x\ntarget: {}\n")


def test_public_reach_requires_allow(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="allow.public"):
        cfg(
            tmp_path,
            "schema: 1\nname: x\ntarget:\n  port: 80\nreach: public\n",
        )


def test_compile_serve_default(tmp_path: Path) -> None:
    plan = compile_up(cfg(tmp_path, MINIMAL))
    assert plan.reach == "tailnet"
    assert plan.persist is True
    assert plan.binary_argv == ["serve", "--bg", "--yes", "--https=443", "3000"]


def test_compile_funnel_without_bg(tmp_path: Path) -> None:
    config = cfg(
        tmp_path,
        """
schema: 1
name: hooks
target:
  port: 8787
reach: tailnet
allow:
  public: true
""",
    )
    plan = compile_up(config, "public")
    assert plan.reach == "public"
    assert plan.persist is False
    assert plan.binary_argv == ["funnel", "--yes", "--https=443", "8787"]


def test_public_disallowed(tmp_path: Path) -> None:
    with pytest.raises(PreconditionError, match="allow.public"):
        compile_up(cfg(tmp_path, MINIMAL), "public")


def test_lan_plan(tmp_path: Path) -> None:
    config = cfg(
        tmp_path,
        """
schema: 1
name: storefront
target:
  port: 5173
allow:
  lan: true
""",
    )
    plan = compile_up(config, "lan")
    assert plan.backend == "lan"
    assert plan.binary_argv == []
    assert plan.lan_hostname == "storefront"
    assert plan.lan_target_port == 5173
    assert plan.reset_first is False


def test_lan_hostname_override(tmp_path: Path) -> None:
    config = cfg(
        tmp_path,
        """
schema: 1
name: storefront
target:
  port: 5173
allow:
  lan: true
lan:
  hostname: shop
  port: 8080
""",
    )
    plan = compile_up(config, "lan")
    assert plan.lan_hostname == "shop"
    assert plan.lan_preferred_port == 8080


def test_lan_disallowed(tmp_path: Path) -> None:
    with pytest.raises(PreconditionError, match="allow.lan"):
        compile_up(cfg(tmp_path, MINIMAL), "lan")


def test_lan_requires_port_target(tmp_path: Path) -> None:
    config = cfg(
        tmp_path,
        """
schema: 1
name: api
target:
  url: https+insecure://127.0.0.1:8443
allow:
  lan: true
""",
    )
    with pytest.raises(PreconditionError, match="target.port"):
        compile_up(config, "lan")


def test_set_path_and_url_target(tmp_path: Path) -> None:
    config = cfg(
        tmp_path,
        """
schema: 1
name: api
target:
  url: https+insecure://127.0.0.1:8443
tailscale:
  path: /api
  persist: false
""",
    )
    plan = compile_up(config)
    assert plan.binary_argv == [
        "serve",
        "--yes",
        "--https=443",
        "--set-path=/api",
        "https+insecure://127.0.0.1:8443",
    ]


def test_public_url() -> None:
    assert public_url("mac.tailnet.ts.net.", 443, "/") == "https://mac.tailnet.ts.net/"
    assert (
        public_url("mac.tailnet.ts.net", 8443, "/app")
        == "https://mac.tailnet.ts.net:8443/app"
    )
