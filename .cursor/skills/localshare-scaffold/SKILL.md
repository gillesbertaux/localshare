---
name: localshare-scaffold
description: >-
  Add localshare.yaml to a project so it can be shared as <name>.local on the
  LAN or via Tailscale Serve/Funnel. Use when a repo has no localshare.yaml,
  the user wants a shareable local project, or an agent needs to mark a
  codebase localshare-capable.
---

# Scaffold localshare.yaml

## Check

Walk up from cwd for `localshare.yaml` / `localshare.yml`. If found, stop and use `localshare-operate`.

## Create

Prefer the CLI (validates name + schema):

```bash
localshare init --name <dns-label> --port <port>
# phone/LAN testing:
localshare init --name <dns-label> --port <port> --allow-lan
# webhooks / public-capable:
localshare init --name <dns-label> --port <port> --allow-public
```

The `--allow-*` flags only raise caps. `reach` stays `tailnet`, so nothing is exposed until the user asks: LAN still needs `up --lan`, Funnel still needs `up --public --yes`.

Name: lowercase DNS label (`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`). It becomes `<name>.local`, so keep it short and memorable. Derive it from the directory if the user did not specify.

Set `target.port` to the dev server's real port (LAN reach requires a port, not a `target.url`).

If the CLI is missing, install it with `pipx install git+https://github.com/gillesbertaux/localshare` (keep the `git+` prefix; the bare PyPI name is an unrelated project). Without it, write the file by hand from the schema and skip validation.

## Git

Commit `localshare.yaml`. Do not commit `localshare.local.yaml` or `*.ts.net` URLs.

Optional overlay for a machine-specific port:

```yaml
target:
  port: 3001
```

## Next

`localshare validate` then, if the user asked to share, follow `localshare-operate`.
