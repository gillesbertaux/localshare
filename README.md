# localshare

A project-local wrapper around **Tailscale Serve** (tailnet) and **Tailscale Funnel** (public internet). Presence of `localshare.yaml` is the flag that a repo is shareable. The file is intent; Tailscale remains the data plane.

Default reach is the tailnet. Funnel is opt-in twice (`allow.public: true` in the file, then `up --public --yes` at runtime). LAN/mDNS (`.local`) is reserved in the schema and not implemented in v1.

## Install

Requires Python 3.11+ and the Tailscale CLI, logged in.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

```bash
localshare doctor
```

## Commands

| Command | What it does |
|---|---|
| `localshare init --name app --port 3000` | Write `localshare.yaml` |
| `localshare validate` | Schema/semantic check |
| `localshare up` | Serve on the tailnet (`tailscale serve`) |
| `localshare up --public --yes` | Funnel to the internet (`tailscale funnel`) |
| `localshare down` | `tailscale serve reset` + `funnel reset` |
| `localshare status` | Config + live Tailscale state |
| `localshare url` | Print the live `https://*.ts.net/` URL |
| `localshare doctor` | PATH / backend / config discovery |

`--json` works on `status`, `url`, `doctor`, `validate`. Discovery walks parent directories from cwd (or `-C`).

## Config

See [`examples/localshare.yaml`](examples/localshare.yaml), [`schemas/localshare.schema.json`](schemas/localshare.schema.json), and [`AGENTS.md`](AGENTS.md).

`localshare.local.yaml` overlays the committed file (gitignored) for machine-local ports.

## Security defaults

- Tailnet unless you pass `--public`.
- Public requires `allow.public: true` **and** `--yes`.
- Public does **not** persist across reboot (`--bg` omitted) unless you set `tailscale.persist: true`.
- `security.exclusive: true` resets existing Serve/Funnel on this machine before `up`.
- Do not commit live `*.ts.net` URLs; `localshare url` generates them from MagicDNS.

## Development

```bash
pytest
```
