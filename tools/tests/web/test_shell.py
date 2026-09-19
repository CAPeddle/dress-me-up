"""Browser scenarios for the web shell, loaded through ``serve.py`` in headless Chromium."""

from __future__ import annotations

import json

import pytest

from tests.web.conftest import FIXTURE_ASSETS, PORTRAIT

pytestmark = pytest.mark.browser

CATALOG = json.loads((FIXTURE_ASSETS / "catalog.json").read_text())
BODIES = json.loads((FIXTURE_ASSETS / "bodies.json").read_text())


def open_game(page, url):
    page.goto(url)
    page.wait_for_selector("html[data-content='ready'], html[data-content='failed']")
    return page


# ---------------------------------------------------------------- happy path

def test_loads_one_body_per_entry_and_one_tile_per_item(page, base_url, console_errors):
    open_game(page, base_url)
    assert page.get_attribute("html", "data-content") == "ready"
    assert page.locator("[data-rig-kind='body']").count() == len(BODIES["bodies"])
    assert page.locator("[data-rig-kind='tile']").count() == len(CATALOG["items"])
    assert page.locator("[data-rig-kind='pager-thumb']").count() == len(BODIES["bodies"])
    assert console_errors == []


def test_module_script_executed_and_policy_applied(page, base_url):
    response = page.goto(base_url)
    assert "default-src 'none'" in response.headers.get("content-security-policy", "")
    page.wait_for_selector("html[data-content='ready']")
    assert page.evaluate("Boolean(document.querySelector('[data-rig-region=\"board\"]'))")
    meta = page.get_attribute("meta[http-equiv='Content-Security-Policy']", "content")
    assert meta == response.headers["content-security-policy"]


def test_images_carry_catalog_dimensions(page, base_url):
    open_game(page, base_url)
    first = CATALOG["items"][0]
    tile_img = page.locator("[data-rig-kind='tile'][data-rig-slot='0'] img")
    assert tile_img.get_attribute("width") == str(first["width"])
    assert tile_img.get_attribute("height") == str(first["height"])
    assert tile_img.get_attribute("src").endswith("assets/" + first["image"])
    assert tile_img.get_attribute("draggable") == "false"
    body_img = page.locator("[data-rig-kind='body'][data-rig-slot='0'] img")
    assert body_img.get_attribute("width") == str(BODIES["bodies"][0]["width"])
    assert body_img.get_attribute("src").endswith("assets/" + BODIES["bodies"][0]["image"])
    # Wait on the condition asserted, not on `complete`, which flips first.
    page.wait_for_function("[...document.images].every(i => i.complete && i.naturalWidth > 0)")


def test_supply_is_grouped_by_category_in_pipeline_order(page, base_url):
    open_game(page, base_url)
    groups = page.locator("[data-rig-region='supply'] [data-category]")
    names = [groups.nth(i).get_attribute("data-category") for i in range(groups.count())]
    present = {i["category"] for i in CATALOG["items"]}
    order = ["hat", "hair", "top", "bottom", "dress", "shoes", "weapon", "shield", "accessory", "wings", "mount"]
    assert names == [c for c in order if c in present]
    assert page.locator("[data-category='hat'] [data-rig-kind='tile']").count() == 2


def test_regions_and_hand_slots_exist(page, base_url):
    open_game(page, base_url)
    for region in ["board", "supply", "hand", "pager"]:
        assert page.locator(f"[data-rig-region='{region}']").count() == 1, region
    slots = page.locator("[data-rig-kind='hand-slot']")
    assert slots.count() >= 4
    assert [slots.nth(i).get_attribute("data-rig-slot") for i in range(slots.count())] == [
        str(i) for i in range(slots.count())
    ]
    assert page.locator("[data-rig-kind='hand-tile']").count() == 0


def test_rig_values_are_enumerated_kinds_and_integer_indices(page, base_url):
    open_game(page, base_url)
    kinds = set(page.eval_on_selector_all("[data-rig-kind]", "els => els.map(e => e.dataset.rigKind)"))
    assert kinds <= {"tile", "hand-slot", "hand-tile", "pager-thumb", "body", "star", "name"}
    slots = page.eval_on_selector_all("[data-rig-slot]", "els => els.map(e => e.dataset.rigSlot)")
    assert all(s.isdigit() for s in slots)
    stages = page.eval_on_selector_all("[data-rig-stage]", "els => els.map(e => e.dataset.rigStage)")
    assert sorted(int(s) for s in stages) == list(range(len(BODIES["bodies"])))
    everything = page.eval_on_selector_all(
        "*", "els => els.flatMap(e => [...e.attributes].filter(a => a.name.startsWith('data-rig-')).map(a => a.value))"
    )
    for value in everything:
        assert value.isdigit() or value in {"board", "supply", "hand", "pager"} or value in kinds, value


def test_tap_targets_are_large_enough(page, base_url):
    open_game(page, base_url)
    page.locator("[data-rig-kind='name']").first.click()  # open the name list too
    boxes = page.eval_on_selector_all(
        "[data-rig-kind], .name-choice, .name-close",
        "els => els.filter(e => e.getClientRects().length > 0)"
        "  .map(e => { const r = e.getBoundingClientRect(); return [e.dataset.rigKind || e.className, r.width, r.height]; })",
    )
    seen = {kind for kind, _, _ in boxes}
    assert {"tile", "pager-thumb", "hand-slot", "star", "name", "name-choice", "name-close"} <= seen, seen
    for kind, w, h in boxes:
        if kind == "body":
            continue
        minimum = 96 if kind in ("tile", "pager-thumb") else 56
        assert w >= minimum and h >= minimum, (kind, w, h)


def test_no_text_input_and_gesture_suppression(page, base_url):
    open_game(page, base_url)
    assert page.locator("input, textarea, [contenteditable]").count() == 0
    root = page.evaluate("getComputedStyle(document.documentElement)")
    body = page.evaluate("getComputedStyle(document.body)")
    assert (root.get("overscrollBehavior") or body.get("overscrollBehavior")) == "none"
    assert page.evaluate("getComputedStyle(document.body).userSelect") == "none"
    viewport = page.get_attribute("meta[name='viewport']", "content")
    assert "user-scalable=no" in viewport
    assert page.evaluate("[...document.images].every(i => i.getAttribute('draggable') === 'false')")
    supply = page.evaluate("getComputedStyle(document.querySelector('[data-rig-region=\"supply\"] .supply-scroll')).touchAction")
    assert supply in ("pan-x", "pan-y")


# ---------------------------------------------------------------- interactions

def test_pager_thumb_brings_that_body_into_view(page, base_url):
    open_game(page, base_url)
    stages = page.locator("[data-rig-stage]")
    assert stages.nth(0).is_visible()
    assert not stages.nth(2).is_visible()
    page.locator("[data-rig-kind='pager-thumb'][data-rig-slot='2']").click()
    assert stages.nth(2).is_visible()
    assert not stages.nth(0).is_visible()
    assert page.locator("[data-rig-kind='pager-thumb'][data-rig-slot='2']").get_attribute("aria-current") == "true"


def test_star_toggles_done(page, base_url):
    open_game(page, base_url)
    star = page.locator("[data-rig-stage='0'] [data-rig-kind='star']")
    assert star.get_attribute("aria-pressed") == "false"
    star.click()
    assert star.get_attribute("aria-pressed") == "true"
    assert page.locator("[data-rig-stage='0'].done").count() == 1
    star.click()
    assert star.get_attribute("aria-pressed") == "false"
    assert page.locator("[data-rig-stage='0'].done").count() == 0
    # done is per body
    page.locator("[data-rig-kind='pager-thumb'][data-rig-slot='1']").click()
    assert page.locator("[data-rig-stage='1'] [data-rig-kind='star']").get_attribute("aria-pressed") == "false"


def test_choosing_a_name_shows_it_and_closes_the_list(page, base_url):
    open_game(page, base_url)
    opener = page.locator("[data-rig-stage='0'] [data-rig-kind='name']").first
    opener.click()
    options = page.locator(".name-list button")
    assert page.locator(".name-list").is_visible()
    assert options.count() >= 20
    chosen = options.nth(3).inner_text().strip()
    options.nth(3).click()
    assert not page.locator(".name-list").is_visible()
    assert page.locator("[data-rig-stage='0'] .body-name").inner_text().strip() == chosen
    assert page.locator("[data-rig-stage='1'] .body-name").inner_text().strip() != chosen


# ---------------------------------------------------------------- orientation

def test_portrait_shows_turn_prompt_and_hides_game(page, base_url):
    open_game(page, base_url)
    assert page.locator(".turn").is_hidden()
    page.set_viewport_size(PORTRAIT)
    assert page.locator(".turn").is_visible()
    assert page.locator("#game").is_hidden()
    box = page.locator(".turn .turn-glyph").bounding_box()
    assert box["width"] >= 96 and box["height"] >= 96
    page.set_viewport_size({"width": 1280, "height": 800})
    assert page.locator(".turn").is_hidden()
    assert page.locator("#game").is_visible()


# ---------------------------------------------------------------- content errors

def test_mismatched_build_ids_show_rebuild_message_and_no_board(page, server_factory, assets_copy, console_errors):
    bodies = json.loads((assets_copy / "bodies.json").read_text())
    bodies["build_id"] = "fixture-0002"
    (assets_copy / "bodies.json").write_text(json.dumps(bodies))
    site = server_factory(assets_copy)
    open_game(page, site.url)
    assert page.get_attribute("html", "data-content") == "failed"
    message = page.locator(".content-message")
    assert message.is_visible()
    assert "rebuil" in message.inner_text().lower()
    assert page.locator("[data-rig-region='board']").count() == 0
    assert page.locator("[data-rig-kind='body']").count() == 0
    assert not any("Uncaught" in e for e in console_errors)


def test_missing_bodies_file_shows_rebuild_message_not_a_blank_page(page, server_factory, assets_copy):
    (assets_copy / "bodies.json").unlink()
    site = server_factory(assets_copy)
    open_game(page, site.url)
    assert page.get_attribute("html", "data-content") == "failed"
    assert page.locator(".content-message").is_visible()
    assert "rebuil" in page.locator(".content-message").inner_text().lower()
    assert page.locator("[data-rig-region='board']").count() == 0


def test_empty_item_list_still_renders_bodies(page, server_factory, assets_copy):
    catalog = json.loads((assets_copy / "catalog.json").read_text())
    catalog["items"] = []
    (assets_copy / "catalog.json").write_text(json.dumps(catalog))
    site = server_factory(assets_copy)
    open_game(page, site.url)
    assert page.get_attribute("html", "data-content") == "ready"
    assert page.locator("[data-rig-kind='body']").count() == len(BODIES["bodies"])
    assert page.locator("[data-rig-kind='tile']").count() == 0
    assert page.locator("[data-rig-region='supply']").count() == 1
