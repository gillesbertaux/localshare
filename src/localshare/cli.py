"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

import yaml

from localshare import __version__
from localshare.compile import compile_up, public_url
from localshare.config import Config, find_project_root, load_config, parse_config
from localshare.errors import (
    EXIT_OK,
    EXIT_USAGE,
    ConfigError,
    LocalshareError,
    PreconditionError,
)
from localshare.tailscale import Tailscale


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localshare",
        description=(
            "Share a local project through Tailscale Serve (tailnet) "
            "or Funnel (public). Driven by localshare.yaml."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "-C",
        "--directory",
        type=Path,
        default=None,
        help="start discovery from this directory (default: cwd)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="machine-readable output on status, url, doctor, validate",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="expose the project according to localshare.yaml")
    reach = up.add_mutually_exclusive_group()
    reach.add_argument("--tailnet", action="store_true", help="force Tailscale Serve")
    reach.add_argument("--public", action="store_true", help="force Tailscale Funnel")
    reach.add_argument("--lan", action="store_true", help="force LAN/mDNS (not in v1)")
    up.add_argument(
        "--yes",
        action="store_true",
        help="required for public funnel when security.confirm_public is true",
    )

    sub.add_parser("down", help="clear Tailscale Serve and Funnel on this machine")
    sub.add_parser("status", help="show config + live Tailscale state")
    sub.add_parser("url", help="print the live HTTPS URL")
    sub.add_parser("validate", help="validate localshare.yaml and exit")
    sub.add_parser("doctor", help="check Tailscale and config discovery")

    init = sub.add_parser("init", help="write a localshare.yaml in the current directory")
    init.add_argument("--name", required=True, help="DNS-label project name")
    init.add_argument("--port", type=int, default=3000, help="local backend port (default 3000)")
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    init.add_argument(
        "--allow-public",
        action="store_true",
        help="set allow.public: true (still defaults to reach: tailnet)",
    )

    return parser


def _reach_override(args: argparse.Namespace) -> str | None:
    if getattr(args, "public", False):
        return "public"
    if getattr(args, "lan", False):
        return "lan"
    if getattr(args, "tailnet", False):
        return "tailnet"
    return None


def _emit_json(payload: Any, stdout: TextIO) -> None:
    json.dump(payload, stdout, indent=2, sort_keys=True)
    stdout.write("\n")


def _config_payload(config: Config) -> dict[str, Any]:
    return {
        "path": str(config.path),
        "name": config.name,
        "reach": config.reach,
        "allow": {"public": config.allow.public, "lan": config.allow.lan},
        "target": {"port": config.target.port, "url": config.target.url},
        "tailscale": {
            "https_port": config.tailscale.https_port,
            "path": config.tailscale.path,
            "persist": config.tailscale.persist,
        },
        "security": {
            "exclusive": config.security.exclusive,
            "stop_on_exit": config.security.stop_on_exit,
            "confirm_public": config.security.confirm_public,
        },
    }


def _live_url(ts: Tailscale, config: Config) -> str | None:
    dns = ts.dns_name()
    if not dns:
        return None
    return public_url(dns, config.tailscale.https_port, config.tailscale.path)


def _cmd_init(args: argparse.Namespace, cwd: Path, stdout: TextIO) -> int:
    dest = cwd / "localshare.yaml"
    if dest.exists() and not args.force:
        raise PreconditionError(f"{dest} already exists (pass --force to overwrite)")
    template = (
        resources.files("localshare.templates")
        .joinpath("localshare.yaml")
        .read_text(encoding="utf-8")
    )
    text = template.replace("{{NAME}}", args.name).replace("{{PORT}}", str(args.port))
    if args.allow_public:
        text = text.replace("public: false", "public: true", 1)
    dest.write_text(text, encoding="utf-8")
    try:
        parse_config(yaml.safe_load(dest.read_text(encoding="utf-8")), dest)
    except ConfigError:
        dest.unlink(missing_ok=True)
        raise
    stdout.write(f"wrote {dest}\n")
    return EXIT_OK


def _cmd_validate(config: Config, as_json: bool, stdout: TextIO) -> int:
    if as_json:
        _emit_json({"ok": True, "config": _config_payload(config)}, stdout)
    else:
        stdout.write(f"ok {config.path} name={config.name} reach={config.reach}\n")
    return EXIT_OK


def _cmd_doctor(
    cwd: Path,
    ts: Tailscale,
    as_json: bool,
    stdout: TextIO,
) -> int:
    root = find_project_root(cwd)
    payload: dict[str, Any] = {
        "directory": str(cwd.resolve()),
        "config_root": str(root) if root else None,
        "tailscale_binary": ts.binary,
        "tailscale_on_path": ts.which() is not None,
        "backend_state": None,
        "dns_name": None,
    }
    if ts.which():
        try:
            payload["backend_state"] = ts.backend_state()
            payload["dns_name"] = ts.dns_name()
        except LocalshareError as exc:
            payload["tailscale_error"] = str(exc)
    if as_json:
        _emit_json(payload, stdout)
        return EXIT_OK
    stdout.write(f"directory:     {payload['directory']}\n")
    stdout.write(f"config:        {payload['config_root'] or '(none found)'}\n")
    stdout.write(f"tailscale:     {payload['tailscale_binary']}\n")
    stdout.write(f"on PATH:       {payload['tailscale_on_path']}\n")
    stdout.write(f"backend:      {payload['backend_state'] or '—'}\n")
    stdout.write(f"MagicDNS:      {payload['dns_name'] or '—'}\n")
    if payload.get("tailscale_error"):
        stdout.write(f"error:         {payload['tailscale_error']}\n")
    return EXIT_OK


def _cmd_up(
    args: argparse.Namespace,
    config: Config,
    ts: Tailscale,
    stdout: TextIO,
) -> int:
    plan = compile_up(config, _reach_override(args))
    if plan.reach == "public" and config.security.confirm_public and not args.yes:
        raise PreconditionError(
            "public Funnel requires --yes (this publishes localhost to the internet)"
        )
    ts.require()
    if plan.reset_first:
        ts.reset_serve()
        ts.reset_funnel()
    ts.apply(plan.binary_argv)
    url = _live_url(ts, config)
    stdout.write(f"name    {config.name}\n")
    stdout.write(f"reach   {plan.reach}\n")
    stdout.write(f"persist {str(plan.persist).lower()}\n")
    stdout.write(f"cmd     tailscale {' '.join(plan.binary_argv)}\n")
    if url:
        stdout.write(f"url     {url}\n")
    if plan.reach == "public":
        stdout.write(
            "warning this URL is on the public internet until `localshare down`\n"
        )
    return EXIT_OK


def _cmd_down(ts: Tailscale, stdout: TextIO) -> int:
    ts.require()
    ts.reset_serve()
    ts.reset_funnel()
    stdout.write("cleared Tailscale Serve and Funnel on this machine\n")
    return EXIT_OK


def _cmd_status(
    config: Config,
    ts: Tailscale,
    as_json: bool,
    stdout: TextIO,
) -> int:
    ts.require()
    url = _live_url(ts, config)
    payload = {
        "config": _config_payload(config),
        "backend_state": ts.backend_state(),
        "dns_name": ts.dns_name(),
        "url": url,
        "serve": ts.serve_status(),
        "funnel": ts.funnel_status(),
    }
    if as_json:
        _emit_json(payload, stdout)
        return EXIT_OK
    stdout.write(f"config  {config.path}\n")
    stdout.write(f"name    {config.name}\n")
    stdout.write(f"reach   {config.reach}\n")
    stdout.write(f"allow   public={config.allow.public} lan={config.allow.lan}\n")
    stdout.write(f"backend {payload['backend_state'] or '—'}\n")
    stdout.write(f"url     {url or '(not resolved)'}\n")
    return EXIT_OK


def _cmd_url(config: Config, ts: Tailscale, as_json: bool, stdout: TextIO) -> int:
    ts.require()
    url = _live_url(ts, config)
    if not url:
        raise PreconditionError("could not resolve MagicDNS name; is Tailscale up?")
    if as_json:
        _emit_json({"url": url, "name": config.name, "reach": config.reach}, stdout)
    else:
        stdout.write(f"{url}\n")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    tailscale: Tailscale | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    cwd = (cwd or Path.cwd()).resolve()
    parser = _parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.directory is not None:
        cwd = args.directory.resolve()

    ts = tailscale or Tailscale()
    as_json = bool(args.json)

    try:
        if args.command == "init":
            return _cmd_init(args, cwd, stdout)
        if args.command == "doctor":
            return _cmd_doctor(cwd, ts, as_json, stdout)

        config = load_config(cwd)
        if args.command == "validate":
            return _cmd_validate(config, as_json, stdout)
        if args.command == "up":
            return _cmd_up(args, config, ts, stdout)
        if args.command == "down":
            return _cmd_down(ts, stdout)
        if args.command == "status":
            return _cmd_status(config, ts, as_json, stdout)
        if args.command == "url":
            return _cmd_url(config, ts, as_json, stdout)
        parser.error(f"unknown command {args.command}")
        return EXIT_USAGE
    except LocalshareError as exc:
        if as_json and args.command in {"status", "url", "validate", "doctor"}:
            _emit_json({"ok": False, "error": str(exc)}, stdout)
        else:
            stderr.write(f"localshare: {exc}\n")
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
