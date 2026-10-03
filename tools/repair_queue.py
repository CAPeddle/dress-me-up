#!/usr/bin/env python3
"""Read the rejections a person recorded back as work, and name the labels that lost their item.

    python tools/repair_queue.py [--sidecars content/sidecars] [--corrections tools/corrections]

Reports two things and changes neither (R15). Nothing here re-cuts a page, edits a
bounding box or touches a segmenter parameter.

The *repair queue* is the cutouts somebody rejected, grouped by the kind of
problem they recorded (R14) and then by source PDF and page. The grouping is the
point rather than presentation: a `multi_item` rejection means two stickers touch
on the paper, and
`docs/solutions/best-practices/thresholds-tuned-on-one-source-fail-on-the-next.md`
records that re-rendering the page at 100, 150, 200 or 300 DPI does not part them,
because the contact is physical. So the only useful next step is pointing a
semantic segmenter at whole pages, and the queue's job is saying *which* pages are
worth that (R15) — a page with six welded pairs on it earns the attention a page
with one does not.

The *unmatched* report is every correction no extracted item has the geometry for.
Corrections identify their item by geometry (KTD2), so a re-extraction that moves
a cutout by a pixel leaves its label attached to nothing. That work is not
repeatable, so it is named here with what it said — the slot it was filed under or
the rejection it recorded — rather than left as a gap in the labelling that only
shows up as a hole in the catalog (R9). The catalogue build prints the same list,
capped, as one line of a build summary; this is the whole of it, uncapped, because
looking at it is the reason to run this.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.corrections import (
    DEFAULT_CORRECTIONS_DIR,
    REJECTION_KINDS,
    Correction,
    CorrectionError,
    load_corrections,
    match,
)
from dressup_pipeline.models import SidecarError, iter_sidecars

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIDECARS = REPO_ROOT / "content" / "sidecars"

# What the later work on each kind actually is, because the obvious guess is wrong
# for two of the three. Looked up rather than iterated, so a kind added to
# REJECTION_KINDS still appears in the queue — unglossed, but never dropped.
KIND_NOTES = {
    "bad_crop": (
        "the cutout is the wrong shape — too much paper, or an item clipped. The page"
        " wants re-cutting, which nothing in this tool does."
    ),
    "multi_item": (
        "more than one item welded into one cutout. These are the pages to point a"
        " semantic segmenter at: the stickers touch on the paper, so re-rendering at"
        " another DPI will not part them, and no threshold sweep will either."
    ),
    "not_an_item": (
        "never dress-up material. Nothing to repair — this is here so the reviewer"
        " knows it was looked at and ruled on."
    ),
}


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


@dataclass
class QueueEntry:
    """One rejected cutout: the verdict, plus the id that finds its PNG on disk.

    The item id is carried alongside rather than derived, because a correction
    deliberately does not know one (KTD2) and a person working the queue needs to
    open the image.
    """

    item_id: str
    correction: Correction


@dataclass
class RepairReport:
    """The rejections, and the corrections whose item is gone.

    Every correction in the files lands in exactly one of the two: a rejection
    whose cutout still exists is repair work, and one whose cutout has moved is
    unmatched instead. It is not both. Re-extracting a page that changed asks for
    re-labelling before it asks for segmentation, and listing a stale rejection as
    live work would send somebody to look at a cutout that is not there any more.
    """

    by_kind: dict[str, list[QueueEntry]] = field(default_factory=dict)
    unmatched: list[Correction] = field(default_factory=list)
    corrections: int = 0
    sidecars: int = 0
    filed: int = 0

    @property
    def rejections(self) -> int:
        return sum(len(entries) for entries in self.by_kind.values())

    def as_report(self) -> str:
        lines = [
            f"{_plural(self.corrections, 'correction')} over"
            f" {_plural(self.sidecars, 'sidecar')}: {self.filed} filed,"
            f" {self.rejections} rejected, {len(self.unmatched)} unmatched"
        ]
        lines += self._queue_lines()
        lines += self._unmatched_lines()
        return "\n".join(lines)

    def _queue_lines(self) -> list[str]:
        if not self.by_kind:
            return ["", "no rejections recorded — nothing is queued for repair"]
        lines = ["", f"repair queue — {_plural(self.rejections, 'rejection')}:"]
        # In REJECTION_KINDS order, so two runs over the same corpus read the same
        # way and a kind nobody used is simply absent.
        for kind in [*REJECTION_KINDS, *sorted(set(self.by_kind) - set(REJECTION_KINDS))]:
            entries = self.by_kind.get(kind)
            if not entries:
                continue
            note = KIND_NOTES.get(kind)
            heading = f"  {kind} — {len(entries)}"
            lines.append(f"{heading}: {note}" if note else heading)
            lines += _page_lines(entries)
        return lines

    def _unmatched_lines(self) -> list[str]:
        if not self.unmatched:
            return []
        lines = [
            "",
            f"unmatched corrections — {len(self.unmatched)}: no extracted item has this"
            " geometry. The labelling is kept; re-file it against the cutout the item"
            " became, or re-extract the PDF it came from.",
        ]
        # Every one of them: this report exists to be read whole, and a correction
        # left off the end is exactly the quietly-lost work R9 is about.
        for correction in self.unmatched:
            lines.append(f"    {correction.describe()} — {_verdict(correction)}")
        return lines


def _verdict(correction: Correction) -> str:
    """What the correction said, in the words the record itself uses."""
    if correction.rejected:
        return f"rejected as {correction.rejection}"
    return f"filed as {correction.category}"


def _page_lines(entries: list[QueueEntry]) -> list[str]:
    """One heading per source PDF and page, then the cutouts on it.

    The heading carries the count, so a page holding six welded pairs is visibly
    worth more segmenter attention than a page holding one — which is the only
    judgement this report is trying to support.
    """
    pages: dict[tuple[str, int], list[QueueEntry]] = {}
    for entry in entries:
        pages.setdefault((entry.correction.source_pdf, entry.correction.page), []).append(entry)
    lines = []
    for (source_pdf, page), on_page in sorted(pages.items()):
        lines.append(f"    {source_pdf} p{page} — {_plural(len(on_page), 'rejection')}")
        for entry in on_page:
            box = entry.correction.bbox
            lines.append(f"      {entry.item_id}  [{box.x},{box.y},{box.w},{box.h}]")
    return lines


def build_repair_report(*, corrections_dir: Path, sidecar_root: Path) -> RepairReport:
    """Resolve every filed verdict against the corpus and sort the result into work.

    `match` accounts for both sides, which is what this needs: the rejections it
    paired with a cutout are the queue, and the corrections it could pair with
    nothing are the lost labelling. Corrections are loaded from every file in the
    directory rather than from the stems the corpus happens to hold, so a PDF whose
    sidecars have all gone still reports its labelling (R9).
    """
    corrections = load_corrections(corrections_dir)
    resolved = match(corrections, (sidecar for _, sidecar in iter_sidecars(sidecar_root)))

    by_kind: dict[str, list[QueueEntry]] = {}
    for item_id, correction in resolved.rejected.items():
        by_kind.setdefault(str(correction.rejection), []).append(QueueEntry(item_id, correction))
    # Sorted by identity, so one page's rejections are adjacent whatever order the
    # sidecar walk found them in.
    for entries in by_kind.values():
        entries.sort(key=lambda entry: entry.correction.key)

    return RepairReport(
        by_kind=by_kind,
        unmatched=sorted(resolved.unmatched, key=lambda correction: correction.key),
        corrections=len(corrections),
        sidecars=len(resolved.labelled) + len(resolved.rejected) + len(resolved.unlabelled),
        filed=len(resolved.labelled),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sidecars", type=Path, default=DEFAULT_SIDECARS, help="sidecar root (default: content/sidecars)")
    parser.add_argument("--corrections", type=Path, default=DEFAULT_CORRECTIONS_DIR, help=f"directory of human labels, one file per source PDF (default: {DEFAULT_CORRECTIONS_DIR})")
    args = parser.parse_args(argv)

    # A mistyped --sidecars would otherwise match nothing and report every label in
    # the tracked files as lost work — the loudest possible false alarm about the
    # one thing this tool exists to be trusted on.
    if not args.sidecars.is_dir():
        parser.error(f"sidecar root does not exist: {args.sidecars}")

    try:
        report = build_repair_report(corrections_dir=args.corrections, sidecar_root=args.sidecars)
    except (CorrectionError, SidecarError) as exc:
        # Nothing is printed before this: a queue built from a file that may be
        # missing records reads as the whole of the work left, and is worse than no
        # queue at all. The messages already name the file.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(report.as_report())
    if report.corrections == 0:
        # Not a failure: the ordinary state of a corpus nobody has been through.
        # Named on stdout with the directory, because pointing the tool at the
        # wrong one looks exactly like having nothing to do.
        print(f"\nnothing under {args.corrections} carries a human verdict yet")
    # Rejections are the expected finding, not an error — this exits non-zero only
    # when a file could not be read.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
