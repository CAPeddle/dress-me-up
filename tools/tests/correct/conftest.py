"""Fixtures for the correction server's tests.

The corpus is built here rather than taken from the shared sidecar fixtures: these
tests care about geometry the *server* hands out and files against, so every item
carries a positive page size and dpi (`Correction.validate` refuses anything
else) and the corrections directory is a throwaway under `tmp_path` — never the
tracked `tools/corrections/`.

Both servers are imported from their tracked locations by path, following
`tests/web/conftest.py`: `correct_server.py` is the tool under test and
`web/serve.py` is the posture it copies, so the port test can compare against the
real shared-port constant instead of a stale literal of it.
"""

from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = REPO_ROOT / "tools"
WEB_DIR = REPO_ROOT / "web"

# The pipeline package, independent of whatever the shared conftest does.
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from dressup_pipeline.models import BBox, Sidecar, SIDECAR_SUFFIX  # noqa: E402

# One real page from content/sidecars/20260509081623, so the fixtures carry the
# geometry the matcher will actually meet.
PAGE = (2480, 3507)
DPI = 300


def _load_module(name: str, path: Path):
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def correct():
    """`tools/correct_server.py`, imported from its tracked location."""
    return _load_module("dressup_correct_server", TOOLS_DIR / "correct_server.py")


@pytest.fixture(scope="session")
def serve():
    """`web/serve.py` — here only so the shared port is read, never assumed."""
    return _load_module("dressup_web_serve", WEB_DIR / "serve.py")


@dataclass
class Corpus:
    """A corpus on disk plus the three directories the server works against."""

    root: Path
    sidecars: Path
    corrections: Path
    thumbs: Path
    client: Path
    items: dict[str, Sidecar] = field(default_factory=dict)

    def add(
        self,
        item_id: str,
        *,
        stem: str = "scan-a",
        page: int = 0,
        bbox: tuple[int, int, int, int] = (120, 240, 160, 200),
        page_size: tuple[int, int] = PAGE,
        dpi: int = DPI,
        category: str | None = "hat",
        group: str | None = "fantasy",
        quality: float | None = 0.93,
        accepted: bool | None = True,
        notes: list[str] | None = None,
        image: str | None = None,
        write_image: bool = True,
    ) -> Sidecar:
        """One extracted item: a cutout PNG the size of its bbox, plus its sidecar."""
        folder = self.sidecars / stem
        folder.mkdir(parents=True, exist_ok=True)
        name = image if image is not None else f"{item_id}.png"
        sidecar = Sidecar(
            item_id=item_id,
            source_pdf=f"{stem}.pdf",
            page=page,
            bbox=BBox(*bbox),
            image=name,
            source_folder="Fantasy",
            page_width=page_size[0],
            page_height=page_size[1],
            dpi=dpi,
            category=category,
            group=group,
            quality=quality,
            accepted=accepted,
            notes=list(notes or []),
        )
        sidecar.write(folder / f"{item_id}{SIDECAR_SUFFIX}")
        if write_image:
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            make_cutout(bbox[2], bbox[3]).save(target)
        self.items[item_id] = sidecar
        return sidecar

    def corrections_file(self, stem: str) -> Path:
        return self.corrections / f"{stem}.corrections.json"

    def cutout(self, item_id: str) -> Path:
        sidecar = self.items[item_id]
        return self.sidecars / Path(sidecar.source_pdf).stem / sidecar.image


def make_cutout(width: int, height: int, margin: int = 12) -> Image.Image:
    """An RGBA cutout: a solid body inside a transparent margin, like a real one."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    body = Image.new("RGBA", (max(width - 2 * margin, 1), max(height - 2 * margin, 1)), (190, 70, 100, 255))
    image.paste(body, (margin, margin))
    return image


@pytest.fixture
def corpus(tmp_path) -> Corpus:
    """Two PDFs' worth of items, an empty corrections directory, no thumb cache yet.

    The corrections directory exists because the tracked one does: a test that
    snapshots the filesystem around a write should see the one file appear, not
    the directory holding it.
    """
    root = tmp_path / "corpus"
    built = Corpus(
        root=root,
        sidecars=root / "sidecars",
        corrections=root / "corrections",
        thumbs=root / "thumbs",
        client=root / "client",
    )
    built.sidecars.mkdir(parents=True)
    built.corrections.mkdir(parents=True)
    built.add("scan-a-p000-i000", stem="scan-a", page=0, bbox=(120, 240, 160, 200), category="hat")
    built.add("scan-a-p000-i001", stem="scan-a", page=0, bbox=(400, 240, 180, 320), category="top")
    built.add("scan-a-p001-i000", stem="scan-a", page=1, bbox=(90, 1100, 110, 170), category=None,
              quality=0.61, accepted=False, notes=["small (110x170)"])
    built.add("scan-b-p000-i000", stem="scan-b", page=0, bbox=(700, 80, 220, 140), category="wings")
    return built


class RunningServer:
    def __init__(self, server):
        self.server = server
        host, port = server.server_address[:2]
        self.host, self.port = host, port
        self.url = f"http://{host}:{port}/"
        # A short poll interval only so `shutdown()` returns promptly: the default
        # half second is paid by every test that starts its own server.
        self._thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self._thread.start()

    def request(self, method: str, path: str, body=None, headers=None):
        """One request over a fresh connection: (status, headers, body bytes)."""
        conn = http.client.HTTPConnection(self.host, self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def get_json(self, path: str):
        status, headers, body = self.request("GET", path)
        assert status == 200, body
        return json.loads(body)

    def post_json(self, path: str, payload):
        raw = json.dumps(payload).encode("utf-8")
        status, headers, body = self.request(
            "POST", path, body=raw,
            headers={"Content-Type": "application/json", "Content-Length": str(len(raw))},
        )
        # Tolerant on purpose: a refusal the API does not answer in JSON should
        # surface as the status it is, not as a decode error on the way past.
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = body.decode("utf-8", "replace")
        return status, headers, parsed

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture
def server_factory(correct):
    """Start `make_server` on 127.0.0.1:0 in a thread; every server stops at test end."""
    started: list[RunningServer] = []

    def _start(built: Corpus, **overrides) -> RunningServer:
        kwargs = {
            "client_dir": built.client,
            "sidecars_dir": built.sidecars,
            "corrections_dir": built.corrections,
            "thumbs_dir": built.thumbs,
        }
        kwargs.update(overrides)
        running = RunningServer(correct.make_server("127.0.0.1", 0, **kwargs))
        started.append(running)
        return running

    yield _start
    for running in started:
        running.stop()


@pytest.fixture
def running(corpus, server_factory) -> RunningServer:
    return server_factory(corpus)


def snapshot(*roots: Path) -> dict[Path, bytes | None]:
    """Every path under each root with its bytes, so a write shows up as a diff."""
    seen: dict[Path, bytes | None] = {}
    for root in roots:
        for path in root.rglob("*"):
            seen[path] = path.read_bytes() if path.is_file() else None
    return seen
