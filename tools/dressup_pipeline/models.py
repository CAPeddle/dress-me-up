"""Core data types shared by every pipeline stage.

The pipeline is a chain of pure-ish transforms over `Sidecar` records. A sidecar
is a JSON file sitting next to an extracted item image, carrying everything we
know about that item: where it came from, what it is, and how good the cutout is.
Stages only ever *add* fields, so a partially processed corpus is still valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterator

# Slot categories an item can occupy. `category` drives snap behaviour in the
# app: an item only snaps to a snap point declaring the same category.
CATEGORIES = (
    "hat",
    "hair",
    "top",
    "bottom",
    "dress",
    "shoes",
    "weapon",
    "shield",
    "accessory",
    "wings",
    "mount",
)

# Thematic groups, used to filter a build down to one sticker book / theme.
GROUPS = ("fantasy", "knight", "princess", "dragon", "misc")

SIDECAR_SUFFIX = ".sidecar.json"


class SidecarError(ValueError):
    """Raised when a sidecar on disk is malformed or references a missing image."""


@dataclass
class BBox:
    """Pixel bounding box of an item within its source page render."""

    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)

    @property
    def area(self) -> int:
        return self.w * self.h


@dataclass
class Sidecar:
    """One candidate item extracted from a scanned page.

    `accepted` is the QA verdict and is deliberately separate from `quality`:
    a human (or a rule) may reject a high-scoring item, and we want to keep the
    score for auditing rather than overwrite it.
    """

    item_id: str
    source_pdf: str
    page: int
    bbox: BBox
    image: str  # path to the cutout PNG, relative to the sidecar's own directory
    # Folder the source file sat in. Scans arrive timestamp-named
    # ("20260509081623.pdf"), so the folder is usually the only thing carrying
    # the theme — see HeuristicClassifier._group.
    source_folder: str = ""
    # Size of the page render this was cut from. Recorded here rather than passed
    # to later stages, so classification can never be run against the wrong
    # dimensions and silently mis-slot every item.
    page_width: int = 0
    page_height: int = 0
    category: str | None = None
    group: str | None = None
    quality: float | None = None
    accepted: bool | None = None
    notes: list[str] = field(default_factory=list)

    # -- validation -------------------------------------------------------

    def validate(self) -> None:
        if self.category is not None and self.category not in CATEGORIES:
            raise SidecarError(f"{self.item_id}: unknown category {self.category!r}")
        if self.group is not None and self.group not in GROUPS:
            raise SidecarError(f"{self.item_id}: unknown group {self.group!r}")
        if self.quality is not None and not 0.0 <= self.quality <= 1.0:
            raise SidecarError(f"{self.item_id}: quality {self.quality} outside 0..1")
        if self.page_width < 0 or self.page_height < 0:
            raise SidecarError(f"{self.item_id}: negative page dimensions")

    @property
    def is_classified(self) -> bool:
        return self.category is not None and self.group is not None

    @property
    def is_qa_complete(self) -> bool:
        return self.quality is not None and self.accepted is not None

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bbox"] = asdict(self.bbox)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Sidecar":
        try:
            bbox = BBox(**data["bbox"])
            sidecar = cls(**{**data, "bbox": bbox})
        except (KeyError, TypeError) as exc:
            raise SidecarError(f"malformed sidecar: {exc}") from exc
        sidecar.validate()
        return sidecar

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "Sidecar":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SidecarError(f"{path}: invalid JSON: {exc}") from exc
        return cls.from_dict(data)


def iter_sidecars(root: Path) -> Iterator[tuple[Path, Sidecar]]:
    """Yield every sidecar under `root`, sorted for reproducible builds.

    Malformed sidecars raise rather than being skipped — a silently dropped item
    is the kind of failure that only shows up as a hole in the catalog much later.
    """
    for path in sorted(root.rglob(f"*{SIDECAR_SUFFIX}")):
        yield path, Sidecar.read(path)


@dataclass
class CatalogItem:
    """One item as the app sees it. Keep this in sync with CatalogRepository.kt."""

    id: str
    category: str
    group: str
    image: str  # relative to the assets root
    width: int
    height: int
    quality: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
