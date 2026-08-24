"""Host-routing proxy for LAN reach.

Reads only the Host header of the first request on a connection, then pipes
raw bytes both ways. Nothing else is parsed or rewritten, so WebSockets,
HMR, SSE and streaming pass through untouched.
"""

from __future__ import annotations

import selectors
import socket
import socketserver
import threading
from collections.abc import Callable, Mapping

HEADER_TIMEOUT_S = 10.0
UPSTREAM_TIMEOUT_S = 5.0
MAX_HEADER_BYTES = 64 * 1024
CHUNK = 65536

RouteProvider = Callable[[], Mapping[str, int]]


def _response(status: str, body: str) -> bytes:
    payload = body.encode()
    return (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode() + payload


# Deliberately says nothing about which names are registered.
_REFUSED = _response("404 Not Found", "Not Found\n")
_NO_BACKEND = _response("502 Bad Gateway", "No local server on that port.\n")


def host_header(raw: bytes) -> str | None:
    head = raw.split(b"\r\n\r\n", 1)[0]
    for line in head.split(b"\r\n")[1:]:
        if line[:5].lower() == b"host:":
            try:
                return line[5:].decode("latin-1").strip()
            except UnicodeDecodeError:
                return None
    return None


def route_key(host: str | None) -> str | None:
    """Map a Host header to a project name."""
    if not host:
        return None
    value = host.strip().lower().rstrip(".")
    if value.startswith("["):  # IPv6 literal, never a project name
        return None
    if ":" in value:
        value = value.rsplit(":", 1)[0]
    if value.endswith(".local"):
        value = value[: -len(".local")]
    return value or None


class _Handler(socketserver.BaseRequestHandler):
    server: "HostRoutingProxy"

    def handle(self) -> None:
        downstream: socket.socket = self.request
        downstream.settimeout(HEADER_TIMEOUT_S)
        buffered = b""
        try:
            while b"\r\n\r\n" not in buffered:
                if len(buffered) >= MAX_HEADER_BYTES:
                    return
                chunk = downstream.recv(CHUNK)
                if not chunk:
                    return
                buffered += chunk
        except OSError:
            return

        name = route_key(host_header(buffered))
        target = self.server.routes().get(name) if name else None
        if target is None:
            self._reply(downstream, _REFUSED)
            return

        try:
            upstream = socket.create_connection(
                ("127.0.0.1", target), timeout=UPSTREAM_TIMEOUT_S
            )
        except OSError:
            self._reply(downstream, _NO_BACKEND)
            return

        try:
            downstream.settimeout(None)
            upstream.settimeout(None)
            upstream.sendall(buffered)
            _pipe(downstream, upstream)
        except OSError:
            pass
        finally:
            _close(upstream)

    @staticmethod
    def _reply(sock: socket.socket, payload: bytes) -> None:
        try:
            sock.sendall(payload)
        except OSError:
            pass


def _close(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def _pipe(left: socket.socket, right: socket.socket) -> None:
    with selectors.DefaultSelector() as selector:
        selector.register(left, selectors.EVENT_READ, right)
        selector.register(right, selectors.EVENT_READ, left)
        open_sides = 2
        while open_sides:
            for key, _ in selector.select():
                source: socket.socket = key.fileobj  # type: ignore[assignment]
                sink: socket.socket = key.data
                try:
                    data = source.recv(CHUNK)
                except OSError:
                    data = b""
                if not data:
                    selector.unregister(source)
                    open_sides -= 1
                    try:
                        sink.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    continue
                try:
                    sink.sendall(data)
                except OSError:
                    return


class HostRoutingProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, bind_host: str, port: int, routes: RouteProvider) -> None:
        self.routes = routes
        super().__init__((bind_host, port), _Handler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="localshare-proxy", daemon=True)
        thread.start()
        return thread


def bind_proxy(
    routes: RouteProvider,
    candidate_ports: list[int],
    bind_host: str = "0.0.0.0",
) -> HostRoutingProxy:
    """Bind the first port that is available.

    Port 80 needs privileges, so the caller passes a fallback (7777) the way
    a normal user session can actually bind.
    """
    last_error: OSError | None = None
    for port in candidate_ports:
        try:
            return HostRoutingProxy(bind_host, port, routes)
        except OSError as exc:
            last_error = exc
    raise OSError(
        f"could not bind any of {candidate_ports}: {last_error}"
    ) from last_error
