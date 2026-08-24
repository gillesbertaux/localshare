---
name: localshare-scaffold
description: >-
  Add localshare.yaml to a project so it can be shared via Tailscale Serve/Funnel.
  Use when a repo has no localshare.yaml, the user wants a shareable local
  project, or an agent needs to mark a codebase localshare-capable.
---

# Scaffold localshare.yaml

## Check

Walk up from cwd for `localshare.yaml` / `localshare.yml`. If found, stop and use `localshare-operate`.

## Create

Prefer the CLI (validates name + schema):

```bash
localshare init --name <dns-label> --port <port>
# webhook / public-capable projects:
localshare init --name <dns-label> --port <port> --allow-public
```

`--allow-public` only sets the cap. `reach` stays `tailnet`. Funnel still needs `localshare up --public --yes`.

Name: lowercase DNS label (`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`). Derive from the directory if the user did not specify.

If the CLI is not installed, copy `src/localshare/templates/localshare.yaml` from this repo, substitute `{{NAME}}` and `{{PORT}}`, then `localshare validate`.

## Git

Commit `localshare.yaml`. Do not commit `localshare.local.yaml` or `*.ts.net` URLs.

Optional overlay for a machine-specific port:

```yaml
target:
  port: 3001
```

## Next

`localshare validate` then, if the user asked to share, follow `localshare-operate`.
