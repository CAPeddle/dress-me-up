"""Page-triage tests.

Synthetic pages pin the logic; the real-page tests at the bottom pin the
thresholds to the corpus they were calibrated on, because a synthetic doll can
be made to satisfy any threshold you like.
"""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dressup_pipeline.pagetype import (
    AMBIGUOUS_FLOATING,
    ITEM_SHEET_FLOATING,
    LOW_CONFIDENCE,
    PAGE_TYPES,
    classify_page,
    floating_regions,
)

PAGE_SIZE = (600, 900)
CORPUS = Path(__file__).resolve().parents[2] / "content" / "source"


# -- synthetic pages ------------------------------------------------------


def _blank_page() -> Image.Image:
    return Image.new("RGB", PAGE_SIZE, "white")


def _with_bleed(page: Image.Image) -> Image.Image:
    """Paint decoration that runs off the left and right edges."""
    draw = ImageDraw.Draw(page)
    draw.rectangle([0, 0, 70, PAGE_SIZE[1]], fill=(120, 160, 90))
    draw.rectangle([PAGE_SIZE[0] - 70, 0, PAGE_SIZE[0], PAGE_SIZE[1]], fill=(120, 160, 90))
    return page


@pytest.fixture
def item_sheet_page():
    """A dozen loose blobs on white — the canonical cuttable sheet."""
    page = _blank_page()
    draw = ImageDraw.Draw(page)
    for row in range(4):
        for col in range(3):
            x, y = 60 + col * 170, 60 + row * 200
            draw.rectangle([x, y, x + 110, y + 130], fill=(200, 60, 60))
    return page


@pytest.fixture
def base_body_page():
    """One tall doll-shaped mass in the middle, decoration bleeding off the sides."""
    page = _with_bleed(_blank_page())
    ImageDraw.Draw(page).rectangle([240, 200, 360, 700], fill=(90, 60, 40))
    return page


@pytest.fixture
def illustration_page():
    """A dense band of colour spanning the full page width, nothing floating."""
    page = _blank_page()
    ImageDraw.Draw(page).rectangle([0, 150, PAGE_SIZE[0], 750], fill=(70, 90, 150))
    return page


# -- floating_regions -----------------------------------------------------


def test_floating_regions_drop_decoration_that_bleeds_off_the_edge(base_body_page):
    """The two bleed stripes are regions; only the doll should survive."""
    from dressup_pipeline.extract import find_item_regions

    assert len(find_item_regions(base_body_page)) == 3
    assert len(floating_regions(base_body_page)) == 1


def test_floating_regions_keep_every_item_on_a_clean_sheet(item_sheet_page):
    assert len(floating_regions(item_sheet_page)) == 12


def test_margin_widens_what_counts_as_touching_the_edge():
    page = _blank_page()
    # Sits 25px in: clear of a 2% margin (12px), inside a 10% one (60px).
    ImageDraw.Draw(page).rectangle([25, 25, 200, 200], fill=(30, 30, 30))

    assert len(floating_regions(page, margin=0.02)) == 1
    assert floating_regions(page, margin=0.10) == []


def test_blank_page_floats_nothing():
    assert floating_regions(_blank_page()) == []


# -- classify_page --------------------------------------------------------


def test_every_verdict_is_a_known_page_type(item_sheet_page, base_body_page, illustration_page):
    pages = [_blank_page(), item_sheet_page, base_body_page, illustration_page]

    for page in pages:
        result = classify_page(page)
        assert result.page_type in PAGE_TYPES
        assert 0.0 <= result.confidence <= 1.0
        assert result.reason


def test_sheet_of_loose_items_is_an_item_sheet(item_sheet_page):
    result = classify_page(item_sheet_page)

    assert result.page_type == "item_sheet"
    assert result.floating_count >= ITEM_SHEET_FLOATING
    assert not result.needs_review


def test_doll_against_bleeding_decoration_is_a_base_body(base_body_page):
    result = classify_page(base_body_page)

    assert result.page_type == "base_body"
    assert result.floating_count < AMBIGUOUS_FLOATING
    assert result.total_count > result.floating_count  # the bleed was seen and dropped


def test_full_width_band_with_nothing_floating_is_an_illustration(illustration_page):
    result = classify_page(illustration_page)

    assert result.page_type == "illustration"
    assert result.floating_count == 0


def test_empty_page_is_blank():
    result = classify_page(_blank_page())

    assert result.page_type == "blank"
    assert result.floating_count == 0


def test_faint_speck_does_not_rescue_a_blank_page():
    page = _blank_page()
    ImageDraw.Draw(page).rectangle([300, 400, 320, 420], fill=(0, 0, 0))

    assert classify_page(page).page_type == "blank"


def test_middling_floating_count_is_flagged_rather_than_guessed_confidently():
    """Five items is the band where two-doll pages and touching items overlap."""
    page = _blank_page()
    draw = ImageDraw.Draw(page)
    for i in range(5):
        x = 60 + (i % 3) * 170
        y = 60 + (i // 3) * 300
        draw.rectangle([x, y, x + 110, y + 200], fill=(200, 60, 60))

    result = classify_page(page)

    assert AMBIGUOUS_FLOATING <= result.floating_count < ITEM_SHEET_FLOATING
    assert result.needs_review
    assert result.confidence <= LOW_CONFIDENCE
    assert "ambiguous" in result.reason or "Needs a look" in result.reason


def test_only_item_sheets_are_offered_to_extraction(item_sheet_page, illustration_page):
    assert classify_page(item_sheet_page).is_extractable
    assert not classify_page(illustration_page).is_extractable
    assert not classify_page(_blank_page()).is_extractable


def test_evidence_travels_with_the_verdict(item_sheet_page):
    """Re-tuning a threshold after a misfile needs the numbers, not just the label."""
    result = classify_page(item_sheet_page)

    assert result.ink_fraction > 0.0
    assert 0.0 < result.floating_area_fraction <= 1.0


# -- real pages -----------------------------------------------------------


def _render(pdf: str, page_no: int) -> Image.Image:
    """Render a corpus page, skipping when the scans are not checked out.

    `content/` is gitignored, so a clean clone has no corpus and these tests
    would otherwise fail for a reason that has nothing to do with the code.
    """
    path = CORPUS / pdf
    if not path.exists():
        pytest.skip(f"corpus page missing: {path}")

    from dressup_pipeline.extract import render_page

    # 100 DPI is enough to separate items and keeps the suite quick; the signals
    # are area fractions, so the verdict is stable across render scale.
    return render_page(path, page_no, dpi=100)


def test_real_base_body_page():
    page = _render("Fantasy/20260509075945.pdf", 0)

    result = classify_page(page)

    assert result.page_type == "base_body", result.reason
    assert result.floating_count < ITEM_SHEET_FLOATING


def test_real_item_sheet_page():
    page = _render("Fantasy/20260509081623.pdf", 0)

    result = classify_page(page)

    assert result.page_type == "item_sheet", result.reason
    assert result.floating_count >= ITEM_SHEET_FLOATING
    assert result.confidence > LOW_CONFIDENCE


def test_real_illustration_page_is_never_offered_to_extraction():
    """The costly error: a plate of posed characters mistaken for cuttable items."""
    page = _render("Fantasy/20260509080438.pdf", 0)

    result = classify_page(page)

    assert result.page_type == "illustration", result.reason
    assert not result.is_extractable


def test_real_illustration_that_looks_busy_is_still_not_an_item_sheet():
    """A row of fully-dressed fairies — the closest an illustration gets to a sheet."""
    page = _render("Fantasy w Boy/20260531091041.pdf", 4)

    result = classify_page(page)

    assert result.page_type == "illustration", result.reason


def test_real_rotated_base_body_still_reads_as_a_base_body():
    """Scanned sideways, so the doll lies horizontal. Area signals survive that."""
    page = _render("Fantasy/20260515170658.pdf", 0)

    result = classify_page(page)

    assert result.page_type == "base_body", result.reason


def test_real_two_doll_page_lands_in_the_ambiguous_band():
    """The page that made 6 the wrong threshold, and 8 the right one."""
    page = _render("Fantasy/20260515171101.pdf", 3)

    result = classify_page(page)

    assert AMBIGUOUS_FLOATING <= result.floating_count < ITEM_SHEET_FLOATING
    assert result.page_type == "base_body", result.reason
    assert result.needs_review
