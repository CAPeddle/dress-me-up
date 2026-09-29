"""Browser scenarios for saved state (U5: R5, R17; KTD7).

One versioned localStorage key holds integer indices, positions, done marks and
name indices, written on every commit and read defensively.
"""

from __future__ import annotations

import json

import pytest

from tests.web.conftest import (
    STORE_KEY,
    body_box,
    center,
    open_game,
    place_from_supply,
    placed,
    raw_store,
    read_store,
    seed_store,
    show_body,
)

pytestmark = pytest.mark.browser

BUILD_ID = "fixture-0001"
ITEM_COUNT = 7  # the fixture catalog's item count; indices run 0..6


def strings_in(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings_in(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings_in(v)]
    return []


# ---------------------------------------------------------------- the store's shape

def test_store_holds_only_indices_positions_marks_and_name_indices(page, base_url):
    open_game(page, base_url)
    assert raw_store(page) is None  # nothing is written before a commit
    place_from_supply(page, 1, 2, 0.4, 0.3)
    store = read_store(page)
    assert set(store) == {"version", "build_id", "placements", "done", "names"}
    assert store["version"] == 1
    assert store["build_id"] == BUILD_ID
    assert len(store["placements"]) == 1
    p = store["placements"][0]
    assert set(p) == {"item", "body", "x", "y", "z"}
    assert p["item"] == 1 and p["body"] == 2
    assert isinstance(p["item"], int) and isinstance(p["body"], int) and isinstance(p["z"], int)
    assert abs(p["x"] - 0.4) < 0.01 and abs(p["y"] - 0.3) < 0.01
    assert store["done"] == [False, False, False]
    assert store["names"] == [-1, -1, -1]
    assert strings_in(store) == [BUILD_ID]
    assert page.evaluate("Object.keys(localStorage)") == [STORE_KEY]


def test_placement_survives_reload_at_the_same_address(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 3, 0, 0.5, 0.5)
    before = placed(page, 0, 3).bounding_box()
    page.reload()
    page.wait_for_selector("html[data-content='ready']")
    element = placed(page, 0, 3)
    assert element.count() == 1
    assert element.bounding_box() == before


def test_nothing_is_written_mid_drag(page, base_url):
    open_game(page, base_url)
    place_from_supply(page, 0, 0)
    stored = raw_store(page)
    x, y = center(placed(page, 0, 0).bounding_box())
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 80, y + 80, steps=8)
    assert raw_store(page) == stored
    page.mouse.up()
    assert raw_store(page) != stored


# ---------------------------------------------------------------- reading defensively

def test_invalid_json_in_the_store_loads_undressed_with_no_error(page, base_url, console_errors):
    seed_store(page, "{not json")
    open_game(page, base_url)
    assert page.get_attribute("html", "data-content") == "ready"
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert console_errors == []
    place_from_supply(page, 0, 0)
    assert read_store(page)["version"] == 1


def test_wrong_version_is_treated_as_fresh(page, base_url, console_errors):
    seed_store(page, json.dumps({
        "version": 2, "build_id": BUILD_ID,
        "placements": [{"item": 0, "body": 0, "x": 0.5, "y": 0.5, "z": 0}],
        "done": [True, False, False], "names": [3, -1, -1],
    }))
    open_game(page, base_url)
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert page.locator("[data-rig-stage='0'] [data-rig-kind='star']").get_attribute("aria-pressed") == "false"
    assert page.locator("[data-rig-stage='0'] .body-name").inner_text().strip() == ""
    assert console_errors == []


def test_foreign_build_id_is_treated_as_fresh(page, base_url, console_errors):
    seed_store(page, json.dumps({
        "version": 1, "build_id": "another-build-0007",
        "placements": [{"item": 0, "body": 0, "x": 0.5, "y": 0.5, "z": 0}],
        "done": [True, False, False], "names": [3, -1, -1],
    }))
    open_game(page, base_url)
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert page.locator("[data-rig-stage='0'] [data-rig-kind='star']").get_attribute("aria-pressed") == "false"
    assert console_errors == []


def test_an_item_index_past_the_catalog_is_treated_as_fresh(page, base_url, console_errors):
    """A catalog that shrank under an unchanged build id must not crash the boot.

    The build id alone cannot tell that item 9 is no longer served; without the
    bound, rendering the placement dies and the whole page falls to the content
    failure screen on every reload.
    """
    seed_store(page, json.dumps({
        "version": 1, "build_id": BUILD_ID,
        "placements": [{"item": ITEM_COUNT + 3, "body": 0, "x": 0.5, "y": 0.5, "z": 0}],
        "done": [True, False, False], "names": [3, -1, -1],
    }))
    open_game(page, base_url)
    assert page.get_attribute("html", "data-content") == "ready"
    assert page.locator("[data-rig-kind='placed']").count() == 0
    assert page.locator("[data-rig-stage='0'] [data-rig-kind='star']").get_attribute("aria-pressed") == "false"
    assert console_errors == []


def test_valid_seeded_store_is_rendered(page, base_url):
    seed_store(page, json.dumps({
        "version": 1, "build_id": BUILD_ID,
        "placements": [{"item": 3, "body": 1, "x": 0.5, "y": 0.5, "z": 0}],
        "done": [False, True, False], "names": [-1, 5, -1],
    }))
    open_game(page, base_url)
    show_body(page, 1)
    element = placed(page, 1, 3)
    assert element.count() == 1
    box = body_box(page, 1)
    cx, cy = center(element.bounding_box())
    assert abs(cx - (box["x"] + 0.5 * box["width"])) < 1.5
    assert abs(cy - (box["y"] + 0.5 * box["height"])) < 1.5
    assert page.locator("[data-rig-stage='1'] [data-rig-kind='star']").get_attribute("aria-pressed") == "true"
    assert page.locator("[data-rig-stage='1'] .body-name").inner_text().strip() != ""


def test_a_throwing_store_still_plays(page, base_url, console_errors):
    page.add_init_script(
        "Object.defineProperty(window, 'localStorage', { get() { throw new Error('storage disabled'); } });"
    )
    open_game(page, base_url)
    assert page.get_attribute("html", "data-content") == "ready"
    place_from_supply(page, 0, 0)
    assert placed(page, 0, 0).count() == 1
    assert console_errors == []


# ---------------------------------------------------------------- done and name

def test_done_mark_survives_reload_and_a_second_tap_clears_it(page, base_url):
    open_game(page, base_url)
    star = page.locator("[data-rig-stage='0'] [data-rig-kind='star']")
    star.click()
    assert star.get_attribute("aria-pressed") == "true"
    assert read_store(page)["done"] == [True, False, False]
    page.reload()
    page.wait_for_selector("html[data-content='ready']")
    star = page.locator("[data-rig-stage='0'] [data-rig-kind='star']")
    assert star.get_attribute("aria-pressed") == "true"
    assert page.locator("[data-rig-stage='0'].done").count() == 1
    star.click()
    assert star.get_attribute("aria-pressed") == "false"
    assert read_store(page)["done"] == [False, False, False]
    page.reload()
    page.wait_for_selector("html[data-content='ready']")
    assert page.locator("[data-rig-stage='0'] [data-rig-kind='star']").get_attribute("aria-pressed") == "false"


def test_name_choice_survives_reload_and_is_stored_as_an_index(page, base_url):
    open_game(page, base_url)
    page.locator("[data-rig-stage='0'] [data-rig-kind='name']").click()
    options = page.locator(".name-list .name-choice")
    chosen = options.nth(7).inner_text().strip()
    options.nth(7).click()
    assert page.locator("[data-rig-stage='0'] .body-name").inner_text().strip() == chosen
    store = read_store(page)
    assert store["names"] == [7, -1, -1]
    assert store["placements"] == [] and store["done"] == [False, False, False]
    assert chosen not in raw_store(page)
    page.reload()
    page.wait_for_selector("html[data-content='ready']")
    assert page.locator("[data-rig-stage='0'] .body-name").inner_text().strip() == chosen
    assert page.locator("[data-rig-stage='1'] .body-name").inner_text().strip() == ""


# ---------------------------------------------------------------- pure helpers

def test_serialize_and_deserialize_are_pure_and_strict(page, base_url):
    """The helpers need no DOM; they run in the page only because that is where ES modules load."""
    open_game(page, base_url)
    result = page.evaluate(
        """async ([buildId]) => {
            const store = await import("./js/store.js");
            const bounds = { buildId, bodyCount: 2, itemCount: 6 };
            const fresh = store.freshState({ buildId, bodyCount: 2 });
            fresh.placements.push({ item: 4, body: 1, x: -0.2, y: 1.3, z: 2 });
            fresh.done[1] = true;
            fresh.names[0] = 9;
            const text = store.serialize(fresh);
            const back = store.deserialize(text, bounds);
            const rejects = [
                "", "null", "[]", "{}", "{bad",
                JSON.stringify({ ...fresh, version: 0 }),
                JSON.stringify({ ...fresh, build_id: "other" }),
                JSON.stringify({ ...fresh, placements: [{ item: "hat_crown", body: 0, x: 0, y: 0, z: 0 }] }),
                JSON.stringify({ ...fresh, placements: [{ item: 1, body: 5, x: 0, y: 0, z: 0 }] }),
                JSON.stringify({ ...fresh, placements: [{ item: 6, body: 0, x: 0, y: 0, z: 0 }] }),
                JSON.stringify({ ...fresh, placements: [{ item: 99, body: 0, x: 0, y: 0, z: 0 }] }),
                JSON.stringify({ ...fresh, done: [true] }),
                JSON.stringify({ ...fresh, names: ["Lily", -1] }),
            ].map(t => store.deserialize(t, bounds));
            return { key: store.STORE_KEY, text, back, rejects, freshKeys: Object.keys(fresh) };
        }""",
        [BUILD_ID],
    )
    assert result["key"] == STORE_KEY
    assert result["freshKeys"] == ["version", "build_id", "placements", "done", "names"]
    assert json.loads(result["text"])["placements"] == [{"item": 4, "body": 1, "x": -0.2, "y": 1.3, "z": 2}]
    assert result["back"] == json.loads(result["text"])
    assert result["rejects"] == [None] * 13


def test_a_missing_bound_is_a_caller_error_not_a_fresh_state(page, base_url):
    """An absent bound must throw, not compare every index against undefined."""
    open_game(page, base_url)
    result = page.evaluate(
        """async ([buildId]) => {
            const store = await import("./js/store.js");
            const text = JSON.stringify({
                version: 1, build_id: buildId,
                placements: [{ item: 4, body: 0, x: 0, y: 0, z: 0 }],
                done: [false, false], names: [-1, -1],
            });
            const attempt = (fn) => {
                try {
                    fn();
                    return null;
                } catch (err) {
                    return { name: err.name, message: err.message };
                }
            };
            return {
                deserializeNoItemCount: attempt(() => store.deserialize(text, { buildId, bodyCount: 2 })),
                deserializeNoBodyCount: attempt(() => store.deserialize(text, { buildId, itemCount: 6 })),
                deserializeBadItemCount: attempt(
                    () => store.deserialize(text, { buildId, bodyCount: 2, itemCount: -1 })),
                loadNoItemCount: attempt(() => store.load({ buildId, bodyCount: 2 })),
            };
        }""",
        [BUILD_ID],
    )
    for key, thrown in result.items():
        assert thrown is not None, key
        assert thrown["name"] == "TypeError", (key, thrown)
    assert "itemCount" in result["deserializeNoItemCount"]["message"]
    assert "bodyCount" in result["deserializeNoBodyCount"]["message"]
    assert "itemCount" in result["deserializeBadItemCount"]["message"]
    assert "itemCount" in result["loadNoItemCount"]["message"]
