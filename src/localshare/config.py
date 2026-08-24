"""Load and validate localshare.yaml (plus optional local overlay)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from localshare.errors import ConfigError

SCHEMA_VERSION = 1
REACH_VALUES = frozenset({"tailnet", "public", "lan", "off"})
FUNNEL_HTTPS_PORTS = frozenset({443, 8443, 10000})
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

CONFIG_FILENAMES = ("localshare.yaml", "localshare.yml")
LOCAL_FILENAMES = ("localshare.local.yaml", "localshare.local.yml")


@dataclass
class Target:
    port: int | None = None
    url: str | None = None

    def as_tailscale_target(self) -> str:
        if self.url:
            return self.url
        if self.port is None:
            raise ConfigError("target.port or target.url is required")
        return str(self.port)


@dataclass
class Allow:
    public: bool = False
    lan: bool = False


@dataclass
class TailscaleOpts:
    https_port: int = 443
    path: str = "/"
    persist: bool | None = None
    proxy_protocol: int | None = None
    service: str | None = None


@dataclass
class LanOpts:
    hostname: str | None = None
    port: int | None = None


@dataclass
class Security:
    exclusive: bool = True
    confirm_public: bool = True


@dataclass
class Config:
    schema: int
    name: str
    target: Target
    reach: str
    allow: Allow
    tailscale: TailscaleOpts
    lan: LanOpts
    security: Security
    path: Path


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in overlay.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for directory in [current, *current.parents]:
        for name in CONFIG_FILENAMES:
            if (directory / name).is_file():
                return directory
    return None


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path} must be a mapping")
    return loaded


def _config_file(root: Path) -> Path:
    for name in CONFIG_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise ConfigError(f"no localshare.yaml under {root}")


def _local_file(root: Path) -> Path | None:
    for name in LOCAL_FILENAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def load_raw(root: Path) -> tuple[Path, dict[str, Any]]:
    config_path = _config_file(root)
    data = _read_yaml(config_path)
    overlay_path = _local_file(root)
    if overlay_path is not None:
        data = deep_merge(data, _read_yaml(overlay_path))
    return config_path, data


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field_name} must be a mapping")
    return value


def _opt_bool(value: Any, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ConfigError(f"{field_name} must be a boolean")
    return value


def _opt_int(value: Any, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} must be an integer")
    return value


def _opt_port(value: Any, field_name: str) -> int | None:
    port = _opt_int(value, field_name)
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError(f"{field_name} must be between 1 and 65535")
    return port


def _opt_dns_label(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ConfigError(
            f"{field_name} must be a DNS label: lowercase letters, digits, "
            "hyphens (1–63 chars, not starting or ending with a hyphen)"
        )
    return value


def _parse_reach(value: Any) -> str:
    # YAML 1.1 parses a bare `off` as the boolean False, and `reach: off` is
    # the documented way to keep a project shareable but not shared.
    if value is False:
        return "off"
    if value not in REACH_VALUES:
        raise ConfigError(f"reach must be one of {sorted(REACH_VALUES)}")
    return value


def _parse_target(raw: dict[str, Any]) -> Target:
    port = _opt_port(raw.get("port"), "target.port")
    url = raw.get("url")
    if url is not None and not isinstance(url, str):
        raise ConfigError("target.url must be a string")
    if (port is None) == (not url):
        raise ConfigError("set exactly one of target.port or target.url")
    return Target(port=port, url=url)


def _parse_allow(raw: dict[str, Any], reach: str) -> Allow:
    allow = Allow(
        public=bool(raw.get("public", False)),
        lan=bool(raw.get("lan", False)),
    )
    if reach == "public" and not allow.public:
        raise ConfigError("reach: public requires allow.public: true")
    if reach == "lan" and not allow.lan:
        raise ConfigError("reach: lan requires allow.lan: true")
    return allow


def _parse_tailscale(raw: dict[str, Any], reach: str) -> TailscaleOpts:
    https_port = _opt_port(raw.get("https_port"), "tailscale.https_port") or 443
    if reach == "public" and https_port not in FUNNEL_HTTPS_PORTS:
        raise ConfigError(
            f"Funnel https_port must be one of {sorted(FUNNEL_HTTPS_PORTS)}"
        )
    path = raw.get("path", "/")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ConfigError("tailscale.path must start with /")
    proxy_protocol = _opt_int(raw.get("proxy_protocol"), "tailscale.proxy_protocol")
    if proxy_protocol is not None and proxy_protocol not in (1, 2):
        raise ConfigError("tailscale.proxy_protocol must be 1 or 2")
    service = raw.get("service")
    if service is not None and not isinstance(service, str):
        raise ConfigError("tailscale.service must be a string")
    return TailscaleOpts(
        https_port=https_port,
        path=path,
        persist=_opt_bool(raw.get("persist"), "tailscale.persist"),
        proxy_protocol=proxy_protocol,
        service=service,
    )


def _parse_lan(raw: dict[str, Any]) -> LanOpts:
    return LanOpts(
        hostname=_opt_dns_label(raw.get("hostname"), "lan.hostname"),
        port=_opt_port(raw.get("port"), "lan.port"),
    )


def _parse_security(raw: dict[str, Any]) -> Security:
    return Security(
        exclusive=bool(raw.get("exclusive", True)),
        confirm_public=bool(raw.get("confirm_public", True)),
    )


def parse_config(data: dict[str, Any], path: Path) -> Config:
    schema = data.get("schema", SCHEMA_VERSION)
    if schema != SCHEMA_VERSION:
        raise ConfigError(f"unsupported schema {schema}; expected {SCHEMA_VERSION}")

    name = _opt_dns_label(data.get("name"), "name")
    if name is None:
        raise ConfigError("name is required")

    reach = _parse_reach(data.get("reach", "tailnet"))

    return Config(
        schema=schema,
        name=name,
        target=_parse_target(_mapping(data.get("target"), "target")),
        reach=reach,
        allow=_parse_allow(_mapping(data.get("allow"), "allow"), reach),
        tailscale=_parse_tailscale(_mapping(data.get("tailscale"), "tailscale"), reach),
        lan=_parse_lan(_mapping(data.get("lan"), "lan")),
        security=_parse_security(_mapping(data.get("security"), "security")),
        path=path,
    )


def load_config(start: Path) -> Config:
    root = find_project_root(start)
    if root is None:
        raise ConfigError(
            f"no localshare.yaml found from {start.resolve()} "
            "(this project is not localshare-capable)"
        )
    config_path, data = load_raw(root)
    return parse_config(data, config_path)
