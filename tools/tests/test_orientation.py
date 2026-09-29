"""Orientation detection, on synthetic pages and on the real sideways scans.

The synthetic pages pin the logic: a page whose content is a tall figure between
two bleeding border strips is exactly the shape the detector reasons about, and
rotating one is a ground truth nothing else can give us — the corpus contains no
upside-down page at all. The real-page tests pin the thing that actually matters,
that the two known sideways scans come out upright and a good page is left alone.
"""

import math
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from dressup_pipeline.extract import render_page
from dressup_pipeline.orientation import (
    correct_orientation,
    detect_orientation,
    measure_orientation,
)
from dressup_pipeline.triage import rotate_page
from synthetic import make_border_doll_page

CONTENT = Path(__file__).resolve().parents[2] / "content" / "source"
SIDEWAYS_PDF = CONTENT / "Fantasy" / "20260515170658.pdf"
UPRIGHT_PDF = CONTENT / "Fantasy" / "20260509075945.pdf"

needs_corpus = pytest.mark.skipif(
    not SIDEWAYS_PDF.exists(), reason="scanned corpus is not checked in; see content/README"
)


@pytest.fixture
def doll_page():
    """A base-body page: a figure between two border strips that bleed off the edge.

    Head-heavy and shoulder-wide on purpose — those are the two cues the which-way-up
    decision rests on.
    """
    return make_border_doll_page()


@pytest.fixture
def item_sheet_page():
    """An item sheet: small things scattered on white, with no dominant shape."""
    page = Image.new("RGB", (660, 700), "white")
    draw = ImageDraw.Draw(page)
    for row in range(4):
        for col in range(3):
            x, y = 60 + col * 200, 60 + row * 170
            draw.rectangle([x, y, x + 120, y + 110], fill=(180, 70 + 30 * col, 90 + 20 * row))
    return page


def test_upright_doll_page_needs_no_rotation(doll_page):
    assert detect_orientation(doll_page) == 0


@pytest.mark.parametrize("applied", [90, 180, 270])
def test_a_turned_page_asks_to_be_turned_back(doll_page, applied):
    turned = rotate_page(doll_page, applied)

    assert detect_orientation(turned) == (360 - applied) % 360


@pytest.mark.parametrize("applied", [90, 180, 270])
def test_correction_lands_a_turned_page_upright(doll_page, applied):
    corrected, degrees = correct_orientation(rotate_page(doll_page, applied))

    assert degrees == (360 - applied) % 360
    assert detect_orientation(corrected) == 0
    assert corrected.size == doll_page.size


def test_correction_returns_an_untouched_upright_page(doll_page):
    corrected, degrees = correct_orientation(doll_page)

    assert degrees == 0
    assert corrected is doll_page


def test_axis_score_reads_positive_for_portrait_content(doll_page):
    """The score is the module's own confidence, and callers triage on it."""
    assert measure_orientation(doll_page).axis_score > 0.5
    assert measure_orientation(rotate_page(doll_page, 90)).axis_score < -0.5


def test_head_cue_sits_in_the_upper_quarter_of_the_figure(doll_page):
    evidence = measure_orientation(doll_page)

    assert evidence.figure is not None
    assert evidence.head_position < 0.4


def test_scattered_items_are_left_alone_rather_than_guessed_at(item_sheet_page):
    """No dominant shape means no evidence, and no evidence must mean no rotation."""
    evidence = measure_orientation(item_sheet_page)

    assert evidence.degrees == 0
    assert abs(evidence.axis_score) < 0.5
    assert evidence.figure is None


def test_blank_page_is_upright_by_default():
    assert detect_orientation(Image.new("RGB", (660, 700), "white")) == 0


def test_decision_survives_a_change_of_render_resolution(doll_page):
    """A page must not change its mind between a 100 dpi proof and a 300 dpi run."""
    small = doll_page.resize((330, 350), Image.BILINEAR)
    large = doll_page.resize((1980, 2100), Image.BILINEAR)

    assert detect_orientation(small) == detect_orientation(large) == 0
    assert detect_orientation(rotate_page(large, 90)) == 270


@needs_corpus
@pytest.mark.parametrize("page_no", [0, 1])
def test_known_sideways_scan_is_detected_and_corrected(page_no):
    """The two pages that motivated this module: doll lying down, head to the left."""
    page = render_page(SIDEWAYS_PDF, page_no, dpi=100)

    corrected, degrees = correct_orientation(page)

    assert degrees == 90
    assert detect_orientation(corrected) == 0
    assert measure_orientation(corrected).axis_score > 0.5


@needs_corpus
def test_known_upright_scan_is_left_alone():
    """A detector that rotates good pages is worse than no detector."""
    page = render_page(UPRIGHT_PDF, 0, dpi=100)

    corrected, degrees = correct_orientation(page)

    assert degrees == 0
    assert corrected is page


@needs_corpus
def test_the_sideways_page_disagrees_with_the_upright_one_on_the_axis():
    """Both calls come from the same number, so the gap between them is the margin."""
    sideways = measure_orientation(render_page(SIDEWAYS_PDF, 0, dpi=100)).axis_score
    upright = measure_orientation(render_page(UPRIGHT_PDF, 0, dpi=100)).axis_score

    assert sideways < -0.5 < 0.5 < upright
    assert math.copysign(1, sideways) != math.copysign(1, upright)


def test_180_requires_a_clear_margin_not_just_crossing_a_half():
    """The 180 branch is the only one that can corrupt an upright page.

    No upside-down page exists in the corpus, so the gate is set above anything
    real (max head_position measured across 61 corpus figures was 0.416) rather
    than at the arithmetic midpoint.
    """
    from dressup_pipeline.orientation import HEAD_180_DECISION

    assert HEAD_180_DECISION > 0.5, "a 0.5 gate would act on ambiguous evidence"
    # A genuinely inverted figure mirrors to 1 - 0.416 = 0.584 at worst, so the
    # gate must stay below that or real inversions stop being detected.
    assert HEAD_180_DECISION < 0.584
