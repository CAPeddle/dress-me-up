"""Stage 0 — decide, per page, which way up it is and what it is, before cutting.

Orientation and page type are each measured by their own module; this one turns
those measurements into a *manifest* the extractor can follow and a human can
correct. One manifest per PDF, one row per page: the rotation that puts the page
upright, the classifier's verdict on the upright page, and a `confirmed` slot
that only a person fills.

The classifier is used in item-sheet-only mode (see pagetype.py): what it accepts
is trusted, what it rejects is not. So the extractor cuts a page when it is a
confirmed item sheet or an unconfirmed page the classifier accepted, and a
confirmation always wins over a verdict — in either direction. Confirmations
live in a separate, hand-authored overrides file and are merged in every time the
manifest is written, so re-running triage never loses them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw

from .extract import render_page
from .orientation import detect_orientation
from .pagetype import PAGE_TYPES, classify_page

# Both classifiers were validated at 100-300 dpi, and orientation rescales every
# page to a fixed working size anyway, so nothing above the bottom of that band
# buys a better verdict. 100 keeps a nine-PDF book to seconds and its contact
# sheets small.
TRIAGE_DPI = 100

MANIFEST_SUFFIX = ".json"
OVERRIDES_SUFFIX = ".overrides.json"

# Contact-sheet layout: thumbnails a parent can read a page from at a glance.
THUMB_SIZE = (200, 280)
SHEET_COLUMNS = 6
LABEL_HEIGHT = 18


class OverrideError(ValueError):
    """An overrides file names a page or a verdict the manifest cannot honour."""


@dataclass
class PageVerdict:
    """One page of a manifest. `confirmed` is set only from an overrides file."""

    page: int
    rotation: int
    verdict: str
    confidence: float
    reason: str
    confirmed: str | None = None


@dataclass
class Manifest:
    pdf: str
    source_folder: str
    triage_dpi: int
    pages: list[PageVerdict] = field(default_factory=list)

    def _page(self, page_no: int) -> PageVerdict:
        for page in self.pages:
            if page.page == page_no:
                return page
        raise KeyError(f"{self.pdf}: no page {page_no} in manifest")

    def rotation(self, page_no: int) -> int:
        return self._page(page_no).rotation

    def effective_verdict(self, page_no: int) -> str:
        page = self._page(page_no)
        return page.confirmed if page.confirmed is not None else page.verdict

    def is_item_sheet(self, page_no: int) -> bool:
        return self.effective_verdict(page_no) == "item_sheet"

    def apply_overrides(self, overrides: dict[int, str]) -> None:
        """Set `confirmed` from `overrides`; refuse the whole set on any bad entry.

        Validated before anything is written so a typo in one line never leaves
        the manifest half-confirmed.
        """
        known = {page.page for page in self.pages}
        for page_no, verdict in overrides.items():
            if page_no not in known:
                raise OverrideError(
                    f"{self.pdf}: override names page {page_no}, but the PDF has pages 0..{len(self.pages) - 1}"
                )
            if verdict not in PAGE_TYPES:
                raise OverrideError(
                    f"{self.pdf}: override for page {page_no} has unknown verdict {verdict!r}; "
                    f"expected one of {', '.join(PAGE_TYPES)}"
                )
        for page_no, verdict in overrides.items():
            self._page(page_no).confirmed = verdict

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        pages = [PageVerdict(**page) for page in data["pages"]]
        return cls(**{**data, "pages": pages})

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def manifest_path(triage_dir: Path, pdf_path: Path) -> Path:
    return triage_dir / f"{pdf_path.stem}{MANIFEST_SUFFIX}"


def overrides_path(triage_dir: Path, pdf_path: Path) -> Path:
    return triage_dir / f"{pdf_path.stem}{OVERRIDES_SUFFIX}"


def load_overrides(path: Path) -> dict[int, str]:
    """Read a hand-authored overrides file: {"pages": {"<page>": "<verdict>"}}.

    Page keys are strings in the file (JSON has no integer keys) and 0-indexed,
    matching the manifest. Validation against the PDF happens in
    `Manifest.apply_overrides`, which knows how many pages there are.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    pages = data.get("pages", {})
    try:
        return {int(page): verdict for page, verdict in pages.items()}
    except (ValueError, AttributeError) as exc:
        raise OverrideError(f"{path}: page keys must be integers as strings: {exc}") from exc


def rotate_page(image: Image.Image, degrees: int) -> Image.Image:
    """Turn `image` clockwise by `degrees`, exactly as `correct_orientation` does."""
    if degrees == 0:
        return image
    # PIL rotates counter-clockwise; the orientation contract is clockwise.
    return image.rotate(-degrees, expand=True)


def triage_pdf(
    pdf_path: Path,
    dpi: int = TRIAGE_DPI,
    on_page: Callable[[int, Image.Image], None] | None = None,
) -> Manifest:
    """Render every page, find its rotation, classify it upright, and report.

    `on_page` is handed each page number with the upright image the verdict was
    taken from. Rendering a scanned PDF is the expensive part of this stage, so a
    caller that wants the pages themselves — contact sheets — takes them from
    here rather than rendering and rotating the whole book a second time.
    """
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count

    pages: list[PageVerdict] = []
    for page_no in range(page_count):
        page = render_page(pdf_path, page_no, dpi=dpi)
        degrees = detect_orientation(page)
        # Classify the page the extractor will actually see, not the scan as it lay.
        upright = rotate_page(page, degrees)
        verdict = classify_page(upright)
        if on_page is not None:
            on_page(page_no, upright)
        pages.append(
            PageVerdict(
                page=page_no,
                rotation=degrees,
                verdict=verdict.page_type,
                confidence=round(verdict.confidence, 3),
                reason=verdict.reason,
            )
        )

    return Manifest(
        pdf=pdf_path.name,
        source_folder=pdf_path.parent.name,
        triage_dpi=dpi,
        pages=pages,
    )


def contact_sheet(
    pages: list[tuple[int, Image.Image]],
    columns: int = SHEET_COLUMNS,
    thumb: tuple[int, int] = THUMB_SIZE,
) -> Image.Image:
    """One grid image of page thumbnails, each labelled with its page number.

    Meant for a human scanning a verdict class for mistakes — a rejected item
    sheet stands out from a row of illustrations at thumbnail size.
    """
    if not pages:
        raise ValueError("contact sheet of no pages")
    columns = max(1, min(columns, len(pages)))
    rows = -(-len(pages) // columns)
    cell_w, cell_h = thumb[0], thumb[1] + LABEL_HEIGHT
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)

    for index, (page_no, image) in enumerate(pages):
        col, row = index % columns, index // columns
        x, y = col * cell_w, row * cell_h
        small = image.copy()
        small.thumbnail(thumb)
        # Centre the thumbnail in its cell so portrait and landscape pages line up.
        sheet.paste(small, (x + (thumb[0] - small.width) // 2, y + LABEL_HEIGHT + (thumb[1] - small.height) // 2))
        draw.text((x + 4, y + 2), f"p{page_no}", fill=(0, 0, 0))

    return sheet
