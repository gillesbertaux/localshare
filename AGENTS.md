# Agent contract — localshare

localshare compiles `localshare.yaml` into one of three reaches: a `.local` name on the LAN (own proxy + OS mDNS), Tailscale Serve on the tailnet, or Tailscale Funnel on the internet. Tailscale is the data plane for the last two; for LAN, the only moving parts are a host-routing proxy and the OS mDNS responder.

Read this file before changing behavior, the YAML schema, or security defaults.

## What exists

- **Flag:** a repo is shareable iff `localshare.yaml` (or `.yml`) exists in it or a parent directory.
- **Default reach:** `tailnet` (Serve). Devices on the operator's tailnet only.
- **LAN:** `<name>.local` on the current network. Requires `allow.lan: true`. Unauthenticated by design — anyone on that Wi-Fi can reach it.
- **Public:** Funnel. Requires `allow.public: true` **and** `--public --yes`.
- **Tailscale Services** (`tailscale.service`): reserved. Error if set on a Tailscale reach.

## Commands an agent may run

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest
localshare doctor --json
localshare validate --json
localshare up --lan # http://<name>.local
localshare up # tailnet
localshare up --public --yes # only if allow.public
localshare url --json
localshare status --json
localshare daemon
localshare down
```

Never run `tailscale funnel` / `tailscale serve` directly unless debugging the wrapper. Never persist Funnel (`--bg`) unless the YAML sets `tailscale.persist: true`. Never run `dns-sd` / `avahi-publish` directly; the daemon owns those processes so that killing it removes the name from the network.

## Invariants

1. No secrets in YAML. No live `*.ts.net` hostnames in git.
2. Do not loosen defaults: `allow.public` and `allow.lan` default false; `--yes` required for public when `security.confirm_public` is true.
3. `up` on a Tailscale reach with `security.exclusive: true` (default) resets Serve **and** Funnel first — one active Tailscale share per machine. LAN is host-routed, so it is deliberately multi-project and never resets.
4. Tailscale compile output stays a thin argv translation of the current Tailscale CLI (`serve`/`funnel`, `--bg`, `--yes`, `--https=`, `--set-path=`, `--proxy-protocol`).
5. The LAN proxy parses only the first `Host` header per connection, then pipes bytes. Do not add header rewriting, TLS termination, logging of request contents, or buffering.
6. An unknown `Host` gets a bare 404. Never enumerate registered projects to an unknown caller.
7. One project per `.local` name. `up --lan` refuses a name another config path already serves rather than silently rerouting it.
8. The daemon is derived state. The CLI only edits the registry; the daemon reconciles. Exiting the daemon must remove every mDNS advertisement.
9. Missing `localshare.yaml` ⇒ not capable. Do not invent a tunnel.
10. Python 3.11+, stdlib + PyYAML. Do not add a web UI, another cloud provider, or a service discovery mechanism beyond mDNS.

## Layout

- `src/localshare/config.py` — load/validate YAML
- `src/localshare/compile.py` — YAML → Tailscale argv or LAN plan
- `src/localshare/tailscale.py` — subprocess wrapper
- `src/localshare/proxy.py` — Host-routing TCP proxy
- `src/localshare/mdns.py` — `dns-sd` / `avahi-publish` advertisements
- `src/localshare/daemon.py` — LAN daemon and its controller
- `src/localshare/state.py` — registry, pidfile, daemon info
- `src/localshare/netinfo.py` — LAN IP and URL helpers
- `src/localshare/cli.py` — commands
- `schemas/localshare.schema.json` — editor/agent schema
- `src/localshare/templates/localshare.yaml` — `init` template
- `tests/` — must stay green

## Definition of done

Tests pass. Schema, template, examples, and `AGENTS.md` stay aligned. LAN needs one gate, public needs two. Changelog-worthy behavior goes in the commit message, not a new markdown file unless asked.
