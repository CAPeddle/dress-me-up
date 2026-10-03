"""Base Bodies cut from decorated pages named in a tracked list.

The synthetic pages here are built the way the scans are — a filled doll on a
smooth colour wash with a border strip off one edge — because that is the case
that separates local-contrast segmentation from the paper threshold the item
extractor uses: a threshold welds the doll into the wash and finds nothing.
"""

import json

import numpy as np
import pytest
from PIL import Image

from dressup_pipeline.bodies import (
    BodyEntry,
    BodyError,
    build_bodies,
    choose_figure,
    cut_body,
    load_body_list,
    render_dpi,
    resolve_pdf,
    shared_dpi,
)
from dressup_pipeline.extract import DEFAULT_DPI, render_page
from dressup_pipeline.models import BBox
from dressup_pipeline.orientation import DETAIL_WINDOW, find_figure_regions
from dressup_pipeline.triage import TRIAGE_DPI, Manifest, PageVerdict, manifest_path
from synthetic import make_doll_page

ONE_DOLL = (260, 60, 340, 760)
LEFT_DOLL = (170, 60, 250, 760)
RIGHT_DOLL = (370, 90, 450, 700)  # a touch shorter: 610 tall against 700


def entry(**overrides):
    fields = dict(id="fantasy-x-p00", pdf="x.pdf", page=0, group="fantasy", region=None)
    fields.update(overrides)
    return BodyEntry(**fields)


def find_figures(page):
    """Just the boxes of `find_figure_regions`, which is all these tests read."""
    return [box for box, _ in find_figure_regions(page)]


def write_list(path, bodies):
    path.write_text(json.dumps({"version": 1, "bodies": bodies}), encoding="utf-8")
    return path


def write_manifest(triage_dir, pdf, rotations):
    triage_dir.mkdir(parents=True, exist_ok=True)
    pages = [
        PageVerdict(page=i, rotation=rot, verdict="base_body", confidence=0.9, reason="test")
        for i, rot in enumerate(rotations)
    ]
    manifest = Manifest(pdf=pdf.name, source_folder=pdf.parent.name, triage_dpi=TRIAGE_DPI, pages=pages)
    manifest.write(manifest_path(triage_dir, pdf))
    return manifest


def save_pdf(path, *pages):
    first, *rest = pages
    first.save(path, save_all=bool(rest), append_images=list(rest))
    return path


def write_sidecar(root, item_id, dpi, group=None):
    root.mkdir(parents=True, exist_ok=True)
    data = {
        "item_id": item_id, "source_pdf": "items.pdf", "page": 0,
        "bbox": {"x": 0, "y": 0, "w": 10, "h": 10}, "image": f"{item_id}.png", "dpi": dpi,
        "group": group,
    }
    (root / f"{item_id}.sidecar.json").write_text(json.dumps(data), encoding="utf-8")


# Local contrast is measured over a window, so a figure's mask straddles its
# outline by half a window on every side; the box is padded by that much.
PAD = DETAIL_WINDOW // 2


def assert_box_close(box, expected, tolerance=PAD + 2):
    left, top, right, bottom = expected
    assert abs(box.x - left) <= tolerance, (box, expected)
    assert abs(box.y - top) <= tolerance, (box, expected)
    assert abs(box.x + box.w - right) <= tolerance, (box, expected)
    assert abs(box.y + box.h - bottom) <= tolerance, (box, expected)


def assert_size_matches_doll(image, doll):
    """A cut is the doll's size plus the pad on both sides."""
    left, top, right, bottom = doll
    assert abs(image.width - (right - left)) <= 2 * PAD + 2, (image.size, doll)
    assert abs(image.height - (bottom - top)) <= 2 * PAD + 2, (image.size, doll)


# -- finding and cutting one doll -------------------------------------------


def test_one_doll_on_a_colour_wash_is_found_where_it_was_drawn():
    page = make_doll_page(dolls=(ONE_DOLL,))

    figures = find_figures(page)

    assert len(figures) == 1
    assert_box_close(figures[0], ONE_DOLL)


def test_figure_boxes_are_in_the_pixels_of_the_image_given():
    """Orientation measures at a fixed working size; the caller gets its own pixels back."""
    small = make_doll_page(size=(600, 800), dolls=(ONE_DOLL,))
    big = small.resize((1800, 2400), Image.BILINEAR)

    (box,) = find_figures(big)

    assert_box_close(box, tuple(v * 3 for v in ONE_DOLL), tolerance=3 * PAD + 6)


def test_cut_body_is_opaque_on_the_doll_and_transparent_on_the_wash():
    page = make_doll_page(dolls=(ONE_DOLL,))
    ((box, mask),) = find_figure_regions(page)

    body = cut_body(page, box, mask)

    assert body.mode == "RGBA"
    assert body.size == (box.w, box.h)
    alpha = np.asarray(body)[:, :, 3]
    left, top, right, bottom = ONE_DOLL
    cx = (left + right) // 2 - box.x
    torso_y = top + int((bottom - top) * 0.35) - box.y
    legs_y = top + int((bottom - top) * 0.8) - box.y
    assert alpha[torso_y, cx] == 255
    # Beside and between the legs is inside the box but on the wash.
    assert alpha[legs_y, 2] == 0 and alpha[legs_y, -3] == 0 and alpha[legs_y, cx] == 0


def test_figures_come_back_left_to_right():
    page = make_doll_page(dolls=(RIGHT_DOLL, LEFT_DOLL))

    figures = find_figures(page)

    assert [f.x for f in figures] == sorted(f.x for f in figures)
    assert len(figures) == 2


# -- choosing among figures ---------------------------------------------------


def test_two_similar_dolls_without_an_ordinal_is_refused_by_name():
    figures = [BBox(100, 50, 80, 700), BBox(400, 80, 80, 600)]  # 600 >= 0.8 * 700

    with pytest.raises(BodyError, match="fantasy-x-p00"):
        choose_figure(figures, entry())


def test_a_clearly_smaller_second_figure_does_not_block_the_tallest():
    figures = [BBox(100, 50, 80, 700), BBox(400, 80, 80, 400)]

    assert choose_figure(figures, entry()) == figures[0]


def test_region_ordinal_picks_that_figure_left_to_right():
    figures = [BBox(100, 50, 80, 700), BBox(400, 80, 80, 690)]

    assert choose_figure(figures, entry(region=1)) == figures[1]


def test_region_ordinal_out_of_range_is_refused_by_name():
    with pytest.raises(BodyError, match="fantasy-x-p00"):
        choose_figure([BBox(100, 50, 80, 700)], entry(region=3))


def test_no_figures_is_refused_naming_id_and_page():
    with pytest.raises(BodyError) as excinfo:
        choose_figure([], entry(page=4))

    assert "fantasy-x-p00" in str(excinfo.value)
    assert "page 4" in str(excinfo.value)


# -- the list ----------------------------------------------------------------


def test_load_body_list_reads_entries_in_order(tmp_path):
    path = write_list(tmp_path / "bodies.json", [
        {"id": "b", "pdf": "x.pdf", "page": 1, "group": "fantasy", "region": None},
        {"id": "a", "pdf": "y.pdf", "page": 0, "group": "knight", "region": 1},
    ])

    entries = load_body_list(path)

    assert [e.id for e in entries] == ["b", "a"]
    assert entries[1] == BodyEntry(id="a", pdf="y.pdf", page=0, group="knight", region=1)


def test_load_body_list_rejects_duplicate_ids(tmp_path):
    path = write_list(tmp_path / "bodies.json", [
        {"id": "same", "pdf": "x.pdf", "page": 0, "group": "fantasy", "region": None},
        {"id": "same", "pdf": "x.pdf", "page": 1, "group": "fantasy", "region": None},
    ])

    with pytest.raises(BodyError, match="same"):
        load_body_list(path)


def test_load_body_list_rejects_unknown_groups(tmp_path):
    path = write_list(tmp_path / "bodies.json", [
        {"id": "odd", "pdf": "x.pdf", "page": 0, "group": "pirate", "region": None},
    ])

    with pytest.raises(BodyError, match="odd"):
        load_body_list(path)


def test_resolve_pdf_searches_the_source_root_recursively(tmp_path):
    pdf = tmp_path / "source" / "Fantasy" / "x.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"")

    assert resolve_pdf(entry(pdf="x.pdf"), tmp_path / "source") == pdf


def test_resolve_pdf_names_the_missing_pdf(tmp_path):
    (tmp_path / "source").mkdir()

    with pytest.raises(BodyError, match="missing.pdf"):
        resolve_pdf(entry(pdf="missing.pdf"), tmp_path / "source")


# -- dpi ---------------------------------------------------------------------


def test_shared_dpi_is_the_one_value_every_sidecar_agrees_on(tmp_path):
    write_sidecar(tmp_path / "sidecars", "a", 300)
    write_sidecar(tmp_path / "sidecars", "b", 300)

    assert shared_dpi(tmp_path / "sidecars") == 300


def test_shared_dpi_refuses_disagreeing_sidecars_naming_the_odd_one(tmp_path):
    write_sidecar(tmp_path / "sidecars", "a", 300)
    write_sidecar(tmp_path / "sidecars", "b", 300)
    write_sidecar(tmp_path / "sidecars", "odd", 150)

    with pytest.raises(BodyError) as excinfo:
        shared_dpi(tmp_path / "sidecars")

    message = str(excinfo.value)
    assert "odd" in message and "150" in message and "300" in message


def test_shared_dpi_treats_an_unrecorded_dpi_as_a_disagreement(tmp_path):
    write_sidecar(tmp_path / "sidecars", "new", 300)
    write_sidecar(tmp_path / "sidecars", "old", 0)

    with pytest.raises(BodyError, match="old"):
        shared_dpi(tmp_path / "sidecars")


def test_shared_dpi_falls_back_to_the_extractor_default_with_no_sidecars(tmp_path):
    (tmp_path / "sidecars").mkdir()

    assert shared_dpi(tmp_path / "sidecars") == DEFAULT_DPI


def test_shared_dpi_asks_only_the_groups_a_filtered_build_selected(tmp_path):
    """A group the build leaves out is not part of the scale it writes."""
    write_sidecar(tmp_path / "sidecars", "fantasy-a", 72, group="fantasy")
    write_sidecar(tmp_path / "sidecars", "knight-a", 300, group="knight")

    assert shared_dpi(tmp_path / "sidecars", groups={"fantasy"}) == 72
    assert shared_dpi(tmp_path / "sidecars", groups={"knight"}) == 300
    with pytest.raises(BodyError):
        shared_dpi(tmp_path / "sidecars", groups={"fantasy", "knight"})


def test_render_dpi_scopes_the_unrecorded_dpi_refusal_to_the_selected_groups(tmp_path):
    """Scoping must not let a legacy sidecar inside the selection through."""
    write_sidecar(tmp_path / "sidecars", "legacy", 0, group="fantasy")
    write_sidecar(tmp_path / "sidecars", "knight-a", 300, group="knight")

    assert render_dpi(tmp_path / "sidecars", groups={"knight"}) == 300
    with pytest.raises(BodyError, match="extract_pdf.py"):
        render_dpi(tmp_path / "sidecars", groups={"fantasy"})


# -- the whole stage ----------------------------------------------------------


@pytest.fixture
def two_page_book(tmp_path):
    """A two-page PDF (one doll each), its manifest, a sidecar root at 72 dpi."""
    source = tmp_path / "source" / "Fantasy"
    source.mkdir(parents=True)
    pdf = save_pdf(source / "book.pdf", make_doll_page(dolls=(ONE_DOLL,)), make_doll_page(dolls=(LEFT_DOLL,)))
    write_manifest(tmp_path / "triage", pdf, [0, 0])
    write_sidecar(tmp_path / "sidecars", "item", 72)
    return pdf


def test_build_bodies_cuts_each_listed_page_in_list_order(tmp_path, two_page_book):
    listing = write_list(tmp_path / "list.json", [
        {"id": "fantasy-book-p01", "pdf": "book.pdf", "page": 1, "group": "fantasy", "region": None},
        {"id": "fantasy-book-p00", "pdf": "book.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    cuts, dpi = build_bodies(load_body_list(listing), tmp_path / "source", tmp_path / "sidecars", tmp_path / "triage")

    assert dpi == 72
    assert [c.id for c in cuts] == ["fantasy-book-p01", "fantasy-book-p00"]
    assert [c.page for c in cuts] == [1, 0]
    assert all(c.source_pdf == "book.pdf" and c.group == "fantasy" for c in cuts)
    assert cuts[1].image.mode == "RGBA"
    assert_size_matches_doll(cuts[1].image, ONE_DOLL)


def test_build_bodies_applies_the_manifest_rotation(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    upright = make_doll_page(dolls=(ONE_DOLL,))
    sideways = upright.rotate(90, expand=True)  # counter-clockwise: needs 90 clockwise back
    pdf = save_pdf(source / "turned.pdf", sideways)
    write_manifest(tmp_path / "triage", pdf, [90])
    write_sidecar(tmp_path / "sidecars", "item", 72)
    listing = write_list(tmp_path / "list.json", [
        {"id": "turned-p00", "pdf": "turned.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    (cut,), _ = build_bodies(load_body_list(listing), source, tmp_path / "sidecars", tmp_path / "triage")

    assert cut.image.height > cut.image.width


def test_build_bodies_with_an_empty_list_does_nothing(tmp_path):
    listing = write_list(tmp_path / "list.json", [])
    (tmp_path / "sidecars").mkdir()

    cuts, dpi = build_bodies(load_body_list(listing), tmp_path / "source", tmp_path / "sidecars", tmp_path / "triage")

    assert cuts == []
    assert dpi == DEFAULT_DPI


def test_build_bodies_refuses_a_page_with_no_figure_rather_than_writing_nothing(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    pdf = save_pdf(source / "blank.pdf", make_doll_page(dolls=()))
    write_manifest(tmp_path / "triage", pdf, [0])
    write_sidecar(tmp_path / "sidecars", "item", 72)
    listing = write_list(tmp_path / "list.json", [
        {"id": "blank-p00", "pdf": "blank.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    with pytest.raises(BodyError) as excinfo:
        build_bodies(load_body_list(listing), source, tmp_path / "sidecars", tmp_path / "triage")

    assert "blank-p00" in str(excinfo.value) and "page 0" in str(excinfo.value)


def test_build_bodies_refuses_a_missing_pdf_by_name(tmp_path, two_page_book):
    listing = write_list(tmp_path / "list.json", [
        {"id": "ghost-p00", "pdf": "ghost.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    with pytest.raises(BodyError, match="ghost.pdf"):
        build_bodies(load_body_list(listing), tmp_path / "source", tmp_path / "sidecars", tmp_path / "triage")


def test_build_bodies_refuses_a_page_with_no_manifest_and_says_how_to_make_one(tmp_path, two_page_book):
    listing = write_list(tmp_path / "list.json", [
        {"id": "fantasy-book-p00", "pdf": "book.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    with pytest.raises(BodyError, match="triage_pages.py"):
        build_bodies(load_body_list(listing), tmp_path / "source", tmp_path / "sidecars", tmp_path / "empty-triage")


def test_build_bodies_two_dolls_need_an_ordinal_and_honour_it(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    pdf = save_pdf(source / "pair.pdf", make_doll_page(dolls=(LEFT_DOLL, RIGHT_DOLL)))
    write_manifest(tmp_path / "triage", pdf, [0])
    write_sidecar(tmp_path / "sidecars", "item", 72)

    ambiguous = write_list(tmp_path / "ambiguous.json", [
        {"id": "pair-p00", "pdf": "pair.pdf", "page": 0, "group": "fantasy", "region": None},
    ])
    with pytest.raises(BodyError, match="pair-p00"):
        build_bodies(load_body_list(ambiguous), source, tmp_path / "sidecars", tmp_path / "triage")

    named = write_list(tmp_path / "named.json", [
        {"id": "pair-p00-right", "pdf": "pair.pdf", "page": 0, "group": "fantasy", "region": 1},
    ])
    (cut,), _ = build_bodies(load_body_list(named), source, tmp_path / "sidecars", tmp_path / "triage")

    assert_size_matches_doll(cut.image, RIGHT_DOLL)


def test_build_bodies_refuses_disagreeing_sidecar_dpis(tmp_path, two_page_book):
    write_sidecar(tmp_path / "sidecars", "stray", 300)
    listing = write_list(tmp_path / "list.json", [
        {"id": "fantasy-book-p00", "pdf": "book.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    with pytest.raises(BodyError, match="stray"):
        build_bodies(load_body_list(listing), tmp_path / "source", tmp_path / "sidecars", tmp_path / "triage")


def test_rendering_back_the_synthetic_pdf_keeps_the_page_size(tmp_path, two_page_book):
    """Guards the fixture: PIL writes at 72 dpi, so 72 dpi renders pixel-for-pixel."""
    assert render_page(two_page_book, 0, dpi=72).size == (600, 800)


def test_shared_dpi_reports_a_corpus_that_records_no_dpi_at_all_as_zero(tmp_path):
    """0 is a true statement about the corpus; the catalog's scale block says it."""
    write_sidecar(tmp_path / "sidecars", "old-a", 0)
    write_sidecar(tmp_path / "sidecars", "old-b", 0)

    assert shared_dpi(tmp_path / "sidecars") == 0


def test_render_dpi_refuses_a_corpus_where_nothing_records_a_dpi(tmp_path):
    """Reporting 0 is honest; rendering at it is not — PyMuPDF reads it as 72."""
    write_sidecar(tmp_path / "sidecars", "old-a", 0)
    write_sidecar(tmp_path / "sidecars", "old-b", 0)

    with pytest.raises(BodyError) as excinfo:
        render_dpi(tmp_path / "sidecars")

    message = str(excinfo.value)
    assert "2" in message and "extract_pdf.py" in message


def test_build_bodies_refuses_to_cut_a_body_at_an_unrecorded_dpi(tmp_path):
    source = tmp_path / "source" / "Fantasy"
    source.mkdir(parents=True)
    pdf = save_pdf(source / "book.pdf", make_doll_page(dolls=(ONE_DOLL,)))
    write_manifest(tmp_path / "triage", pdf, [0])
    write_sidecar(tmp_path / "sidecars", "legacy", 0)
    listing = write_list(tmp_path / "list.json", [
        {"id": "fantasy-book-p00", "pdf": "book.pdf", "page": 0, "group": "fantasy", "region": None},
    ])

    with pytest.raises(BodyError, match="extract_pdf.py"):
        build_bodies(load_body_list(listing), tmp_path / "source", tmp_path / "sidecars", tmp_path / "triage")


def test_resolve_pdf_names_both_folders_when_a_basename_is_ambiguous(tmp_path):
    for folder in ("Fantasy", "Knight"):
        pdf = tmp_path / "source" / folder / "x.pdf"
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"")

    with pytest.raises(BodyError) as excinfo:
        resolve_pdf(entry(pdf="x.pdf"), tmp_path / "source")

    message = str(excinfo.value)
    assert "Fantasy" in message and "Knight" in message


def test_resolve_pdf_treats_the_basename_literally_not_as_a_glob(tmp_path):
    """A hand-authored name is a filename; `*.pdf` names no file that exists."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "x.pdf").write_bytes(b"")

    with pytest.raises(BodyError) as excinfo:
        resolve_pdf(entry(pdf="*.pdf"), source)

    assert "not found" in str(excinfo.value)
