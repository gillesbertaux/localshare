---
name: localshare-operate
description: >-
  Operate localshare (up/down/status/url/daemon/doctor/validate) against a
  localshare.yaml. Use when sharing a local dev server as <name>.local on the
  LAN, over Tailscale Serve, or publicly over Funnel; when exposing localhost
  for phone testing or webhooks; or when tearing a share down.
---

# Operate localshare

## Pick the reach

| The user wants | Reach | Command |
|---|---|---|
| test on a phone/tablet on the same Wi-Fi, show a teammate in the room | `lan` | `localshare up --lan` |
| reach it from their own devices anywhere | `tailnet` | `localshare up` |
| a webhook or an outsider to hit it | `public` | `localshare up --public --yes` |

## Rules

1. Read the nearest `localshare.yaml` (or run `localshare validate --json`) before `up`.
2. Use the reach in the file unless the user's intent clearly points elsewhere. Never escalate reach on your own.
3. `--lan` requires `allow.lan: true`; `--public` requires `allow.public: true` plus `--yes`. If the cap is false, tell the user to set it in YAML — do not bypass.
4. LAN is unauthenticated. Say so once when bringing a project up on a network the user did not describe as theirs.
5. After `up`, print `localshare url`. When the user is done, `localshare down`.
6. If `localshare.yaml` is missing, stop and offer `init` / the scaffold skill. Do not shell out to raw `tailscale`, `dns-sd`, or `avahi-publish`.

## Commands

```bash
localshare doctor --json      # tailscale + mDNS + LAN IP + daemon
localshare validate --json
localshare up --lan           # http://<name>.local
localshare up                 # tailnet
localshare up --public --yes
localshare status --json      # both rungs
localshare url --json
localshare daemon             # what the LAN daemon is serving
localshare down               # LAN name + Serve/Funnel
localshare down --lan         # LAN only
```

Discovery starts at cwd (or `-C DIR`) and walks parents.

## Failures

- `allow.lan: false` / `allow.public: false` → set the cap in YAML, do not bypass.
- `no mDNS publisher` → macOS has `dns-sd` built in; on Linux install `avahi-utils`.
- LAN URL shows `:7777` → port 80 was unavailable. That is fine; the URL just carries the port.
- `.local` will not resolve on older Android or on a network with mDNS/client isolation disabled (many guest and corporate Wi-Fi). Fall back to `tailnet`.
- Tailscale missing or not logged in → `localshare doctor`, then install/log in.
