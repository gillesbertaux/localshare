# localshare

One config file, three reaches for a local dev server:

| Reach | URL | Who can reach it | Backend |
|---|---|---|---|
| `lan` | `http://app.local/` | anyone on the same Wi-Fi | local proxy + Bonjour/mDNS |
| `tailnet` | `https://<machine>.<tailnet>.ts.net/` | your devices only | `tailscale serve` |
| `public` | `https://<machine>.<tailnet>.ts.net/` | the internet | `tailscale funnel` |

Presence of `localshare.yaml` is the flag that a repo is shareable. The file is intent, not state.

## Install

Python 3.11+. LAN reach needs `dns-sd` (built into macOS) or `avahi-publish`. Tailnet and public reach need the Tailscale CLI, logged in.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
localshare doctor
```

## Use

```bash
localshare init --name app --port 3000 --allow-lan
localshare up --lan          # http://app.local/
localshare up                # tailnet (default reach)
localshare up --public --yes # internet
localshare down
```

| Command | What it does |
|---|---|
| `localshare init --name app --port 3000` | Write `localshare.yaml` |
| `localshare validate` | Schema/semantic check |
| `localshare up [--lan\|--tailnet\|--public --yes]` | Expose it |
| `localshare down [--lan\|--tailscale]` | Stop sharing |
| `localshare status` | Config plus live LAN and Tailscale state |
| `localshare url [--lan\|--tailnet\|--public]` | Print the live URL |
| `localshare daemon [--stop]` | Inspect or stop the LAN daemon |
| `localshare doctor` | PATH, mDNS, LAN IP, backend, discovery |

`--json` works on `status`, `url`, `validate`, `doctor` and `daemon`, on either side of the subcommand. Discovery walks parent directories from cwd (or `-C`).

## How LAN reach works

`up --lan` writes the project into a small registry and starts one shared daemon that:

1. publishes `<name>.local` → this machine's LAN IPv4 through the OS mDNS responder, and
2. listens on port 80 (falling back to 7777) and routes by `Host` header to `127.0.0.1:<target.port>`.

Because routing is by hostname, several projects share the one port at once: `app.local` and `api.local` can both be up. The proxy reads only the first `Host` header of a connection and then pipes raw bytes, so WebSockets, HMR, SSE and streaming pass through unmodified. Nothing is rewritten and no traffic leaves the network.

`.local` names are Bonjour, so they resolve on macOS and iOS out of the box, on Android 12+ and on Linux with Avahi. The name exists only while the daemon runs; `localshare down` removes it from the network.

## Config

```yaml
schema: 1
name: app
target:
  port: 3000
reach: lan          # lan | tailnet | public | off
allow:
  lan: true
  public: false
lan:
  hostname: app     # -> app.local
```

Full reference: [`examples/`](examples), [`schemas/localshare.schema.json`](schemas/localshare.schema.json), [`AGENTS.md`](AGENTS.md).

`localshare.local.yaml` overlays the committed file (gitignored) for machine-local ports.

## Security defaults

- `reach` defaults to `tailnet`. Nothing is exposed by a file alone.
- LAN requires `allow.lan: true`. It is unauthenticated by design, so it is a per-project opt-in and the daemon refuses any `Host` it does not know (404, no names leaked).
- Public requires `allow.public: true` **and** `--yes`, and does not survive a reboot unless `tailscale.persist: true`.
- `security.exclusive: true` resets existing Serve/Funnel before `up`. It does not apply to LAN, which is host-routed and multi-project.
- Do not commit live `*.ts.net` URLs; `localshare url` derives them from MagicDNS.

## Development

```bash
pytest
```
