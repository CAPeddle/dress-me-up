"""`tools/correct_server.py`: read the corpus, write nothing but corrections.

The write endpoint is where this server deliberately leaves `web/serve.py`'s
posture behind, so it is pinned hardest: a filing has to survive to disk, a second
batch must not erase the first (nor a concurrent one), and a batch with one bad
record must not land half of itself. Everything else here is that read-only
posture copied across — one explicit loopback address, one policy on every
response, and no filesystem path ever built out of something a client sent.
"""

from __future__ import annotations

import http.client
import io
import json
import os
import socket
import threading
import time

import pytest
from PIL import Image

from dressup_pipeline.corrections import REJECTION_KINDS, read_corrections
from dressup_pipeline.models import CATEGORIES

from tests.correct.conftest import make_cutout, snapshot


def write_client(corpus):
    """The page U5 will fill: `tools/correct/index.html` plus its js and css."""
    (corpus.client / "js").mkdir(parents=True, exist_ok=True)
    (corpus.client / "css").mkdir(parents=True, exist_ok=True)
    (corpus.client / "index.html").write_text("<!doctype html><title>wall</title>\n", encoding="utf-8")
    (corpus.client / "js" / "wall.js").write_text("export const wall = 1;\n", encoding="utf-8")
    (corpus.client / "css" / "wall.css").write_text(".tile { }\n", encoding="utf-8")


def manifest_item(manifest, item_id):
    return next(record for record in manifest["items"] if record["item_id"] == item_id)


# ------------------------------------------------------------ the write endpoint

def test_a_filing_lands_in_the_correction_file(running, corpus):
    status, _, payload = running.post_json(
        "/api/corrections",
        {"filings": [{"item_id": "scan-a-p000-i000", "category": "shoes"}]},
    )

    assert status == 200, payload
    assert payload["failed"] == []
    assert [entry["source_pdf"] for entry in payload["written"]] == ["scan-a"]

    on_disk = read_corrections(corpus.corrections_file("scan-a"))
    assert len(on_disk) == 1
    correction = next(iter(on_disk.values()))
    assert correction.category == "shoes"
    assert correction.source_pdf == "scan-a"
    # The geometry is the server's own, taken off the sidecar: the client sent none.
    sidecar = corpus.items["scan-a-p000-i000"]
    assert correction.bbox.as_tuple() == sidecar.bbox.as_tuple()
    assert (correction.page, correction.page_width, correction.page_height, correction.dpi) == (
        sidecar.page, sidecar.page_width, sidecar.page_height, sidecar.dpi
    )


def test_a_write_touches_the_one_correction_file_and_nothing_else(running, corpus):
    before = snapshot(corpus.root)

    status, _, _ = running.post_json(
        "/api/corrections",
        {"filings": [{"item_id": "scan-a-p000-i001", "rejection": "bad_crop"}]},
    )
    assert status == 200

    after = snapshot(corpus.root)
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    assert changed == {corpus.corrections_file("scan-a")}


def test_a_rejection_records_its_kind(running, corpus):
    running.post_json(
        "/api/corrections",
        {"filings": [{"item_id": "scan-a-p001-i000", "rejection": "not_an_item"}]},
    )
    correction = next(iter(read_corrections(corpus.corrections_file("scan-a")).values()))
    assert correction.rejected and correction.rejection == "not_an_item"
    assert correction.effective_category is None


def test_a_second_batch_keeps_the_first_batch(running, corpus):
    running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "category": "hat"}]}
    )
    status, _, payload = running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i001", "category": "top"}]}
    )

    assert status == 200
    assert payload["written"] == [{"source_pdf": "scan-a", "filed": 1, "unfiled": 0, "total": 2}]

    filed = {
        correction.bbox.as_tuple(): correction.category
        for correction in read_corrections(corpus.corrections_file("scan-a")).values()
    }
    assert filed == {(120, 240, 160, 200): "hat", (400, 240, 180, 320): "top"}


def test_refiling_an_item_replaces_its_verdict_without_duplicating_it(running, corpus):
    running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "category": "hat"}]}
    )
    running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "category": "hair"}]}
    )

    # read_corrections refuses a file holding one item twice, so a duplicate would
    # fail here rather than quietly double-count the wall's progress.
    on_disk = read_corrections(corpus.corrections_file("scan-a"))
    assert [correction.category for correction in on_disk.values()] == ["hair"]


def test_a_selection_spanning_two_pdfs_is_written_per_pdf(running, corpus):
    status, _, payload = running.post_json(
        "/api/corrections",
        {
            "filings": [
                {"item_id": "scan-a-p000-i000", "category": "hat"},
                {"item_id": "scan-b-p000-i000", "category": "wings"},
                {"item_id": "scan-a-p000-i001", "category": "top"},
            ]
        },
    )

    assert status == 200
    assert payload["written"] == [
        {"source_pdf": "scan-a", "filed": 2, "unfiled": 0, "total": 2},
        {"source_pdf": "scan-b", "filed": 1, "unfiled": 0, "total": 1},
    ]
    assert len(read_corrections(corpus.corrections_file("scan-a"))) == 2
    assert len(read_corrections(corpus.corrections_file("scan-b"))) == 1


def test_a_failing_pdf_names_itself_and_the_others_are_still_written(running, corpus):
    # A corrections file that cannot be read is the realistic failure: a hand edit
    # that broke the JSON. The other book's filings must not be held hostage by it.
    corpus.corrections_file("scan-b").write_text("{ not json", encoding="utf-8")

    status, _, payload = running.post_json(
        "/api/corrections",
        {
            "filings": [
                {"item_id": "scan-a-p000-i000", "category": "hat"},
                {"item_id": "scan-b-p000-i000", "category": "wings"},
            ]
        },
    )

    assert status == 500
    assert [entry["source_pdf"] for entry in payload["written"]] == ["scan-a"]
    assert [entry["source_pdf"] for entry in payload["failed"]] == ["scan-b"]
    assert len(read_corrections(corpus.corrections_file("scan-a"))) == 1


def test_two_batches_for_one_pdf_at_once_keep_both(running, corpus, correct, monkeypatch):
    """Two filings in flight for one book must not erase one another.

    Each request is its own thread, so an unsynchronised read-merge-write would let
    both load the same file and the later write would drop the earlier batch. The
    write is slowed here so the interleaving is certain rather than lucky.
    """
    real_write = correct.write_corrections
    calls = []

    def slow_write(path, corrections):
        calls.append(path)
        time.sleep(0.2)
        real_write(path, corrections)

    monkeypatch.setattr(correct, "write_corrections", slow_write)

    def post(item_id, category):
        running.post_json(
            "/api/corrections", {"filings": [{"item_id": item_id, "category": category}]}
        )

    threads = [
        threading.Thread(target=post, args=("scan-a-p000-i000", "hat")),
        threading.Thread(target=post, args=("scan-a-p000-i001", "top")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(calls) == 2
    filed = {
        correction.bbox.as_tuple(): correction.category
        for correction in read_corrections(corpus.corrections_file("scan-a")).values()
    }
    assert filed == {(120, 240, 160, 200): "hat", (400, 240, 180, 320): "top"}


def test_the_written_file_carries_no_path_and_no_address(running, corpus):
    running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "category": "hat"}]}
    )
    text = corpus.corrections_file("scan-a").read_text(encoding="utf-8")
    assert str(corpus.root) not in text
    assert running.host not in text
    assert "http" not in text and ".png" not in text


# ------------------------------------------------------------ refusing a write

@pytest.mark.parametrize("filings, reason", [
    ([{"item_id": "scan-a-p000-i000", "category": "trousers"}], "category"),
    ([{"item_id": "scan-a-p000-i000", "rejection": "ugly"}], "rejection"),
    ([{"item_id": "scan-a-p000-i000", "category": "hat", "rejection": "bad_crop"}], "both"),
    ([{"item_id": "scan-a-p000-i000"}], "neither"),
    ([{"item_id": "nobody-p000-i000", "category": "hat"}], "unknown item"),
    ([{"category": "hat"}], "no item"),
    (["scan-a-p000-i000"], "not an object"),
    ([], "empty"),
])
def test_a_bad_filing_refuses_the_whole_batch(running, corpus, filings, reason):
    # One keystroke files a whole selection, so half of it landing would leave the
    # person no way to tell which half.
    batch = [{"item_id": "scan-a-p000-i001", "category": "top"}, *filings] if filings else filings

    status, headers, payload = running.post_json("/api/corrections", {"filings": batch})

    assert status == 400, reason
    assert "error" in payload
    assert headers["Content-Type"].startswith("application/json")
    assert not corpus.corrections_file("scan-a").exists()


def test_an_invalid_category_leaves_an_existing_file_untouched(running, corpus):
    running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "category": "hat"}]}
    )
    before = corpus.corrections_file("scan-a").read_bytes()

    status, _, _ = running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i001", "category": "cloak"}]}
    )

    assert status == 400
    assert corpus.corrections_file("scan-a").read_bytes() == before


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b'{"filings": 3}', b'"filings"'])
def test_a_malformed_body_is_refused_in_json(running, corpus, body):
    status, headers, payload = running.request(
        "POST", "/api/corrections", body=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    assert status == 400
    assert headers["Content-Type"].startswith("application/json")
    assert "error" in json.loads(payload)
    assert not corpus.corrections_file("scan-a").exists()


def test_a_post_that_announces_no_length_is_refused(running):
    # Raw, because `http.client` always sends a Content-Length: a request without
    # one has a body the server cannot know the end of, so it reads none of it.
    sock = socket.create_connection((running.host, running.port), timeout=5)
    try:
        sock.sendall(
            b"POST /api/corrections HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Type: application/json\r\n\r\n"
        )
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                break
            head += chunk
    finally:
        sock.close()
    assert b"411" in head.split(b"\r\n")[0]


def test_an_oversized_body_is_refused_before_it_is_read(running, correct):
    # The length is believed, not the body: the cap has to hold without the server
    # first reading a megabyte of it.
    oversized = correct.MAX_BODY + 1
    status, _, body = running.request(
        "POST", "/api/corrections", body=b"{}",
        headers={"Content-Length": str(oversized)},
    )
    assert status == 413
    assert str(correct.MAX_BODY) in json.loads(body)["error"]


def test_a_post_anywhere_else_is_refused(running, corpus):
    status, _, payload = running.post_json("/api/anything", {"filings": []})
    assert status == 404
    assert "error" in payload
    assert not list(corpus.corrections.iterdir())


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH", "OPTIONS"])
def test_unused_methods_are_refused(running, method):
    status, headers, _ = running.request(method, "/api/corrections")
    assert status == 405
    assert headers["Allow"] == "GET, HEAD, POST"


# ------------------------------------------------------------ the manifest

def test_the_manifest_describes_the_whole_corpus(running, corpus):
    manifest = running.get_json("/api/corpus")

    assert manifest["count"] == 4
    assert len(manifest["items"]) == 4
    # Read at runtime, never copied: `companion` joined CATEGORIES after this tool
    # was planned and the wall has to offer it without a second edit.
    assert manifest["categories"] == list(CATEGORIES)
    assert "companion" in manifest["categories"]
    assert manifest["rejections"] == list(REJECTION_KINDS)

    record = manifest_item(manifest, "scan-a-p001-i000")
    assert record["source_pdf"] == "scan-a"
    assert record["page"] == 1
    assert record["bbox"] == {"x": 90, "y": 1100, "w": 110, "h": 170}
    assert (record["page_width"], record["page_height"], record["dpi"]) == (2480, 3507, 300)
    assert record["suggestion"] is None          # the classifier had no guess
    assert record["accepted"] is False           # and QA rejected it: still on the wall
    assert record["notes"] == ["small (110x170)"]
    assert record["thumb"].startswith("/thumb/scan-a-p001-i000?v=")
    assert record["source"] == "/item/scan-a-p001-i000"
    assert record["filed"] is None


def test_the_manifest_carries_no_image_data(running):
    body = running.request("GET", "/api/corpus")[2]
    assert b"data:image" not in body and b"base64" not in body
    # The whole corpus in one response (KTD8), so it has to stay small.
    assert len(body) < 4096


def test_the_manifest_orders_items_by_the_classifier_s_guess(running):
    manifest = running.get_json("/api/corpus")
    suggestions = [record["suggestion"] for record in manifest["items"]]
    # Alike guesses adjacent (R4), and the unguessed items last, where the work is
    # most obviously unstarted.
    assert suggestions == ["hat", "top", "wings", None]


def test_the_manifest_reports_what_has_already_been_filed(running, corpus):
    running.post_json(
        "/api/corrections",
        {
            "filings": [
                {"item_id": "scan-a-p000-i000", "category": "hair"},
                {"item_id": "scan-a-p001-i000", "rejection": "multi_item"},
            ]
        },
    )
    manifest = running.get_json("/api/corpus")

    assert manifest_item(manifest, "scan-a-p000-i000")["filed"] == {
        "category": "hair", "rejection": None
    }
    assert manifest_item(manifest, "scan-a-p001-i000")["filed"] == {
        "category": None, "rejection": "multi_item"
    }
    assert manifest_item(manifest, "scan-b-p000-i000")["filed"] is None


def test_a_broken_corrections_file_is_reported_rather_than_ignored(running, corpus):
    corpus.corrections_file("scan-a").write_text('{"corrections": [{"page": 0}]}', encoding="utf-8")
    status, headers, body = running.request("GET", "/api/corpus")
    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert "error" in json.loads(body)


# ------------------------------------------------------------ images

def test_a_thumbnail_is_derived_cached_and_reused(running, corpus, correct, monkeypatch):
    record = manifest_item(running.get_json("/api/corpus"), "scan-a-p000-i001")

    status, headers, body = running.request("GET", record["thumb"])
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    # The URL carries a key derived from the cutout, so the answer cannot go stale.
    assert "immutable" in headers["Cache-Control"]

    with Image.open(io.BytesIO(body)) as thumb:
        assert max(thumb.size) <= correct.THUMB_EDGE
        assert thumb.mode == "RGBA"          # a cutout's transparent margin survives

    cached = sorted(path.name for path in corpus.thumbs.iterdir())
    assert len(cached) == 1 and cached[0].endswith(".png")   # nothing half-written left behind

    # Derived once: a second ask must come off the cache, not out of Pillow again.
    monkeypatch.setattr(correct, "render_thumb", lambda *a, **kw: pytest.fail("re-derived"))
    assert running.request("GET", record["thumb"])[2] == body


def test_a_thumbnails_long_cache_does_not_outlive_its_response(running):
    """One handler serves every request on a kept-alive connection, so the
    thumbnail's day-long cache must not be inherited by the manifest behind it."""
    thumb = manifest_item(running.get_json("/api/corpus"), "scan-a-p000-i000")["thumb"]
    conn = http.client.HTTPConnection(running.host, running.port, timeout=5)
    try:
        conn.request("GET", thumb, headers={"Connection": "keep-alive"})
        first = conn.getresponse()
        first.read()
        assert "immutable" in first.getheader("Cache-Control")

        conn.request("GET", "/api/corpus", headers={"Connection": "keep-alive"})
        second = conn.getresponse()
        second.read()
        assert second.getheader("Cache-Control") == "no-cache"
    finally:
        conn.close()


def test_a_small_item_is_not_enlarged_into_its_thumbnail(running, corpus):
    # KTD7's reason for serving the original on request: a fixed thumbnail size
    # would defeat judging a small item, and stretching one would lie about it.
    record = manifest_item(running.get_json("/api/corpus"), "scan-a-p001-i000")
    body = running.request("GET", record["thumb"])[2]
    with Image.open(io.BytesIO(body)) as thumb:
        assert thumb.size == (110, 170)


def test_a_changed_cutout_changes_its_thumbnail_key(running, corpus):
    first = manifest_item(running.get_json("/api/corpus"), "scan-a-p000-i000")["thumb"]
    path = corpus.cutout("scan-a-p000-i000")
    make_cutout(160, 200, margin=40).save(path)
    os.utime(path, (1, 1))

    second = manifest_item(running.get_json("/api/corpus"), "scan-a-p000-i000")["thumb"]
    assert first != second
    assert running.request("GET", first)[0] == 200 and running.request("GET", second)[0] == 200


def test_the_thumbnail_cache_lives_outside_the_tracked_tree(correct):
    # `content/` is ignored; a cache under `tools/` would be committed image data.
    assert correct.DEFAULT_THUMBS.parent.name == "content"
    assert correct.TOOLS_DIR not in correct.DEFAULT_THUMBS.parents


def test_an_item_serves_its_original_cutout(running, corpus):
    status, headers, body = running.request("GET", "/item/scan-a-p000-i001")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body == corpus.cutout("scan-a-p000-i001").read_bytes()


@pytest.mark.parametrize("route", ["/item/", "/thumb/"])
@pytest.mark.parametrize("suffix", [
    "nobody-p000-i000",
    "",
    "../../../etc/passwd",
    "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "scan-a-p000-i000/../scan-b-p000-i000",
    "scan-a-p000-i000.png",
])
def test_an_unknown_item_never_becomes_a_filesystem_path(running, corpus, route, suffix):
    status, _, body = running.request("GET", route + suffix)
    assert status == 404
    assert b"root:" not in body
    # Nothing was derived, so the cache directory was never even made.
    assert not corpus.thumbs.exists()


@pytest.mark.parametrize("route", ["/item/", "/thumb/"])
def test_a_cutout_that_escapes_the_corpus_is_refused(corpus, server_factory, route):
    """A sidecar's `image` is data off the disk, and a symlink out of the corpus is
    the one way it can name a file the corpus does not hold."""
    outside = corpus.root / "outside.png"
    make_cutout(40, 40).save(outside)
    secret = outside.read_bytes()
    folder = corpus.sidecars / "scan-a"
    (folder / "escape.png").symlink_to(outside)
    corpus.add("scan-a-p002-i000", stem="scan-a", page=2, image="escape.png", write_image=False)

    running = server_factory(corpus)
    status, _, body = running.request("GET", route + "scan-a-p002-i000")

    assert status == 404
    assert body != secret


def test_a_traversing_image_field_is_refused(corpus, server_factory):
    # `sidecars/scan-a/../../outside.png` is a real file just outside the corpus,
    # so the refusal is containment and not merely a missing file.
    outside = corpus.root / "outside.png"
    make_cutout(40, 40).save(outside)
    corpus.add("scan-a-p003-i000", stem="scan-a", page=3, image="../../outside.png", write_image=False)

    running = server_factory(corpus)
    status, _, body = running.request("GET", "/item/scan-a-p003-i000")
    assert status == 404
    assert body != outside.read_bytes()


# ------------------------------------------------------------ the client's files

def test_the_page_and_its_assets_are_served(corpus, server_factory):
    write_client(corpus)
    running = server_factory(corpus)

    status, headers, body = running.request("GET", "/")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"<!doctype html>" in body
    assert running.request("GET", "/js/wall.js")[1]["Content-Type"].startswith("text/javascript")
    assert running.request("GET", "/css/wall.css")[1]["Content-Type"].startswith("text/css")


def test_the_api_answers_before_the_page_exists(running, corpus):
    """U5 has not written the wall yet; the corpus and its images still serve."""
    assert not corpus.client.exists()
    status, headers, body = running.request("GET", "/")
    assert status == 404
    assert headers["Content-Type"].startswith("text/plain")
    assert running.request("GET", "/api/corpus")[0] == 200


@pytest.mark.parametrize("path", [
    "/../../../../etc/passwd",
    "/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/serve.py",
    "/js/../../../correct_server.py",
])
def test_a_path_out_of_the_client_directory_is_refused(corpus, server_factory, path):
    write_client(corpus)
    running = server_factory(corpus)
    status, _, body = running.request("GET", path)
    assert status == 404
    assert b"root:" not in body and b"CORRECT_PORT" not in body


def test_head_answers_without_a_body(corpus, server_factory):
    write_client(corpus)
    running = server_factory(corpus)
    for path in ("/", "/api/corpus", "/item/scan-a-p000-i000"):
        status, headers, body = running.request("HEAD", path)
        assert status == 200 and body == b""
        assert int(headers["Content-Length"]) > 0


# ------------------------------------------------------------ posture

def test_every_response_carries_the_content_policy(corpus, server_factory, correct):
    write_client(corpus)
    running = server_factory(corpus)
    thumb = manifest_item(running.get_json("/api/corpus"), "scan-a-p000-i000")["thumb"]

    exchanges = [
        running.request("GET", "/"),
        running.request("GET", "/api/corpus"),
        running.request("GET", thumb),
        running.request("GET", "/item/scan-a-p000-i000"),
        running.request("GET", "/nope.html"),
        running.request("PUT", "/api/corrections"),
        running.post_json("/api/corrections", {"filings": [{"item_id": "scan-b-p000-i000", "category": "wings"}]}),
        running.post_json("/api/corrections", {"filings": [{"item_id": "scan-b-p000-i000", "category": "nope"}]}),
    ]

    assert [status for status, _, _ in exchanges] == [200, 200, 200, 200, 404, 405, 200, 400]
    for status, headers, _ in exchanges:
        assert headers["Content-Security-Policy"] == correct.CONTENT_SECURITY_POLICY, status
        assert headers["X-Content-Type-Options"] == "nosniff", status


def test_nothing_is_written_to_the_terminal_while_serving(capfd, corpus, server_factory):
    write_client(corpus)
    running = server_factory(corpus)
    thumb = manifest_item(running.get_json("/api/corpus"), "scan-a-p000-i000")["thumb"]

    running.request("GET", "/")
    running.request("GET", thumb)
    running.request("GET", "/nope")
    running.request("GET", "/item/nobody")
    running.request("PUT", "/api/corrections")
    running.request("POST", "/api/corrections", body=b"not json",
                    headers={"Content-Length": "8"})
    running.post_json("/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "category": "hat"}]})
    running.stop()

    captured = capfd.readouterr()
    assert (captured.out, captured.err) == ("", "")


# The first four are caught by name; the rest spell the same two wildcard
# addresses in ways no literal set can enumerate, so only the address the socket
# actually bound can refuse them.
@pytest.mark.parametrize("host", [
    "0.0.0.0", "::", "*", "", "0", "0.0", "00.0.0.0", "::0", "0:0:0:0:0:0:0:0",
])
def test_wildcard_host_is_refused(correct, corpus, monkeypatch, capsys, host):
    monkeypatch.setattr(correct, "CORRECT_PORT", 0)  # never touch the tool's own port
    created = []
    real_make_server = correct.make_server

    def spy(host, port, **roots):
        server = real_make_server(host, port, **roots)
        server.serve_forever = lambda *a, **kw: pytest.fail(
            f"started serving on the wildcard address {server.server_address}"
        )
        created.append(server)
        return server

    monkeypatch.setattr(correct, "make_server", spy)

    code = correct.main([
        "--host", host,
        "--sidecars", str(corpus.sidecars),
        "--corrections", str(corpus.corrections),
        "--thumbs", str(corpus.thumbs),
        "--client", str(corpus.client),
    ])
    err = capsys.readouterr().err

    assert code == 2
    assert repr(host) in err
    assert "refusing" in err.lower()
    # Whatever was bound to find out is closed again: nothing is left listening.
    assert all(server.socket.fileno() == -1 for server in created)


def test_the_host_defaults_to_loopback(correct, corpus, monkeypatch, capsys):
    """Unlike `web/serve.py`, which requires the flag: that one serves the tablet
    across the house and this one serves this desk (R16)."""
    monkeypatch.setattr(correct, "CORRECT_PORT", 0)
    bound = []
    real_make_server = correct.make_server

    def spy(host, port, **roots):
        server = real_make_server(host, port, **roots)
        server.serve_forever = lambda *a, **kw: None
        bound.append(server)
        return server

    monkeypatch.setattr(correct, "make_server", spy)

    code = correct.main([
        "--sidecars", str(corpus.sidecars),
        "--corrections", str(corpus.corrections),
        "--thumbs", str(corpus.thumbs),
        "--client", str(corpus.client),
    ])

    assert code == 0
    assert bound[0].server_address[0] == "127.0.0.1"
    out = capsys.readouterr().out
    assert "127.0.0.1" in out
    # The page is not written yet, and the person should hear that rather than
    # meet a 404 with no explanation.
    assert "index.html" in out


def test_the_tool_does_not_share_the_web_version_s_port(correct, serve):
    # 8777 is shared so the web version and the collector cannot co-run (KTD6);
    # this tool has to work while the tablet is being served.
    assert correct.CORRECT_PORT != serve.SHARED_PORT
    flags = {opt for action in correct.build_parser()._actions for opt in action.option_strings}
    assert "--port" not in flags
    assert correct.WILDCARD_HOSTS == serve.WILDCARD_HOSTS


def test_a_held_port_refuses_to_bind(correct, corpus, running):
    with pytest.raises(OSError):
        correct.make_server(
            "127.0.0.1", running.port,
            client_dir=corpus.client, sidecars_dir=corpus.sidecars,
            corrections_dir=corpus.corrections, thumbs_dir=corpus.thumbs,
        )


def test_a_missing_corpus_is_refused(correct, corpus, capsys, tmp_path):
    code = correct.main([
        "--host", "127.0.0.1",
        "--sidecars", str(tmp_path / "nope"),
        "--corrections", str(corpus.corrections),
    ])
    assert code == 2
    assert "refusing to start" in capsys.readouterr().err


def test_a_repeated_item_id_is_refused_before_anything_binds(correct, corpus):
    """The client names an item by its id, so two items answering to one id would
    serve one and file the verdict against whichever won."""
    corpus.add("scan-a-p000-i000", stem="scan-b", page=0, bbox=(5, 5, 60, 60))

    with pytest.raises(correct.CorpusError) as caught:
        correct.make_server(
            "127.0.0.1", 0,
            client_dir=corpus.client, sidecars_dir=corpus.sidecars,
            corrections_dir=corpus.corrections, thumbs_dir=corpus.thumbs,
        )
    assert "scan-a-p000-i000" in str(caught.value)


# ------------------------------------------------- unfiling, so undo can reach disk

def test_an_unfile_removes_that_record_and_leaves_the_rest(running, corpus):
    """Undo has to reach disk, because a filed item leaves the wall immediately.

    A run filed by one mis-key can be dozens of items, and the batch flushes on a
    short interval, so by the time somebody reaches for undo the records are
    usually already written. Without this the only recovery is editing the file.
    """
    running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i000", "category": "hat"},
        {"item_id": "scan-a-p000-i001", "category": "top"},
    ]})

    status, _, payload = running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-a-p000-i000", "unfile": True}]}
    )

    assert status == 200, payload
    assert payload["failed"] == []
    assert payload["written"] == [{"source_pdf": "scan-a", "filed": 0, "unfiled": 1, "total": 1}]
    on_disk = read_corrections(corpus.corrections_file("scan-a"))
    assert [c.category for c in on_disk.values()] == ["top"]


def test_an_unfiled_item_is_on_the_wall_again(running, corpus):
    """The manifest is what the wall reads, so undo is only real if `filed` clears."""
    running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i000", "category": "hat"}]})
    filed = {i["item_id"]: i["filed"] for i in running.get_json("/api/corpus")["items"]}
    assert filed["scan-a-p000-i000"] == {"category": "hat", "rejection": None}

    running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i000", "unfile": True}]})

    after = {i["item_id"]: i["filed"] for i in running.get_json("/api/corpus")["items"]}
    assert after["scan-a-p000-i000"] is None


def test_unfiling_something_never_filed_is_not_an_error(running, corpus):
    """Undo of a filing the server never received is the state the caller wanted."""
    status, _, payload = running.post_json(
        "/api/corrections", {"filings": [{"item_id": "scan-b-p000-i000", "unfile": True}]}
    )

    assert status == 200, payload
    assert payload["failed"] == []
    assert read_corrections(corpus.corrections_file("scan-b")) == {}


def test_an_unfile_carrying_a_verdict_is_refused_whole(running, corpus):
    """Filing and unfiling one item in one breath is a client bug, not a merge."""
    running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i000", "category": "hat"}]})
    before = corpus.corrections_file("scan-a").read_bytes()

    status, _, payload = running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i001", "category": "top"},
        {"item_id": "scan-a-p000-i000", "unfile": True, "category": "shoes"},
    ]})

    assert status == 400
    assert "scan-a-p000-i000" in payload["error"]
    assert corpus.corrections_file("scan-a").read_bytes() == before


def test_an_unfile_spanning_two_pdfs_touches_only_those_files(running, corpus):
    """Undo of a run crosses books the same way filing it did."""
    running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i000", "category": "hat"},
        {"item_id": "scan-b-p000-i000", "category": "wings"},
    ]})
    before = snapshot(corpus.sidecars, corpus.corrections, corpus.thumbs)

    status, _, payload = running.post_json("/api/corrections", {"filings": [
        {"item_id": "scan-a-p000-i000", "unfile": True},
        {"item_id": "scan-b-p000-i000", "unfile": True},
    ]})

    assert status == 200, payload
    assert [entry["source_pdf"] for entry in payload["written"]] == ["scan-a", "scan-b"]
    after = snapshot(corpus.sidecars, corpus.corrections, corpus.thumbs)
    changed = {path for path in set(before) | set(after) if before.get(path) != after.get(path)}
    assert changed == {corpus.corrections_file("scan-a"), corpus.corrections_file("scan-b")}
    assert read_corrections(corpus.corrections_file("scan-a")) == {}
