"""Translate localshare.yaml into an action: Tailscale argv, or a LAN route."""

from __future__ import annotations

from dataclasses import dataclass, field

from localshare.config import FUNNEL_HTTPS_PORTS, Config
from localshare.errors import ConfigError, PreconditionError

VALID_REACH = frozenset({"tailnet", "public", "lan", "off"})

BACKEND_TAILSCALE = "tailscale"
BACKEND_LAN = "lan"


@dataclass(frozen=True)
class Plan:
    reach: str
    backend: str
    persist: bool
    reset_first: bool
    binary_argv: list[str] = field(default_factory=list)
    lan_hostname: str | None = None
    lan_target_port: int | None = None
    lan_preferred_port: int | None = None


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


def _compile_lan(config: Config, reach: str) -> Plan:
    if config.target.port is None:
        raise PreconditionError(
            "LAN reach needs target.port (the proxy speaks plain HTTP to "
            "127.0.0.1; target.url is Tailscale-only)"
        )
    return Plan(
        reach=reach,
        backend=BACKEND_LAN,
        persist=True,
        reset_first=False,
        lan_hostname=config.lan.hostname or config.name,
        lan_target_port=config.target.port,
        lan_preferred_port=config.lan.port,
    )


def compile_up(config: Config, reach_override: str | None = None) -> Plan:
    reach = resolve_reach(config, reach_override)
    if reach == "lan":
        return _compile_lan(config, reach)

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
        backend=BACKEND_TAILSCALE,
        persist=persist,
        reset_first=config.security.exclusive,
        binary_argv=argv,
    )


def public_url(dns_name: str, https_port: int, path: str) -> str:
    host = dns_name.rstrip(".")
    origin = f"https://{host}" if https_port == 443 else f"https://{host}:{https_port}"
    if path in ("", "/"):
        return f"{origin}/"
    return f"{origin}{path}"
