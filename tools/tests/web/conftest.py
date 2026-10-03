"""Shared fixtures for the web version's tests.

Pages always load through ``web/serve.py`` bound to loopback on an ephemeral
port, never from a file URL, so the content policy is exercised (KTD10).
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_DIR = REPO_ROOT / "web"
FIXTURE_ASSETS = Path(__file__).resolve().parent / "fixtures" / "assets"
LANDSCAPE = {"width": 1280, "height": 800}
PORTRAIT = {"width": 800, "height": 1280}


SERVE_MODULE_NAME = "dressup_web_serve"


def load_serve_module():
    """``web/serve.py`` imported from its tracked location, once per session.

    Public because the purity scan reads ``CONTENT_TYPES`` from it rather than
    keeping a second copy of the table of what the server hands to a browser.
    """
    cached = sys.modules.get(SERVE_MODULE_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(SERVE_MODULE_NAME, WEB_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def serve():
    """The ``web/serve.py`` module, imported from its tracked location."""
    return load_serve_module()


class RunningServer:
    def __init__(self, server):
        self.server = server
        host, port = server.server_address[:2]
        self.url = f"http://{host}:{port}/"
        self.port = port
        self._thread = threading.Thread(target=server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5)


@pytest.fixture(scope="session")
def server_factory(serve):
    """Start ``make_server`` on 127.0.0.1:0 in a thread; every server is stopped at session end."""
    started = []

    def _start(assets_dir: Path, web_dir: Path = WEB_DIR) -> RunningServer:
        running = RunningServer(serve.make_server("127.0.0.1", 0, web_dir, assets_dir))
        started.append(running)
        return running

    yield _start
    for running in started:
        running.stop()


@pytest.fixture(scope="session")
def site(server_factory):
    """The tracked ``web/`` plus the fixture assets, served for the whole session."""
    return server_factory(FIXTURE_ASSETS)


@pytest.fixture(scope="session")
def base_url(site):
    return site.url


@pytest.fixture
def assets_copy(tmp_path):
    """A writable copy of the fixture assets for tests that break the content on purpose."""
    target = tmp_path / "assets"
    shutil.copytree(FIXTURE_ASSETS, target)
    return target


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": dict(LANDSCAPE)}


@pytest.fixture
def console_errors(page):
    """Collects console errors and uncaught exceptions raised by the page."""
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    return errors


@pytest.fixture(autouse=True)
def _short_page_timeout(request):
    """Keep a broken page from stalling the run: 10 s is generous on loopback."""
    if "page" in request.fixturenames:
        request.getfixturevalue("page").set_default_timeout(10_000)


# ---------------------------------------------------------------- U5 helpers
# Plain functions, imported by the gesture and persistence tests.

STORE_KEY = "dressmeup.v1"


def open_game(page, url):
    page.goto(url)
    page.wait_for_selector("html[data-content='ready'], html[data-content='failed']")
    return page


def read_store(page):
    """The saved state as parsed JSON, or None when nothing is stored."""
    return page.evaluate(
        "key => { const t = localStorage.getItem(key); return t === null ? null : JSON.parse(t); }", STORE_KEY
    )


def raw_store(page):
    return page.evaluate("key => localStorage.getItem(key)", STORE_KEY)


def seed_store(page, text: str):
    """Pre-seed the one store key before any page script runs (also on reloads)."""
    page.add_init_script(f"localStorage.setItem({STORE_KEY!r}, {text!r});")


def center(box):
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def body_box(page, body: int):
    return page.locator(f"[data-rig-kind='body'][data-rig-slot='{body}'] > img").bounding_box()


def placed(page, body: int, item: int):
    return page.locator(f"[data-rig-stage='{body}'] [data-rig-kind='placed'][data-rig-slot='{item}']")


def tap_tile(page, item: int):
    page.locator(f"[data-rig-kind='tile'][data-rig-slot='{item}']").click()


def show_body(page, body: int):
    page.locator(f"[data-rig-kind='pager-thumb'][data-rig-slot='{body}']").click()
    page.wait_for_selector(f"[data-rig-stage='{body}']:not([hidden])")


def place_from_supply(page, item: int, body: int, fx: float = 0.5, fy: float = 0.5):
    """Tap a supply tile, page to ``body``, tap the body at fractions (fx, fy) of its image."""
    tap_tile(page, item)
    show_body(page, body)
    box = body_box(page, body)
    x, y = box["x"] + fx * box["width"], box["y"] + fy * box["height"]
    page.mouse.click(x, y)
    placed(page, body, item).wait_for()
    return x, y


def drag(page, from_xy, to_xy, steps: int = 8):
    """A single-pointer drag with the real mouse (pointerId 1)."""
    page.mouse.move(*from_xy)
    page.mouse.down()
    page.mouse.move(*to_xy, steps=steps)
    page.mouse.up()


def pointer(page, event_type: str, pointer_id: int, x: float, y: float, selector: str | None = None):
    """Dispatch a synthetic PointerEvent with its own pointer id at (x, y).

    Targets ``selector`` when given, else whatever is under the point, and bubbles
    so document-level listeners see it too.
    """
    page.evaluate(
        """([sel, type, id, x, y]) => {
            const el = sel ? document.querySelector(sel) : document.elementFromPoint(x, y);
            el.dispatchEvent(new PointerEvent(type, {
                pointerId: id, clientX: x, clientY: y, bubbles: true, cancelable: true, pointerType: "touch",
            }));
        }""",
        [selector, event_type, pointer_id, x, y],
    )
