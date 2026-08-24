from __future__ import annotations

import socket
import socketserver
import threading

import pytest

from localshare.netinfo import lan_url, mdns_host
from localshare.proxy import bind_proxy, host_header, route_key


class _Echo(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        request = self.request.recv(65536)
        body = b"hello from backend"
        self.request.sendall(
            b"HTTP/1.1 200 OK\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\nConnection: close\r\n\r\n"
            + body
        )
        self.server.last_request = request  # type: ignore[attr-defined]


@pytest.fixture
def backend():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Echo)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def proxy(backend):
    routes = {"venue": backend.server_address[1]}
    server = bind_proxy(lambda: routes, [0], bind_host="127.0.0.1")
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


def _get(port: int, host: str) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(
            f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
        )
        chunks = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks)


def test_routes_local_host_to_backend(proxy) -> None:
    response = _get(proxy.port, "venue.local")
    assert b"200 OK" in response
    assert b"hello from backend" in response


def test_routes_with_explicit_port(proxy) -> None:
    response = _get(proxy.port, f"venue.local:{proxy.port}")
    assert b"hello from backend" in response


def test_unknown_host_reveals_nothing(proxy) -> None:
    response = _get(proxy.port, "secret.local")
    assert b"404 Not Found" in response
    assert b"venue" not in response


def test_passes_request_bytes_untouched(proxy, backend) -> None:
    _get(proxy.port, "venue.local")
    assert backend.last_request.startswith(b"GET / HTTP/1.1\r\n")
    assert b"Host: venue.local" in backend.last_request
    assert b"X-Forwarded" not in backend.last_request


def test_host_header_parsing() -> None:
    raw = b"GET / HTTP/1.1\r\nUser-Agent: x\r\nHost: Venue.local:80\r\n\r\n"
    assert host_header(raw) == "Venue.local:80"
    assert route_key(host_header(raw)) == "venue"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("venue.local", "venue"),
        ("venue.local.", "venue"),
        ("venue.local:7777", "venue"),
        ("venue", "venue"),
        ("[::1]:80", None),
        (None, None),
        ("", None),
    ],
)
def test_route_key(host, expected) -> None:
    assert route_key(host) == expected


def test_url_helpers() -> None:
    assert mdns_host("venue") == "venue.local"
    assert mdns_host("venue.local") == "venue.local"
    assert lan_url("venue", 80) == "http://venue.local/"
    assert lan_url("venue", 7777) == "http://venue.local:7777/"
