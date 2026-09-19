"""The tracked ``web/`` is the plain build: no recording fingerprint may be in it (R10, KTD10).

A literal scan of the browser-delivered files (index.html, css/, js/).  It proves no
fingerprint is present, not that none could be reconstructed at runtime (AE5).
``serve.py`` is not browser-delivered; its refusal of POST is proved by test_serve.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from tests.web.conftest import WEB_DIR

# (label, pattern).  Patterns run per line.  Same-origin relative fetches are
# allowed (R8 needs them); any absolute or protocol-relative URL is not.
FINGERPRINTS = [
    ("rig marker", re.compile(r"PLAYTEST-RIG-DO-NOT-SHIP")),
    ("the word instrument", re.compile(r"instrument", re.IGNORECASE)),
    ("events path", re.compile(r"/events")),
    ("POST", re.compile(r"\bPOST\b")),
    ("sendBeacon", re.compile(r"sendBeacon")),
    ("WebSocket", re.compile(r"WebSocket")),
    ("EventSource", re.compile(r"EventSource")),
    ("XMLHttpRequest", re.compile(r"XMLHttpRequest")),
    ("absolute URL", re.compile(r"\b(?:https?|wss?)://", re.IGNORECASE)),
    ("protocol-relative URL", re.compile(r"""(?<=["'(=,])//""")),
    ("text input", re.compile(r"<input", re.IGNORECASE)),
    ("textarea", re.compile(r"<textarea", re.IGNORECASE)),
    ("contenteditable", re.compile(r"contenteditable", re.IGNORECASE)),
]


def browser_delivered_files(web_dir: Path) -> list[Path]:
    files = [web_dir / "index.html"]
    for sub in ("css", "js"):
        files.extend(sorted(p for p in (web_dir / sub).rglob("*") if p.is_file()))
    return files


def scan_plain_build(web_dir: Path | str) -> list[str]:
    """Findings as ``<relative file>:<line>: <label>``; empty means the build is plain."""
    web_dir = Path(web_dir)
    findings = []
    for path in browser_delivered_files(web_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in FINGERPRINTS:
                if pattern.search(line):
                    findings.append(f"{path.relative_to(web_dir)}:{number}: {label}")
    return findings


def test_tracked_web_is_plain():
    assert browser_delivered_files(WEB_DIR)
    assert scan_plain_build(WEB_DIR) == []


@pytest.fixture
def web_copy(tmp_path):
    target = tmp_path / "web"
    shutil.copytree(WEB_DIR, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def plant(path: Path, line: str) -> None:
    path.write_text(path.read_text() + "\n" + line + "\n")


def test_planted_marker_is_named(web_copy):
    plant(web_copy / "js" / "main.js", "// PLAYTEST-RIG-DO-NOT-SHIP")
    findings = scan_plain_build(web_copy)
    assert findings == ["js/main.js:%d: rig marker" % (len((web_copy / "js" / "main.js").read_text().splitlines()))]


def test_planted_post_is_named(web_copy):
    plant(web_copy / "js" / "catalog.js", 'fetch("/events", { method: "POST" });')
    findings = scan_plain_build(web_copy)
    assert any(f.startswith("js/catalog.js:") and f.endswith(": POST") for f in findings)
    assert any(f.startswith("js/catalog.js:") and f.endswith(": events path") for f in findings)


def test_planted_text_input_is_named(web_copy):
    plant(web_copy / "index.html", '<input type="text" name="who">')
    findings = scan_plain_build(web_copy)
    assert findings == [f"index.html:{len((web_copy / 'index.html').read_text().splitlines())}: text input"]


@pytest.mark.parametrize("line, label", [
    ("const url = 'https://example.invalid/x';", "absolute URL"),
    ("const url = 'HTTP://example.invalid/x';", "absolute URL"),
    ("const s = new WebSocket('ws://x');", "WebSocket"),
    ("<img src=//cdn.invalid/a.png>", "protocol-relative URL"),
    ("background: url(//cdn.invalid/a.png);", "protocol-relative URL"),
    ("navigator.sendBeacon(u, d);", "sendBeacon"),
    ("new EventSource(u);", "EventSource"),
    ("new XMLHttpRequest();", "XMLHttpRequest"),
    ("<div contenteditable>", "contenteditable"),
    ("<textarea></textarea>", "textarea"),
    ("// wire the Instrument here", "the word instrument"),
])
def test_each_fingerprint_is_caught(web_copy, line, label):
    plant(web_copy / "css" / "game.css", line)
    findings = scan_plain_build(web_copy)
    assert any(f.startswith("css/game.css:") and f.endswith(": " + label) for f in findings), findings


@pytest.mark.parametrize("line", [
    'fetch("assets/catalog.json")',
    "// a plain comment with a slash pair",
    "const half = total / 2; // ratio",
    "position: absolute;",
    "border-radius: 50%;",
])
def test_same_origin_and_ordinary_lines_pass(web_copy, line):
    plant(web_copy / "js" / "main.js", line)
    assert scan_plain_build(web_copy) == []


def test_serve_py_is_not_scanned(web_copy):
    (web_copy / "serve.py").write_text("PLAYTEST-RIG-DO-NOT-SHIP POST")
    assert scan_plain_build(web_copy) == []
