"""Stage 3b — the human labels, and the only labels the catalogue build accepts.

`HeuristicClassifier` reasons from geometry relative to the page, and on this
corpus that premise is simply false: the books lay items out to fill paper, not
by what they are. So the classifier's verdict stays where it is — a *suggestion*
on the sidecar — and a person's verdict lives here, in a separate record the
build reads instead.

Three things about that record are load-bearing:

Corrections are never a field on `Sidecar` (KTD3). Keeping them out means
`classify_sidecar` keeps its unconditional write and the additive-stage rule
(KTD-12) needs no exception carved into it. A re-run of classify rewrites its own
suggestion and cannot reach the labelling work.

A correction identifies its item by geometry, not by `item_id` (KTD2, R8). Item
ids are positional, so re-extracting a page renumbers everything after a cutout
the segmenter no longer finds, and every label after it would land on the wrong
item. The five geometry fields are not unique on their own either — two scans of
the same physical page share byte-identical boxes at the same page size and dpi —
so the source PDF's stem is part of the key. A cutout that moved by one pixel is
a different item, and its correction stays in the file, reported as unmatched
rather than dropped (R9): half an hour of judgement is not repeatable, and a
label silently applied to the wrong item is worse than no label.

The files are tracked in git (R7, KTD1), one per source PDF under
`tools/corrections/`, carrying geometry and a verdict — no image data, no paths,
nothing about this machine. `content/` cannot hold them: it is ignored but for
its README.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .models import CATEGORIES, BBox, Sidecar

CORRECTIONS_SUFFIX = ".corrections.json"

# Why a cutout is not a catalogue item. Each kind is a different piece of later
# work — a crop to redo, a pair to segment, a thing that was never a costume — so
# a reviewer can act on one kind without re-reviewing the rest (R14). A welded
# pair that works as one item is not here: it is filed with a category like any
# other item (R18), and the distinction is exactly whether the person filed it or
# rejected it.
REJECTION_KINDS = ("bad_crop", "multi_item", "not_an_item")

# KTD1 pins the location, and the build, the labelling server and the repair
# queue all need it; one constant beats three copies of the same path, even
# though the CLIs otherwise own their own defaults.
DEFAULT_CORRECTIONS_DIR = Path(__file__).resolve().parents[1] / "corrections"

# (stem, page, x, y, w, h, page_width, page_height, dpi) — see KTD2.
CorrectionKey = tuple[str, int, int, int, int, int, int, int, int]


class CorrectionError(ValueError):
    """A corrections file holds a record that cannot be trusted to identify an item."""


@dataclass
class Correction:
    """One human verdict on one extracted cutout.

    Either `category` names the slot the person filed it under, or `rejection`
    names why it is not an item at all — exactly one of the two.
    """

    source_pdf: str  # the PDF's stem, never a path: `pdf_stem(sidecar.source_pdf)`
    page: int
    bbox: BBox
    page_width: int
    page_height: int
    dpi: int
    category: str | None = None
    rejection: str | None = None

    # -- validation -------------------------------------------------------

    def validate(self) -> None:
        if self.category is not None and self.rejection is not None:
            raise CorrectionError(
                f"{self.describe()}: filed as {self.category!r} and rejected as "
                f"{self.rejection!r} both; a correction is one or the other"
            )
        if self.category is None and self.rejection is None:
            raise CorrectionError(f"{self.describe()}: neither filed nor rejected")
        if self.category is not None and self.category not in CATEGORIES:
            raise CorrectionError(
                f"{self.describe()}: unknown category {self.category!r}; "
                f"expected one of {', '.join(CATEGORIES)}"
            )
        if self.rejection is not None and self.rejection not in REJECTION_KINDS:
            raise CorrectionError(
                f"{self.describe()}: unknown rejection kind {self.rejection!r}; "
                f"expected one of {', '.join(REJECTION_KINDS)}"
            )
        # Geometry against an unrecorded page size or dpi identifies nothing: it
        # would match whichever item also lost its scale. Extract refuses an
        # unknown dpi upstream, so nothing real is turned away here.
        if self.page < 0:
            raise CorrectionError(f"{self.describe()}: negative page {self.page}")
        if self.page_width <= 0 or self.page_height <= 0:
            raise CorrectionError(
                f"{self.describe()}: page size {self.page_width}x{self.page_height} is not a page"
            )
        if self.dpi <= 0:
            raise CorrectionError(f"{self.describe()}: no recorded dpi ({self.dpi})")

    def describe(self) -> str:
        """Name the item the way an error message has to: the PDF and where on it."""
        box = self.bbox
        return f"{self.source_pdf} p{self.page} [{box.x},{box.y},{box.w},{box.h}]"

    # -- identity ---------------------------------------------------------

    @property
    def key(self) -> CorrectionKey:
        return (
            self.source_pdf,
            self.page,
            *self.bbox.as_tuple(),
            self.page_width,
            self.page_height,
            self.dpi,
        )

    # -- the verdict ------------------------------------------------------

    @property
    def rejected(self) -> bool:
        return self.rejection is not None

    @property
    def effective_category(self) -> str | None:
        """The slot the build should use, or None when the person rejected the item."""
        return self.category

    # -- persistence ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        # `asdict` recurses into `BBox`, so the nested shape comes for free.
        return asdict(self)

    @classmethod
    def for_sidecar(
        cls, sidecar: Sidecar, *, category: str | None = None, rejection: str | None = None
    ) -> "Correction":
        """A verdict on the item this sidecar describes.

        The way to build one: `Sidecar.source_pdf` is a filename and a
        correction's is a stem, so copying that field straight across produces a
        record that writes happily and refuses to read back.
        """
        correction = cls(
            source_pdf=pdf_stem(sidecar.source_pdf),
            page=sidecar.page,
            bbox=BBox(*sidecar.bbox.as_tuple()),
            page_width=sidecar.page_width,
            page_height=sidecar.page_height,
            dpi=sidecar.dpi,
            category=category,
            rejection=rejection,
        )
        correction.validate()
        return correction

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Correction":
        try:
            correction = cls(
                source_pdf=str(data["source_pdf"]),
                page=int(data["page"]),
                bbox=BBox(**data["bbox"]),
                page_width=int(data["page_width"]),
                page_height=int(data["page_height"]),
                dpi=int(data["dpi"]),
                category=None if data.get("category") is None else str(data["category"]),
                rejection=None if data.get("rejection") is None else str(data["rejection"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorrectionError(f"malformed correction {data!r}: {exc}") from exc
        correction.validate()
        return correction


@dataclass
class MatchReport:
    """What a set of corrections has to say about a corpus of sidecars.

    `unlabelled` and `unmatched` are the two halves of the labelling job that is
    left: items nobody has ruled on, and rulings whose item has moved. Neither is
    ever silently folded into the other.
    """

    labelled: dict[str, Correction] = field(default_factory=dict)  # item_id -> filed correction
    rejected: dict[str, Correction] = field(default_factory=dict)  # item_id -> rejection
    unlabelled: list[str] = field(default_factory=list)  # item ids no correction covers
    unmatched: list[Correction] = field(default_factory=list)  # corrections no item matches


def sidecar_key(sidecar: Sidecar) -> CorrectionKey:
    """The identity a correction is matched on, taken off a sidecar.

    `source_pdf` holds a bare filename, so the stem comes off it with `pdf_stem`
    rather than by splitting the item id — stems contain hyphens
    ("fantasy-smoke") and the id's own separator is a hyphen too.
    """
    box = sidecar.bbox
    return (
        pdf_stem(sidecar.source_pdf),
        sidecar.page,
        *box.as_tuple(),
        sidecar.page_width,
        sidecar.page_height,
        sidecar.dpi,
    )


def pdf_stem(source_pdf: Path | str) -> str:
    """The stem a correction is filed under, taken off a scan's filename.

    Only a real `.pdf` suffix comes off. On a name ending `.pdf`, `Path.stem`
    agrees — it strips the final suffix and nothing more. Where it differs is a
    value that is *already* a stem, and these stems hold dots: scanners name
    files by timestamp, so `Path("2026-09-28 14.08.32").stem` is
    `2026-09-28 14.08`. Stemming twice
    was the bug this replaced, and a dotted stem handed back through here survives
    it. The stem is still taken off once, at identity, because `report.pdf` is
    both a filename and a stem and no rule here can tell which one a caller meant.
    """
    name = Path(source_pdf).name
    return name[:-4] if name.lower().endswith(".pdf") else name


def corrections_path(corrections_dir: Path, stem: str) -> Path:
    """Where one PDF's corrections live. `stem` is a stem, never a filename.

    Deriving it here too would mean guessing which of the two this caller meant,
    and a name ending `.pdf.pdf` makes that guess wrong. The stem is taken off
    the filename once, by `pdf_stem`, where the identity is built.
    """
    return corrections_dir / f"{stem}{CORRECTIONS_SUFFIX}"


def read_corrections(path: Path) -> dict[CorrectionKey, Correction]:
    """Load one PDF's corrections, keyed by item identity.

    The file is a list of records with named fields so that a diff of half an
    hour's labelling is readable; the key is composed here rather than stored.

    Every record is validated before any is returned, following
    `Manifest.apply_overrides`: a file that is half-trustworthy would leave the
    catalogue half-corrected, and a typo is meant to be fixed, not worked around.
    A missing file is not an error — a PDF nobody has labelled yet simply has no
    corrections.
    """
    if not path.exists():
        return {}
    # The read is split from the parse because a decode failure is neither a
    # `JSONDecodeError` nor an `OSError`, and those two are what the labelling
    # server catches to isolate one book's failure from the batch. Unwrapped, one
    # bad byte in one file fails every PDF in the pass, and the client's
    # whole-batch revert puts verdicts that were already written back on the wall
    # as unfiled — the loss the per-PDF isolation exists to prevent.
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CorrectionError(f"{path}: not valid UTF-8: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorrectionError(f"{path}: invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise CorrectionError(f"{path}: expected an object with a 'corrections' list")
    records = data.get("corrections", [])
    if not isinstance(records, list):
        raise CorrectionError(f"{path}: 'corrections' is not a list")

    # Whatever precedes the suffix, taken whole — a stem may hold dots and hyphens.
    stem = path.name.removesuffix(CORRECTIONS_SUFFIX)
    corrections: dict[CorrectionKey, Correction] = {}
    for raw in records:
        try:
            correction = Correction.from_dict(raw)
        except CorrectionError as exc:
            raise CorrectionError(f"{path}: {exc}") from exc
        # One file per PDF, so a record naming another one was pasted in by hand
        # or written against the wrong stem. Honouring it would apply a label
        # across scans of the same page — precisely what the stem in the key
        # exists to prevent.
        if correction.source_pdf != stem:
            raise CorrectionError(
                f"{path}: record names {correction.source_pdf!r}, but this file is {stem!r}"
            )
        if correction.key in corrections:
            raise CorrectionError(f"{path}: {correction.describe()} is corrected more than once")
        corrections[correction.key] = correction
    return corrections


def write_corrections(path: Path, corrections: Iterable[Correction]) -> None:
    """Write one PDF's corrections, sorted by identity.

    Sorted because these files are tracked and rewritten every labelling pass:
    insertion order would make each pass a whole-file diff and bury the one
    verdict that changed.

    Written beside the target and moved into place, rather than over it. This file
    is the only durable copy of judgement nothing can derive again — the reason it
    is tracked at all — and a write that dies partway through would otherwise
    leave a truncated file where a whole book's labelling was. The move is atomic
    on the same filesystem, so a reader sees the old file or the new one.
    """
    records = sorted(corrections, key=lambda correction: correction.key)
    payload = {"corrections": [correction.to_dict() for correction in records]}
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        # The write is inside too, not just the move: a full disk leaves a part of
        # a record here, and one of those per attempt piles up beside the file it
        # was meant to become until nobody can tell which is the labelling.
        temp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def load_corrections(corrections_dir: Path) -> dict[CorrectionKey, Correction]:
    """Every filed verdict under one directory, in one mapping.

    Loaded whole before a single sidecar is read, rather than per PDF as the walk
    reaches one. A lookup keyed on the stems the corpus happens to contain would
    never open the file of a PDF whose cutouts have all moved or vanished, so a
    whole pass of labelling could go unreported — the opposite of what R9 asks
    for. The stem is part of every key, so the files merge without collision.

    A directory that is not there yet holds no corrections and is not an error:
    a corpus nobody has labelled builds empty and says so.
    """
    corrections: dict[CorrectionKey, Correction] = {}
    if not corrections_dir.is_dir():
        return corrections
    for path in sorted(corrections_dir.glob(f"*{CORRECTIONS_SUFFIX}")):
        corrections.update(read_corrections(path))
    return corrections


def match(
    corrections: Mapping[CorrectionKey, Correction], sidecars: Iterable[Sidecar]
) -> MatchReport:
    """Resolve a set of corrections against a corpus, accounting for every one.

    Nothing is dropped on either side: an item with no correction is reported, and
    so is a correction whose item is no longer there (R9).
    """
    report = MatchReport()
    seen: set[CorrectionKey] = set()
    for sidecar in sidecars:
        key = sidecar_key(sidecar)
        correction = corrections.get(key)
        if correction is None:
            report.unlabelled.append(sidecar.item_id)
            continue
        seen.add(key)
        if correction.rejected:
            report.rejected[sidecar.item_id] = correction
        else:
            report.labelled[sidecar.item_id] = correction
    report.unmatched = [
        correction for key, correction in corrections.items() if key not in seen
    ]
    return report
