#!/usr/bin/env python3
"""Static server for the web version, standard library only.

Serves ``web/`` at ``/`` and the pipeline's assets directory under ``/assets/``,
read-only, GET and HEAD only, on the one shared port (KTD8).  ``--host`` is
required and a wildcard bind is refused (R9).  Every response carries the same
content policy the playtest collector sends, so the plain build and a playtest
build run under one policy.
"""

from __future__ import annotations

import argparse
import errno
import ipaddress
import posixpath
import socket
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

# One origin for the tablet's saved state: the collector serves playtest builds on
# this same port, and each refuses to start while the other holds it.
SHARED_PORT = 8777

# The common spellings, caught before any socket is made, for a friendly message.
# They are not the check: `--host 0`, `00.0.0.0` and `::0` are wildcards too, and
# only the address the kernel actually bound can tell (R9).
WILDCARD_HOSTS = {"0.0.0.0", "::", "*", ""}

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; form-action 'none'; base-uri 'none'"
)

# Only these are ever handed out.  Anything else under either root (this file,
# caches, editor leftovers) is a 404, the same as a path outside the roots.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

WEB_DIR = Path(__file__).resolve().parent
DEFAULT_ASSETS_DIR = WEB_DIR.parent / "app" / "src" / "main" / "assets"
ASSETS_PREFIX = "/assets/"


def resolve_path(url_path: str, web_dir: Path, assets_dir: Path) -> Path | None:
    """Map a request path onto a file under one of the two roots, or None.

    ``/`` is the index.  ``/assets/...`` maps into the assets root, everything
    else into ``web/``.  The path is unquoted and normalised before it touches
    the filesystem, then the resolved file must still sit inside its root and
    carry a served extension.
    """
    raw = unquote(urlsplit(url_path).path)
    if "\x00" in raw:
        return None
    clean = posixpath.normpath("/" + raw.lstrip("/"))
    if clean == "/":
        clean = "/index.html"
    if clean.startswith(ASSETS_PREFIX):
        root, relative = assets_dir, clean[len(ASSETS_PREFIX):]
    else:
        root, relative = web_dir, clean[1:]
    if not relative:
        return None
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate == root or root not in candidate.parents:
        return None
    if candidate.suffix.lower() not in CONTENT_TYPES:
        return None
    if not candidate.is_file():
        return None
    return candidate


class StaticHandler(BaseHTTPRequestHandler):
    server_version = "DressMeUp/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # no access log
        pass

    def end_headers(self):
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _refuse(self, status: HTTPStatus, body: str = "") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if status is HTTPStatus.METHOD_NOT_ALLOWED:
            self.send_header("Allow", "GET, HEAD")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _serve(self, send_body: bool) -> None:
        target = resolve_path(self.path, self.server.web_dir, self.server.assets_dir)
        if target is None:
            self._refuse(HTTPStatus.NOT_FOUND, "not found\n")
            return
        try:
            data = target.read_bytes()
        except OSError:
            self._refuse(HTTPStatus.NOT_FOUND, "not found\n")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", CONTENT_TYPES[target.suffix.lower()])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if send_body:
            self.wfile.write(data)

    def do_GET(self):
        try:
            self._serve(send_body=True)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        try:
            self._serve(send_body=False)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _method_not_allowed(self):
        # The body is never read: nothing a client sends is stored or acted on.
        try:
            self._refuse(HTTPStatus.METHOD_NOT_ALLOWED, "read-only\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        self.close_connection = True

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed


class StaticServer(ThreadingHTTPServer):
    daemon_threads = True
    # A socket left in TIME_WAIT by the last run must not keep this one off the
    # port; a live listener is still refused by the kernel, which is the only
    # exclusivity the shared port needs.
    allow_reuse_address = True

    def __init__(self, host: str, port: int, web_dir: Path, assets_dir: Path):
        if ":" in host:
            self.address_family = socket.AF_INET6
        self.web_dir = Path(web_dir)
        self.assets_dir = Path(assets_dir)
        super().__init__((host, port), StaticHandler)

    def handle_error(self, request, client_address):
        pass  # never print client addresses


def make_server(host: str, port: int, web_dir: Path | str, assets_dir: Path | str) -> StaticServer:
    """Bind and return a server (not yet serving).  Raises OSError if the port is held."""
    return StaticServer(host, port, Path(web_dir), Path(assets_dir))


def is_wildcard_bind(address: str) -> bool:
    """True when a bound address is INADDR_ANY / in6addr_any, however it was spelled."""
    try:
        return ipaddress.ip_address(address.partition("%")[0]).is_unspecified
    except ValueError:
        return False


def url_for(host: str, port: int) -> str:
    shown = f"[{host}]" if ":" in host else host
    return f"http://{shown}:{port}/"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the web version on one explicit home-network address.",
    )
    parser.add_argument(
        "--host",
        required=True,
        help="the address to bind, e.g. this machine's home-network address; wildcards are refused",
    )
    parser.add_argument(
        "--assets",
        type=Path,
        default=DEFAULT_ASSETS_DIR,
        help="the pipeline's assets directory (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = args.host.strip()
    if host in WILDCARD_HOSTS:
        print(f"refusing to start: --host {host!r} is a wildcard bind.", file=sys.stderr)
        print("Pass this machine's own home-network address instead.", file=sys.stderr)
        return 2
    if not args.assets.is_dir():
        print(f"refusing to start: assets directory {args.assets} does not exist.", file=sys.stderr)
        return 2
    try:
        server = make_server(host, SHARED_PORT, WEB_DIR, args.assets)
    except OSError as exc:
        name = errno.errorcode.get(exc.errno, str(exc.errno))
        print(f"refusing to start: cannot bind {host}:{SHARED_PORT} ({name}).", file=sys.stderr)
        if exc.errno == errno.EADDRINUSE:
            print("Something already holds the shared port; stop it first.", file=sys.stderr)
        return 1
    bound_host, bound_port = server.server_address[:2]
    if is_wildcard_bind(bound_host):
        server.server_close()
        print(
            f"refusing to start: --host {host!r} resolves to the wildcard address {bound_host}.",
            file=sys.stderr,
        )
        print("Pass this machine's own home-network address instead.", file=sys.stderr)
        return 2
    print(f"serving {WEB_DIR} at / and {args.assets} at /assets/ (read-only)")
    print(f"open {url_for(bound_host, bound_port)}")
    print("stop with Ctrl-C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
