"""Browser scenarios for the wall client, served by `correct_server.py` in Chromium.

What is pinned here is the half hour at the desk: a keystroke files what is
selected, the wall empties as the work is done, and nothing the person believed
was saved is lost between the keystroke and the disk. So the filing tests always
end at the correction file rather than at the page's own count — the page's count
is the thing that could be lying.

The page is served from `tools/correct/`, never from a file URL, so the content
policy the tool runs under is the one exercised (as `tests/web` does for the web
version).
"""

from __future__ import annotations

import pytest

from dressup_pipeline.corrections import REJECTION_KINDS, read_corrections
from dressup_pipeline.models import CATEGORIES

from tests.correct.conftest import (
    BIG_COUNT,
    click_tile,
    legend,
    open_wall,
    rendered_items,
    status,
    tile,
    wait_for_file,
    wait_for_flush,
)

pytestmark = pytest.mark.browser


def filed_categories(corpus, stem: str) -> list[str | None]:
    return [c.category for c in read_corrections(corpus.corrections_file(stem)).values()]


def file_as(page, item_ids, action: str):
    """Select `item_ids` (a run, by shift-click) and file them under `action`."""
    for index, item_id in enumerate(item_ids):
        click_tile(page, item_id, shift=index > 0)
    page.keyboard.press(legend(page)[action])


# ---------------------------------------------------------------- the wall itself

def test_the_whole_corpus_is_one_wall_including_what_qa_rejected(page, wall, corpus, console_errors):
    open_wall(page, wall.url)

    assert page.locator("[data-wall-kind='tile']").count() == len(corpus.items)
    assert status(page, "remaining") == len(corpus.items)
    # The QA-rejected item is on the wall too: all of the real rejections are for
    # being small, and a hair clip is legitimately small.
    assert tile(page, "scan-a-p001-i000").count() == 1
    assert console_errors == []


def test_the_wall_keeps_the_manifest_s_order_so_alike_items_sit_together(page, wall):
    manifest = wall.get_json("/api/corpus")
    open_wall(page, wall.url)

    assert rendered_items(page) == [record["item_id"] for record in manifest["items"]]
    suggestions = page.eval_on_selector_all(
        "[data-wall-kind='tile']", "els => els.map(e => e.dataset.wallSuggestion)"
    )
    assert suggestions == ["hat", "top", "wings", "none"]


def test_every_action_has_its_own_key_and_the_legend_lists_all_of_them(page, wall):
    open_wall(page, wall.url)
    keys = legend(page)

    for name in (*CATEGORIES, *REJECTION_KINDS, "undo", "enlarge", "filed"):
        assert name in keys, name
    assert len(set(keys.values())) == len(keys), keys
    kinds = dict(
        page.eval_on_selector_all(
            "[data-wall-kind='legend-entry']",
            "els => els.map(e => [e.dataset.wallAction, e.dataset.wallActionKind])",
        )
    )
    assert {kinds[name] for name in CATEGORIES} == {"category"}
    assert {kinds[name] for name in REJECTION_KINDS} == {"rejection"}
    assert kinds["undo"] == "command"


def test_the_page_s_policy_is_the_server_s_policy(page, wall, correct):
    response = page.goto(wall.url)
    meta = page.get_attribute("meta[http-equiv='Content-Security-Policy']", "content")
    assert meta == correct.CONTENT_SECURITY_POLICY
    assert meta == response.headers["content-security-policy"]


def test_the_wall_s_data_hooks_are_a_closed_set_of_values(page, wall):
    open_wall(page, wall.url)
    page.keyboard.press(legend(page)["filed"])

    kinds = set(page.eval_on_selector_all("[data-wall-kind]", "els => els.map(e => e.dataset.wallKind)"))
    assert kinds <= {"tile", "filed-tile", "bucket", "legend-entry", "enlarged"}, kinds
    regions = set(page.eval_on_selector_all("[data-wall-region]", "els => els.map(e => e.dataset.wallRegion)"))
    assert regions <= {"header", "legend", "wall", "status", "message", "enlarge", "filed"}, regions
    assert page.get_attribute("html", "data-wall") in {"loading", "ready", "failed"}
    selected = set(page.eval_on_selector_all("[data-wall-selected]", "els => els.map(e => e.dataset.wallSelected)"))
    assert selected <= {"true", "false"}, selected
    suggestions = set(
        page.eval_on_selector_all("[data-wall-suggestion]", "els => els.map(e => e.dataset.wallSuggestion)")
    )
    assert suggestions <= {*CATEGORIES, "none"}, suggestions


# ---------------------------------------------------------------- filing

def test_filing_an_item_takes_it_off_the_wall_and_decrements_the_count(page, wall, corpus):
    open_wall(page, wall.url)
    before = status(page, "remaining")

    file_as(page, ["scan-a-p000-i000"], "shoes")

    assert tile(page, "scan-a-p000-i000").count() == 0
    assert status(page, "remaining") == before - 1
    wait_for_flush(page)
    assert filed_categories(corpus, "scan-a") == ["shoes"]


def test_a_welded_pair_filed_under_a_category_is_a_category_filing(page, wall, corpus):
    """AE7: a cutout holding a pair of boots that reads as one item."""
    open_wall(page, wall.url)

    file_as(page, ["scan-a-p000-i000"], "shoes")
    wait_for_flush(page)

    filed = list(read_corrections(corpus.corrections_file("scan-a")).values())
    assert len(filed) == 1
    assert filed[0].category == "shoes"
    assert filed[0].rejection is None
    assert filed[0].rejected is False


def test_each_rejection_kind_is_recorded_distinctly(page, wall, corpus):
    """AE6: the repair queue can tell a multi-item cutout from a bad crop."""
    open_wall(page, wall.url)

    file_as(page, ["scan-a-p000-i000"], "bad_crop")
    file_as(page, ["scan-a-p000-i001"], "multi_item")
    file_as(page, ["scan-a-p001-i000"], "not_an_item")
    wait_for_flush(page)

    filed = read_corrections(corpus.corrections_file("scan-a"))
    assert len(filed) == 3
    by_bbox = {c.bbox.as_tuple(): (c.category, c.rejection) for c in filed.values()}
    assert by_bbox == {
        (120, 240, 160, 200): (None, "bad_crop"),
        (400, 240, 180, 320): (None, "multi_item"),
        (90, 1100, 110, 170): (None, "not_an_item"),
    }


def test_a_run_is_selected_by_shift_click_and_filed_in_one_action(page, wall, corpus):
    open_wall(page, wall.url)

    click_tile(page, "scan-a-p000-i000")
    click_tile(page, "scan-a-p000-i001", shift=True)
    assert page.locator("[data-wall-selected='true']").count() == 2
    page.keyboard.press(legend(page)["hat"])

    assert status(page, "remaining") == len(corpus.items) - 2
    wait_for_flush(page)
    assert filed_categories(corpus, "scan-a") == ["hat", "hat"]


def test_a_selection_spanning_two_pdfs_writes_to_both_correction_files(page, wall, corpus):
    manifest = wall.get_json("/api/corpus")
    order = [record["item_id"] for record in manifest["items"]]
    open_wall(page, wall.url)

    file_as(page, order, "accessory")

    assert status(page, "remaining") == 0
    wait_for_flush(page)
    assert len(read_corrections(corpus.corrections_file("scan-a"))) == 3
    assert len(read_corrections(corpus.corrections_file("scan-b"))) == 1


def test_a_keystroke_with_nothing_selected_files_nothing(page, wall, corpus):
    open_wall(page, wall.url)

    page.keyboard.press(legend(page)["hat"])

    assert status(page, "remaining") == len(corpus.items)
    assert status(page, "queued") == 0
    assert not corpus.corrections_file("scan-a").exists()


# ---------------------------------------------------------------- resuming

def test_a_reload_after_filing_shows_exactly_the_unfiled_items(page, wall, corpus):
    """AE5: a pass interrupted partway does not re-present what was filed."""
    open_wall(page, wall.url)
    file_as(page, ["scan-a-p000-i000", "scan-a-p000-i001"], "hat")
    wait_for_flush(page)

    open_wall(page, wall.url)

    assert sorted(rendered_items(page)) == ["scan-a-p001-i000", "scan-b-p000-i000"]
    assert status(page, "remaining") == 2
    assert status(page, "filed") == 2


def test_a_finished_pass_is_an_empty_wall(page, wall, corpus):
    wall.post_json(
        "/api/corrections",
        {"filings": [{"item_id": item_id, "category": "hat"} for item_id in corpus.items]},
    )

    open_wall(page, wall.url)

    assert page.locator("[data-wall-kind='tile']").count() == 0
    assert status(page, "remaining") == 0
    message = page.locator("[data-wall-region='message']")
    assert message.is_visible()
    assert message.get_attribute("data-wall-empty") == "finished"


def test_an_empty_corpus_is_an_empty_wall_not_a_broken_page(page, server_factory, empty_corpus, console_errors):
    site = server_factory(empty_corpus)
    open_wall(page, site.url)

    assert page.get_attribute("html", "data-wall") == "ready"
    assert status(page, "remaining") == 0
    assert page.locator("[data-wall-region='message']").get_attribute("data-wall-empty") == "corpus"
    assert console_errors == []


def test_a_manifest_that_fails_to_load_says_so_rather_than_showing_a_blank_wall(page, wall, corpus):
    corpus.corrections_file("scan-a").write_text('{"corrections": [{"page": 0}]}', encoding="utf-8")

    open_wall(page, wall.url)

    assert page.get_attribute("html", "data-wall") == "failed"
    assert page.locator("[data-wall-region='message']").is_visible()
    assert page.locator("[data-wall-kind='tile']").count() == 0


# ---------------------------------------------------------------- undo and re-filing

def test_undoing_a_run_returns_every_item_and_removes_their_records(page, wall, corpus):
    manifest = wall.get_json("/api/corpus")
    order = [record["item_id"] for record in manifest["items"]]
    open_wall(page, wall.url)

    # The first three of the wall span both books, so the undo has to reach both.
    file_as(page, order[:3], "wings")
    wait_for_flush(page)
    assert len(read_corrections(corpus.corrections_file("scan-a"))) == 2
    assert len(read_corrections(corpus.corrections_file("scan-b"))) == 1

    page.keyboard.press(legend(page)["undo"])

    assert status(page, "remaining") == len(corpus.items)
    assert rendered_items(page) == order
    wait_for_flush(page)
    assert read_corrections(corpus.corrections_file("scan-a")) == {}
    assert read_corrections(corpus.corrections_file("scan-b")) == {}


def test_undoing_before_the_batch_flushes_leaves_nothing_written_at_all(page, wall, corpus):
    """A filing and its undo can share one batch, and the server applies filings
    after it pops withdrawals — so the open batch is keyed by item and the later
    verdict replaces the earlier one rather than queueing behind it.
    """
    open_wall(page, wall.url)

    file_as(page, ["scan-a-p000-i000"], "hat")
    assert status(page, "queued") == 1, "the batch flushed on its own; the test proves nothing"
    page.keyboard.press(legend(page)["undo"])
    wait_for_flush(page)

    assert read_corrections(corpus.corrections_file("scan-a")) == {}
    assert tile(page, "scan-a-p000-i000").count() == 1
    assert status(page, "remaining") == len(corpus.items)


def test_a_filed_item_can_be_found_in_the_filed_view_and_refiled(page, wall, corpus):
    open_wall(page, wall.url)
    file_as(page, ["scan-a-p000-i000"], "hat")
    wait_for_flush(page)

    page.keyboard.press(legend(page)["filed"])
    filed_view = page.locator("[data-wall-region='filed']")
    assert filed_view.is_visible()
    assert filed_view.locator("[data-wall-bucket='hat'] [data-wall-kind='filed-tile']").count() == 1
    filed_view.locator("[data-wall-item='scan-a-p000-i000']").click()
    page.keyboard.press(legend(page)["shoes"])
    wait_for_flush(page)

    filed = list(read_corrections(corpus.corrections_file("scan-a")).values())
    assert len(filed) == 1
    assert filed[0].category == "shoes"
    assert tile(page, "scan-a-p000-i000").count() == 0


# ---------------------------------------------------------------- judging an item

def test_the_focused_item_is_enlarged_to_its_cutout_without_leaving_the_wall(page, wall):
    open_wall(page, wall.url)
    keys = legend(page)

    click_tile(page, "scan-a-p001-i000")
    page.keyboard.press(keys["enlarge"])

    enlarge = page.locator("[data-wall-region='enlarge']")
    assert enlarge.is_visible()
    src = enlarge.locator("[data-wall-kind='enlarged']").get_attribute("src")
    assert src.endswith("/item/scan-a-p001-i000")
    # The wall is behind it, not replaced by it: the pass does not lose its place.
    assert page.locator("[data-wall-kind='tile']").count() == 4
    page.keyboard.press("Escape")
    assert enlarge.is_hidden()


# ---------------------------------------------------------------- windowing (KTD8)

def test_the_wall_windows_a_corpus_several_times_the_real_one(page, server_factory, big_corpus):
    site = server_factory(big_corpus)
    thumbs = []
    page.on("request", lambda request: thumbs.append(request.url) if "/thumb/" in request.url else None)

    open_wall(page, site.url)

    assert status(page, "remaining") == BIG_COUNT
    rendered = page.locator("[data-wall-kind='tile'] img").count()
    assert 0 < rendered < BIG_COUNT // 4, rendered
    assert len(thumbs) < BIG_COUNT // 4, len(thumbs)

    # One continuous list, not pages: the end of it is reachable by scrolling, and
    # no intermediate state of the scroll is an empty wall reading as a finished pass.
    manifest = site.get_json("/api/corpus")
    last = manifest["items"][-1]["item_id"]
    assert tile(page, last).count() == 0
    page.eval_on_selector("[data-wall-region='wall']", "el => { el.scrollTop = el.scrollHeight; }")
    tile(page, last).wait_for()
    assert status(page, "remaining") == BIG_COUNT
    assert page.locator("[data-wall-kind='tile'] img").count() < BIG_COUNT // 4


# ---------------------------------------------------------------- the write reaching disk

def test_a_batch_still_queued_is_flushed_when_the_page_goes_away(page, wall, corpus):
    """An item leaves the wall when filed, so an unflushed batch is work believed saved."""
    open_wall(page, wall.url)

    file_as(page, ["scan-a-p000-i000"], "dress")
    assert status(page, "queued") == 1, "the batch flushed on its own; the test proves nothing"

    page.goto("about:blank")

    assert wait_for_file(corpus.corrections_file("scan-a")), "the queued batch never reached disk"
    assert filed_categories(corpus, "scan-a") == ["dress"]


def test_a_failed_write_leaves_the_items_on_the_wall_and_says_so(page, wall, corpus):
    open_wall(page, wall.url)
    # Broken after the manifest loaded, so the failure is the write's own: this is
    # the realistic one, a hand edit that broke the JSON mid-sitting.
    corpus.corrections_file("scan-a").write_text("{ not json", encoding="utf-8")

    file_as(page, ["scan-a-p000-i000", "scan-a-p000-i001"], "top")

    message = page.locator("[data-wall-region='message']")
    message.wait_for()
    assert message.get_attribute("data-wall-failed") == "write"
    assert tile(page, "scan-a-p000-i000").count() == 1
    assert tile(page, "scan-a-p000-i001").count() == 1
    assert status(page, "remaining") == len(corpus.items)
