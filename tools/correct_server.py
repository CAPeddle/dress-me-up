#!/usr/bin/env python3
"""Server for the catalogue correction tool, standard library plus Pillow.

Serves the wall (`tools/correct/`), a manifest of the whole extracted corpus, a
derived thumbnail per item and the original cutout on request, and accepts one
write: a batch of human filings, which is the only thing about this machine that
a client may change (R17).

The read-only posture is `web/serve.py`'s, copied deliberately: one explicit
address with every wildcard spelling refused, one content policy on every
response, no access log and no client address in any error (R16). It diverges on
two points. `--host` defaults to loopback instead of being required, because that
file serves the tablet across the home network and the address has to be a
decision, while this tool is a person at this desk. And POST is answered rather
than refused, which is why this is a separate module (KTD5) — `web/serve.py`'s
promise is that a request body is never read, and it keeps it.

The port is its own, not `SHARED_PORT`: 8777 is shared between the web version and
the playtest collector precisely so they cannot co-run, and this tool has to be
usable while the web version is serving the tablet (KTD6).
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import io
import ipaddress
import json
import os
import posixpath
import socket
import sys
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, UnidentifiedImageError

from dressup_pipeline.corrections import (
    DEFAULT_CORRECTIONS_DIR,
    REJECTION_KINDS,
    Correction,
    CorrectionError,
    CorrectionKey,
    corrections_path,
    read_corrections,
    sidecar_key,
    write_corrections,
)
from dressup_pipeline.models import CATEGORIES, Sidecar, SidecarError, iter_sidecars

# Not `SHARED_PORT` (KTD6). The next port up, so the two are obviously related and
# obviously not the same one.
CORRECT_PORT = 8778

# The common spellings, caught before any socket is made, for a friendly message.
# They are not the check: `--host 0`, `00.0.0.0` and `::0` are wildcards too, and
# only the address the kernel actually bound can tell (R16).
WILDCARD_HOSTS = {"0.0.0.0", "::", "*", ""}

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; connect-src 'self'; form-action 'none'; base-uri 'none'"
)

# Only these are ever handed out of the client directory. Anything else under it
# is a 404, the same as a path outside it.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

CORPUS_ROUTE = "/api/corpus"
CORRECTIONS_ROUTE = "/api/corrections"
THUMB_PREFIX = "/thumb/"
ITEM_PREFIX = "/item/"

# Long edge of a wall thumbnail. Small items are never scaled *up*: a 111x172
# cutout stays 111x172, which is the whole reason the original is a request away
# (KTD7).
THUMB_EDGE = 192

# One batch of filings is a few hundred bytes per item. A megabyte is thousands of
# them; anything larger is a defect rather than a sitting's work.
MAX_BODY = 1 << 20

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
DEFAULT_CLIENT_DIR = TOOLS_DIR / "correct"
DEFAULT_SIDECARS = REPO_ROOT / "content" / "sidecars"
# Derived images, keyed by their source, regenerable at any time: `content/` is
# ignored by git, and a cache under `tools/` would be committed image data.
DEFAULT_THUMBS = REPO_ROOT / "content" / "correct-thumbs"


class CorpusError(ValueError):
    """The corpus on disk cannot be served as a wall of distinct items."""


class BadRequest(ValueError):
    """A request is malformed or names something the corpus does not hold."""


@dataclass(frozen=True)
class CorpusItem:
    """One wall item: its sidecar, and where the cutout that sidecar names sits."""

    sidecar: Sidecar
    sidecar_path: Path
    image_path: Path

    @property
    def item_id(self) -> str:
        return self.sidecar.item_id

    @property
    def stem(self) -> str:
        return Path(self.sidecar.source_pdf).stem


# ---------------------------------------------------------------- the corpus

def load_corpus(sidecars_dir: Path) -> dict[str, CorpusItem]:
    """Every extracted item under `sidecars_dir`, keyed by item id.

    Loaded once, at startup: a re-extraction mid-sitting changes item ids under
    the wall the person is looking at, and picking that up silently is how a
    keystroke lands on the wrong item.

    A repeated item id is refused rather than resolved, because the id is what the
    client names an item by — two items answering to one id would serve one of
    them and file the verdict against whichever won.
    """
    items: dict[str, CorpusItem] = {}
    for path, sidecar in iter_sidecars(sidecars_dir):
        if sidecar.item_id in items:
            raise CorpusError(
                f"{sidecar.item_id} is described by two sidecars: "
                f"{items[sidecar.item_id].sidecar_path.name} and {path.name}"
            )
        items[sidecar.item_id] = CorpusItem(
            sidecar=sidecar, sidecar_path=path, image_path=path.parent / sidecar.image
        )
    return items


def contained(candidate: Path, root: Path) -> Path | None:
    """`candidate` resolved, but only if it is a file genuinely inside `root`.

    Resolved at the moment of use, not at startup: a sidecar's `image` is data off
    the disk like any other, and a symlink planted after the corpus loaded points
    somewhere else than the one that loaded.
    """
    try:
        root = root.resolve()
        resolved = candidate.resolve()
    except OSError:
        return None
    if resolved == root or root not in resolved.parents:
        return None
    if not resolved.is_file():
        return None
    return resolved


def resolve_client_path(url_path: str, client_dir: Path) -> Path | None:
    """Map a request path onto a file in the client directory, or None.

    `/` is the index. The path is unquoted and normalised before it touches the
    filesystem, then the resolved file must still sit inside the root and carry a
    served extension.
    """
    raw = unquote(urlsplit(url_path).path)
    if "\x00" in raw:
        return None
    clean = posixpath.normpath("/" + raw.lstrip("/"))
    if clean == "/":
        clean = "/index.html"
    relative = clean[1:]
    if not relative:
        return None
    candidate = client_dir / relative
    if candidate.suffix.lower() not in CONTENT_TYPES:
        return None
    return contained(candidate, client_dir)


def item_id_from(url_path: str, prefix: str) -> str:
    """The item id a request names — one URL segment, never joined onto anything.

    Whatever comes back is looked up in the loaded corpus before any file is
    opened, so a traversal attempt is a missing key rather than a path.
    """
    raw = unquote(urlsplit(url_path).path)
    return raw[len(prefix):]


# ---------------------------------------------------------------- thumbnails

def thumb_key(item: CorpusItem, image_path: Path, edge: int = THUMB_EDGE) -> str:
    """A cache name that changes when the cutout behind it changes.

    Size and modification time rather than the file's bytes: hashing 109 MB of
    corpus to answer 333 thumbnail requests would cost more than deriving them.
    Nothing corpus-supplied reaches the filename — the id goes into the digest,
    not into a path component.
    """
    try:
        stat = image_path.stat()
        stamp = f"{stat.st_size}:{stat.st_mtime_ns}"
    except OSError:
        stamp = "missing"
    seed = f"{item.item_id}\0{stamp}\0{edge}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def render_thumb(image_path: Path, edge: int = THUMB_EDGE) -> bytes:
    """A PNG no longer than `edge` on its long side, transparency intact."""
    with Image.open(image_path) as source:
        # Palette-mode PNGs carry their alpha in the palette; converting first
        # keeps a cutout's transparent margin from turning black.
        thumb = source.convert("RGBA")
        thumb.thumbnail((edge, edge), Image.LANCZOS)
        buffer = io.BytesIO()
        thumb.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def cached_thumb(image_path: Path, cache_dir: Path, key: str, edge: int = THUMB_EDGE) -> bytes:
    """The thumbnail for `image_path`, derived on first ask and kept under `cache_dir`.

    The cache file is written whole and moved into place, and the bytes served are
    the ones in hand: two windows of the wall can ask for the same thumbnail at
    once, and neither may read the other's half-written PNG.
    """
    target = cache_dir / f"{key}.png"
    try:
        return target.read_bytes()
    except OSError:
        pass
    data = render_thumb(image_path, edge)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        pending = cache_dir / f"{key}.{os.getpid()}-{threading.get_ident()}.part"
        pending.write_bytes(data)
        os.replace(pending, target)
    except OSError:
        pass  # an uncacheable thumbnail is still a servable one
    return data


# ---------------------------------------------------------------- the manifest

def _suggestion_order(item: CorpusItem) -> tuple[str, str]:
    # Items the classifier guessed alike sit together (R4), and the ones it had no
    # guess for sit at the end where the work is most obviously unstarted.
    suggestion = item.sidecar.category
    return ("￿" if suggestion is None else suggestion, item.item_id)


def corpus_manifest(
    items: dict[str, CorpusItem], corrections_dir: Path, edge: int = THUMB_EDGE
) -> dict:
    """The whole corpus in one response, plus what has already been filed.

    Compact on purpose (KTD8): the client renders a window of this list, so the
    list itself carries geometry and URLs and no image data. Corrections are read
    fresh on every call, so reloading the wall mid-sitting shows the work done.
    """
    filed: dict[CorrectionKey, Correction] = {}
    for stem in sorted({item.stem for item in items.values()}):
        for correction in read_corrections(corrections_path(corrections_dir, stem)).values():
            filed[correction.key] = correction

    records = []
    for item in sorted(items.values(), key=_suggestion_order):
        sidecar = item.sidecar
        correction = filed.get(sidecar_key(sidecar))
        records.append(
            {
                "item_id": item.item_id,
                "source_pdf": item.stem,
                "page": sidecar.page,
                "bbox": {
                    "x": sidecar.bbox.x,
                    "y": sidecar.bbox.y,
                    "w": sidecar.bbox.w,
                    "h": sidecar.bbox.h,
                },
                "page_width": sidecar.page_width,
                "page_height": sidecar.page_height,
                "dpi": sidecar.dpi,
                "suggestion": sidecar.category,
                "group": sidecar.group,
                "quality": sidecar.quality,
                "accepted": sidecar.accepted,
                "notes": list(sidecar.notes),
                "thumb": f"{THUMB_PREFIX}{item.item_id}?v={thumb_key(item, item.image_path, edge)}",
                "source": f"{ITEM_PREFIX}{item.item_id}",
                "filed": None
                if correction is None
                else {"category": correction.category, "rejection": correction.rejection},
            }
        )
    return {
        "categories": list(CATEGORIES),
        "rejections": list(REJECTION_KINDS),
        "count": len(records),
        "items": records,
    }


# ---------------------------------------------------------------- the one write

def parse_filings(
    payload: object, items: dict[str, CorpusItem]
) -> tuple[list[Correction], list[CorrectionKey]]:
    """Turn a posted batch into corrections to file and identities to unfile.

    Every record is built with `Correction.for_sidecar` off the sidecar the server
    already holds, so the client supplies an item id and a verdict and nothing
    else: geometry it sent would be geometry nobody checked.

    `"unfile": true` in place of a verdict withdraws whatever was filed for that
    item. Undo needs it: a filed item leaves the wall at once and the batch
    flushes on a short interval, so one mis-keyed run is on disk before anybody
    reaches for undo, and without this the only way back is editing the file.
    """
    if not isinstance(payload, dict):
        raise BadRequest("expected an object with a 'filings' list")
    raw = payload.get("filings")
    if not isinstance(raw, list):
        raise BadRequest("'filings' is not a list")
    if not raw:
        raise BadRequest("'filings' is empty; nothing to file")

    filings: list[Correction] = []
    unfilings: list[CorrectionKey] = []
    # Which way each item was meant to go. Withdrawals are applied before
    # filings, so a batch asking for both on one item would keep the filing and
    # drop the undo silently — the one outcome nobody asked for.
    intents: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise BadRequest(f"filing {entry!r} is not an object")
        item_id = entry.get("item_id")
        if not isinstance(item_id, str) or item_id not in items:
            raise BadRequest(f"unknown item {item_id!r}")
        category = entry.get("category")
        rejection = entry.get("rejection")
        intent = "unfile" if entry.get("unfile") else "file"
        if intents.setdefault(item_id, intent) != intent:
            raise BadRequest(f"{item_id}: filed and unfiled in one batch")
        if entry.get("unfile"):
            # Refused rather than resolved: filing and withdrawing one item in the
            # same breath is a client bug, and picking a winner would hide it.
            if category is not None or rejection is not None:
                raise BadRequest(f"{item_id}: unfile carries a verdict as well")
            unfilings.append(sidecar_key(items[item_id].sidecar))
            continue
        if category is not None and not isinstance(category, str):
            raise BadRequest(f"{item_id}: category {category!r} is not a name")
        if rejection is not None and not isinstance(rejection, str):
            raise BadRequest(f"{item_id}: rejection {rejection!r} is not a name")
        try:
            filings.append(
                Correction.for_sidecar(
                    items[item_id].sidecar, category=category, rejection=rejection
                )
            )
        except CorrectionError as exc:
            raise BadRequest(str(exc)) from exc
    return filings, unfilings


def apply_filings(
    corrections_dir: Path,
    filings: list[Correction],
    unfilings: list[CorrectionKey] | tuple[()] = (),
) -> tuple[list[dict], list[dict]]:
    """Merge a batch into the per-PDF files it belongs to; report each file's outcome.

    The wall is ordered by the classifier's guess, so one selection spans several
    PDFs and one batch becomes several writes (R7's file per source PDF). Each
    file is loaded, the batch merged into what is already there and the whole file
    rewritten: writing the batch as the file's contents would erase everything
    filed earlier in the same sitting. Merging through a dict keyed by identity
    makes a duplicate record structurally impossible, which is the validation
    `write_corrections` deliberately does not do.
    """
    batches: dict[str, list[Correction]] = {}
    for correction in filings:
        batches.setdefault(correction.source_pdf, []).append(correction)
    # The stem is the key's first field, so a withdrawal routes to its file the
    # same way a filing does.
    withdrawals: dict[str, list[CorrectionKey]] = {}
    for key in unfilings:
        withdrawals.setdefault(key[0], []).append(key)

    written, failed = [], []
    for stem in sorted(set(batches) | set(withdrawals)):
        path = corrections_path(corrections_dir, stem)
        try:
            # The directory is tracked and normally there; a branch switch mid-
            # sitting can take it away, and a filing is worth more than the tidiness
            # of refusing to recreate it.
            path.parent.mkdir(parents=True, exist_ok=True)
            merged = read_corrections(path)
            gone = 0
            for key in withdrawals.get(stem, ()):
                # Withdrawing something never filed is the state the caller asked
                # for, so it is silent rather than an error.
                gone += merged.pop(key, None) is not None
            for correction in batches.get(stem, ()):
                merged[correction.key] = correction
            if merged or path.exists():
                write_corrections(path, merged.values())
        except (CorrectionError, OSError) as exc:
            # Named per PDF: a partial failure has to say which books were written.
            failed.append({"source_pdf": stem, "error": str(exc)})
            continue
        written.append({
            "source_pdf": stem,
            "filed": len(batches.get(stem, ())),
            "unfiled": gone,
            "total": len(merged),
        })
    return written, failed


# ---------------------------------------------------------------- the server

class CorrectHandler(BaseHTTPRequestHandler):
    server_version = "DressMeUpCorrect/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    # A client that announces a body and never sends it must not hold a thread for
    # the rest of the sitting.
    timeout = 30

    # Overwritten per response. Thumbnail URLs carry a key derived from their
    # source, so that one answer can never go stale; nothing else may be kept.
    cache_control = "no-cache"

    def log_message(self, fmt, *args):  # no access log
        pass

    def end_headers(self):
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", self.cache_control)
        super().end_headers()

    # -- replies ----------------------------------------------------------

    def _send(self, status: HTTPStatus, content_type: str, data: bytes, send_body: bool = True) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if status is HTTPStatus.METHOD_NOT_ALLOWED:
            self.send_header("Allow", "GET, HEAD, POST")
        self.end_headers()
        if send_body and self.command != "HEAD":
            self.wfile.write(data)

    def _refuse(self, status: HTTPStatus, message: str) -> None:
        self._send(status, "text/plain; charset=utf-8", f"{message}\n".encode("utf-8"))

    def _refuse_json(self, status: HTTPStatus, message: str) -> None:
        """The API's errors are JSON, so the wall can report one without guessing."""
        body = json.dumps({"error": message}) + "\n"
        self._send(status, "application/json; charset=utf-8", body.encode("utf-8"))

    # -- reads ------------------------------------------------------------

    def _serve_manifest(self, send_body: bool) -> None:
        try:
            # Under the write lock too: a correction file is rewritten whole, and a
            # reload that reads one mid-rewrite would see an empty file and report
            # it as a corpus nobody has labelled.
            with self.server.write_lock:
                manifest = corpus_manifest(self.server.items, self.server.corrections_dir)
        except CorrectionError as exc:
            self._refuse_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        body = (json.dumps(manifest) + "\n").encode("utf-8")
        self._send(HTTPStatus.OK, "application/json; charset=utf-8", body, send_body)

    def _lookup(self, prefix: str) -> CorpusItem | None:
        return self.server.items.get(item_id_from(self.path, prefix))

    def _serve_thumb(self, send_body: bool) -> None:
        item = self._lookup(THUMB_PREFIX)
        if item is None:
            self._refuse(HTTPStatus.NOT_FOUND, "no such item")
            return
        image = contained(item.image_path, self.server.sidecars_dir)
        if image is None:
            self._refuse(HTTPStatus.NOT_FOUND, "no such item")
            return
        try:
            data = cached_thumb(image, self.server.thumbs_dir, thumb_key(item, image))
        except (OSError, UnidentifiedImageError, ValueError):
            self._refuse(HTTPStatus.NOT_FOUND, "no such item")
            return
        self.cache_control = "private, max-age=86400, immutable"
        self._send(HTTPStatus.OK, "image/png", data, send_body)

    def _serve_cutout(self, send_body: bool) -> None:
        item = self._lookup(ITEM_PREFIX)
        image = None if item is None else contained(item.image_path, self.server.sidecars_dir)
        if image is None:
            self._refuse(HTTPStatus.NOT_FOUND, "no such item")
            return
        try:
            data = image.read_bytes()
        except OSError:
            self._refuse(HTTPStatus.NOT_FOUND, "no such item")
            return
        self._send(HTTPStatus.OK, "image/png", data, send_body)

    def _serve_client(self, send_body: bool) -> None:
        target = resolve_client_path(self.path, self.server.client_dir)
        if target is None:
            self._refuse(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            data = target.read_bytes()
        except OSError:
            self._refuse(HTTPStatus.NOT_FOUND, "not found")
            return
        self._send(HTTPStatus.OK, CONTENT_TYPES[target.suffix.lower()], data, send_body)

    def _serve(self, send_body: bool) -> None:
        bare = urlsplit(self.path).path
        if bare == CORPUS_ROUTE:
            self._serve_manifest(send_body)
        elif bare.startswith(THUMB_PREFIX):
            self._serve_thumb(send_body)
        elif bare.startswith(ITEM_PREFIX):
            self._serve_cutout(send_body)
        elif bare.startswith("/api/"):
            self._refuse_json(HTTPStatus.NOT_FOUND, "no such endpoint")
        else:
            self._serve_client(send_body)

    def do_GET(self):
        self._guard(lambda: self._serve(send_body=True))

    def do_HEAD(self):
        self._guard(lambda: self._serve(send_body=False))

    def _method_not_allowed(self):
        # The body is never read on this path, so the connection must close behind
        # it: unread bytes in the socket desync the next request on it.
        self._guard(lambda: self._refuse(HTTPStatus.METHOD_NOT_ALLOWED, "not a method this tool uses"))
        self.close_connection = True

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed

    # -- the one write ----------------------------------------------------

    def _read_body(self) -> bytes | None:
        """The posted bytes, or None when the request was already refused.

        Every refusal here answers without draining the body, so each one closes
        the connection behind it.
        """
        raw = self.headers.get("Content-Length")
        if raw is None:
            self.close_connection = True
            self._refuse_json(HTTPStatus.LENGTH_REQUIRED, "a batch of filings needs a Content-Length")
            return None
        try:
            length = int(raw)
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            self.close_connection = True
            self._refuse_json(HTTPStatus.BAD_REQUEST, f"Content-Length {raw!r} is not a length")
            return None
        if length > MAX_BODY:
            self.close_connection = True
            self._refuse_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body of {length} bytes is over the {MAX_BODY} cap"
            )
            return None
        return self.rfile.read(length) if length else b""

    def _handle_post(self) -> None:
        if urlsplit(self.path).path != CORRECTIONS_ROUTE:
            # Corrections are the only write (R17), and the body of anything else
            # goes unread — so the connection closes behind the refusal.
            self.close_connection = True
            self._refuse_json(HTTPStatus.NOT_FOUND, "corrections are the only thing this tool writes")
            return
        body = self._read_body()
        if body is None:
            return
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._refuse_json(HTTPStatus.BAD_REQUEST, f"invalid JSON: {exc}")
            return
        try:
            filings, unfilings = parse_filings(payload, self.server.items)
        except BadRequest as exc:
            # Whole-batch: a selection filed by one keystroke is one judgement, and
            # landing half of it would leave the person guessing which half.
            self._refuse_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        # One lock around the whole read-merge-write. Each request is its own
        # thread, so two batches for one PDF would otherwise both load the file,
        # and the second write would erase the first batch's filings — the same
        # erasure the merge exists to prevent, arrived at concurrently.
        with self.server.write_lock:
            written, failed = apply_filings(
                self.server.corrections_dir, filings, unfilings
            )
        status = HTTPStatus.INTERNAL_SERVER_ERROR if failed else HTTPStatus.OK
        data = (json.dumps({"written": written, "failed": failed}) + "\n").encode("utf-8")
        self._send(status, "application/json; charset=utf-8", data)

    def do_POST(self):
        self._guard(self._handle_post)

    def _guard(self, work) -> None:
        """Answer, and let nothing a client sends take the server down or print.

        Half an hour of filing is behind this process; an unhandled request is
        worth a 500 and silence, never an exit or a line of log.

        Also where the per-response policy is reset: one handler instance serves
        every request on a keep-alive connection, so a thumbnail's day-long cache
        would otherwise be inherited by whatever was asked for next.
        """
        self.cache_control = "no-cache"
        try:
            work()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001
            try:
                self._refuse(HTTPStatus.INTERNAL_SERVER_ERROR, "error")
            except Exception:  # noqa: BLE001
                pass
            self.close_connection = True


class CorrectServer(ThreadingHTTPServer):
    daemon_threads = True
    # A socket left in TIME_WAIT by the last run must not keep this one off the
    # port; a live listener is still refused by the kernel.
    allow_reuse_address = True

    def __init__(
        self,
        host: str,
        port: int,
        *,
        client_dir: Path,
        sidecars_dir: Path,
        corrections_dir: Path,
        thumbs_dir: Path,
    ):
        if ":" in host:
            self.address_family = socket.AF_INET6
        self.client_dir = Path(client_dir)
        self.sidecars_dir = Path(sidecars_dir)
        self.corrections_dir = Path(corrections_dir)
        self.thumbs_dir = Path(thumbs_dir)
        self.items = load_corpus(self.sidecars_dir)
        self.write_lock = threading.Lock()
        super().__init__((host, port), CorrectHandler)

    def handle_error(self, request, client_address):
        pass  # never print client addresses


def make_server(
    host: str,
    port: int,
    *,
    client_dir: Path | str,
    sidecars_dir: Path | str,
    corrections_dir: Path | str,
    thumbs_dir: Path | str,
) -> CorrectServer:
    """Load the corpus, bind, and return a server (not yet serving).

    Raises `CorpusError` for a corpus that cannot be served and `OSError` if the
    port is held; the corpus is read before the socket, so a broken corpus never
    leaves a listener behind.
    """
    return CorrectServer(
        host,
        port,
        client_dir=Path(client_dir),
        sidecars_dir=Path(sidecars_dir),
        corrections_dir=Path(corrections_dir),
        thumbs_dir=Path(thumbs_dir),
    )


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
        description="Serve the catalogue correction tool on this machine.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="the address to bind (default: %(default)s); wildcards are refused",
    )
    parser.add_argument(
        "--sidecars",
        type=Path,
        default=DEFAULT_SIDECARS,
        help="the extracted corpus to label (default: %(default)s)",
    )
    parser.add_argument(
        "--corrections",
        type=Path,
        default=DEFAULT_CORRECTIONS_DIR,
        help="where the per-PDF correction files live (default: %(default)s)",
    )
    parser.add_argument(
        "--thumbs",
        type=Path,
        default=DEFAULT_THUMBS,
        help="wall thumbnail cache, regenerable (default: %(default)s)",
    )
    parser.add_argument(
        "--client",
        type=Path,
        default=DEFAULT_CLIENT_DIR,
        help="the tool's own page (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = args.host.strip()
    if host in WILDCARD_HOSTS:
        print(f"refusing to start: --host {host!r} is a wildcard bind.", file=sys.stderr)
        print("This tool is for this machine; leave --host off for loopback.", file=sys.stderr)
        return 2
    if not args.sidecars.is_dir():
        print(f"refusing to start: corpus directory {args.sidecars} does not exist.", file=sys.stderr)
        return 2
    try:
        args.corrections.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"refusing to start: cannot use {args.corrections} ({exc}).", file=sys.stderr)
        return 2
    try:
        server = make_server(
            host,
            CORRECT_PORT,
            client_dir=args.client,
            sidecars_dir=args.sidecars,
            corrections_dir=args.corrections,
            thumbs_dir=args.thumbs,
        )
    except CorpusError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    except SidecarError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        name = errno.errorcode.get(exc.errno, str(exc.errno))
        print(f"refusing to start: cannot bind {host}:{CORRECT_PORT} ({name}).", file=sys.stderr)
        if exc.errno == errno.EADDRINUSE:
            print("Another correction server is already running; stop it first.", file=sys.stderr)
        return 1
    bound_host, bound_port = server.server_address[:2]
    if is_wildcard_bind(bound_host):
        server.server_close()
        print(
            f"refusing to start: --host {host!r} resolves to the wildcard address {bound_host}.",
            file=sys.stderr,
        )
        print("This tool is for this machine; leave --host off for loopback.", file=sys.stderr)
        return 2
    print(f"serving {len(server.items)} items from {args.sidecars}")
    print(f"corrections are written to {args.corrections}")
    if not (args.client / "index.html").is_file():
        print(f"note: {args.client / 'index.html'} is not there yet; the API still answers")
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
