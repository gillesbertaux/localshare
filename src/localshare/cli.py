"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any, TextIO

import yaml

from localshare import __version__, state
from localshare.compile import LanPlan, compile_up, public_url
from localshare.config import Config, find_project_root, load_config, parse_config
from localshare.daemon import DaemonController, DaemonInfo, run_daemon
from localshare.errors import (
    EXIT_OK,
    ConfigError,
    LocalshareError,
    PreconditionError,
)
from localshare.mdns import find_publisher
from localshare.netinfo import lan_ip, lan_url
from localshare.tailscale import Tailscale

JSON_COMMANDS = frozenset({"status", "url", "validate", "doctor"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localshare",
        description=(
            "Share a local project on your LAN (<name>.local), your tailnet, "
            "or the public internet. Driven by localshare.yaml."
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
        help="machine-readable output on status, url, validate, doctor, daemon",
    )

    # Accept `validate --json` as well as `--json validate`. SUPPRESS keeps the
    # subcommand's default from overwriting a --json given before the subcommand.
    json_flag = argparse.ArgumentParser(add_help=False)
    json_flag.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable output",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="expose the project according to localshare.yaml")
    reach = up.add_mutually_exclusive_group()
    reach.add_argument("--tailnet", action="store_true", help="Tailscale Serve")
    reach.add_argument("--lan", action="store_true", help="LAN only, <name>.local")
    reach.add_argument("--public", action="store_true", help="Tailscale Funnel")
    up.add_argument(
        "--yes",
        action="store_true",
        help="required for public funnel when security.confirm_public is true",
    )
    up.add_argument(
        "--lan-port",
        type=int,
        default=None,
        help="preferred LAN listen port (default 80, falls back to 7777)",
    )

    down = sub.add_parser("down", help="stop sharing this project")
    down_scope = down.add_mutually_exclusive_group()
    down_scope.add_argument("--lan", action="store_true", help="only remove the .local name")
    down_scope.add_argument(
        "--tailscale", action="store_true", help="only reset Serve/Funnel"
    )

    status = sub.add_parser(
        "status", parents=[json_flag], help="show config + live state"
    )
    status.add_argument(
        "--no-tailscale",
        action="store_true",
        help="skip Tailscale queries (LAN-only machines)",
    )

    url = sub.add_parser("url", parents=[json_flag], help="print the live URL")
    url_scope = url.add_mutually_exclusive_group()
    url_scope.add_argument("--lan", action="store_true", help="print the .local URL")
    url_scope.add_argument("--tailnet", action="store_true", help="print the tailnet URL")
    url_scope.add_argument("--public", action="store_true", help="print the funnel URL")

    sub.add_parser(
        "validate", parents=[json_flag], help="validate localshare.yaml and exit"
    )
    sub.add_parser(
        "doctor",
        parents=[json_flag],
        help="check Tailscale, mDNS, daemon, config discovery",
    )

    init = sub.add_parser("init", help="write a localshare.yaml in the current directory")
    init.add_argument("--name", required=True, help="DNS-label project name")
    init.add_argument("--port", type=int, default=3000, help="local backend port (default 3000)")
    init.add_argument("--force", action="store_true", help="overwrite an existing file")
    init.add_argument(
        "--allow-public",
        action="store_true",
        help="set allow.public: true (still defaults to reach: tailnet)",
    )
    init.add_argument(
        "--allow-lan",
        action="store_true",
        help="set allow.lan: true so `up --lan` is permitted",
    )

    daemon = sub.add_parser(
        "daemon", parents=[json_flag], help="inspect or stop the LAN daemon"
    )
    daemon.add_argument("--stop", action="store_true", help="stop the daemon")

    internal = sub.add_parser("_daemon", help=argparse.SUPPRESS)
    internal.add_argument("--lan-port", type=int, default=None)

    return parser


def _reach_override(args: argparse.Namespace) -> str | None:
    """`up` and `url` both take the same mutually exclusive reach flags."""
    if args.public:
        return "public"
    if args.lan:
        return "lan"
    if args.tailnet:
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
        "lan": {"hostname": config.lan.hostname or config.name, "port": config.lan.port},
        "security": {
            "exclusive": config.security.exclusive,
            "confirm_public": config.security.confirm_public,
        },
    }


def _tailscale_url(ts: Tailscale, config: Config) -> str | None:
    dns = ts.dns_name()
    if not dns:
        return None
    return public_url(dns, config.tailscale.https_port, config.tailscale.path)


def _lan_url_in(info: DaemonInfo | None, name: str) -> str | None:
    project = ((info or {}).get("projects") or {}).get(name)
    if isinstance(project, dict) and isinstance(project.get("url"), str):
        return project["url"]
    return None


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
    if args.allow_lan:
        text = text.replace("lan: false", "lan: true", 1)
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
    daemon: DaemonController,
    as_json: bool,
    stdout: TextIO,
) -> int:
    root = find_project_root(cwd)
    publisher = find_publisher()
    info = daemon.info()
    payload: dict[str, Any] = {
        "directory": str(cwd.resolve()),
        "config_root": str(root) if root else None,
        "tailscale_binary": ts.binary,
        "tailscale_on_path": ts.which() is not None,
        "backend_state": None,
        "dns_name": None,
        "mdns_publisher": publisher.binary if publisher else None,
        "lan_ip": lan_ip(),
        "lan_daemon": info,
        "state_dir": str(state.state_dir()),
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
    stdout.write(f"directory      {payload['directory']}\n")
    stdout.write(f"config         {payload['config_root'] or '(none found)'}\n")
    stdout.write(f"tailscale      {payload['tailscale_binary']} "
                 f"(on PATH: {payload['tailscale_on_path']})\n")
    stdout.write(f"backend        {payload['backend_state'] or '—'}\n")
    stdout.write(f"MagicDNS       {payload['dns_name'] or '—'}\n")
    stdout.write(f"mDNS publisher {payload['mdns_publisher'] or '(none: install dns-sd/avahi)'}\n")
    stdout.write(f"LAN IP         {payload['lan_ip'] or '—'}\n")
    if info:
        stdout.write(
            f"LAN daemon     pid {info.get('pid')} on port {info.get('port')} "
            f"({len(info.get('projects') or {})} project(s))\n"
        )
    else:
        stdout.write("LAN daemon     not running\n")
    if payload.get("tailscale_error"):
        stdout.write(f"error          {payload['tailscale_error']}\n")
    return EXIT_OK


def _claim_name(config: Config, plan: LanPlan) -> None:
    """Refuse to hijack a `.local` name another project is already serving."""
    owner = str(config.path)
    for entry in state.read_lan_entries().values():
        if entry.config_path == owner:
            continue
        if entry.name == config.name or entry.hostname == plan.hostname:
            raise PreconditionError(
                f"{plan.hostname}.local is already served for {entry.config_path}; "
                "rename this project or run `localshare down --lan` there first"
            )
    state.put_lan_entry(
        state.LanEntry(
            name=config.name,
            hostname=plan.hostname,
            port=plan.target_port,
            config_path=owner,
            updated_at=time.time(),
        )
    )


def _up_lan(
    config: Config,
    plan: LanPlan,
    daemon: DaemonController,
    preferred_port: int | None,
    stdout: TextIO,
) -> int:
    if find_publisher() is None:
        raise PreconditionError(
            "no mDNS publisher available (need dns-sd on macOS or avahi-publish)"
        )
    _claim_name(config, plan)
    info = daemon.ensure(preferred_port or plan.preferred_port)
    port = int(info.get("port", 80))
    url = _lan_url_in(info, config.name) or lan_url(plan.hostname, port)
    stdout.write(f"name    {config.name}\n")
    stdout.write("reach   lan\n")
    stdout.write(f"target  http://127.0.0.1:{plan.target_port}\n")
    stdout.write(f"url     {url}\n")
    if info.get("ip"):
        stdout.write(f"ip      {info['ip']}\n")
    if port != 80:
        stdout.write(
            f"note    port 80 unavailable, serving on {port} "
            "(run with privileges for a bare http://<name>.local)\n"
        )
    stdout.write("note    reachable by anyone on this network until `localshare down`\n")
    return EXIT_OK


def _cmd_up(
    args: argparse.Namespace,
    config: Config,
    ts: Tailscale,
    daemon: DaemonController,
    stdout: TextIO,
) -> int:
    plan = compile_up(config, _reach_override(args))
    if isinstance(plan, LanPlan):
        return _up_lan(config, plan, daemon, args.lan_port, stdout)

    if plan.reach == "public" and config.security.confirm_public and not args.yes:
        raise PreconditionError(
            "public Funnel requires --yes (this publishes localhost to the internet)"
        )
    ts.require()
    if plan.reset_first:
        ts.reset_serve()
        ts.reset_funnel()
    ts.run(plan.argv)
    url = _tailscale_url(ts, config)
    stdout.write(f"name    {config.name}\n")
    stdout.write(f"reach   {plan.reach}\n")
    stdout.write(f"persist {str(plan.persist).lower()}\n")
    stdout.write(f"cmd     tailscale {' '.join(plan.argv)}\n")
    if url:
        stdout.write(f"url     {url}\n")
    if plan.reach == "public":
        stdout.write(
            "warning this URL is on the public internet until `localshare down`\n"
        )
    return EXIT_OK


def _cmd_down(
    args: argparse.Namespace,
    config: Config,
    ts: Tailscale,
    daemon: DaemonController,
    stdout: TextIO,
) -> int:
    do_lan = args.lan or not args.tailscale
    do_tailscale = args.tailscale or not args.lan

    if do_lan:
        existed, remaining = state.drop_lan_entry(config.name)
        if existed:
            stdout.write(f"lan     removed {config.name}.local\n")
        if not remaining and daemon.stop():
            stdout.write("lan     daemon stopped\n")
        elif remaining and existed:
            daemon.refresh()

    if do_tailscale:
        ts.require()
        ts.reset_serve()
        ts.reset_funnel()
        stdout.write("tailscale cleared Serve and Funnel on this machine\n")
    return EXIT_OK


def _cmd_status(
    args: argparse.Namespace,
    config: Config,
    ts: Tailscale,
    daemon: DaemonController,
    as_json: bool,
    stdout: TextIO,
) -> int:
    info = daemon.info()
    entries = state.read_lan_entries()
    lan_entry = entries.get(config.name)
    payload: dict[str, Any] = {
        "config": _config_payload(config),
        "lan": {
            "registered": lan_entry is not None,
            "daemon": info,
            "url": _lan_url_in(info, config.name),
        },
        "tailscale": None,
    }
    if not args.no_tailscale and ts.which():
        try:
            payload["tailscale"] = {
                "backend_state": ts.backend_state(),
                "dns_name": ts.dns_name(),
                "url": _tailscale_url(ts, config),
                "serve": ts.serve_status(),
                "funnel": ts.funnel_status(),
            }
        except LocalshareError as exc:
            payload["tailscale"] = {"error": str(exc)}

    if as_json:
        _emit_json(payload, stdout)
        return EXIT_OK

    stdout.write(f"config  {config.path}\n")
    stdout.write(f"name    {config.name}\n")
    stdout.write(f"reach   {config.reach}\n")
    stdout.write(f"allow   public={config.allow.public} lan={config.allow.lan}\n")
    lan_state = payload["lan"]
    if lan_state["registered"]:
        stdout.write(f"lan     {lan_state['url'] or '(daemon not running)'}\n")
    else:
        stdout.write("lan     off\n")
    ts_state = payload["tailscale"]
    if isinstance(ts_state, dict) and not ts_state.get("error"):
        stdout.write(f"tailnet {ts_state.get('url') or '(not resolved)'}\n")
        stdout.write(f"backend {ts_state.get('backend_state') or '—'}\n")
    elif isinstance(ts_state, dict):
        stdout.write(f"tailnet error: {ts_state['error']}\n")
    else:
        stdout.write("tailnet (skipped)\n")
    return EXIT_OK


def _cmd_url(
    args: argparse.Namespace,
    config: Config,
    ts: Tailscale,
    daemon: DaemonController,
    as_json: bool,
    stdout: TextIO,
) -> int:
    reach = _reach_override(args) or config.reach
    if reach == "lan":
        url = _lan_url_in(daemon.info(), config.name)
        if not url:
            raise PreconditionError(
                f"{config.name} is not on the LAN; run `localshare up --lan`"
            )
    else:
        ts.require()
        url = _tailscale_url(ts, config)
        if not url:
            raise PreconditionError("could not resolve MagicDNS name; is Tailscale up?")
    if as_json:
        _emit_json({"url": url, "name": config.name, "reach": reach}, stdout)
    else:
        stdout.write(f"{url}\n")
    return EXIT_OK


def _cmd_daemon(
    args: argparse.Namespace,
    daemon: DaemonController,
    as_json: bool,
    stdout: TextIO,
) -> int:
    if args.stop:
        stopped = daemon.stop()
        stdout.write("daemon stopped\n" if stopped else "daemon was not running\n")
        return EXIT_OK
    info = daemon.info()
    if as_json:
        _emit_json({"daemon": info}, stdout)
        return EXIT_OK
    if not info:
        stdout.write("daemon not running\n")
        return EXIT_OK
    stdout.write(f"pid   {info.get('pid')}\n")
    stdout.write(f"port  {info.get('port')}\n")
    stdout.write(f"ip    {info.get('ip') or '—'}\n")
    for name, project in sorted((info.get("projects") or {}).items()):
        stdout.write(f"      {name} -> {project.get('url')}\n")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    tailscale: Tailscale | None = None,
    daemon: DaemonController | None = None,
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
    daemon = daemon or DaemonController()
    as_json = bool(args.json)

    try:
        if args.command == "_daemon":
            return run_daemon(args.lan_port)
        if args.command == "init":
            return _cmd_init(args, cwd, stdout)
        if args.command == "doctor":
            return _cmd_doctor(cwd, ts, daemon, as_json, stdout)
        if args.command == "daemon":
            return _cmd_daemon(args, daemon, as_json, stdout)

        config = load_config(cwd)
        if args.command == "validate":
            return _cmd_validate(config, as_json, stdout)
        if args.command == "up":
            return _cmd_up(args, config, ts, daemon, stdout)
        if args.command == "down":
            return _cmd_down(args, config, ts, daemon, stdout)
        if args.command == "status":
            return _cmd_status(args, config, ts, daemon, as_json, stdout)
        if args.command == "url":
            return _cmd_url(args, config, ts, daemon, as_json, stdout)
        parser.error(f"unknown command {args.command}")
    except LocalshareError as exc:
        if as_json and args.command in JSON_COMMANDS:
            _emit_json({"ok": False, "error": str(exc)}, stdout)
        else:
            stderr.write(f"localshare: {exc}\n")
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
