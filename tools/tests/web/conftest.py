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


def _load_serve_module():
    spec = importlib.util.spec_from_file_location("dressup_web_serve", WEB_DIR / "serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def serve():
    """The ``web/serve.py`` module, imported from its tracked location."""
    return _load_serve_module()


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
