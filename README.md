<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/png/logo-lockup-dark-480.png">
  <img src="brand/png/logo-lockup-480.png" alt="localshare" width="240" height="64">
</picture>

Share a local dev server under a name you choose: call the project `app` and it answers on `app.local` for anyone on your Wi-Fi. One config file switches that same project to your tailnet or the public internet.

| Reach | URL | Who can reach it | Backend |
|---|---|---|---|
| `lan` | `http://<name>.local/` | anyone on the same Wi-Fi | local proxy + Bonjour/mDNS |
| `tailnet` | `https://<machine>.<tailnet>.ts.net/` | your devices only | `tailscale serve` |
| `public` | `https://<machine>.<tailnet>.ts.net/` | the internet | `tailscale funnel` |

`<name>` is yours: any lowercase DNS label, so `app`, `api`, `checkout-v2`. It only shapes the `.local` address, because the two Tailscale reaches serve from your machine's own name.

A repo is shareable once it has a `localshare.yaml`. Nothing is exposed until you run `localshare up`.

## Install

localshare is not on PyPI yet, so install it from git:

```bash
pipx install git+https://github.com/gillesbertaux/localshare
# or
uv tool install git+https://github.com/gillesbertaux/localshare
```

Either one puts `localshare` on your PATH in its own isolated environment, so there is no venv to activate. Then check your machine:

```bash
localshare doctor
```

If the command is not found, run `pipx ensurepath` and open a new shell.

You need Python 3.11+. `.local` names need `dns-sd` (built into macOS) or `avahi-publish` (Linux). Tailnet and public reach need the Tailscale CLI, logged in. `doctor` tells you which of those are missing.

Two gotchas with a git install. Keep the `git+` prefix: plain `pipx install localshare` fetches an unrelated 2015 package that happens to own the name on PyPI. And a git install tracks `main`, so an upgrade can change the code while the version still reads `1.1.0`.

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
| `localshare validate` | Schema and semantic check |
| `localshare up [--lan\|--tailnet\|--public --yes]` | Expose it |
| `localshare down [--lan\|--tailscale]` | Stop sharing |
| `localshare status` | Config plus live LAN and Tailscale state |
| `localshare url [--lan\|--tailnet\|--public]` | Print the live URL |
| `localshare daemon [--stop]` | Inspect or stop the LAN daemon |
| `localshare doctor` | PATH, mDNS, LAN IP, backend, discovery |

Every command looks for `localshare.yaml` in the current directory and its parents. To start somewhere else, put `-C <dir>` before the subcommand. `status`, `url`, `validate`, `doctor` and `daemon` accept `--json`, before or after the subcommand.

## Config

```yaml
schema: 1
name: app           # your choice -> app.local
target:
  port: 3000
reach: lan          # lan | tailnet | public | off
allow:
  lan: true
  public: false
```

That is the whole minimal file. `name` doubles as the `.local` hostname, so add `lan.hostname` only when you want the address to differ from the project name.

Full reference: [`examples/`](examples), [`schemas/localshare.schema.json`](schemas/localshare.schema.json).

Commit that file. To change a port on one machine only, add a gitignored `localshare.local.yaml`, which overlays it.

## How LAN reach works

`up --lan` adds the project to a small registry and starts one shared daemon. The daemon:

1. publishes `<name>.local` pointing at this machine's LAN IPv4, through the OS mDNS responder
2. listens on port 80, or 7777 if 80 is taken, and routes by `Host` header to `127.0.0.1:<target.port>`

Because it routes by hostname, projects share that one port. `app.local` and `api.local` can both be up. The proxy reads the first `Host` header of a connection and then pipes bytes, so WebSockets, HMR, SSE and streaming pass through untouched. No traffic leaves the network.

`.local` names resolve out of the box on macOS and iOS, on Android 12+, and on Linux with Avahi. A name exists only while the daemon runs, and `localshare down` removes it.

## Security defaults

- `reach` defaults to `tailnet`. A config file on its own exposes nothing.
- LAN needs `allow.lan: true`. It is unauthenticated by design, so it is opt-in per project. Unknown hosts get a bare 404, so the daemon never reveals what else you are serving.
- Public needs both `allow.public: true` and `--yes`, and it does not survive a reboot unless `tailscale.persist: true`.
- `security.exclusive: true` resets any existing Serve and Funnel before `up`, so one Tailscale share is active at a time. LAN is exempt: it is host-routed and deliberately multi-project.
- Don't commit live `*.ts.net` URLs. `localshare url` derives them from MagicDNS when you need them.

## Development

```bash
git clone https://github.com/gillesbertaux/localshare
cd localshare
make install   # venv with an editable install and dev deps
make test
```

Contributions welcome. [`AGENTS.md`](AGENTS.md) is the contract for this repo: it lists the invariants a change should not quietly break, such as what the proxy is allowed to parse and which reach needs which gate. It applies to people and coding agents alike.

## Brand

Logo, reach-state icons and colour tokens: [`brand/`](brand/BRAND.md). There is one colour per reach, so reuse them if you build a client and `lan`, `tailnet` and `public` will look the same everywhere.

## License

[MIT](LICENSE) © Gilles Bertaux
