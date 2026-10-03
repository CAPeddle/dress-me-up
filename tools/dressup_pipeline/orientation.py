"""Stage 0 — put a scanned page the right way up before anything else reads it.

Some pages went through the scanner sideways. The PDF carries no rotation
metadata to lean on — every page reports rotation 0 inside a portrait mediabox —
so the evidence has to come from the pixels, and the pixel evidence worth
trusting is the *shape* of the artwork. A paper-doll page is built out of tall
things: a standing doll, a strip of border decoration running down one edge. Turn
the page on its side and every one of them lies down.

Two decisions are made separately, because they are not equally reliable:

**Which axis** — aggregate the elongation of the page's objects, weighted by
area. Portrait-dominant content means the page is already on its correct axis.
This decision is the confident one: over 104 corpus pages the two sideways scans
score -1.1 and -1.4 while no upright page falls below -0.05, so the ±0.5 gate has
a wide empty band on either side of it.

**Which way up** — only a figure can answer that, and only a figure is asked. A
paper doll is widest about a quarter of the way down from the head (shoulders and
arms) and darkest there too (hair, eyes, mouth), while the leg half is thin and
pale. A page with no figure on it — an item sheet, an illustration plate — holds
no evidence either way. On its correct axis such a page is reported upright
rather than guessed at; already known to be sideways, it is turned 90° clockwise,
because a coin flip still beats leaving a page the extractor can read nothing
from.

Objects are found by *local contrast* rather than by thresholding brightness. The
decorative backgrounds are smooth colour washes that a brightness threshold
swallows the doll into; a standard-deviation filter sees straight through them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

# Pixels at or above this luminance are paper, not artwork. Imported rather than
# restated so that "the page content" cannot come to mean one thing here and
# another in extract.py.
from .extract import DEFAULT_PAPER_THRESHOLD as PAPER_THRESHOLD
from .models import BBox

# Everything below is measured at this longest-side pixel size, so a page renders
# to the same decision at 100 dpi as at 300. The morphology below uses fixed
# pixel structuring elements, and at much less than this the closing starts
# welding a doll onto the decoration behind it.
WORK_SIZE = 1200

# Local standard deviation over this window separates drawn artwork from the
# smooth background washes. 6 grey levels is well above scanner noise on these
# scans and well below the contrast of any printed edge.
DETAIL_WINDOW = 9
DETAIL_STD = 6.0

# An object smaller than this share of the page is a speck, a star in the
# background, or a scanner mote.
MIN_OBJECT_AREA_FRAC = 0.004
# Cropping to the scan needs a looser floor than segmentation does — it only has
# to outvote the dust the scanner leaves in the blank part of the mediabox.
MIN_CONTENT_AREA_FRAC = 0.0005

# How far the area-weighted elongation must lean before the axis is called. The
# corpus leaves a wide empty band either side of this: sideways pages sit near
# -1.2, upright doll pages above +0.8, and figureless pages near 0.
AXIS_DECISION = 0.5

# A figure is elongated but not a sliver: a doll runs about 5:1, while a fold
# line or a scan edge artifact runs 50:1 and carries no anatomy.
FIGURE_MIN_ELONGATION = 2.5
FIGURE_MAX_ELONGATION = 10.0
# ...and it occupies real estate. Slivers pass the elongation test on shape alone.
FIGURE_MIN_BOX_FRAC = 0.05
# Decoration bleeds off the page edge; a doll floats clear of it *sideways*.
# A doll may well run right off the top and bottom — in several books it fills
# the page height — so only the short axis of a figure is checked.
BORDER_MARGIN_FRAC = 0.02

# How far the head cue must sit from the midpoint before which-end is called.
# Observed heads land near 0.3; the margin exists so an ambiguous figure declines
# to answer instead of flipping a good page.
HEAD_DECISION = 0.06

# Returning 180 is the only way this module can corrupt an upright page, and no
# upside-down page exists in the corpus to validate it against. So the bar for
# 180 is deliberately higher than the bar for 0: measured over all 61 figures in
# the corpus, head_position spans 0.239-0.416, meaning a genuinely inverted page
# would score >= 0.584. Gating at 0.56 keeps every inverted page while leaving a
# 0.14-wide dead band above anything real, where the answer falls back to 0.
HEAD_180_DECISION = 0.56


@dataclass(frozen=True)
class _Object:
    """One piece of artwork on the page, in working-scale pixels."""

    x: int
    y: int
    w: int
    h: int
    area: float
    touches_left_or_right: bool
    touches_top_or_bottom: bool
    mask: np.ndarray  # boolean, cropped to the bounding box
    grey: np.ndarray  # luminance under the same crop

    @property
    def elongation(self) -> float:
        """Long side over short side, always >= 1."""
        return max(self.w, self.h) / max(1, min(self.w, self.h))

    @property
    def upright(self) -> bool:
        return self.h >= self.w


@dataclass(frozen=True)
class Orientation:
    """Why `detect_orientation` answered the way it did.

    Exposed because a page this module declines to rotate and a page it is sure
    about look identical from the outside, and triage wants to tell them apart.
    """

    degrees: int
    axis_score: float
    """Area-weighted mean of log(height/width) over the page's objects.

    Positive means portrait-dominant content, negative landscape-dominant, and
    near zero means the page is a scatter of items with no dominant shape.
    """

    head_position: float | None
    """Where the figure's head sits along its long axis, 0 (start) to 1 (end).

    None when no figure was found, which is the normal case for item sheets.
    """

    figure: BBox | None
    """The figure's bounding box in working-scale pixels, for debugging."""


def detect_orientation(image: Image.Image) -> int:
    """Degrees the image must be rotated CLOCKWISE to become upright.

    One of 0, 90, 180, 270. Returns 0 whenever the evidence is weak: a detector
    that rotates a good page costs more than one that misses a bad one, so an
    item sheet — which carries no orientation evidence at all — is always left
    alone. 180 is only ever returned for a page with a figure on it, and no
    upside-down page exists in the corpus to confirm it against; see the tests,
    which check it against pages turned over synthetically.
    """
    return measure_orientation(image).degrees


def correct_orientation(image: Image.Image) -> tuple[Image.Image, int]:
    """Rotate `image` upright; return it alongside the rotation that was applied."""
    degrees = detect_orientation(image)
    if degrees == 0:
        return image, 0
    # PIL rotates counter-clockwise, and our contract is clockwise degrees.
    return image.rotate(-degrees, expand=True), degrees


def measure_orientation(image: Image.Image) -> Orientation:
    """Full evidence behind the orientation call — see `Orientation`."""
    grey = _page_content(image)
    if grey is None:
        return Orientation(0, 0.0, None, None)

    objects = _find_objects(grey)
    axis = _axis_score(objects)
    if abs(axis) < AXIS_DECISION:
        return Orientation(0, axis, None, None)

    sideways = axis < 0
    figure = _find_figure(objects, sideways, grey.size)
    if figure is None:
        # The axis is clear but nothing on the page says which end is up. For a
        # sideways page some rotation still beats none, so assume the head lies
        # to the left — the way both known sideways scans went in.
        return Orientation(90 if sideways else 0, axis, None, None)

    head = _head_position(figure, sideways)
    box = BBox(figure.x, figure.y, figure.w, figure.h)
    if abs(head - 0.5) < HEAD_DECISION:
        return Orientation(90 if sideways else 0, axis, head, box)

    head_first = head < 0.5
    if sideways:
        # Head at the left edge -> a clockwise quarter turn lifts it to the top.
        degrees = 90 if head_first else 270
    else:
        # Asymmetric on purpose — see HEAD_180_DECISION. Between 0.5 and the gate
        # the figure is upside-down by the letter of the cue but not by enough to
        # act on, and leaving a page alone costs far less than inverting a good one.
        degrees = 180 if head > HEAD_180_DECISION else 0
    return Orientation(degrees, axis, head, box)


def _page_content(image: Image.Image) -> np.ndarray | None:
    """Working-scale luminance, cropped to the scanned area of the page."""
    located = _locate_page_content(image)
    return None if located is None else located[0]


def _locate_page_content(image: Image.Image) -> tuple[np.ndarray, int, int, float] | None:
    """The working-scale page crop, with where it sits: (grey, x0, y0, scale).

    Scanner apps drop a square-ish scan into a portrait mediabox and leave the
    rest blank, so the mediabox says nothing about the page. Cropping to the
    non-paper pixels — ignoring specks, which survive in the blank margin as
    stray dust — recovers the page the scanner actually saw. `x0`, `y0` are the
    crop's origin in working-scale pixels and `scale` maps the caller's pixels
    to working scale, so a measurement made here can be handed back in the
    caller's own coordinates.
    """
    scale = min(1.0, WORK_SIZE / max(image.size))
    if scale < 1.0:
        size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
        image = image.resize(size, Image.BILINEAR)

    grey = np.asarray(image.convert("L"))
    ink = grey < PAPER_THRESHOLD
    labels, count = ndimage.label(ink)
    if count == 0:
        return None

    areas = ndimage.sum(ink, labels, range(1, count + 1))
    substantial = np.zeros(count + 1, dtype=bool)
    substantial[1:] = areas >= MIN_CONTENT_AREA_FRAC * ink.size
    ys, xs = np.nonzero(substantial[labels])
    if not len(ys):
        return None
    x0, y0 = int(xs.min()), int(ys.min())
    return grey[y0 : ys.max() + 1, x0 : xs.max() + 1], x0, y0, scale


def _find_objects(grey: np.ndarray) -> list[_Object]:
    """Segment the page into artwork blobs by local contrast.

    Filling holes then opening turns an outlined drawing into one solid shape,
    which is what the elongation measure needs — an outline alone has the right
    bounding box but a misleading area.
    """
    values = grey.astype(np.float32)
    mean = ndimage.uniform_filter(values, DETAIL_WINDOW)
    mean_square = ndimage.uniform_filter(values * values, DETAIL_WINDOW)
    detail = np.sqrt(np.maximum(mean_square - mean * mean, 0.0)) > DETAIL_STD

    detail = ndimage.binary_closing(detail, np.ones((7, 7)))
    detail = ndimage.binary_fill_holes(detail)
    detail = ndimage.binary_opening(detail, np.ones((5, 5)))

    labels, count = ndimage.label(detail)
    if count == 0:
        return []

    height, width = grey.shape
    min_area = MIN_OBJECT_AREA_FRAC * height * width
    margin_y = BORDER_MARGIN_FRAC * height
    margin_x = BORDER_MARGIN_FRAC * width
    areas = ndimage.sum(detail, labels, range(1, count + 1))

    objects: list[_Object] = []
    for index, (y_slice, x_slice) in enumerate(ndimage.find_objects(labels)):
        if areas[index] < min_area:
            continue
        objects.append(
            _Object(
                x=int(x_slice.start),
                y=int(y_slice.start),
                w=int(x_slice.stop - x_slice.start),
                h=int(y_slice.stop - y_slice.start),
                area=float(areas[index]),
                touches_left_or_right=(
                    x_slice.start < margin_x or x_slice.stop > width - margin_x
                ),
                touches_top_or_bottom=(
                    y_slice.start < margin_y or y_slice.stop > height - margin_y
                ),
                mask=labels[y_slice, x_slice] == index + 1,
                grey=grey[y_slice, x_slice],
            )
        )
    return objects


def _axis_score(objects: list[_Object]) -> float:
    """Area-weighted mean of log(h/w): positive is portrait, negative landscape.

    Every object votes, decoration included. That is deliberate — the border
    strip is part of the page, so it lies down when the page does, and it is
    often the largest evidence available on a page with no doll on it.
    """
    total = sum(o.area for o in objects)
    if total <= 0:
        return 0.0
    return sum(o.area * math.log(o.h / o.w) for o in objects) / total


def _find_figure(objects: list[_Object], sideways: bool, page_area: float) -> _Object | None:
    """The largest doll-shaped object lying along the page's long axis.

    A figure must float clear of the page edge *across* its short axis. That is
    what separates a doll from the border decoration, which is equally tall and
    equally elongated but hugs one edge — and unlike a blanket border test, it
    still finds the dolls that run off the top and bottom of the page.
    """
    candidates = [o for o in objects if _is_figure(o, sideways, page_area)]
    if not candidates:
        return None
    return max(candidates, key=lambda o: o.w * o.h)


def _is_figure(o: _Object, sideways: bool, page_area: float) -> bool:
    """The one definition of "doll-shaped" — see `_find_figure` for why each gate."""
    return (
        not (o.touches_top_or_bottom if sideways else o.touches_left_or_right)
        and o.upright != sideways
        and FIGURE_MIN_ELONGATION <= o.elongation <= FIGURE_MAX_ELONGATION
        and o.w * o.h >= FIGURE_MIN_BOX_FRAC * page_area
    )


def find_figure_regions(image: Image.Image) -> list[tuple[BBox, np.ndarray]]:
    """Every doll-shaped object on an upright page, in the image's own pixels.

    The seam the bodies stage cuts through: a figure is whatever `_find_figure`
    would consider, found by the same local-contrast segmentation, so a page
    that orients by its doll also yields that doll as a body. Each result is
    the figure's bounding box at full resolution and a boolean mask of the same
    size, cropped to the box — the filled connected component, scaled back up
    from working scale. Ordered left to right.
    """
    located = _locate_page_content(image)
    if located is None:
        return []
    grey, x0, y0, scale = located
    page_area = grey.shape[0] * grey.shape[1]

    regions: list[tuple[BBox, np.ndarray]] = []
    for o in sorted(_find_objects(grey), key=lambda o: o.x):
        if not _is_figure(o, sideways=False, page_area=page_area):
            continue
        left = min(image.width, max(0, round((o.x + x0) / scale)))
        top = min(image.height, max(0, round((o.y + y0) / scale)))
        right = min(image.width, max(left, round((o.x + o.w + x0) / scale)))
        bottom = min(image.height, max(top, round((o.y + o.h + y0) / scale)))
        box = BBox(left, top, right - left, bottom - top)
        if box.w == 0 or box.h == 0:
            continue
        mask = Image.fromarray(o.mask.astype(np.uint8) * 255).resize((box.w, box.h), Image.NEAREST)
        regions.append((box, np.asarray(mask) > 0))
    return regions


def _head_position(figure: _Object, sideways: bool) -> float:
    """Where the head sits along the figure's long axis, 0 (start) to 1 (end).

    Two independent cues, averaged because each is weak on its own:

    * where the figure is widest — shoulders and arms, roughly a quarter down
      from the crown, against two thin legs at the other end;
    * where the ink is darkest — hair and face, against pale bare legs.

    Both were ~0.24 and ~0.25-0.44 respectively for every doll in the corpus,
    upright and sideways alike.
    """
    axis = 0 if sideways else 1  # sum across the figure's short axis
    span = figure.mask.shape[1 - axis]
    positions = np.arange(span)

    widths = figure.mask.sum(axis=axis).astype(np.float64)
    darkness = np.where(figure.mask, 255.0 - figure.grey.astype(np.float64), 0.0).sum(axis=axis)

    # Smooth before taking the peak so a single wide row (an outflung arm) does
    # not outvote the shoulder region it belongs to.
    smoothed = ndimage.uniform_filter1d(widths, max(3, span // 20))
    widest = float(np.argmax(smoothed)) / span
    darkest = float((darkness * positions).sum() / max(darkness.sum(), 1e-9)) / span
    return (widest + darkest) / 2
