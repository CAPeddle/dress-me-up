"""``web/serve.py``: explicit address, read-only, two roots, one content policy."""

from __future__ import annotations

import http.client
import subprocess
import sys

import pytest

from tests.web.conftest import FIXTURE_ASSETS, REPO_ROOT, WEB_DIR

SERVE_PY = WEB_DIR / "serve.py"


def request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=body)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def snapshot(*roots):
    return {p for root in roots for p in root.rglob("*")}


# ---------------------------------------------------------------- CLI posture

@pytest.mark.parametrize("host", ["0.0.0.0", "::", "*", ""])
def test_wildcard_host_is_refused_by_name(host):
    result = subprocess.run(
        [sys.executable, str(SERVE_PY), "--host", host, "--assets", str(FIXTURE_ASSETS)],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2
    assert repr(host) in result.stderr
    assert "refusing" in result.stderr.lower()


def test_host_is_required():
    result = subprocess.run(
        [sys.executable, str(SERVE_PY)], capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 2
    assert "--host" in result.stderr


def test_cli_has_no_port_flag(serve):
    parser = serve.build_parser()
    flags = {opt for action in parser._actions for opt in action.option_strings}
    assert "--port" not in flags
    assert serve.SHARED_PORT == 8777
    assert serve.WILDCARD_HOSTS == {"0.0.0.0", "::", "*", ""}


def test_held_port_refuses_to_bind(serve, site):
    with pytest.raises(OSError):
        serve.make_server("127.0.0.1", site.port, WEB_DIR, FIXTURE_ASSETS)


def test_cli_reports_held_port(serve, site, monkeypatch, capsys):
    monkeypatch.setattr(serve, "SHARED_PORT", site.port)
    code = serve.main(["--host", "127.0.0.1", "--assets", str(FIXTURE_ASSETS)])
    assert code != 0
    err = capsys.readouterr().err
    assert "refusing to start" in err
    assert str(site.port) in err


def test_missing_assets_dir_is_refused(serve, tmp_path, capsys):
    code = serve.main(["--host", "127.0.0.1", "--assets", str(tmp_path / "nope")])
    assert code == 2
    assert "assets" in capsys.readouterr().err


def test_url_for_brackets_ipv6(serve):
    assert serve.url_for("127.0.0.1", 8777) == "http://127.0.0.1:8777/"
    assert serve.url_for("fd00::1", 8777) == "http://[fd00::1]:8777/"


# ---------------------------------------------------------------- serving

def test_index_carries_the_content_policy(serve, site):
    status, headers, body = request(site.port, "GET", "/")
    assert status == 200
    assert headers["Content-Security-Policy"] == serve.CONTENT_SECURITY_POLICY
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert headers["Content-Type"].startswith("text/html")
    assert b"<script type=\"module\"" in body


def test_every_response_carries_the_policy(serve, site):
    for method, path in [("GET", "/nope.html"), ("HEAD", "/"), ("POST", "/"), ("GET", "/assets/catalog.json")]:
        _, headers, _ = request(site.port, method, path)
        assert headers.get("Content-Security-Policy") == serve.CONTENT_SECURITY_POLICY, (method, path)


def test_module_script_has_javascript_type(site):
    status, headers, _ = request(site.port, "GET", "/js/main.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")


def test_assets_root_is_served_under_assets(site):
    status, headers, body = request(site.port, "GET", "/assets/catalog.json")
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert b"fixture-0001" in body
    status, headers, body = request(site.port, "GET", "/assets/bodies/body_a.png")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body[:8] == b"\x89PNG\r\n\x1a\n"


def test_head_returns_headers_without_body(site):
    status, headers, body = request(site.port, "HEAD", "/")
    assert status == 200
    assert int(headers["Content-Length"]) > 0
    assert body == b""


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_writes_are_refused_and_nothing_is_written(site, method):
    before = snapshot(WEB_DIR, FIXTURE_ASSETS)
    for path in ["/", "/events", "/assets/catalog.json", "/anything"]:
        status, headers, _ = request(site.port, method, path, body=b'{"x":1}')
        assert status == 405, (method, path)
        assert headers.get("Allow") == "GET, HEAD"
    assert snapshot(WEB_DIR, FIXTURE_ASSETS) == before


@pytest.mark.parametrize("path", [
    "/../tools/pyproject.toml",
    "/../../tools/pyproject.toml",
    "/%2e%2e/tools/pyproject.toml",
    "/assets/../serve.py",
    "/assets/../../tools/pyproject.toml",
    "/serve.py",
    "/css/",
    "/assets/",
    "/assets",
    "/js/../js/../../CLAUDE.md",
])
def test_paths_outside_the_two_roots_are_refused(site, path):
    status, _, _ = request(site.port, "GET", path)
    assert status == 404, path


def test_resolve_path_is_pure(serve, tmp_path):
    web = tmp_path / "web"
    assets = tmp_path / "assets"
    (web / "css").mkdir(parents=True)
    assets.mkdir()
    (web / "index.html").write_text("x")
    (web / "css" / "game.css").write_text("x")
    (web / "serve.py").write_text("x")
    (assets / "catalog.json").write_text("{}")
    (tmp_path / "secret.json").write_text("{}")
    assert serve.resolve_path("/", web, assets) == (web / "index.html").resolve()
    assert serve.resolve_path("/css/game.css?v=1", web, assets) == (web / "css" / "game.css").resolve()
    assert serve.resolve_path("/assets/catalog.json", web, assets) == (assets / "catalog.json").resolve()
    assert serve.resolve_path("/serve.py", web, assets) is None
    assert serve.resolve_path("/../secret.json", web, assets) is None
    assert serve.resolve_path("/assets/../secret.json", web, assets) is None
    assert serve.resolve_path("/assets/../../secret.json", web, assets) is None
    assert serve.resolve_path("/css", web, assets) is None
    assert serve.resolve_path("/index.html%00.png", web, assets) is None


def test_no_access_log_on_stdout(serve, tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", (
            "import importlib.util, sys, threading, http.client\n"
            f"spec = importlib.util.spec_from_file_location('s', {str(SERVE_PY)!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            f"s = m.make_server('127.0.0.1', 0, {str(WEB_DIR)!r}, {str(FIXTURE_ASSETS)!r})\n"
            "t = threading.Thread(target=s.serve_forever, daemon=True); t.start()\n"
            "c = http.client.HTTPConnection('127.0.0.1', s.server_address[1]); c.request('GET', '/'); c.getresponse().read()\n"
            "c.request('GET', '/missing'); c.getresponse().read()\n"
            "s.shutdown(); s.server_close()\n"
        )],
        capture_output=True, text=True, timeout=30, cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
