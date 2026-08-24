"""Translate localshare.yaml into `tailscale serve` / `funnel` argv."""

from __future__ import annotations

from dataclasses import dataclass

from localshare.config import FUNNEL_HTTPS_PORTS, Config
from localshare.errors import ConfigError, PreconditionError

VALID_REACH = frozenset({"tailnet", "public", "lan", "off"})


@dataclass(frozen=True)
class Plan:
    reach: str
    binary_argv: list[str]
    persist: bool
    reset_first: bool


def effective_persist(reach: str, persist: bool | None) -> bool:
    if persist is not None:
        return persist
    return reach == "tailnet"


def resolve_reach(config: Config, override: str | None) -> str:
    reach = override or config.reach
    if reach not in VALID_REACH:
        raise ConfigError(f"unknown reach {reach!r}")
    if reach == "off":
        raise PreconditionError(
            "reach is off; pass --tailnet or --public (if allowed) to expose"
        )
    if reach == "public" and not config.allow.public:
        raise PreconditionError(
            "public funnel is not allowed for this project (allow.public: false)"
        )
    if reach == "lan" and not config.allow.lan:
        raise PreconditionError(
            "LAN/mDNS is not allowed for this project (allow.lan: false)"
        )
    if reach == "lan":
        raise PreconditionError(
            "LAN/mDNS (.local) is not implemented in v1; use tailnet or public"
        )
    if config.tailscale.service:
        raise PreconditionError(
            "tailscale.service (Tailscale Services) is reserved for a later "
            "version; remove it for v1"
        )
    return reach


def compile_up(config: Config, reach_override: str | None = None) -> Plan:
    reach = resolve_reach(config, reach_override)
    persist = effective_persist(reach, config.tailscale.persist)
    https_port = config.tailscale.https_port
    path = config.tailscale.path
    target = config.target.as_tailscale_target()

    if reach == "public":
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
    if path != "/":
        argv.append(f"--set-path={path}")
    if config.tailscale.proxy_protocol is not None:
        argv.extend(["--proxy-protocol", str(config.tailscale.proxy_protocol)])
    argv.append(target)

    return Plan(
        reach=reach,
        binary_argv=argv,
        persist=persist,
        reset_first=config.security.exclusive,
    )


def public_url(dns_name: str, https_port: int, path: str) -> str:
    host = dns_name.rstrip(".")
    origin = f"https://{host}" if https_port == 443 else f"https://{host}:{https_port}"
    if path in ("", "/"):
        return f"{origin}/"
    return f"{origin}{path}"


public_url = public_url
