---
name: localshare-operate
description: >-
  Operate localshare (up/down/status/url/doctor/validate) against a
  localshare.yaml. Use when sharing a local dev server over Tailscale Serve
  or Funnel, exposing localhost, printing a *.ts.net URL, or tearing a share
  down.
---

# Operate localshare

## Rules

1. Read the nearest `localshare.yaml` (or run `localshare validate --json`) before `up`.
2. Default is **tailnet** (`localshare up`). Do not pass `--public` unless the user asked to publish on the internet **and** `allow.public` is true.
3. Public requires `localshare up --public --yes`.
4. After `up`, print `localshare url`. After the user is done, `localshare down`.
5. If `localshare.yaml` is missing, stop. Offer `init` / the scaffold skill — do not shell out to raw `tailscale funnel`.

## Commands

```bash
localshare doctor --json
localshare validate --json
localshare up
localshare up --public --yes
localshare status --json
localshare url --json
localshare down
```

Discovery starts at cwd (or `-C DIR`) and walks parents.

## Failures

- `allow.public: false` + `--public` → tell the user to set the cap in YAML, do not bypass.
- Tailscale missing / not logged in → `localshare doctor`, then install/login Tailscale.
- LAN/`--lan` → v1 unsupported; use tailnet (phone on Tailscale) or wait for later LAN.
