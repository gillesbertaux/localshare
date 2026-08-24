"""Exit codes and typed failures."""

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_PRECONDITION = 2
EXIT_TAILSCALE = 3


class LocalshareError(Exception):
    exit_code = EXIT_USAGE


class ConfigError(LocalshareError):
    """Invalid or missing localshare.yaml."""


class PreconditionError(LocalshareError):
    """Missing binary, disallowed reach, or a name already in use."""

    exit_code = EXIT_PRECONDITION


class TailscaleError(LocalshareError):
    """tailscale CLI failed."""

    exit_code = EXIT_TAILSCALE
