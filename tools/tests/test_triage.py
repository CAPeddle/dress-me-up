"""Page triage: per-PDF manifests, hand overrides, contact sheets, and the CLI.

The classifier thresholds are pinned by test_orientation.py and test_pagetype.py;
these tests pin the stage around them — that a manifest has one row per page,
that a confirmation survives a re-run, and that a bad override refuses to write.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from dressup_pipeline.pagetype import PAGE_TYPES
from dressup_pipeline.triage import (
    Manifest,
    OverrideError,
    PageVerdict,
    TRIAGE_DPI,
    contact_sheet,
    load_overrides,
    manifest_path,
    overrides_path,
    rotate_page,
    triage_pdf,
)
from conftest import make_border_doll_page

TOOLS = Path(__file__).resolve().parents[1]


def _smoke_pdf(tmp_path, pages=2):
    import make_smoke_pdf

    pdf = tmp_path / "smoke.pdf"
    images = [make_smoke_pdf.build_page() for _ in range(pages)]
    images[0].save(pdf, save_all=True, append_images=images[1:])
    return pdf


def _manifest(pages):
    return Manifest(pdf="book.pdf", source_folder="Fantasy", triage_dpi=TRIAGE_DPI, pages=pages)


def _verdict(page, verdict="item_sheet", rotation=0, confirmed=None):
    return PageVerdict(
        page=page, rotation=rotation, verdict=verdict, confidence=0.8, reason="test", confirmed=confirmed
    )


# -- triage_pdf -------------------------------------------------------------


def test_smoke_pdf_yields_one_row_per_page_with_empty_confirmations(tmp_path):
    pdf = _smoke_pdf(tmp_path, pages=2)

    manifest = triage_pdf(pdf)

    assert manifest.pdf == "smoke.pdf"
    assert manifest.source_folder == tmp_path.name
    assert manifest.triage_dpi == TRIAGE_DPI
    assert [p.page for p in manifest.pages] == [0, 1]
    assert all(p.confirmed is None for p in manifest.pages)
    assert all(p.verdict in PAGE_TYPES for p in manifest.pages)
    assert all(p.rotation == 0 for p in manifest.pages)  # a scatter of items is left alone


def test_single_page_pdf_is_a_one_row_manifest(tmp_path):
    pdf = _smoke_pdf(tmp_path, pages=1)

    manifest = triage_pdf(pdf)

    assert len(manifest.pages) == 1
    assert manifest.rotation(0) == 0
    assert manifest.effective_verdict(0) == manifest.pages[0].verdict


def test_sideways_doll_page_gets_a_rotation_and_is_classified_upright(tmp_path):
    pdf = tmp_path / "doll.pdf"
    rotate_page(make_border_doll_page(), 270).save(pdf)  # laid on its side; 90 cw brings it back

    manifest = triage_pdf(pdf)

    assert manifest.rotation(0) == 90
    # Classified after rotation: the doll is a base body, not an item sheet.
    assert manifest.effective_verdict(0) == "base_body"
    assert not manifest.is_item_sheet(0)


def test_triage_dpi_is_in_the_validated_band():
    assert 100 <= TRIAGE_DPI <= 300


# -- Manifest ---------------------------------------------------------------


def test_manifest_roundtrips_through_json(tmp_path):
    manifest = _manifest([_verdict(0, rotation=90), _verdict(1, "illustration", confirmed="item_sheet")])
    path = tmp_path / "book.json"

    manifest.write(path)

    data = json.loads(path.read_text())
    assert data["pdf"] == "book.pdf"
    assert data["source_folder"] == "Fantasy"
    assert data["triage_dpi"] == TRIAGE_DPI
    assert data["pages"][0] == {
        "page": 0,
        "rotation": 90,
        "verdict": "item_sheet",
        "confidence": 0.8,
        "reason": "test",
        "confirmed": None,
    }
    assert data["pages"][1]["confirmed"] == "item_sheet"
    assert Manifest.read(path) == manifest


def test_effective_verdict_prefers_confirmation():
    manifest = _manifest([_verdict(0, "illustration", confirmed="item_sheet"), _verdict(1, "item_sheet")])

    assert manifest.effective_verdict(0) == "item_sheet"
    assert manifest.effective_verdict(1) == "item_sheet"
    assert manifest.is_item_sheet(0)
    assert manifest.is_item_sheet(1)


def test_confirmation_overrides_an_accepted_item_sheet_too():
    manifest = _manifest([_verdict(0, "item_sheet", confirmed="illustration")])

    assert not manifest.is_item_sheet(0)


def test_unconfirmed_non_item_sheet_is_not_extractable():
    manifest = _manifest([_verdict(0, "base_body")])

    assert not manifest.is_item_sheet(0)


def test_manifest_refuses_a_page_it_does_not_know():
    manifest = _manifest([_verdict(0)])

    with pytest.raises(KeyError, match="7"):
        manifest.rotation(7)


# -- overrides --------------------------------------------------------------


def test_apply_overrides_sets_confirmed_and_leaves_the_verdict_alone():
    manifest = _manifest([_verdict(0, "illustration"), _verdict(1, "item_sheet")])

    manifest.apply_overrides({0: "item_sheet"})

    assert manifest.pages[0].confirmed == "item_sheet"
    assert manifest.pages[0].verdict == "illustration"
    assert manifest.pages[1].confirmed is None


def test_override_for_a_missing_page_fails_loudly_before_anything_changes():
    manifest = _manifest([_verdict(0), _verdict(1)])

    with pytest.raises(OverrideError, match="page 5"):
        manifest.apply_overrides({0: "item_sheet", 5: "base_body"})

    assert all(p.confirmed is None for p in manifest.pages)


def test_override_with_an_unknown_verdict_fails_loudly():
    manifest = _manifest([_verdict(0)])

    with pytest.raises(OverrideError, match="jetpack"):
        manifest.apply_overrides({0: "jetpack"})


def test_load_overrides_reads_string_page_keys_as_ints(tmp_path):
    path = tmp_path / "book.overrides.json"
    path.write_text(json.dumps({"pages": {"3": "item_sheet", "5": "base_body"}}))

    assert load_overrides(path) == {3: "item_sheet", 5: "base_body"}


def test_empty_overrides_file_confirms_nothing(tmp_path):
    path = tmp_path / "book.overrides.json"
    path.write_text(json.dumps({"pages": {}}))

    assert load_overrides(path) == {}


def test_paths_are_named_after_the_pdf_stem(tmp_path):
    pdf = Path("content/source/Fantasy/20260515170658.pdf")

    assert manifest_path(tmp_path, pdf) == tmp_path / "20260515170658.json"
    assert overrides_path(tmp_path, pdf) == tmp_path / "20260515170658.overrides.json"


# -- rotate_page / contact_sheet -------------------------------------------


def test_rotate_page_zero_is_the_identity():
    page = Image.new("RGB", (30, 50), "white")

    assert rotate_page(page, 0) is page


def test_rotate_page_matches_the_orientation_module_contract():
    page = Image.new("RGB", (30, 50), "white")
    page.putpixel((0, 0), (0, 0, 0))  # top-left corner

    turned = rotate_page(page, 90)

    assert turned.size == (50, 30)
    assert turned.getpixel((49, 0)) == (0, 0, 0)  # clockwise: top-left lands top-right


def test_contact_sheet_lays_out_one_thumbnail_per_page():
    pages = [(i, Image.new("RGB", (60, 90), (200, 40 * i, 40))) for i in range(5)]

    sheet = contact_sheet(pages, columns=3, thumb=(60, 90))

    assert sheet.width == 3 * 60
    assert sheet.height >= 2 * 90


# -- CLI --------------------------------------------------------------------


def _run_cli(argv):
    import triage_pages

    return triage_pages.main(argv)


def test_cli_writes_a_manifest_and_a_contact_sheet_per_verdict(tmp_path, capsys):
    pdf = _smoke_pdf(tmp_path, pages=2)
    out = tmp_path / "triage"

    assert _run_cli([str(pdf), "--out", str(out)]) == 0

    manifest = Manifest.read(out / "smoke.json")
    assert len(manifest.pages) == 2
    verdicts = {p.verdict for p in manifest.pages}
    for verdict in PAGE_TYPES:
        assert (out / f"smoke.{verdict}.png").exists() == (verdict in verdicts)
    assert "smoke.pdf" in capsys.readouterr().out


def test_cli_merges_overrides_on_every_run(tmp_path):
    pdf = _smoke_pdf(tmp_path, pages=2)
    out = tmp_path / "triage"
    out.mkdir()
    (out / "smoke.overrides.json").write_text(json.dumps({"pages": {"1": "illustration"}}))

    _run_cli([str(pdf), "--out", str(out)])
    _run_cli([str(pdf), "--out", str(out)])  # a re-run must not lose the confirmation

    manifest = Manifest.read(out / "smoke.json")
    assert manifest.pages[0].confirmed is None
    assert manifest.pages[1].confirmed == "illustration"


def test_cli_fails_on_an_override_for_a_missing_page_and_writes_nothing(tmp_path, capsys):
    pdf = _smoke_pdf(tmp_path, pages=2)
    out = tmp_path / "triage"
    out.mkdir()
    (out / "smoke.overrides.json").write_text(json.dumps({"pages": {"9": "item_sheet"}}))

    assert _run_cli([str(pdf), "--out", str(out)]) != 0

    assert not (out / "smoke.json").exists()
    assert "page 9" in capsys.readouterr().err
