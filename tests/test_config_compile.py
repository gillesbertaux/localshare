from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from localshare.compile import LanPlan, TailscalePlan, compile_up, public_url
from localshare.config import parse_config
from localshare.errors import ConfigError, PreconditionError

MINIMAL = """
schema: 1
name: venue
target:
  port: 3000
"""

LAN = """
schema: 1
name: storefront
target:
  port: 5173
allow:
  lan: true
"""


def cfg(tmp_path: Path, text: str):
    path = tmp_path / "localshare.yaml"
    path.write_text(text, encoding="utf-8")
    return parse_config(yaml.safe_load(text), path)


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


def test_rejects_bad_lan_hostname(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="lan.hostname"):
        cfg(tmp_path, LAN + "lan:\n  hostname: Shop_1\n")


def test_rejects_out_of_range_port(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="target.port must be between"):
        cfg(tmp_path, "schema: 1\nname: x\ntarget:\n  port: 99999\n")


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
    assert isinstance(plan, TailscalePlan)
    assert plan.reach == "tailnet"
    assert plan.persist is True
    assert plan.reset_first is True
    assert plan.argv == ["serve", "--bg", "--yes", "--https=443", "3000"]


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
    assert isinstance(plan, TailscalePlan)
    assert plan.reach == "public"
    assert plan.persist is False
    assert plan.argv == ["funnel", "--yes", "--https=443", "8787"]


def test_funnel_override_rejects_bad_https_port(tmp_path: Path) -> None:
    config = cfg(
        tmp_path,
        """
schema: 1
name: hooks
target:
  port: 8787
allow:
  public: true
tailscale:
  https_port: 8080
""",
    )
    with pytest.raises(ConfigError, match="Funnel https_port"):
        compile_up(config, "public")


def test_public_disallowed(tmp_path: Path) -> None:
    with pytest.raises(PreconditionError, match="allow.public"):
        compile_up(cfg(tmp_path, MINIMAL), "public")


@pytest.mark.parametrize("literal", ["off", '"off"'])
def test_reach_off_needs_a_flag(tmp_path: Path, literal: str) -> None:
    """Bare `off` is a YAML 1.1 boolean; both spellings must mean the same thing."""
    config = cfg(tmp_path, f"schema: 1\nname: x\ntarget:\n  port: 80\nreach: {literal}\n")
    assert config.reach == "off"
    with pytest.raises(PreconditionError, match="reach is off"):
        compile_up(config)


def test_rejects_unknown_reach(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="reach must be one of"):
        cfg(tmp_path, "schema: 1\nname: x\ntarget:\n  port: 80\nreach: everyone\n")


def test_service_is_reserved(tmp_path: Path) -> None:
    config = cfg(tmp_path, MINIMAL + "tailscale:\n  service: svc:web\n")
    with pytest.raises(PreconditionError, match="reserved"):
        compile_up(config)


def test_lan_plan(tmp_path: Path) -> None:
    plan = compile_up(cfg(tmp_path, LAN), "lan")
    assert isinstance(plan, LanPlan)
    assert plan.hostname == "storefront"
    assert plan.target_port == 5173
    assert plan.preferred_port is None


def test_lan_hostname_override(tmp_path: Path) -> None:
    plan = compile_up(cfg(tmp_path, LAN + "lan:\n  hostname: shop\n  port: 8080\n"), "lan")
    assert isinstance(plan, LanPlan)
    assert plan.hostname == "shop"
    assert plan.preferred_port == 8080


def test_lan_ignores_reserved_service(tmp_path: Path) -> None:
    """Tailscale Services are irrelevant to a LAN share, so they do not block it."""
    plan = compile_up(cfg(tmp_path, LAN + "tailscale:\n  service: svc:web\n"), "lan")
    assert isinstance(plan, LanPlan)


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
    assert isinstance(plan, TailscalePlan)
    assert plan.argv == [
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
