"""Stage 2 — assign a category and group to each extracted item.

`Classifier` is a protocol so a trained model can replace the shipped heuristic
without touching the pipeline. The heuristic exists because it is auditable: when
an item lands in the wrong slot you can read the rule that put it there.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import CATEGORIES, GROUPS, Sidecar

# Substrings matched against the source PDF name, longest first so that a more
# specific book name wins over a generic one.
GROUP_HINTS: dict[str, str] = {
    "princess": "princess",
    "fantasy": "fantasy",
    "dragon": "dragon",
    "knight": "knight",
}


@dataclass(frozen=True)
class Shape:
    """The geometric evidence the heuristic reasons about, all page-relative."""

    aspect: float  # width / height
    area_frac: float  # share of the page the item occupies
    centre_y: float  # 0 at page top, 1 at page bottom


class Classifier(Protocol):
    def classify(self, sidecar: Sidecar, shape: Shape) -> tuple[str, str]:
        """Return (category, group) for one item."""


def shape_of(sidecar: Sidecar) -> Shape:
    """Derive page-relative geometry from the dimensions the sidecar recorded."""
    if sidecar.page_width <= 0 or sidecar.page_height <= 0:
        raise ValueError(
            f"{sidecar.item_id}: no page dimensions recorded — re-run tools/extract_pdf.py"
        )
    box = sidecar.bbox
    return Shape(
        aspect=box.w / max(1, box.h),
        area_frac=box.area / (sidecar.page_width * sidecar.page_height),
        centre_y=(box.y + box.h / 2) / sidecar.page_height,
    )


class HeuristicClassifier:
    """Rule-based first pass, tuned for the fantasy/knight sticker books.

    Sticker sheets group items by kind and lay them out roughly by body order, so
    vertical position on the page carries real signal alongside shape.
    """

    def classify(self, sidecar: Sidecar, shape: Shape) -> tuple[str, str]:
        return self._category(shape), self._group(sidecar)

    def _category(self, shape: Shape) -> str:
        # Long and thin, in either orientation: a weapon (sword, staff, lance).
        if shape.aspect >= 3.0 or shape.aspect <= 1 / 3.0:
            return "weapon"
        # Large and tall: a full-body garment rather than a separate top/bottom.
        if shape.area_frac >= 0.09 and shape.aspect < 0.9:
            return "dress"
        # Wide and short items near the top of the sheet read as headwear.
        if shape.centre_y < 0.25:
            return "hat" if shape.aspect >= 1.1 else "hair"
        if shape.centre_y > 0.80:
            return "shoes"
        if shape.area_frac < 0.015:
            return "accessory"
        # Roughly square mid-page items are shields; taller ones are garments.
        if 0.85 <= shape.aspect <= 1.2:
            return "shield"
        return "top" if shape.centre_y < 0.55 else "bottom"

    def _group(self, sidecar: Sidecar) -> str:
        """Folder first, then filename.

        Scanner apps name files by timestamp, so the containing folder ("Fantasy",
        "Fantasy w Boy", "Knight ") is normally the only place the theme survives.
        Filename is kept as a fallback for hand-named files.
        """
        for candidate in (sidecar.source_folder, sidecar.source_pdf):
            group = self._match(candidate)
            if group:
                return group
        return "misc"

    @staticmethod
    def _match(text: str) -> str | None:
        haystack = text.lower()
        # Longest hint first, so "princess" is not shadowed by a shorter match.
        for hint, group in sorted(GROUP_HINTS.items(), key=lambda kv: -len(kv[0])):
            if hint in haystack:
                return group
        return None


def classify_sidecar(sidecar: Sidecar, shape: Shape, classifier: Classifier | None = None) -> Sidecar:
    """Stamp category and group onto a sidecar, in place."""
    classifier = classifier or HeuristicClassifier()
    category, group = classifier.classify(sidecar, shape)
    if category not in CATEGORIES:
        raise ValueError(f"classifier produced unknown category {category!r}")
    if group not in GROUPS:
        raise ValueError(f"classifier produced unknown group {group!r}")
    sidecar.category = category
    sidecar.group = group
    return sidecar
