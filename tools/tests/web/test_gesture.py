"""Browser scenarios for the placement engine and the hand (U5: R3, R4, R5, R15, R16; KTD6).

Single-pointer gestures use Playwright's mouse, which emits real pointer events.
Multi-pointer and cancel cases dispatch PointerEvents carrying their own pointer
ids (KTD10).
"""

from __future__ import annotations

import json

import pytest

from tests.web.conftest import (
    FIXTURE_ASSETS,
    body_box,
    center,
    drag,
    open_game,
    place_from_supply,
    placed,
    pointer,
    read_store,
    show_body,
    tap_tile,
)

pytestmark = pytest.mark.browser

CATALOG = json.loads((FIXTURE_ASSETS / "catalog.json").read_text())
BODIES = json.loads((FIXTURE_ASSETS / "bodies.json").read_text())

HAND_TILES = "[data-rig-region='hand'] [data-rig-kind='hand-tile']"


def hand_items(page):
    return [int(s) for s in page.eval_on_selector_all(HAND_TILES, "els => els.map(e => e.dataset.rigSlot)")]


def approx(a, b, tol=1.5):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- hand and placing

def test_tap_two_items_then_body_places_first_at_tap_point_and_keeps_second(page, base_url, console_errors):
    """AE3."""
    open_game(page, base_url)
    tap_tile(page, 0)
    tap_tile(page, 3)
    assert hand_items(page) == [0, 3]
    show_body(page, 1)
    assert hand_items(page) == [0, 3]
    box = body_box(page, 1)
    x, y = box["x"] + 0.5 * box["width"], box["y"] + 0.15 * box["height"]
    page.mouse.click(x, y)
    element = placed(page, 1, 0)
    element.wait_for()
    cx, cy = center(element.bounding_box())
    assert approx(cx, x) and approx(cy, y), (cx, cy, x, y)
    assert hand_items(page) == [3]
    assert placed(page, 0, 0).count() == 0
    assert console_errors == []


def test_tap_on_body_with_empty_hand_places_nothing(page, base_url):
    open_game(page, base_url)
    box = body_box(page, 0)
    page.mouse.click(*center(box))
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert read_store(page) is None


def test_full_hand_ignores_a_seventh_tap(page, base_url):
    open_game(page, base_url)
    for _ in range(6):
        tap_tile(page, 2)
    assert hand_items(page) == [2] * 6
    tap_tile(page, 4)
    assert hand_items(page) == [2] * 6
    assert page.locator("[data-rig-kind='hand-slot']").count() == 6


def test_tap_on_hand_tile_returns_it_to_the_supply(page, base_url):
    open_game(page, base_url)
    tap_tile(page, 0)
    tap_tile(page, 1)
    page.locator(f"{HAND_TILES}[data-rig-slot='0']").click()
    assert hand_items(page) == [1]


def test_pager_thumb_brings_body_into_view_with_hand_unchanged(page, base_url):
    open_game(page, base_url)
    tap_tile(page, 1)
    tap_tile(page, 5)
    show_body(page, 2)
    assert page.locator("[data-rig-stage='2']").is_visible()
    assert not page.locator("[data-rig-stage='0']").is_visible()
    assert hand_items(page) == [1, 5]


def test_held_pointer_past_the_tap_window_adds_nothing(page, base_url):
    open_game(page, base_url)
    tile = page.locator("[data-rig-kind='tile'][data-rig-slot='0']")
    page.mouse.move(*center(tile.bounding_box()))
    page.mouse.down()
    page.wait_for_timeout(600)  # past the 400 ms tap window on purpose
    page.mouse.up()
    assert hand_items(page) == []
    # the engine is free again: a normal tap still works
    tap_tile(page, 0)
    assert hand_items(page) == [0]


# ---------------------------------------------------------------- swipes are not taps

def test_swipe_across_supply_adds_nothing_and_swipe_on_body_neither_pages_nor_places(page, base_url):
    open_game(page, base_url)
    tile = page.locator("[data-rig-kind='tile'][data-rig-slot='0']")
    x, y = center(tile.bounding_box())
    drag(page, (x, y), (x, y - 80))
    assert hand_items(page) == []
    tap_tile(page, 0)
    assert hand_items(page) == [0]
    bx, by = center(body_box(page, 0))
    drag(page, (bx, by), (bx + 200, by))
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert page.locator("[data-rig-stage='0']").is_visible()
    assert hand_items(page) == [0]
    assert read_store(page) is None


# ---------------------------------------------------------------- dragging placed items

def test_three_px_drag_on_placed_item_is_a_tap_and_does_nothing(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 0, 0)
    element = placed(page, 0, 0)
    before = element.bounding_box()
    store_before = read_store(page)
    x, y = center(before)
    drag(page, (x, y), (x + 3, y))
    assert element.bounding_box() == before
    assert read_store(page) == store_before


def test_drag_moves_item_and_commits_on_release(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 0, 0)
    element = placed(page, 0, 0)
    before = element.bounding_box()
    x, y = center(before)
    drag(page, (x, y), (x + 60, y + 40))
    after = element.bounding_box()
    assert approx(after["x"], before["x"] + 60) and approx(after["y"], before["y"] + 40)
    store = read_store(page)
    assert len(store["placements"]) == 1
    p = store["placements"][0]
    box = body_box(page, 0)
    assert approx(p["x"], (x + 60 - box["x"]) / box["width"], 0.01)
    assert approx(p["y"], (y + 40 - box["y"]) / box["height"], 0.01)


def test_pointercancel_mid_drag_reverts_and_store_is_unchanged(page, base_url):
    """AE8."""
    open_game(page, base_url)
    place_from_supply(page, 0, 0)
    element = placed(page, 0, 0)
    before = element.bounding_box()
    store_before = read_store(page)
    x, y = center(before)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 120, y + 30, steps=6)
    moved = element.bounding_box()
    assert approx(moved["x"], before["x"] + 120), (moved, before)
    pointer(page, "pointercancel", 1, x + 120, y + 30, selector="[data-rig-kind='placed']")
    assert element.bounding_box() == before
    assert read_store(page) == store_before
    page.mouse.up()
    assert element.bounding_box() == before
    assert read_store(page) == store_before


def test_second_pointer_during_drag_is_ignored_and_first_drag_still_commits(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 0, 0, 0.5, 0.2)
    place_from_supply(page, 4, 0, 0.5, 0.9)
    first = placed(page, 0, 0)
    second = placed(page, 0, 4)
    first_before = first.bounding_box()
    second_before = second.bounding_box()
    fx, fy = center(first_before)
    sx, sy = center(second_before)
    page.mouse.move(fx, fy)
    page.mouse.down()
    page.mouse.move(fx + 50, fy, steps=5)
    # a second finger lands on the other item, drags, and lifts
    sel_second = "[data-rig-stage='0'] [data-rig-kind='placed'][data-rig-slot='4']"
    pointer(page, "pointerdown", 7, sx, sy, selector=sel_second)
    pointer(page, "pointermove", 7, sx + 200, sy - 100, selector=sel_second)
    pointer(page, "pointerup", 7, sx + 200, sy - 100, selector=sel_second)
    assert second.bounding_box() == second_before
    # and a stray move from the other id does not steer the live drag
    pointer(page, "pointermove", 7, fx + 300, fy + 300, selector="[data-rig-stage='0'] [data-rig-kind='placed'][data-rig-slot='0']")
    mid = first.bounding_box()
    assert approx(mid["x"], first_before["x"] + 50) and approx(mid["y"], first_before["y"])
    page.mouse.up()
    after = first.bounding_box()
    assert approx(after["x"], first_before["x"] + 50) and approx(after["y"], first_before["y"])
    assert second.bounding_box() == second_before
    store = read_store(page)
    assert sorted(p["item"] for p in store["placements"]) == [0, 4]


def test_release_off_body_stays_and_release_on_another_item_stacks_above(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 0, 0, 0.5, 0.1)
    crown = placed(page, 0, 0)
    box = body_box(page, 0)
    board = page.locator("[data-rig-region='board']").bounding_box()
    # off the body but on the board: left of the body image, mid height
    target_x = (board["x"] + box["x"]) / 2
    target_y = box["y"] + 0.5 * box["height"]
    x, y = center(crown.bounding_box())
    drag(page, (x, y), (target_x, target_y))
    cx, cy = center(crown.bounding_box())
    assert approx(cx, target_x) and approx(cy, target_y)
    p = read_store(page)["placements"][0]
    assert p["x"] < 0
    # now a gown placed on the body, then the crown dragged onto it stacks above
    place_from_supply(page, 3, 0, 0.5, 0.5)
    gown = placed(page, 0, 3)
    gx, gy = center(gown.bounding_box())
    drag(page, (cx, cy), (gx, gy))
    top = page.evaluate("([x, y]) => document.elementFromPoint(x, y).dataset.rigSlot", [gx, gy])
    assert top == "0"
    store = read_store(page)
    z = {p["item"]: p["z"] for p in store["placements"]}
    assert z[0] > z[3]
    # the reverse: gown dragged onto the crown goes above it
    drag(page, (gx + 40, gy + 120), (gx + 40, gy + 120 + 5))
    drag(page, (gx, gy + 150), (gx, gy + 150 + 20))
    top = page.evaluate("([x, y]) => document.elementFromPoint(x, y).dataset.rigSlot", [gx, gy + 20])
    assert top == "3"


# ---------------------------------------------------------------- taking items off (R5)

def test_release_over_hand_moves_item_into_hand(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 2, 0)
    element = placed(page, 0, 2)
    hand = page.locator("[data-rig-region='hand']").bounding_box()
    drag(page, center(element.bounding_box()), center(hand))
    assert placed(page, 0, 2).count() == 0
    assert hand_items(page) == [2]
    assert read_store(page)["placements"] == []
    # and it can go onto another body
    show_body(page, 2)
    page.mouse.click(*center(body_box(page, 2)))
    assert placed(page, 2, 2).count() == 1
    assert hand_items(page) == []


def test_release_over_supply_removes_the_placement(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 5, 0)
    element = placed(page, 0, 5)
    supply = page.locator("[data-rig-region='supply']").bounding_box()
    drag(page, center(element.bounding_box()), center(supply))
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert hand_items(page) == []
    assert read_store(page)["placements"] == []


# ---------------------------------------------------------------- scale (R4)

def test_item_scales_by_displayed_over_recorded_body_height_not_the_build_target(page, server_factory, assets_copy):
    bodies = json.loads((assets_copy / "bodies.json").read_text())
    bodies["bodies"][0]["height"] = 512
    bodies["scale"]["target_body_height_px"] = 900
    (assets_copy / "bodies.json").write_text(json.dumps(bodies))
    catalog = json.loads((assets_copy / "catalog.json").read_text())
    catalog["items"][0]["height"] = 300
    catalog["items"][0]["width"] = 120
    catalog["scale"]["target_body_height_px"] = 900
    (assets_copy / "catalog.json").write_text(json.dumps(catalog))
    site = server_factory(assets_copy)
    open_game(page, site.url)
    place_from_supply(page, 0, 0)
    displayed = body_box(page, 0)["height"]
    assert displayed > 400
    box = placed(page, 0, 0).bounding_box()
    assert approx(box["height"], 300 * displayed / 512, 1.0), (box, displayed)
    assert approx(box["width"], 120 * displayed / 512, 1.0)
    assert not approx(box["height"], 300 * displayed / 900, 5.0)


def test_crown_and_gown_keep_their_page_proportions(page, base_url):
    """AE2 on fixture content: sizes follow the catalog, not the tile."""
    open_game(page, base_url)
    place_from_supply(page, 0, 0, 0.5, 0.1)
    place_from_supply(page, 3, 0, 0.5, 0.6)
    crown = placed(page, 0, 0).bounding_box()
    gown = placed(page, 0, 3).bounding_box()
    factor = body_box(page, 0)["height"] / BODIES["bodies"][0]["height"]
    assert approx(crown["width"], CATALOG["items"][0]["width"] * factor, 1.0)
    assert approx(gown["height"], CATALOG["items"][3]["height"] * factor, 1.0)
    assert gown["height"] / crown["height"] == pytest.approx(500 / 90, rel=0.02)


# The body image and the placed Item are read in the same tick: the viewport is
# resized before the resize handler relays the Item out, so waiting on the image
# alone can read a placement that has not caught up yet.
RELAID_OUT = """
([item, fx, fy, tol]) => {
    const img = document.querySelector("[data-rig-kind='body'][data-rig-slot='0'] > img");
    const node = document.querySelector(
        `[data-rig-stage='0'] [data-rig-kind='placed'][data-rig-slot='${item}']`);
    if (!img || !node) return false;
    const box = img.getBoundingClientRect();
    if (box.height >= 500) return false;   // the resize itself has not landed
    const r = node.getBoundingClientRect();
    return Math.abs(r.x + r.width / 2 - (box.x + fx * box.width)) <= tol
        && Math.abs(r.y + r.height / 2 - (box.y + fy * box.height)) <= tol;
}
"""


def test_placed_items_relayout_on_resize(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 0, 0, 0.5, 0.25)
    page.set_viewport_size({"width": 1024, "height": 640})
    page.wait_for_function(RELAID_OUT, arg=[0, 0.5, 0.25, 2.0])
    box = body_box(page, 0)
    cx, cy = center(placed(page, 0, 0).bounding_box())
    assert approx(cx, box["x"] + 0.5 * box["width"], 2.0)
    assert approx(cy, box["y"] + 0.25 * box["height"], 2.0)
    factor = box["height"] / BODIES["bodies"][0]["height"]
    assert approx(placed(page, 0, 0).bounding_box()["height"], 90 * factor, 1.0)


def test_resize_mid_drag_keeps_the_live_transform_and_commits_the_drag_delta(page, base_url):
    """A relayout must not wipe a live drag's transform: what is shown would stop
    following the finger, and the commit would still apply the whole delta."""
    open_game(page, base_url)
    place_from_supply(page, 0, 0, 0.5, 0.25)   # the crown, dragged
    place_from_supply(page, 4, 0, 0.5, 0.8)    # a bystander, proves the relayout ran
    dragged = placed(page, 0, 0)
    bystander = placed(page, 0, 4)
    before_dragged = dragged.bounding_box()
    before_bystander = bystander.bounding_box()
    x, y = center(before_dragged)
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 60, y + 40, steps=4)   # past the 12 px slop: the drag is live
    assert "translate" in dragged.evaluate("el => el.style.transform")

    page.set_viewport_size({"width": 1024, "height": 640})
    # The bystander is the signal: it is the element layoutPlaced does touch, so
    # once it has moved the resize handler has certainly run.
    page.wait_for_function(RELAID_OUT, arg=[4, 0.5, 0.8, 2.0])
    assert bystander.bounding_box()["height"] < before_bystander["height"]
    # ... and the live drag came through it with its transform intact.
    assert "translate" in dragged.evaluate("el => el.style.transform"), "relayout cleared a live drag"

    page.mouse.move(x + 60, y + 90, steps=4)
    page.mouse.up()
    # releasePlaced translates the placement by the drag delta against a fresh
    # frame, so the committed centre is the old fraction shifted by dx/dy over the
    # post-resize body box -- an Item is grabbed anywhere, not re-centred on the finger.
    assert placed(page, 0, 0).count() == 1, "the release fell outside the board region"
    box = body_box(page, 0)
    crown = next(p for p in read_store(page)["placements"] if p["item"] == 0)
    assert approx(crown["x"], 0.5 + 60 / box["width"], 0.01), (crown, box)
    assert approx(crown["y"], 0.25 + 90 / box["height"], 0.01), (crown, box)


# ---------------------------------------------------------------- integration

def test_tap_tap_page_tap_drag_reload(page, base_url, console_errors):
    open_game(page, base_url)
    tap_tile(page, 3)
    tap_tile(page, 0)
    show_body(page, 1)
    box = body_box(page, 1)
    page.mouse.click(box["x"] + 0.5 * box["width"], box["y"] + 0.55 * box["height"])
    page.mouse.click(box["x"] + 0.5 * box["width"], box["y"] + 0.08 * box["height"])
    assert hand_items(page) == []
    crown = placed(page, 1, 0)
    cx, cy = center(crown.bounding_box())
    drag(page, (cx, cy), (cx + 30, cy + 10))
    gown_box = placed(page, 1, 3).bounding_box()
    crown_box = crown.bounding_box()
    page.reload()
    page.wait_for_selector("html[data-content='ready']")
    show_body(page, 1)
    assert placed(page, 1, 3).bounding_box() == gown_box
    assert placed(page, 1, 0).bounding_box() == crown_box
    assert page.locator("[data-rig-stage='0'] [data-rig-kind='placed']").count() == 0
    assert hand_items(page) == []  # the hand is her fingers, not the book
    assert console_errors == []
