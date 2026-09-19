"""Page triage — decide what a scanned page *is* before trying to cut it up.

The extractor was built assuming every page is a sheet of loose cut-outs. Only
about a third are. The rest are paper-doll base bodies and full-bleed
illustration plates, and running the segmenter over those yields cropped torsos
and chunks of scenery that QA then has to throw away. Classifying first lets
extraction route by page type instead of extracting first and apologising later.

Two measurements carry the whole decision:

*How many regions float clear of the page edge.* Page decoration bleeds off the
edge; real cut-outs sit in white space. Discarding border-touching regions
separates an item sheet from a base body or an illustration without looking at
the picture at all.

The size of that gap is per-book, not a property of the corpus — item-sheet
floating counts run 10-31 in Fantasy, 3-26 in Fantasy w Boy, and 4-6 in Knight,
because in the latter two the cut-outs touch each other on the paper and merge
into one region. Higher DPI does not recover them (tested 100/150/200/300): the
contact is physical. So 13 of 35 real item sheets sit at or below
ITEM_SHEET_FLOATING, which is why the ambiguous band below it has to stay
low-confidence rather than guessing.

*How much of the page that floating ink covers.* Base bodies and illustrations
both produce few floating regions, so the count alone cannot separate them. But
a base body's doll is a single large mass floating in the middle of the page,
while an illustration's figures are welded into the full-bleed art and float
nothing bigger than a stray highlight. Measured over the 101-page hand-labelled
corpus, floating area covers <=3.0% of an illustration and >=3.9% of every base
body bar one.

Calibrated against that corpus: 95/101 correct — an IN-SAMPLE figure, since every
threshold here was fitted to the same pages it was then scored on. Independent
re-scoring against the hand survey gave 96/102, and splitting that by book is
what the aggregate hides:

    Fantasy         60/62 = 96.8%   <- the book the thresholds came from
    Fantasy w Boy   35/36 = 97.2%
    Knight           1/4  = 25.0%   <- every item sheet lost

Item-sheet precision is 31/31 but recall is 31/35: what this module *accepts* is
trustworthy, what it *rejects* is not. Zero illustrations were called item sheets
— the expensive direction, since it feeds uncuttable art into the catalog — but
that held by luck rather than design: FLOATING_MASS_FRAC sits about 0.0035 from
the nearest counterexample. Nor is `needs_review` usable as a review queue; 21 of
its 24 flags landed on correct pages while 3 of the 6 real errors rode at
confidence 0.75-0.80.

Treat this as usable in item_sheet-only mode, with a human confirming every
non-item_sheet verdict on books other than Fantasy. See docs/CONTENT-STRUCTURE.md
for the fix order, and docs/solutions/best-practices/ for why a threshold fitted
to one source should not be quoted as a property of the corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from .extract import DEFAULT_PAPER_THRESHOLD, find_item_regions
from .models import BBox

PAGE_TYPES = ("base_body", "item_sheet", "illustration", "blank")

# Fraction of page width/height treated as the bleed zone. A region overlapping
# it is decoration running off the edge, not an item.
DEFAULT_MARGIN = 0.02

# A page with this many floating regions is a sheet of cut-outs and nothing else.
ITEM_SHEET_FLOATING = 8
# Below this, floating regions are too few to mean anything on their own. In
# between, the count is real signal but not proof: a base page holding two dolls
# produced 6, and item sheets whose items touch each other produce 4-7.
AMBIGUOUS_FLOATING = 4

# Share of the page covered by floating ink. Above it there is a doll (or items)
# floating clear of the decoration; below it the page is one welded illustration.
# The corpus gap is 3.0% to 3.9%, so this threshold is tight by construction —
# widening it starts calling illustrations base bodies.
FLOATING_MASS_FRAC = 0.035

# Ink coverage above which a page is too busy to be a doll on a decorative
# ground. Only used to break the ambiguous band, where illustrations are already
# ruled out by their floating mass.
BUSY_INK_FRAC = 0.20

# Below this there is nothing on the page worth routing anywhere.
BLANK_INK_FRAC = 0.02

# Anything at or below this is a guess the caller should not act on unreviewed.
LOW_CONFIDENCE = 0.4


@dataclass(frozen=True)
class PageClassification:
    """What a page is, how sure we are, and the evidence behind both.

    The measurements ride along with the verdict on purpose: when triage gets a
    page wrong, the numbers are what let a human re-tune a threshold instead of
    re-deriving the whole signal from the image.
    """

    page_type: str
    confidence: float
    floating_count: int
    total_count: int
    reason: str
    ink_fraction: float
    floating_area_fraction: float

    @property
    def needs_review(self) -> bool:
        """True when the verdict is a coin-flip dressed as an answer."""
        return self.confidence <= LOW_CONFIDENCE

    @property
    def is_extractable(self) -> bool:
        """Only item sheets hold cuttable items; everything else is a dead end."""
        return self.page_type == "item_sheet"


def floating_regions(image: Image.Image, margin: float = DEFAULT_MARGIN) -> list[BBox]:
    """Regions that clear the page margin on all four sides.

    A region overlapping the margin is almost always background art bleeding off
    the edge, since scans are trimmed to the page. Dropping those is what turns
    an unusable region count into the corpus's strongest page-type signal.
    """
    boxes = find_item_regions(image)
    return [b for b in boxes if _is_floating(b, image.width, image.height, margin)]


def classify_page(image: Image.Image, margin: float = DEFAULT_MARGIN) -> PageClassification:
    """Decide which of `PAGE_TYPES` a rendered page belongs to."""
    boxes = find_item_regions(image)
    floating = [b for b in boxes if _is_floating(b, image.width, image.height, margin)]

    page_area = image.width * image.height
    ink = _ink_fraction(image)
    mass = sum(b.area for b in floating) / page_area if page_area else 0.0

    page_type, confidence, reason = _verdict(len(floating), ink, mass)
    return PageClassification(
        page_type=page_type,
        confidence=confidence,
        floating_count=len(floating),
        total_count=len(boxes),
        reason=reason,
        ink_fraction=ink,
        floating_area_fraction=mass,
    )


# -- internals ------------------------------------------------------------


def _is_floating(box: BBox, width: int, height: int, margin: float) -> bool:
    dx, dy = margin * width, margin * height
    return (
        box.x > dx
        and box.y > dy
        and box.x + box.w < width - dx
        and box.y + box.h < height - dy
    )


def _ink_fraction(image: Image.Image, paper_threshold: int = DEFAULT_PAPER_THRESHOLD) -> float:
    """Share of the page darker than paper — how much of it carries any art."""
    grey = np.asarray(image.convert("L"))
    if grey.size == 0:
        return 0.0
    return float((grey < paper_threshold).mean())


def _verdict(floating: int, ink: float, mass: float) -> tuple[str, float, str]:
    """Map the two measurements onto a page type, a confidence and an argument.

    Ordered cheapest-and-surest first, so the ambiguous band is only ever reached
    by pages that no confident rule claimed.
    """
    if ink < BLANK_INK_FRAC:
        return "blank", 0.9, f"only {ink:.1%} of the page carries ink"

    if floating >= ITEM_SHEET_FLOATING:
        # More floating regions means more of the page is unambiguously loose
        # items, so the count doubles as the strength of the claim.
        confidence = min(0.95, 0.75 + 0.02 * (floating - ITEM_SHEET_FLOATING))
        return (
            "item_sheet",
            confidence,
            f"{floating} regions float clear of the page edge — a sheet of loose cut-outs",
        )

    if floating >= AMBIGUOUS_FLOATING:
        if mass < FLOATING_MASS_FRAC:
            return (
                "illustration",
                LOW_CONFIDENCE,
                f"{floating} floating regions but they cover only {mass:.1%} of the page — "
                "too little loose art to be items, so treating it as an illustration",
            )
        if ink >= BUSY_INK_FRAC:
            return (
                "item_sheet",
                LOW_CONFIDENCE,
                f"{floating} floating regions is short of {ITEM_SHEET_FLOATING}, but ink covers "
                f"{ink:.1%} of the page — likely items that touch each other. Needs a look.",
            )
        return (
            "base_body",
            LOW_CONFIDENCE,
            f"{floating} floating regions over only {ink:.1%} ink — likelier a page of one or "
            "two dolls than a sheet of items, but the count is in the ambiguous band.",
        )

    if mass >= FLOATING_MASS_FRAC:
        return (
            "base_body",
            0.75,
            f"just {floating} floating region(s), but they cover {mass:.1%} of the page — "
            "a doll floating clear of full-bleed decoration",
        )

    return (
        "illustration",
        0.8,
        f"{floating} floating region(s) covering {mass:.1%} of the page against {ink:.1%} ink — "
        "art welded to the page edge, nothing cuttable",
    )
