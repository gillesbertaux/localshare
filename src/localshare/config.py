"""Load and validate localshare.yaml (plus optional local overlay)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
    stop_on_exit: bool = True
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
    raw: dict[str, Any] = field(default_factory=dict)


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


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
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


def parse_config(data: dict[str, Any], path: Path) -> Config:
    schema = data.get("schema", SCHEMA_VERSION)
    if schema != SCHEMA_VERSION:
        raise ConfigError(f"unsupported schema {schema}; expected {SCHEMA_VERSION}")

    name = data.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ConfigError(
            "name must be a DNS label: lowercase letters, digits, hyphens "
            "(1–63 chars, not starting or ending with a hyphen)"
        )

    target_raw = _require_mapping(data.get("target"), "target")
    port = _opt_int(target_raw.get("port"), "target.port")
    url = target_raw.get("url")
    if url is not None and not isinstance(url, str):
        raise ConfigError("target.url must be a string")
    if (port is None) == (not url):
        raise ConfigError("set exactly one of target.port or target.url")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError("target.port must be between 1 and 65535")

    reach = data.get("reach", "tailnet")
    if reach not in REACH_VALUES:
        raise ConfigError(f"reach must be one of {sorted(REACH_VALUES)}")

    allow_raw = _require_mapping(data.get("allow"), "allow")
    allow = Allow(
        public=bool(allow_raw.get("public", False)),
        lan=bool(allow_raw.get("lan", False)),
    )
    if reach == "public" and not allow.public:
        raise ConfigError("reach: public requires allow.public: true")
    if reach == "lan" and not allow.lan:
        raise ConfigError("reach: lan requires allow.lan: true")

    ts_raw = _require_mapping(data.get("tailscale"), "tailscale")
    https_port = ts_raw.get("https_port", 443)
    if isinstance(https_port, bool) or not isinstance(https_port, int):
        raise ConfigError("tailscale.https_port must be an integer")
    path_value = ts_raw.get("path", "/")
    if not isinstance(path_value, str) or not path_value.startswith("/"):
        raise ConfigError("tailscale.path must start with /")
    persist = _opt_bool(ts_raw.get("persist"), "tailscale.persist")
    proxy_protocol = _opt_int(ts_raw.get("proxy_protocol"), "tailscale.proxy_protocol")
    if proxy_protocol is not None and proxy_protocol not in (1, 2):
        raise ConfigError("tailscale.proxy_protocol must be 1 or 2")
    service = ts_raw.get("service")
    if service is not None and not isinstance(service, str):
        raise ConfigError("tailscale.service must be a string")

    ts = TailscaleOpts(
        https_port=https_port,
        path=path_value,
        persist=persist,
        proxy_protocol=proxy_protocol,
        service=service,
    )
    if reach == "public" and ts.https_port not in FUNNEL_HTTPS_PORTS:
        raise ConfigError(
            f"Funnel https_port must be one of {sorted(FUNNEL_HTTPS_PORTS)}"
        )

    lan_raw = _require_mapping(data.get("lan"), "lan")
    hostname = lan_raw.get("hostname")
    if hostname is not None and not isinstance(hostname, str):
        raise ConfigError("lan.hostname must be a string")
    if hostname is not None and not NAME_RE.fullmatch(hostname):
        raise ConfigError("lan.hostname must be a DNS label (it becomes <host>.local)")
    lan_port = _opt_int(lan_raw.get("port"), "lan.port")
    if lan_port is not None and not 1 <= lan_port <= 65535:
        raise ConfigError("lan.port must be between 1 and 65535")

    sec_raw = _require_mapping(data.get("security"), "security")
    security = Security(
        exclusive=bool(sec_raw.get("exclusive", True)),
        stop_on_exit=bool(sec_raw.get("stop_on_exit", True)),
        confirm_public=bool(sec_raw.get("confirm_public", True)),
    )

    return Config(
        schema=schema,
        name=name,
        target=Target(port=port, url=url),
        reach=reach,
        allow=allow,
        tailscale=ts,
        lan=LanOpts(hostname=hostname, port=lan_port),
        security=security,
        path=path,
        raw=data,
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
