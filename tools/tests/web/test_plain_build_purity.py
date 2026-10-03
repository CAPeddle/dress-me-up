"""The tracked ``web/`` is the plain build: no recording fingerprint may be in it (R10, KTD10).

A literal scan of every text file ``serve.py`` would hand a browser, at any depth
under ``web/``.  The set of served extensions is read from ``serve.CONTENT_TYPES``
so the scan cannot fall behind what the server delivers.  It proves no fingerprint
is present, not that none could be reconstructed at runtime (AE5).  ``serve.py``
itself is not browser-delivered (``.py`` is not a served extension); its refusal of
POST is proved by test_serve.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from tests.web.conftest import WEB_DIR, load_serve_module

# (label, pattern).  Patterns run per line.  Same-origin relative fetches are
# allowed (R8 needs them); any absolute or protocol-relative URL is not.
FINGERPRINTS = [
    ("rig marker", re.compile(r"PLAYTEST-RIG-DO-NOT-SHIP")),
    ("the word instrument", re.compile(r"instrument", re.IGNORECASE)),
    ("events path", re.compile(r"/events")),
    # A write verb shouted in a served file, and separately a `method` option
    # naming one in any case: browsers normalise `method: "post"`, so the bare
    # word check stays case-sensitive (lowercase `delete` is Map.delete, and
    # `input`/`output` must not trip anything).
    ("write verb", re.compile(r"\b(?:POST|PUT|PATCH|DELETE)\b")),
    ("write method", re.compile(
        r"""\bmethod\b\s*[:=]\s*["'`]?\s*(?:POST|PUT|PATCH|DELETE)\b""", re.IGNORECASE)),
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


# Exactly what serve.py hands out, so a file dropped anywhere under web/ with a
# served extension is scanned rather than quietly skipped.
SERVED_SUFFIXES = set(load_serve_module().CONTENT_TYPES)

# Served, but not text: scanning their bytes for words would only produce noise.
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".ico"}

SKIP_DIRS = {"__pycache__"}


def browser_delivered_files(web_dir: Path) -> list[Path]:
    """Every text file under ``web_dir`` the server would deliver, in path order."""
    files = [
        path
        for path in web_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SERVED_SUFFIXES
        and path.suffix.lower() not in BINARY_SUFFIXES
        and not SKIP_DIRS.intersection(path.relative_to(web_dir).parts)
    ]
    return sorted(files, key=lambda path: path.relative_to(web_dir).as_posix())


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
    assert any(f.startswith("js/catalog.js:") and f.endswith(": write verb") for f in findings)
    assert any(f.startswith("js/catalog.js:") and f.endswith(": write method") for f in findings)
    assert any(f.startswith("js/catalog.js:") and f.endswith(": events path") for f in findings)


@pytest.mark.parametrize("line", [
    'fetch(u, { method: "post" });',
    "fetch(u, { method:'Put' });",
    'const method = "patch";',
    'options.method = "delete";',
    '<form method=post>',
])
def test_a_lowercased_write_method_is_caught(web_copy, line):
    """Browsers normalise the verb's case, so the scan may not rely on it being shouted."""
    plant(web_copy / "js" / "main.js", line)
    findings = scan_plain_build(web_copy)
    assert any(f.startswith("js/main.js:") and f.endswith(": write method") for f in findings), findings


# The bare-word check stays case-sensitive on purpose; these are the lines in the
# tracked tree (gesture.js) and the ordinary words it must leave alone.
@pytest.mark.parametrize("line", [
    "live.delete(id);",
    "map.delete(x);",
    "const output = input + 1;",
    "// put the tile back",
    "element.dispatchEvent(new PointerEvent('pointerup'));",
])
def test_ordinary_lowercase_words_are_not_write_verbs(line):
    """A pure check on the patterns themselves: no files, no copy of web/."""
    for label, pattern in FINGERPRINTS:
        assert not pattern.search(line), (label, line)


def test_the_write_patterns_discriminate():
    """The two write patterns, checked directly against the strings that matter."""
    verb = dict(FINGERPRINTS)["write verb"]
    option = dict(FINGERPRINTS)["write method"]
    assert verb.search("xhr.open('POST', u);")
    assert verb.search("send a PUT here")
    assert not verb.search('fetch(u, { method: "post" });')
    assert option.search('fetch(u, { method: "post" });')
    assert not option.search("live.delete(id);")
    assert not option.search("map.delete(x);")


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


def test_served_file_outside_css_and_js_is_named(web_copy):
    """serve.py delivers any served extension at any depth, so the scan must reach there too."""
    vendor = web_copy / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "x.js").write_text("// PLAYTEST-RIG-DO-NOT-SHIP\n")
    assert scan_plain_build(web_copy) == ["vendor/x.js:1: rig marker"]


def test_every_served_text_extension_is_scanned(web_copy):
    """One planted file per served text extension; none may be skipped."""
    for suffix in sorted(SERVED_SUFFIXES - BINARY_SUFFIXES):
        (web_copy / f"planted{suffix}").write_text("PLAYTEST-RIG-DO-NOT-SHIP\n")
    findings = scan_plain_build(web_copy)
    for suffix in sorted(SERVED_SUFFIXES - BINARY_SUFFIXES):
        assert f"planted{suffix}:1: rig marker" in findings, (suffix, findings)


def test_unserved_extension_is_not_scanned(web_copy):
    (web_copy / "notes.txt").write_text("PLAYTEST-RIG-DO-NOT-SHIP POST")
    assert scan_plain_build(web_copy) == []
