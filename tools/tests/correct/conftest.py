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
import time
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


# ---------------------------------------------------------------- the wall client
# The page is served from its tracked location, never copied into `tmp_path`: a
# copy is a second version of the thing under test, and the CSP test compares the
# real file's meta tag against the real server's constant.

CLIENT_DIR = TOOLS_DIR / "correct"

# A desk, not a tablet: the wall's column count comes from the viewport, so the
# windowing test needs one that does not move under it.
DESKTOP = {"width": 1280, "height": 800}


@pytest.fixture
def wall(corpus, server_factory) -> RunningServer:
    """The tracked wall client served against a throwaway corpus."""
    return server_factory(corpus, client_dir=CLIENT_DIR)


@pytest.fixture
def empty_corpus(tmp_path) -> Corpus:
    """A corpus directory with nothing extracted into it yet."""
    root = tmp_path / "empty"
    built = Corpus(
        root=root,
        sidecars=root / "sidecars",
        corrections=root / "corrections",
        thumbs=root / "thumbs",
        client=CLIENT_DIR,
    )
    built.sidecars.mkdir(parents=True)
    built.corrections.mkdir(parents=True)
    return built


BIG_COUNT = 1200


@pytest.fixture
def big_corpus(tmp_path) -> Corpus:
    """A corpus several times the real one's size, for the windowing test.

    Every item points at one cutout on disk rather than its own: the wall is being
    measured on how many thumbnails it asks for, and writing 1200 distinct PNGs
    would spend the whole test budget on the fixture. The geometry still differs
    per item, because geometry is the identity a filing is keyed on.
    """
    from dressup_pipeline.models import CATEGORIES

    root = tmp_path / "big"
    built = Corpus(
        root=root,
        sidecars=root / "sidecars",
        corrections=root / "corrections",
        thumbs=root / "thumbs",
        client=CLIENT_DIR,
    )
    built.sidecars.mkdir(parents=True)
    built.corrections.mkdir(parents=True)
    for index in range(BIG_COUNT):
        built.add(
            f"scan-big-p{index // 100:03d}-i{index % 100:03d}",
            stem="scan-big",
            page=index // 100,
            bbox=(20 + (index % 40) * 60, 20 + (index // 40) * 100, 44, 56),
            category=CATEGORIES[index % len(CATEGORIES)],
            image="shared.png",
            write_image=index == 0,
        )
    return built


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": dict(DESKTOP)}


@pytest.fixture
def console_errors(page):
    """Console errors and uncaught exceptions the page raised."""
    errors: list[str] = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


@pytest.fixture(autouse=True)
def _short_page_timeout(request):
    """Keep a broken page from stalling the run: 10 s is generous on loopback."""
    if "page" in request.fixturenames:
        request.getfixturevalue("page").set_default_timeout(10_000)


# -- helpers, imported by the browser tests ------------------------------------

def open_wall(page, url):
    """Load the wall and wait for it to have settled either way."""
    page.goto(url)
    page.wait_for_selector("html[data-wall='ready'], html[data-wall='failed']")
    return page


def legend(page) -> dict[str, str]:
    """The key map as the page publishes it: action name -> key.

    Read off the page rather than hardcoded, because the mapping is derived from
    the arrays the server sends and a test that assumed one would only ever check
    its own copy.
    """
    return dict(
        page.eval_on_selector_all(
            "[data-wall-kind='legend-entry']",
            "els => els.map(e => [e.dataset.wallAction, e.dataset.wallKey])",
        )
    )


def status(page, name: str) -> int:
    return int(page.get_attribute("[data-wall-region='status']", f"data-wall-{name}"))


def tile(page, item_id: str):
    return page.locator(f"[data-wall-kind='tile'][data-wall-item='{item_id}']")


def rendered_items(page) -> list[str]:
    """The item ids the wall has actually put in the DOM, in wall order.

    Only the window: the full order is the manifest's, which a test reads from the
    server rather than from a page that deliberately does not hold all of it.
    """
    return page.eval_on_selector_all(
        "[data-wall-kind='tile']", "els => els.map(e => e.dataset.wallItem)"
    )


def click_tile(page, item_id: str, shift: bool = False):
    tile(page, item_id).click(modifiers=["Shift"] if shift else [])


def wait_for_flush(page):
    """Wait until nothing is queued or in flight, so the disk holds every filing."""
    page.wait_for_selector("[data-wall-region='status'][data-wall-queued='0']")


def wait_for_file(path, timeout: float = 5.0):
    """Poll for a corrections file a page-hide flush is expected to have written."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


class HeldWrite:
    """The server's first correction write, stopped in the middle of itself.

    Two of the wall's failure paths only exist while a request is genuinely in
    flight: a second verdict chosen before the first one's batch has landed, and a
    request that wedges instead of erroring. Neither can be staged from the page —
    a `fetch` that fails fails immediately — so the stall is put where the work
    actually is. `correct_server` resolves `write_corrections` by name at call
    time, which is what `test_two_batches_for_one_pdf_at_once_keep_both` already
    leans on, so the real write can be swapped for one that announces itself and
    then waits to be let go.

    One write is held and every other one runs for real, so a test can stall one
    batch and still watch the next reach disk. `hold` picks which: the first by
    default, and a later one where the batch under test is not the first thing the
    sitting writes — an undo only has its own request once the filing it withdraws
    has landed, because the client posts one batch at a time.
    """

    def __init__(self, real, hold: int = 1):
        self._real = real
        self._entered = threading.Event()
        self._go = threading.Event()
        self._error: Exception | None = None
        self.calls = 0
        self.hold = hold

    def __call__(self, path, corrections):
        self.calls += 1
        if self.calls != self.hold:
            return self._real(path, corrections)
        self._entered.set()
        # Bounded, so a test that forgets to release fails as a test rather than
        # hanging the run behind a server thread nobody will wake.
        self._go.wait(timeout=30)
        if self._error is not None:
            raise self._error
        return self._real(path, corrections)

    def wait_until_in_flight(self, timeout: float = 10.0) -> None:
        assert self._entered.wait(timeout), "the batch never reached the server's write"

    def release(self, error: Exception | None = None) -> None:
        """Let the held write finish, either for real or by raising `error`."""
        self._error = error
        self._go.set()


@pytest.fixture
def held_write(correct, monkeypatch) -> HeldWrite:
    held = HeldWrite(correct.write_corrections)
    monkeypatch.setattr(correct, "write_corrections", held)
    yield held
    # Whatever the test did, the server thread must not be left parked on the
    # write lock while the next test starts.
    held.release()
