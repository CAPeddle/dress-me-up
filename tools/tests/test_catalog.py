import json

from PIL import Image

from dressup_pipeline.catalog import build_catalog, downsample
from conftest import make_item_image


ACCEPTED = dict(category="hat", group="fantasy", quality=0.95, accepted=True)


def test_downsample_fits_the_box_and_preserves_aspect():
    result = downsample(Image.new("RGBA", (2000, 1000)), max_px=512)

    assert result.size == (512, 256)


def test_downsample_never_upscales():
    result = downsample(Image.new("RGBA", (100, 80)), max_px=512)

    assert result.size == (100, 80)


def test_writes_accepted_items_and_their_images(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([{"item_id": "a", **ACCEPTED}, {"item_id": "b", **ACCEPTED}])
    assets = tmp_path / "assets"

    summary = build_catalog(root, assets, min_quality=0.90)

    catalog = json.loads((assets / "catalog.json").read_text())
    assert summary.written == 2
    assert [item["id"] for item in catalog["items"]] == ["a", "b"]
    assert (assets / "items" / "a.png").exists()


def test_items_are_sorted_by_id_regardless_of_disk_order(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([{"item_id": n, **ACCEPTED} for n in ("c", "a", "b")])

    build_catalog(root, tmp_path / "assets", min_quality=0.90)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert [item["id"] for item in catalog["items"]] == ["a", "b", "c"]


def test_min_quality_filters_and_the_reason_is_reported(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([
        {"item_id": "good", **ACCEPTED},
        {"item_id": "weak", **{**ACCEPTED, "quality": 0.72}},
    ])

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90)

    assert summary.written == 1
    assert summary.skipped["below --min-quality 0.9"] == 1


def test_group_filter_restricts_the_build(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([
        {"item_id": "f", **ACCEPTED},
        {"item_id": "k", **{**ACCEPTED, "group": "knight"}},
    ])

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90, groups={"knight"})

    assert summary.written == 1
    assert summary.by_group == {"knight": 1}
    assert summary.skipped["group not selected"] == 1


def test_unclassified_and_unscored_items_are_skipped_with_distinct_reasons(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([
        {"item_id": "raw"},
        {"item_id": "classified-only", "category": "hat", "group": "fantasy"},
        {"item_id": "rejected", **{**ACCEPTED, "accepted": False}},
    ])

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90)

    assert summary.written == 0
    assert summary.skipped == {"not classified": 1, "QA not run": 1, "rejected by QA": 1}


def test_missing_image_is_skipped_rather_than_crashing_the_build(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([{"item_id": "a", **ACCEPTED}])
    (root / "a.png").unlink()

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90)

    assert summary.written == 0
    assert summary.skipped["image missing on disk"] == 1


def test_catalog_records_the_post_downsample_dimensions(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([{"item_id": "big", **ACCEPTED, "size": (1200, 800)}])

    build_catalog(root, tmp_path / "assets", min_quality=0.90, max_px=512)

    item = json.loads((tmp_path / "assets" / "catalog.json").read_text())["items"][0]
    assert (item["width"], item["height"]) == (512, 341)


def test_empty_corpus_still_writes_a_valid_catalog(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert summary.written == 0
    assert catalog["items"] == []
    assert catalog["version"] == 1
