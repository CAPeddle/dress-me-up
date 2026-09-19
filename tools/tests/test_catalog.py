import json

import pytest
from PIL import Image

from dressup_pipeline.bodies import BodyError
from dressup_pipeline.catalog import BodiesSource, build_catalog, new_build_id
from dressup_pipeline.triage import TRIAGE_DPI, Manifest, PageVerdict, manifest_path
from conftest import make_doll_page, make_item_image


ACCEPTED = dict(category="hat", group="fantasy", quality=0.95, accepted=True)
AT_72 = dict(ACCEPTED, dpi=72)


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


def test_catalog_records_the_dimensions_after_the_build_factor(tmp_path, sidecar_corpus):
    """With no bodies the Item ceiling is the only bound: 512/1200 for both edges."""
    root, _ = sidecar_corpus([{"item_id": "big", **ACCEPTED, "size": (1200, 800)}])

    build_catalog(root, tmp_path / "assets", min_quality=0.90)

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


# -- bodies beside the catalog ------------------------------------------------

DOLL_A = (260, 60, 340, 760)
DOLL_B = (170, 100, 250, 700)


@pytest.fixture
def body_book(tmp_path):
    """A two-page doll PDF under a source root, triaged, plus a body list naming both."""
    source = tmp_path / "source" / "Fantasy"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    first, second = make_doll_page(dolls=(DOLL_A,)), make_doll_page(dolls=(DOLL_B,))
    first.save(pdf, save_all=True, append_images=[second])

    triage = tmp_path / "triage"
    triage.mkdir()
    pages = [PageVerdict(page=i, rotation=0, verdict="base_body", confidence=0.9, reason="t") for i in range(2)]
    Manifest(pdf=pdf.name, source_folder="Fantasy", triage_dpi=TRIAGE_DPI, pages=pages).write(manifest_path(triage, pdf))

    def _list(bodies, name="bodies.json"):
        path = tmp_path / name
        path.write_text(json.dumps({"version": 1, "bodies": bodies}), encoding="utf-8")
        return path

    return dict(source=tmp_path / "source", triage=triage, write_list=_list)


TWO_BODIES = [
    {"id": "fantasy-book-p01", "pdf": "book.pdf", "page": 1, "group": "fantasy", "region": None},
    {"id": "fantasy-book-p00", "pdf": "book.pdf", "page": 0, "group": "fantasy", "region": None},
]


def test_build_id_is_fresh_each_time():
    a, b = new_build_id(), new_build_id()

    assert a and a != b


def test_catalog_without_a_body_list_gains_only_a_build_id(tmp_path, sidecar_corpus):
    root, _ = sidecar_corpus([{"item_id": "a", **ACCEPTED}])

    build_catalog(root, tmp_path / "assets", min_quality=0.90)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert set(catalog) == {"version", "min_quality", "items", "build_id", "scale"}
    assert not (tmp_path / "assets" / "bodies.json").exists()


def test_bodies_are_written_beside_the_catalog_in_list_order(tmp_path, sidecar_corpus, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])
    assets = tmp_path / "assets"

    summary = build_catalog(
        root, assets, min_quality=0.90,
        bodies=BodiesSource(body_book["write_list"](TWO_BODIES), body_book["source"], body_book["triage"]),
    )

    bodies = json.loads((assets / "bodies.json").read_text())
    catalog = json.loads((assets / "catalog.json").read_text())
    assert summary.bodies == 2
    assert "bodies: 2" in summary.as_report()
    assert bodies["version"] == 1
    assert bodies["build_id"] == catalog["build_id"]
    assert bodies["scale"] == catalog["scale"]
    assert [b["id"] for b in bodies["bodies"]] == ["fantasy-book-p01", "fantasy-book-p00"]
    assert set(bodies) == {"version", "build_id", "scale", "bodies"}
    assert set(bodies["bodies"][0]) == {"id", "image", "width", "height", "source_pdf", "group"}
    assert bodies["bodies"][1]["image"] == "bodies/fantasy-book-p00.png"
    assert bodies["bodies"][1]["source_pdf"] == "book.pdf"
    assert bodies["bodies"][1]["group"] == "fantasy"
    with Image.open(assets / "bodies" / "fantasy-book-p00.png") as png:
        assert png.mode == "RGBA"
        assert png.size == (bodies["bodies"][1]["width"], bodies["bodies"][1]["height"])
        assert abs(png.width - (DOLL_A[2] - DOLL_A[0])) <= 10
        assert abs(png.height - (DOLL_A[3] - DOLL_A[1])) <= 10
    with Image.open(assets / "bodies" / "fantasy-book-p01.png") as png:
        assert abs(png.height - (DOLL_B[3] - DOLL_B[1])) <= 10


def test_catalog_keeps_every_prior_key_when_bodies_are_built(tmp_path, sidecar_corpus, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])
    plain_assets, with_bodies = tmp_path / "plain", tmp_path / "with"
    build_catalog(root, plain_assets, min_quality=0.90)

    build_catalog(
        root, with_bodies, min_quality=0.90,
        bodies=BodiesSource(body_book["write_list"](TWO_BODIES), body_book["source"], body_book["triage"]),
    )

    # The scale blocks compare equal only because both builds clamp to a factor
    # of one: nothing here is near the Item ceiling or the body-height target.
    before = json.loads((plain_assets / "catalog.json").read_text())
    after = json.loads((with_bodies / "catalog.json").read_text())
    assert {k: v for k, v in before.items() if k != "build_id"} == {k: v for k, v in after.items() if k != "build_id"}
    assert before["items"] == after["items"]


def test_a_written_item_group_with_no_body_fails_the_build_by_group(tmp_path, sidecar_corpus, body_book):
    root, _ = sidecar_corpus([{"item_id": "k", **AT_72, "group": "knight"}])

    with pytest.raises(BodyError, match="knight"):
        build_catalog(
            root, tmp_path / "assets", min_quality=0.90,
            bodies=BodiesSource(body_book["write_list"](TWO_BODIES), body_book["source"], body_book["triage"]),
        )


def test_an_empty_body_list_is_a_no_op(tmp_path, sidecar_corpus, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])

    summary = build_catalog(
        root, tmp_path / "assets", min_quality=0.90,
        bodies=BodiesSource(body_book["write_list"]([]), body_book["source"], body_book["triage"]),
    )

    assert summary.bodies == 0
    assert summary.written == 1
    assert not (tmp_path / "assets" / "bodies.json").exists()
