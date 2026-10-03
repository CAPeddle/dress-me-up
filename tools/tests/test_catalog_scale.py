"""One factor for every image a build writes (KTD4).

Per-image fitting made a crown and a gown the same width on screen. The build
now computes one factor — the smaller of the target body height over the tallest
Base Body and the 512px item ceiling over the largest Item edge — and applies it
to every body and every Item, so relative size survives into the app.

The numeric cases are pure `compute_scale` tests; the cases about what lands on
disk build a real catalog beside real bodies.
"""

import json

import pytest
from PIL import Image

import build_catalog as build_catalog_cli
from dressup_pipeline.bodies import BodyError
from dressup_pipeline.catalog import (
    DEFAULT_BODY_HEIGHT_PX,
    ITEM_CEILING_PX,
    BodiesSource,
    build_catalog,
    compute_scale,
)
from dressup_pipeline.extract import DEFAULT_DPI
from dressup_pipeline.triage import TRIAGE_DPI, Manifest, PageVerdict, manifest_path
from synthetic import make_doll_page

# `correction` is what puts an item in a build at all (R11); the sizes are what
# these cases are about.
LABELLED = dict(category="hat", group="fantasy", quality=0.95, accepted=True, correction="hat")
AT_72 = dict(LABELLED, dpi=72)


def scaled(edge: int, decision) -> int:
    """What the build makes of an edge that long: the factor, never below 1px."""
    return max(1, round(edge * decision.factor))


# -- the factor itself ---------------------------------------------------------


def test_the_target_height_decides_when_no_item_is_near_the_ceiling():
    decision = compute_scale(body_heights=[1200], item_edges=[300], target_body_height=600)

    assert decision.bound == "target_height"
    assert scaled(1200, decision) == 600
    assert scaled(300, decision) == 150


def test_two_items_of_different_sizes_scale_by_the_one_factor():
    """The small Item shrinks with the big one instead of being left at full size."""
    decision = compute_scale(body_heights=[], item_edges=[900, 200], target_body_height=1000)

    assert decision.bound == "item_ceiling"
    assert scaled(900, decision) == ITEM_CEILING_PX
    assert scaled(200, decision) == 114
    assert scaled(900, decision) > 4 * scaled(200, decision)


def test_the_item_ceiling_wins_over_a_generous_target():
    decision = compute_scale(body_heights=[1000], item_edges=[1000], target_body_height=900)

    assert decision.bound == "item_ceiling"
    assert scaled(1000, decision) == ITEM_CEILING_PX


def test_a_target_above_the_tallest_body_is_clamped_and_says_so():
    decision = compute_scale(body_heights=[800], item_edges=[300], target_body_height=1000)

    assert decision.factor == 1.0
    assert decision.bound == "clamped"


def test_with_no_items_the_target_height_is_the_only_bound():
    decision = compute_scale(body_heights=[800], item_edges=[], target_body_height=400)

    assert decision.bound == "target_height"
    assert scaled(800, decision) == 400


def test_with_neither_bodies_nor_items_nothing_constrains_the_factor():
    decision = compute_scale(body_heights=[], item_edges=[], target_body_height=1000)

    assert decision.factor == 1.0
    assert decision.bound == "clamped"


def test_the_decision_carries_the_target_and_the_ceiling_it_was_given():
    decision = compute_scale(body_heights=[2000], item_edges=[900], target_body_height=750)

    assert decision.target_body_height_px == 750
    assert decision.item_ceiling_px == ITEM_CEILING_PX


def test_a_non_positive_target_height_is_refused():
    with pytest.raises(ValueError, match="positive"):
        compute_scale(body_heights=[1000], item_edges=[500], target_body_height=0)


def test_the_cli_refuses_a_non_positive_body_height(tmp_path, capsys):
    sidecars = tmp_path / "sidecars"
    sidecars.mkdir()

    with pytest.raises(SystemExit):
        build_catalog_cli.main([
            "--sidecars", str(sidecars), "--assets", str(tmp_path / "assets"), "--body-height", "0",
        ])

    assert "--body-height" in capsys.readouterr().err


# -- what lands on disk --------------------------------------------------------


def test_the_catalog_dimensions_are_the_written_pngs_dimensions(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([
        {"item_id": "wide", **LABELLED, "size": (1400, 600)},
        {"item_id": "tall", **LABELLED, "size": (500, 1100)},
    ])
    assets = tmp_path / "assets"

    build_catalog(root, assets, corrections_dir=corrections_dir)

    catalog = json.loads((assets / "catalog.json").read_text())
    assert len(catalog["items"]) == 2
    for item in catalog["items"]:
        with Image.open(assets / item["image"]) as png:
            assert png.size == (item["width"], item["height"]), item["id"]


def test_no_written_item_exceeds_the_item_ceiling(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([
        {"item_id": "huge", **LABELLED, "size": (3000, 1000)},
        {"item_id": "small", **LABELLED, "size": (200, 160)},
    ])
    assets = tmp_path / "assets"

    build_catalog(root, assets, corrections_dir=corrections_dir)

    catalog = json.loads((assets / "catalog.json").read_text())
    # The factor is truncated to 4 dp, so the largest Item reaches the ceiling to
    # within a pixel and never passes it.
    largest = max(max(item["width"], item["height"]) for item in catalog["items"])
    assert ITEM_CEILING_PX - 1 <= largest <= ITEM_CEILING_PX
    # The small Item shrank by the same factor rather than staying at its own size.
    small = next(item for item in catalog["items"] if item["id"] == "small")
    assert small["width"] < 200


def test_an_item_one_pixel_across_survives_a_small_factor(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([
        {"item_id": "huge", **LABELLED, "size": (3000, 1000)},
        {"item_id": "tiny", **LABELLED},
    ])
    Image.new("RGBA", (1, 1), (200, 60, 90, 255)).save(root / "tiny.png")
    assets = tmp_path / "assets"

    build_catalog(root, assets, corrections_dir=corrections_dir)

    tiny = next(i for i in json.loads((assets / "catalog.json").read_text())["items"] if i["id"] == "tiny")
    assert (tiny["width"], tiny["height"]) == (1, 1)
    with Image.open(assets / "items" / "tiny.png") as png:
        assert png.size == (1, 1)


def test_the_scale_block_is_written_into_the_catalog(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([{"item_id": "a", **LABELLED, "size": (1024, 800)}])

    build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir, target_body_height=1000)

    scale = json.loads((tmp_path / "assets" / "catalog.json").read_text())["scale"]
    assert set(scale) == {"target_body_height_px", "factor", "source_dpi", "bound", "item_ceiling_px"}
    assert scale == {
        "target_body_height_px": 1000,
        "factor": 0.5,
        "source_dpi": DEFAULT_DPI,
        "bound": "item_ceiling",
        "item_ceiling_px": ITEM_CEILING_PX,
    }


# -- bodies and items out of one build -----------------------------------------

DOLL = (260, 60, 340, 760)


@pytest.fixture
def body_book(tmp_path):
    """A one-page doll PDF under a source root, triaged, plus a list naming it."""
    source = tmp_path / "source" / "Fantasy"
    source.mkdir(parents=True)
    pdf = source / "book.pdf"
    make_doll_page(dolls=(DOLL,)).save(pdf)

    triage = tmp_path / "triage"
    triage.mkdir()
    pages = [PageVerdict(page=0, rotation=0, verdict="base_body", confidence=0.9, reason="t")]
    Manifest(pdf=pdf.name, source_folder="Fantasy", triage_dpi=TRIAGE_DPI, pages=pages).write(manifest_path(triage, pdf))

    listing = tmp_path / "bodies-list.json"
    listing.write_text(json.dumps({"version": 1, "bodies": [
        {"id": "fantasy-book-p00", "pdf": "book.pdf", "page": 0, "group": "fantasy", "region": None},
    ]}), encoding="utf-8")

    return dict(source=tmp_path / "source", triage=triage, listing=listing)


def build_with_bodies(root, assets, corrections_dir, body_book, **kwargs):
    return build_catalog(
        root, assets, corrections_dir=corrections_dir,
        bodies=BodiesSource(body_book["listing"], body_book["source"], body_book["triage"]),
        **kwargs,
    )


def test_both_files_carry_the_same_build_id_and_scale_block(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])
    assets = tmp_path / "assets"

    build_with_bodies(root, assets, corrections_dir, body_book)

    catalog = json.loads((assets / "catalog.json").read_text())
    bodies = json.loads((assets / "bodies.json").read_text())
    assert len(catalog["items"]) == 1
    assert catalog["build_id"] == bodies["build_id"]
    assert catalog["scale"] == bodies["scale"]
    assert catalog["scale"]["source_dpi"] == 72


def test_one_factor_governs_the_bodies_and_the_items(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72, "size": (300, 400)}])
    assets = tmp_path / "assets"

    summary = build_with_bodies(root, assets, corrections_dir, body_book, target_body_height=300)

    catalog = json.loads((assets / "catalog.json").read_text())
    body = json.loads((assets / "bodies.json").read_text())["bodies"][0]
    factor = catalog["scale"]["factor"]
    assert catalog["scale"]["bound"] == "target_height"
    # The tallest body lands on the target, and the Item is the same factor smaller.
    assert abs(body["height"] - 300) <= 1
    assert (catalog["items"][0]["width"], catalog["items"][0]["height"]) == (
        max(1, round(300 * factor)), max(1, round(400 * factor)),
    )
    with Image.open(assets / "bodies" / "fantasy-book-p00.png") as png:
        assert png.size == (body["width"], body["height"])
    assert summary.scale.factor == factor


def test_the_report_tables_each_source_pdf_and_names_the_bound(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([
        {"item_id": "a", **AT_72, "source_pdf": "items.pdf", "size": (300, 400)},
        {"item_id": "b", **AT_72, "source_pdf": "items.pdf", "size": (300, 200)},
    ])

    summary = build_with_bodies(root, tmp_path / "assets", corrections_dir, body_book, target_body_height=300)

    report = summary.as_report()
    assert "items.pdf" in report and "book.pdf" in report
    assert "fantasy" in report
    assert "300" in report  # the median Item height in scan pixels
    assert "target_height" in report
    assert str(summary.tallest_body) in report and str(summary.largest_item_edge) in report


def test_the_default_target_body_height_is_the_documented_one():
    assert DEFAULT_BODY_HEIGHT_PX == 1000


# -- a --group build asks only its own groups about dpi ------------------------

# A second book, extracted at the default rather than the 72 dpi the fantasy
# items beside it carry. It is labelled and otherwise catalogue-ready, so only
# the group filter keeps it out of the builds below.
KNIGHT = dict(LABELLED, group="knight", dpi=DEFAULT_DPI, source_pdf="knight-book-1.pdf")


def test_a_filtered_build_ignores_the_dpi_of_a_group_it_left_out(tmp_path, sidecar_corpus, corrections_dir):
    """The scale block describes this build, so a book it never writes has no say."""
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}, {"item_id": "k", **KNIGHT}])
    assets = tmp_path / "assets"

    build_catalog(root, assets, groups={"fantasy"}, corrections_dir=corrections_dir)

    catalog = json.loads((assets / "catalog.json").read_text())
    assert [item["id"] for item in catalog["items"]] == ["a"]
    assert catalog["scale"]["source_dpi"] == 72


def test_a_filtered_build_cuts_bodies_at_its_own_groups_dpi(tmp_path, sidecar_corpus, corrections_dir, body_book):
    """The bodies path scopes the same way; otherwise the fix is still reachable."""
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}, {"item_id": "k", **KNIGHT}])
    assets = tmp_path / "assets"

    build_with_bodies(root, assets, corrections_dir, body_book, groups={"fantasy"})

    catalog = json.loads((assets / "catalog.json").read_text())
    bodies = json.loads((assets / "bodies.json").read_text())
    assert catalog["scale"] == bodies["scale"]
    assert catalog["scale"]["source_dpi"] == 72


def test_a_filtered_build_still_refuses_a_disagreement_inside_its_own_groups(
    tmp_path, sidecar_corpus, corrections_dir
):
    """Narrowing the question must not retire it: one book, two dpis, still refused."""
    root, _ = sidecar_corpus([
        {"item_id": "a", **AT_72},
        {"item_id": "odd", **LABELLED, "dpi": 150},
    ])

    with pytest.raises(BodyError) as excinfo:
        build_catalog(root, tmp_path / "assets", groups={"fantasy"}, corrections_dir=corrections_dir)

    assert "odd" in str(excinfo.value)
