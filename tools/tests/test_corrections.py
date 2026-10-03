"""Human corrections: the record, its per-PDF file, and the geometry matcher.

The classifier's verdict is a suggestion and the build only trusts a person, so
these tests pin the part that decides *which* person's verdict applies to which
cutout. Two failures matter more than the rest and are pinned hardest: a
correction quietly matching an item it was not written for (a nudged bbox, a
re-rendered page, a record pasted into the wrong PDF's file), and a correction
quietly vanishing when its cutout moves. Both cost half an hour of unrepeatable
judgement, one silently and one loudly.
"""

import json
import os
from pathlib import Path

import pytest

from dressup_pipeline.classify import Shape, classify_sidecar
from dressup_pipeline.corrections import (
    CORRECTIONS_SUFFIX,
    REJECTION_KINDS,
    Correction,
    CorrectionError,
    corrections_path,
    pdf_stem,
    match,
    read_corrections,
    sidecar_key,
    write_corrections,
)
from dressup_pipeline.models import CATEGORIES, BBox, Sidecar

# One real item out of content/sidecars/20260509081050, so the fixtures are the
# geometry the matcher will actually meet.
PAGE = (2480, 3507)
DPI = 300


def _correction(
    source_pdf="20260509081050",
    page=0,
    bbox=(1145, 81, 170, 108),
    page_size=PAGE,
    dpi=DPI,
    category="hat",
    rejection=None,
):
    return Correction(
        source_pdf=source_pdf,
        page=page,
        bbox=BBox(*bbox),
        page_width=page_size[0],
        page_height=page_size[1],
        dpi=dpi,
        category=category,
        rejection=rejection,
    )


def _sidecar(
    item_id="20260509081050-p000-i001",
    source_pdf="20260509081050.pdf",
    page=0,
    bbox=(1145, 81, 170, 108),
    page_size=PAGE,
    dpi=DPI,
    category="hat",
):
    return Sidecar(
        item_id=item_id,
        source_pdf=source_pdf,
        page=page,
        bbox=BBox(*bbox),
        image=f"{item_id}.png",
        page_width=page_size[0],
        page_height=page_size[1],
        dpi=dpi,
        category=category,
        group="fantasy",
    )


def _file(tmp_path, records, stem="20260509081050"):
    """Hand-write a corrections file the way a person or the server would."""
    path = tmp_path / f"{stem}{CORRECTIONS_SUFFIX}"
    path.write_text(json.dumps({"corrections": records}, indent=2) + "\n", encoding="utf-8")
    return path


# -- the record and its file ---------------------------------------------------


def test_roundtrips_through_json(tmp_path):
    original = {
        _correction(category="bottom").key: _correction(category="bottom"),
        _correction(bbox=(400, 900, 200, 300), category=None, rejection="bad_crop").key: _correction(
            bbox=(400, 900, 200, 300), category=None, rejection="bad_crop"
        ),
    }
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    write_corrections(path, original.values())

    assert read_corrections(path) == original


def test_the_file_is_a_list_of_named_fields(tmp_path):
    """Readable in a git diff: no composite string keys on disk (KTD1, R7)."""
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    write_corrections(path, [_correction()])

    data = json.loads(path.read_text(encoding="utf-8"))

    assert [record["page"] for record in data["corrections"]] == [0]
    assert data["corrections"][0]["bbox"] == {"x": 1145, "y": 81, "w": 170, "h": 108}
    assert data["corrections"][0]["source_pdf"] == "20260509081050"


def test_written_records_are_key_sorted_so_a_rewrite_is_a_clean_diff(tmp_path):
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    late = _correction(page=4, bbox=(10, 10, 20, 20))
    early = _correction(page=0, bbox=(5, 5, 20, 20))
    write_corrections(path, [late, early])

    data = json.loads(path.read_text(encoding="utf-8"))

    assert [record["page"] for record in data["corrections"]] == [0, 4]


def test_corrections_path_is_one_file_per_pdf_stem(tmp_path):
    """A stem may hold hyphens, so it is never parsed back out of anything."""
    assert corrections_path(tmp_path, "fantasy-smoke").name == f"fantasy-smoke{CORRECTIONS_SUFFIX}"
    assert corrections_path(tmp_path, "20260509081050").name == f"20260509081050{CORRECTIONS_SUFFIX}"


# -- matching ------------------------------------------------------------------


def test_matches_a_sidecar_with_identical_geometry():
    correction = _correction(category="bottom")

    assert correction.key == sidecar_key(_sidecar())


def test_for_sidecar_takes_the_stem_and_the_geometry_off_the_sidecar():
    """`Sidecar.source_pdf` is a filename and a correction's is a stem, so nobody
    should be copying that field across by hand."""
    sidecar = _sidecar()

    correction = Correction.for_sidecar(sidecar, category="bottom")

    assert correction.source_pdf == "20260509081050"
    assert correction.key == sidecar_key(sidecar)
    assert correction.effective_category == "bottom"

    rejected = Correction.for_sidecar(sidecar, rejection="bad_crop")

    assert rejected.rejected
    assert rejected.key == sidecar_key(sidecar)


def test_two_pdfs_sharing_geometry_resolve_to_different_corrections():
    """20260509081050 and 20260509081623 are two scans of the same physical page.

    Five of their bounding boxes are byte-identical at the same page size and
    dpi, so the stem has to be part of the key (KTD2) or one scan's labels would
    leak onto the other's items.
    """
    corrections = {
        c.key: c
        for c in (
            _correction(source_pdf="20260509081050", category="hat"),
            _correction(source_pdf="20260509081623", category="shoes"),
        )
    }
    assert len(corrections) == 2

    first = _sidecar(source_pdf="20260509081050.pdf")
    second = _sidecar(item_id="20260509081623-p000-i001", source_pdf="20260509081623.pdf")

    assert corrections[sidecar_key(first)].category == "hat"
    assert corrections[sidecar_key(second)].category == "shoes"


def test_a_bbox_off_by_one_pixel_does_not_match_and_is_reported_unmatched():
    """Covers AE1 (R9): a moved cutout is a different item, and the label is kept."""
    moved = _correction(bbox=(1145, 81, 170, 108), category="bottom")
    still_there = _correction(bbox=(400, 900, 200, 300), category="top")
    corrections = {c.key: c for c in (moved, still_there)}

    sidecars = [
        _sidecar(item_id="20260509081050-p000-i001", bbox=(1145, 81, 170, 109)),
        _sidecar(item_id="20260509081050-p000-i002", bbox=(400, 900, 200, 300)),
    ]

    assert moved.key != sidecar_key(sidecars[0])

    report = match(corrections, sidecars)

    assert report.labelled == {"20260509081050-p000-i002": still_there}
    assert report.unlabelled == ["20260509081050-p000-i001"]
    assert report.unmatched == [moved]


def test_a_different_page_size_does_not_match_even_with_the_same_bbox():
    """A re-rendered page puts every item somewhere else relative to the page."""
    correction = _correction(page_size=(2480, 3507))

    assert correction.key != sidecar_key(_sidecar(page_size=(2481, 3507)))


def test_a_different_dpi_does_not_match():
    assert _correction(dpi=300).key != sidecar_key(_sidecar(dpi=200))


def test_a_rejected_correction_reports_itself_and_yields_no_category():
    rejected = _correction(category=None, rejection="multi_item")
    corrections = {rejected.key: rejected}
    sidecar = _sidecar()

    assert rejected.rejected
    assert rejected.effective_category is None

    report = match(corrections, [sidecar])

    assert report.rejected == {sidecar.item_id: rejected}
    assert report.labelled == {}
    assert report.unlabelled == []


def test_a_welded_pair_kept_as_one_is_an_ordinary_category_correction():
    """R18: what distinguishes the two is whether the person filed or rejected it."""
    kept = _correction(category="dress")

    assert not kept.rejected
    assert kept.effective_category == "dress"


# -- refusals ------------------------------------------------------------------


def test_one_invalid_category_raises_before_any_record_is_returned(tmp_path):
    path = _file(
        tmp_path,
        [
            _correction(category="top").to_dict(),
            _correction(bbox=(400, 900, 200, 300), category="jetpack").to_dict(),
        ],
    )

    with pytest.raises(CorrectionError, match="jetpack"):
        read_corrections(path)


def test_an_unknown_rejection_kind_raises(tmp_path):
    path = _file(tmp_path, [_correction(category=None, rejection="blurry").to_dict()])

    with pytest.raises(CorrectionError, match="blurry"):
        read_corrections(path)


def test_a_record_that_is_both_filed_and_rejected_raises(tmp_path):
    path = _file(tmp_path, [_correction(category="top", rejection="bad_crop").to_dict()])

    with pytest.raises(CorrectionError, match="both"):
        read_corrections(path)


def test_a_record_that_is_neither_filed_nor_rejected_raises(tmp_path):
    path = _file(tmp_path, [_correction(category=None).to_dict()])

    with pytest.raises(CorrectionError, match="neither"):
        read_corrections(path)


def test_a_record_naming_another_pdf_raises(tmp_path):
    """One file per PDF, so a record pasted into the wrong file mis-slots silently."""
    path = _file(tmp_path, [_correction(source_pdf="20260509081623").to_dict()], stem="20260509081050")

    with pytest.raises(CorrectionError, match="20260509081623"):
        read_corrections(path)


def test_two_records_for_the_same_item_raise_rather_than_last_winning(tmp_path):
    path = _file(
        tmp_path,
        [_correction(category="top").to_dict(), _correction(category="bottom").to_dict()],
    )

    with pytest.raises(CorrectionError, match="more than once"):
        read_corrections(path)


def test_a_record_with_no_recorded_scale_raises(tmp_path):
    """Geometry against an unknown page size or dpi cannot identify anything."""
    path = _file(tmp_path, [_correction(dpi=0).to_dict()])

    with pytest.raises(CorrectionError, match="dpi"):
        read_corrections(path)


def test_a_malformed_record_names_the_file_it_is_in(tmp_path):
    path = _file(tmp_path, [{"source_pdf": "20260509081050", "category": "hat"}])

    with pytest.raises(CorrectionError, match=f"20260509081050{CORRECTIONS_SUFFIX}"):
        read_corrections(path)


def test_a_file_that_is_not_a_record_list_names_the_file(tmp_path):
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    path.write_text(json.dumps([_correction().to_dict()]) + "\n", encoding="utf-8")

    with pytest.raises(CorrectionError, match=f"20260509081050{CORRECTIONS_SUFFIX}"):
        read_corrections(path)


def test_a_stem_holding_a_dot_is_not_truncated(tmp_path):
    """The stem is whatever precedes the suffix, taken whole — see `fantasy-smoke`."""
    path = _file(tmp_path, [_correction(source_pdf="set.2").to_dict()], stem="set.2")

    assert len(read_corrections(path)) == 1


def test_malformed_json_names_the_file(tmp_path):
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(CorrectionError, match=f"20260509081050{CORRECTIONS_SUFFIX}"):
        read_corrections(path)


def test_a_file_that_is_not_utf8_names_the_file_like_a_syntax_error_does(tmp_path):
    """Syntactically whole JSON, but one byte an editor wrote in Latin-1.

    A decode failure is not a `JSONDecodeError` and not an `OSError`, so unwrapped
    it slips through the per-PDF net the labelling server catches on and takes the
    whole batch down with it — and a whole-batch failure puts verdicts that were
    already written back on the wall as unfiled.
    """
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    path.write_bytes(b'{"corrections": [], "note": "caf\xe9"}\n')

    with pytest.raises(CorrectionError, match=f"20260509081050{CORRECTIONS_SUFFIX}"):
        read_corrections(path)


def test_a_pdf_with_no_corrections_file_is_ordinary(tmp_path):
    assert read_corrections(tmp_path / f"never-labelled{CORRECTIONS_SUFFIX}") == {}


def test_every_category_the_app_knows_is_fileable(tmp_path):
    """Read CATEGORIES at runtime: the slot list grows, and this must grow with it."""
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    records = [
        _correction(bbox=(index * 10, 0, 20, 20), category=category)
        for index, category in enumerate(CATEGORIES)
    ]
    write_corrections(path, records)

    assert len(read_corrections(path)) == len(CATEGORIES)


def test_every_rejection_kind_is_recordable(tmp_path):
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    records = [
        _correction(bbox=(index * 10, 0, 20, 20), category=None, rejection=kind)
        for index, kind in enumerate(REJECTION_KINDS)
    ]
    write_corrections(path, records)

    assert {c.rejection for c in read_corrections(path).values()} == set(REJECTION_KINDS)


# -- the guarantee KTD3 buys ---------------------------------------------------


def test_re_running_classify_leaves_the_correction_file_byte_identical(tmp_path):
    """Covers AE4 (R10): the suggestion may change, the human label may not.

    Corrections are never a field on the sidecar (KTD3), so `classify_sidecar`
    keeps its unconditional write and this holds structurally. Pinned anyway —
    the moment anything teaches a stage to touch a correction, this goes red.
    """
    path = tmp_path / f"20260509081050{CORRECTIONS_SUFFIX}"
    write_corrections(path, [_correction(category="bottom")])
    before = path.read_bytes()

    sidecar = _sidecar(category="hat")
    sidecar_path = tmp_path / "item.sidecar.json"
    sidecar.write(sidecar_path)

    # Re-run the classify stage over the corrected item with a shape that slots
    # it somewhere else entirely.
    classify_sidecar(sidecar, Shape(aspect=5.0, area_frac=0.02, centre_y=0.5))
    sidecar.write(sidecar_path)

    assert sidecar.category == "weapon"
    assert path.read_bytes() == before

    corrections = read_corrections(path)
    assert corrections[sidecar_key(Sidecar.read(sidecar_path))].category == "bottom"


def test_a_failed_write_leaves_the_previous_labelling_intact(tmp_path, monkeypatch):
    """The file is replaced, never truncated in place.

    It holds the one durable copy of judgement nothing can derive again — the
    reason these files are tracked at all — so a write that dies partway must
    leave the last good version where it was rather than a half-file.
    """
    path = corrections_path(tmp_path, "set")
    write_corrections(path, [_correction(source_pdf="set", category="hat")])
    before = path.read_bytes()

    def explode(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        write_corrections(path, [_correction(source_pdf="set", category="top")])

    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_failed_temp_write_leaves_nothing_behind_either(tmp_path, monkeypatch):
    """The other half of the same guarantee: a full disk fails mid-write.

    The tracked file surviving is the whole point of writing beside it, and that
    part already held. What did not is the temp file: one accumulates per attempt,
    beside the only durable copy of half an hour of judgement, until somebody has
    to work out which of those files is the labelling.
    """
    path = corrections_path(tmp_path, "set")
    write_corrections(path, [_correction(source_pdf="set", category="hat")])
    before = path.read_bytes()

    def fills_the_disk(self, *args, **kwargs):
        # Partial, the way ENOSPC leaves it: the file exists and is not a record.
        self.write_bytes(b'{\n  "corrections": [\n    {\n      "source')
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "write_text", fills_the_disk)
    with pytest.raises(OSError):
        write_corrections(path, [_correction(source_pdf="set", category="top")])

    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_stem_is_taken_off_a_scanners_filename_exactly_once(tmp_path):
    """The path is built from a stem as readily as from a filename.

    On a filename `Path.stem` agrees with `pdf_stem`, so the assertions that end
    in `.pdf` discriminate nothing. The one that does is the already-stemmed
    input: a stem may hold dots — scanners name files by timestamp — and
    `Path("album.2").stem` is `album`, which would route a book's filing to a
    file whose name disagrees with the records inside it. Stemming twice was the
    bug. A name ending `.pdf.pdf` is the case that shows why the stem is taken
    once here rather than guessed at again further down.
    """
    assert pdf_stem("album.2.pdf") == "album.2"
    assert pdf_stem(Path("/scans/album.2.pdf")) == "album.2"
    assert pdf_stem("2026-09-28 14.08.32.pdf") == "2026-09-28 14.08.32"
    assert pdf_stem("report.pdf.pdf") == "report.pdf"
    assert pdf_stem("album.2") == "album.2"
    assert corrections_path(tmp_path, pdf_stem("album.2.pdf")).name == f"album.2{CORRECTIONS_SUFFIX}"


def test_a_filing_on_a_dotted_stem_reads_back(tmp_path):
    """Write it the way the server does, then read it the way the build does.

    The loader takes the stem back off the filename and refuses a record naming
    another PDF, so a write that lands under a truncated name loses that whole
    book's labelling — silently at write time, and only visible the next time
    anything tries to read it.
    """
    correction = _correction(source_pdf="2026-09-28 14.08.32", category="hat")
    path = corrections_path(tmp_path, correction.source_pdf)

    write_corrections(path, [correction])

    assert read_corrections(path) == {correction.key: correction}
