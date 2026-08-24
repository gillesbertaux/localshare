"""Thin subprocess wrapper around the Tailscale CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from localshare.errors import PreconditionError, TailscaleError

Runner = Callable[..., subprocess.CompletedProcess[str]]


def default_binary() -> str:
    return os.environ.get("LOCALSHARE_TAILSCALE", "tailscale")


class Tailscale:
    def __init__(
        self,
        binary: str | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.binary = binary or default_binary()
        self._runner = runner or subprocess.run
        self._status: dict[str, Any] | None = None

    def which(self) -> str | None:
        if os.path.sep in self.binary:
            return self.binary if os.path.exists(self.binary) else None
        return shutil.which(self.binary)

    def require(self) -> None:
        if not self.which():
            raise PreconditionError(
                f"tailscale CLI not found ({self.binary!r}); install Tailscale "
                "and ensure `tailscale` is on PATH"
            )

    def run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = [self.binary, *args]
        try:
            completed = self._runner(
                argv,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise TailscaleError(f"failed to execute {self.binary}: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise TailscaleError(
                f"`{' '.join(argv)}` failed ({completed.returncode})"
                + (f": {detail}" if detail else "")
            )
        return completed

    def json_cmd(self, args: Sequence[str]) -> Any:
        stdout = self.run(args).stdout.strip()
        if not stdout:
            return {}
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise TailscaleError(f"non-JSON from `{' '.join(args)}`: {exc}") from exc

    def status(self) -> dict[str, Any]:
        """Cached: one CLI invocation is one snapshot of the tailnet."""
        if self._status is None:
            data = self.json_cmd(["status", "--json"])
            self._status = data if isinstance(data, dict) else {}
        return self._status

    def serve_status(self) -> Any:
        return self.json_cmd(["serve", "status", "--json"])

    def funnel_status(self) -> Any:
        return self.json_cmd(["funnel", "status", "--json"])

    def reset_serve(self) -> None:
        self.run(["serve", "reset"])

    def reset_funnel(self) -> None:
        self.run(["funnel", "reset"])

    def dns_name(self) -> str | None:
        self_status = self.status().get("Self") or {}
        name = self_status.get("DNSName")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def backend_state(self) -> str | None:
        state = self.status().get("BackendState")
        return state if isinstance(state, str) else None
