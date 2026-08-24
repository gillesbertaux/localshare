# Agent contract — localshare

localshare is a CLI that compiles `localshare.yaml` into `tailscale serve` / `tailscale funnel`. It does not tunnel itself. Tailscale is the data plane.

Read this file before changing behavior, the YAML schema, or security defaults.

## What v1 is

- **Flag:** a repo is shareable iff `localshare.yaml` (or `.yml`) exists in it or a parent directory.
- **Default reach:** `tailnet` (Serve). Devices on the operator's tailnet only.
- **Public:** Funnel. Allowed only when `allow.public: true` **and** the operator passes `--public --yes`.
- **LAN / `.local`:** schema fields exist; `up --lan` errors. Do not fake Bonjour.
- **Tailscale Services** (`tailscale.service`): reserved. Error if set.

## Commands an agent may run

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest
localshare doctor --json
localshare validate --json
localshare up                  # tailnet
localshare up --public --yes   # only if allow.public
localshare url --json
localshare status --json
localshare down
```

Never run `tailscale funnel` / `tailscale serve` directly unless debugging the wrapper. Never persist Funnel (`--bg`) unless the YAML sets `tailscale.persist: true`.

## Invariants

1. No secrets in YAML. No live `*.ts.net` hostnames in git.
2. Do not loosen public defaults: `allow.public` defaults false; `--yes` required when `security.confirm_public` is true.
3. `up` with `security.exclusive: true` (default) resets Serve **and** Funnel first. v1 is one active share per machine.
4. Compile output must stay a thin argv translation of the current Tailscale CLI (`serve`/`funnel`, `--bg`, `--yes`, `--https=`, `--set-path=`, `--proxy-protocol`).
5. Missing `localshare.yaml` ⇒ not capable. Do not invent a tunnel.
6. Python 3.11+, stdlib + PyYAML. Do not add a web UI, daemon, or extra cloud provider in v1.

## Layout

- `src/localshare/config.py` — load/validate YAML
- `src/localshare/compile.py` — YAML → argv
- `src/localshare/tailscale.py` — subprocess
- `src/localshare/cli.py` — commands
- `schemas/localshare.schema.json` — editor/agent schema
- `src/localshare/templates/localshare.yaml` — `init` template
- `tests/` — must stay green

## Definition of done

Tests pass. Schema, template, examples, and `AGENTS.md` stay aligned. Public path still requires two gates. Changelog-worthy behavior goes in the commit message, not a new markdown file unless asked.
