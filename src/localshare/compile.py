"""Turn a validated config plus flags into the one action `up` should take."""

from __future__ import annotations

from dataclasses import dataclass

from localshare.config import FUNNEL_HTTPS_PORTS, REACH_VALUES, Config
from localshare.errors import ConfigError, PreconditionError


@dataclass(frozen=True)
class TailscalePlan:
    """A `tailscale serve` / `tailscale funnel` invocation."""

    reach: str
    argv: list[str]
    persist: bool
    reset_first: bool


@dataclass(frozen=True)
class LanPlan:
    """A name to advertise and the local port to route it to."""

    hostname: str
    target_port: int
    preferred_port: int | None


Plan = TailscalePlan | LanPlan


def effective_persist(reach: str, persist: bool | None) -> bool:
    """Tailnet shares survive a reboot; public ones must be re-armed."""
    if persist is not None:
        return persist
    return reach == "tailnet"


def resolve_reach(config: Config, override: str | None) -> str:
    reach = override or config.reach
    if reach not in REACH_VALUES:
        raise ConfigError(f"unknown reach {reach!r}")
    if reach == "off":
        raise PreconditionError(
            "reach is off; pass --tailnet, --lan, or --public (if allowed) to expose"
        )
    if reach == "public" and not config.allow.public:
        raise PreconditionError(
            "public funnel is not allowed for this project (allow.public: false)"
        )
    if reach == "lan" and not config.allow.lan:
        raise PreconditionError(
            "LAN is not allowed for this project (allow.lan: false)"
        )
    if reach != "lan" and config.tailscale.service:
        raise PreconditionError(
            "tailscale.service (Tailscale Services) is reserved for a later "
            "version; remove it to share this project"
        )
    return reach


def _lan_plan(config: Config) -> LanPlan:
    if config.target.port is None:
        raise PreconditionError(
            "LAN reach needs target.port (the proxy speaks plain HTTP to "
            "127.0.0.1; target.url is Tailscale-only)"
        )
    return LanPlan(
        hostname=config.lan.hostname or config.name,
        target_port=config.target.port,
        preferred_port=config.lan.port,
    )


def _tailscale_plan(config: Config, reach: str) -> TailscalePlan:
    persist = effective_persist(reach, config.tailscale.persist)
    https_port = config.tailscale.https_port

    if reach == "public":
        # Reachable when --public overrides a file whose own reach is not public,
        # so the port has not been checked against Funnel's allowed set yet.
        if https_port not in FUNNEL_HTTPS_PORTS:
            raise ConfigError(
                f"Funnel https_port must be one of {sorted(FUNNEL_HTTPS_PORTS)}"
            )
        argv = ["funnel"]
    else:
        argv = ["serve"]

    if persist:
        argv.append("--bg")
    argv.extend(["--yes", f"--https={https_port}"])
    if config.tailscale.path != "/":
        argv.append(f"--set-path={config.tailscale.path}")
    if config.tailscale.proxy_protocol is not None:
        argv.extend(["--proxy-protocol", str(config.tailscale.proxy_protocol)])
    argv.append(config.target.as_tailscale_target())

    return TailscalePlan(
        reach=reach,
        argv=argv,
        persist=persist,
        reset_first=config.security.exclusive,
    )


def compile_up(config: Config, reach_override: str | None = None) -> Plan:
    reach = resolve_reach(config, reach_override)
    if reach == "lan":
        return _lan_plan(config)
    return _tailscale_plan(config, reach)


def public_url(dns_name: str, https_port: int, path: str) -> str:
    host = dns_name.rstrip(".")
    origin = f"https://{host}" if https_port == 443 else f"https://{host}:{https_port}"
    if path in ("", "/"):
        return f"{origin}/"
    return f"{origin}{path}"
