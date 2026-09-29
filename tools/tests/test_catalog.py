import json

import pytest
from PIL import Image

import build_catalog as build_catalog_cli
from dressup_pipeline.bodies import BodyError
from dressup_pipeline.catalog import BodiesSource, build_catalog, new_build_id
from dressup_pipeline.corrections import (
    Correction,
    corrections_path,
    pdf_stem,
    read_corrections,
    write_corrections,
)
from dressup_pipeline.models import BBox
from dressup_pipeline.triage import TRIAGE_DPI, Manifest, PageVerdict, manifest_path
from synthetic import make_doll_page


# The ordinary item: classified, QA'd, and filed by a person under the category
# the classifier happened to guess too. `correction` is what admits it — nothing
# else in this dict does (R11).
LABELLED = dict(category="hat", group="fantasy", quality=0.95, accepted=True, correction="hat")
AT_72 = dict(LABELLED, dpi=72)


def test_writes_labelled_items_and_their_images(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([{"item_id": "a", **LABELLED}, {"item_id": "b", **LABELLED}])
    assets = tmp_path / "assets"

    summary = build_catalog(root, assets, corrections_dir=corrections_dir)

    catalog = json.loads((assets / "catalog.json").read_text())
    assert summary.written == 2
    assert [item["id"] for item in catalog["items"]] == ["a", "b"]
    assert (assets / "items" / "a.png").exists()


def test_items_are_sorted_by_id_regardless_of_disk_order(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([{"item_id": n, **LABELLED} for n in ("c", "a", "b")])

    build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert [item["id"] for item in catalog["items"]] == ["a", "b", "c"]


def test_only_labelled_items_reach_the_catalog_and_the_rest_do_not_fail_it(tmp_path, sidecar_corpus, corrections_dir):
    """AE2: a half-labelled corpus builds, and builds only what was labelled."""
    root, _ = sidecar_corpus([
        {"item_id": "filed", **LABELLED},
        {"item_id": "untouched", "category": "hat", "group": "fantasy", "quality": 0.95, "accepted": True},
    ])

    summary = build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert summary.written == 1
    assert [item["id"] for item in catalog["items"]] == ["filed"]
    assert summary.skipped == {"no human label": 1}


def test_a_human_label_admits_an_item_qa_rejected_and_leaves_its_sidecar_alone(tmp_path, sidecar_corpus, corrections_dir):
    """AE3: QA scored it 0.84 and rejected it for being small; a person filed it.

    A hair clip is legitimately small, so QA's verdict is advisory here and the
    label wins whatever --min-quality says. QA's own fields are QA's: the build
    reads them and writes nothing back, which the byte comparison pins down.
    """
    root, _ = sidecar_corpus([
        {"item_id": "clip", "category": "hat", "group": "fantasy", "quality": 0.84,
         "accepted": False, "correction": "accessory"},
    ])
    sidecar_file = root / "clip.sidecar.json"
    before = sidecar_file.read_bytes()

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90, corrections_dir=corrections_dir)

    item = json.loads((tmp_path / "assets" / "catalog.json").read_text())["items"][0]
    assert summary.written == 1
    assert summary.skipped == {}
    # The person's category, not the classifier's suggestion of "hat".
    assert (item["id"], item["category"]) == ("clip", "accessory")
    assert item["quality"] == 0.84
    assert sidecar_file.read_bytes() == before


def test_a_human_rejection_keeps_an_item_out_and_is_counted_by_its_kind(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([
        {"item_id": "good", **LABELLED},
        {"item_id": "torn", **{**LABELLED, "correction": None, "rejection": "bad_crop"}},
        {"item_id": "pair", **{**LABELLED, "correction": None, "rejection": "multi_item"}},
    ])

    summary = build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert [item["id"] for item in catalog["items"]] == ["good"]
    assert summary.skipped == {
        "rejected by a person: bad_crop": 1,
        "rejected by a person: multi_item": 1,
    }


def test_the_report_names_how_many_items_qa_would_have_excluded(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([
        {"item_id": "solid", **LABELLED},
        {"item_id": "weak", **{**LABELLED, "quality": 0.72}},
        {"item_id": "spurned", **{**LABELLED, "accepted": False}},
    ])

    summary = build_catalog(root, tmp_path / "assets", min_quality=0.90, corrections_dir=corrections_dir)

    assert summary.written == 3
    assert summary.admitted_over_qa == 2
    assert "QA advisory: 2 of the items written would not have passed QA's own gate" in summary.as_report()


def test_a_correction_matching_no_item_is_reported_rather_than_failing_the_build(tmp_path, sidecar_corpus, corrections_dir):
    """R9: half an hour of judgement is not repeatable, so nothing is discarded.

    The stranded file names a PDF the corpus holds nothing from at all — the case
    a per-stem lookup would never open, and so never report.
    """
    root, built = sidecar_corpus([{"item_id": "a", **LABELLED}])
    stranded = Correction(
        source_pdf="retired-book", page=3, bbox=BBox(11, 22, 300, 400),
        page_width=2480, page_height=3508, dpi=300, category="dress",
    )
    write_corrections(corrections_path(corrections_dir, "retired-book"), [stranded])
    # And one whose cutout moved a pixel within a PDF the corpus does still hold,
    # filed beside the label that still matches.
    moved = Correction.for_sidecar(built["a"], category="top")
    moved.bbox = BBox(moved.bbox.x + 1, moved.bbox.y, moved.bbox.w, moved.bbox.h)
    same_pdf = corrections_path(corrections_dir, pdf_stem(built["a"].source_pdf))
    write_corrections(same_pdf, [*read_corrections(same_pdf).values(), moved])

    summary = build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    report = summary.as_report()
    assert summary.written == 1
    assert sorted(correction.describe() for correction in summary.unmatched) == sorted(
        [stranded.describe(), moved.describe()]
    )
    assert "unmatched corrections: 2" in report
    assert stranded.describe() in report and moved.describe() in report


def test_group_filter_restricts_the_build(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([
        {"item_id": "f", **LABELLED},
        {"item_id": "k", **{**LABELLED, "group": "knight"}},
    ])

    summary = build_catalog(root, tmp_path / "assets", groups={"knight"}, corrections_dir=corrections_dir)

    assert summary.written == 1
    assert summary.by_group == {"knight": 1}
    assert summary.skipped["group not selected"] == 1


def test_an_unfinished_item_is_still_skipped_for_being_unfinished(tmp_path, sidecar_corpus, corrections_dir):
    """A label cannot stand in for a stage that never ran.

    Both of these carry a human category, so only the pipeline's own progress
    keeps them out — and `is_classified`/`is_qa_complete` ask whether the stage
    ran, never how it ruled.
    """
    root, _ = sidecar_corpus([
        {"item_id": "raw", "correction": "hat"},
        {"item_id": "classified-only", "category": "hat", "group": "fantasy", "correction": "hat"},
    ])

    summary = build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    assert summary.written == 0
    assert summary.skipped == {"not classified": 1, "QA not run": 1}


def test_missing_image_is_skipped_rather_than_crashing_the_build(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([{"item_id": "a", **LABELLED}])
    (root / "a.png").unlink()

    summary = build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    assert summary.written == 0
    assert summary.skipped["image missing on disk"] == 1


def test_catalog_records_the_dimensions_after_the_build_factor(tmp_path, sidecar_corpus, corrections_dir):
    """With no bodies the Item ceiling is the only bound: 512/1200 for both edges."""
    root, _ = sidecar_corpus([{"item_id": "big", **LABELLED, "size": (1200, 800)}])

    build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    item = json.loads((tmp_path / "assets" / "catalog.json").read_text())["items"][0]
    assert (item["width"], item["height"]) == (512, 341)


def test_empty_corpus_still_writes_a_valid_catalog(tmp_path):
    """And a corrections directory nobody has created yet is not an error."""
    root = tmp_path / "empty"
    root.mkdir()

    summary = build_catalog(root, tmp_path / "assets", corrections_dir=tmp_path / "never-labelled")

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


def test_catalog_without_a_body_list_gains_only_a_build_id(tmp_path, sidecar_corpus, corrections_dir):
    root, _ = sidecar_corpus([{"item_id": "a", **LABELLED}])

    build_catalog(root, tmp_path / "assets", corrections_dir=corrections_dir)

    catalog = json.loads((tmp_path / "assets" / "catalog.json").read_text())
    assert set(catalog) == {"version", "min_quality", "items", "build_id", "scale"}
    assert not (tmp_path / "assets" / "bodies.json").exists()


def test_bodies_are_written_beside_the_catalog_in_list_order(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])
    assets = tmp_path / "assets"

    summary = build_catalog(
        root, assets, corrections_dir=corrections_dir,
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


def test_catalog_keeps_every_prior_key_when_bodies_are_built(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])
    plain_assets, with_bodies = tmp_path / "plain", tmp_path / "with"
    build_catalog(root, plain_assets, corrections_dir=corrections_dir)

    build_catalog(
        root, with_bodies, corrections_dir=corrections_dir,
        bodies=BodiesSource(body_book["write_list"](TWO_BODIES), body_book["source"], body_book["triage"]),
    )

    # The scale blocks compare equal only because both builds clamp to a factor
    # of one: nothing here is near the Item ceiling or the body-height target.
    before = json.loads((plain_assets / "catalog.json").read_text())
    after = json.loads((with_bodies / "catalog.json").read_text())
    assert {k: v for k, v in before.items() if k != "build_id"} == {k: v for k, v in after.items() if k != "build_id"}
    assert [item["id"] for item in before["items"]] == ["a"]
    assert before["items"] == after["items"]


def test_a_written_item_group_with_no_body_fails_the_build_by_group(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([{"item_id": "k", **AT_72, "group": "knight"}])

    with pytest.raises(BodyError, match="knight"):
        build_catalog(
            root, tmp_path / "assets", corrections_dir=corrections_dir,
            bodies=BodiesSource(body_book["write_list"](TWO_BODIES), body_book["source"], body_book["triage"]),
        )


def test_an_empty_body_list_is_a_no_op(tmp_path, sidecar_corpus, corrections_dir, body_book):
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])

    summary = build_catalog(
        root, tmp_path / "assets", corrections_dir=corrections_dir,
        bodies=BodiesSource(body_book["write_list"]([]), body_book["source"], body_book["triage"]),
    )

    assert summary.bodies == 0
    assert summary.written == 1
    assert not (tmp_path / "assets" / "bodies.json").exists()


def test_a_rebuild_without_bodies_clears_the_stale_bodies_from_the_assets_dir(tmp_path, sidecar_corpus, corrections_dir, body_book):
    """A catalog-only rebuild must not leave last build's bodies.json behind.

    catalog.json always gets a fresh build_id, so a stale bodies.json beside it
    is a pair the web version refuses to load with nothing to explain it.
    """
    root, _ = sidecar_corpus([{"item_id": "a", **AT_72}])
    assets = tmp_path / "assets"
    build_catalog(
        root, assets, corrections_dir=corrections_dir,
        bodies=BodiesSource(body_book["write_list"](TWO_BODIES), body_book["source"], body_book["triage"]),
    )
    stale_build_id = json.loads((assets / "catalog.json").read_text())["build_id"]
    assert (assets / "bodies" / "fantasy-book-p00.png").exists()

    summary = build_catalog(root, assets, corrections_dir=corrections_dir)

    catalog = json.loads((assets / "catalog.json").read_text())
    assert not (assets / "bodies.json").exists()
    assert not (assets / "bodies").exists()
    assert catalog["build_id"] != stale_build_id
    assert "bodies: 0 (removed a stale bodies.json from an earlier build)" in summary.as_report()


# -- the CLI and the tracked body list ----------------------------------------


def test_the_cli_skips_the_tracked_body_list_when_none_of_its_pdfs_are_here(tmp_path, sidecar_corpus, corrections_dir, capsys):
    """A fresh clone has no scans, so the quickstart must still write a catalog."""
    assert build_catalog_cli._default_bodies_list() is not None, "the tracked list must list bodies for this test to mean anything"
    root, _ = sidecar_corpus([{"item_id": "a", **LABELLED}])
    assets = tmp_path / "assets"
    source = tmp_path / "no-scans-here"  # deliberately never created

    code = build_catalog_cli.main([
        "--sidecars", str(root), "--assets", str(assets), "--corrections", str(corrections_dir),
        "--source", str(source), "--triage", str(tmp_path / "triage"),
    ])

    assert code == 0
    assert [item["id"] for item in json.loads((assets / "catalog.json").read_text())["items"]] == ["a"]
    assert not (assets / "bodies.json").exists()
    err = capsys.readouterr().err
    assert "base_bodies.json" in err and "skipped" in err and str(source) in err


def test_an_explicit_body_list_is_never_skipped_when_its_pdf_is_missing(tmp_path, sidecar_corpus, corrections_dir, capsys):
    """--bodies is a human saying "these bodies"; a PDF it cannot find is an error."""
    root, _ = sidecar_corpus([])  # empty, so the unbodied-group check cannot be what fails
    listing = tmp_path / "explicit-bodies.json"
    listing.write_text(
        json.dumps({"version": 1, "bodies": [
            {"id": "fantasy-nowhere-p00", "pdf": "nowhere.pdf", "page": 0, "group": "fantasy", "region": None},
        ]}),
        encoding="utf-8",
    )
    source = tmp_path / "source"
    source.mkdir()

    code = build_catalog_cli.main([
        "--sidecars", str(root), "--assets", str(tmp_path / "assets"), "--corrections", str(corrections_dir),
        "--bodies", str(listing), "--source", str(source), "--triage", str(tmp_path / "triage"),
    ])

    assert code == 1
    assert "not found under" in capsys.readouterr().err


def test_an_uncorrected_corpus_exits_non_zero_and_says_why(tmp_path, sidecar_corpus, corrections_dir, capsys):
    """The ordinary state of a corpus nobody has been through, named as such.

    Still non-zero — an empty catalog is never what the caller asked for — but
    the message points at the labelling rather than implying the build broke.
    """
    root, _ = sidecar_corpus([
        {"item_id": "a", "category": "hat", "group": "fantasy", "quality": 0.95, "accepted": True},
    ])

    code = build_catalog_cli.main([
        "--sidecars", str(root), "--assets", str(tmp_path / "assets"),
        "--corrections", str(corrections_dir), "--source", str(tmp_path / "no-scans-here"),
        "--triage", str(tmp_path / "triage"),
    ])

    out, err = capsys.readouterr()
    assert code == 1
    assert "no human label" in out
    assert "carries a human label" in err and str(corrections_dir) in err
