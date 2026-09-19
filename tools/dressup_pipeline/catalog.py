"""Stage 4 — aggregate accepted sidecars into the app's catalog + assets.

This is the pipeline/app contract. `catalog.json` and the scaled PNGs beside it
are the only things the app ever sees; everything upstream is working material
that stays out of the APK.

Given a body list, the same build also writes `bodies.json` and `bodies/<id>.png`
(KTD3). Both files carry one `build_id` and one `scale` block, so a reader can
tell that its bodies and its items came out of the same run rather than from two
builds that no longer share a scale.

**One factor for the whole build** (KTD4). Fitting each image into its own box
destroyed relative size: a crown and a gown came out the same width, though the
page prints one a fraction of the other. So the build measures first and writes
second — it collects every eligible Item's size and cuts the bodies, computes a
single factor from the tallest body and the largest Item edge, and only then
resizes anything. Upscaling stays forbidden; a factor above one is clamped.
"""

from __future__ import annotations

import json
import math
import secrets
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .bodies import BodyCut, BodyError, build_bodies, load_body_list, shared_dpi
from .models import CatalogItem, Sidecar, iter_sidecars

CATALOG_VERSION = 1
BODIES_VERSION = 1
ITEMS_SUBDIR = "items"
BODIES_SUBDIR = "bodies"

# No Item's longest edge may pass this. CLAUDE.md's memory budget is sized on it:
# a decoded 512px bitmap is ~1 MB on a 4 GB tablet, and the tray preloads 48 of
# them. Raising it is a deliberate memory decision, not a tuning knob (KTD4).
ITEM_CEILING_PX = 512

# How tall the tallest Base Body should come out. Bodies are the frame the Items
# are judged against, so this is the size the build aims for when the Item
# ceiling leaves room for it.
DEFAULT_BODY_HEIGHT_PX = 1000

# The factor is written into both files, so it is truncated to something a reader
# can hold — and truncated rather than rounded, so what is written is exactly
# what was applied and can never push the largest Item past the ceiling.
FACTOR_PLACES = 4


@dataclass(frozen=True)
class ScaleDecision:
    """The one factor a build applies to every image, and which bound chose it."""

    factor: float
    bound: str  # "target_height", "item_ceiling", or "clamped"
    target_body_height_px: int
    item_ceiling_px: int

    def to_dict(self, source_dpi: int) -> dict[str, object]:
        return {
            "target_body_height_px": self.target_body_height_px,
            "factor": self.factor,
            "source_dpi": source_dpi,
            "bound": self.bound,
            "item_ceiling_px": self.item_ceiling_px,
        }


def compute_scale(
    body_heights: list[int],
    item_edges: list[int],
    target_body_height: int,
    item_ceiling: int = ITEM_CEILING_PX,
) -> ScaleDecision:
    """The factor for one build: the smaller of the two ratios, never above one.

    The target ratio is the wanted body height over the tallest body; the ceiling
    ratio is the Item ceiling over the largest Item edge. A build with no bodies
    has no target ratio and one with no Items has no ceiling ratio; with neither,
    nothing constrains the factor and it clamps to one like any factor above one.
    """
    if target_body_height <= 0:
        raise ValueError(f"target body height must be a positive number of pixels, not {target_body_height}")

    ratios: list[tuple[str, float]] = []
    if body_heights:
        ratios.append(("target_height", target_body_height / max(body_heights)))
    if item_edges:
        ratios.append(("item_ceiling", item_ceiling / max(item_edges)))

    bound, factor = min(ratios, key=lambda pair: pair[1]) if ratios else ("clamped", 1.0)
    if factor > 1.0:
        bound, factor = "clamped", 1.0
    factor = math.floor(factor * 10**FACTOR_PLACES) / 10**FACTOR_PLACES
    return ScaleDecision(
        factor=factor,
        bound=bound,
        target_body_height_px=target_body_height,
        item_ceiling_px=item_ceiling,
    )


@dataclass
class SourceRow:
    """What one source PDF contributed, measured in the scan's own pixels.

    Per PDF rather than per book: a book whose PDFs were scanned at different
    settings hides inside its own median otherwise, which is the failure the
    thresholds learning in docs/solutions/best-practices/ is about.
    """

    group: str
    pdf: str
    body_heights: list[int] = field(default_factory=list)
    item_heights: list[int] = field(default_factory=list)


@dataclass
class BuildSummary:
    """What a build did, and — more importantly — what it left out and why."""

    total: int = 0
    written: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_group: dict[str, int] = field(default_factory=dict)
    bodies: int = 0
    rows: dict[tuple[str, str], SourceRow] = field(default_factory=dict)
    scale: ScaleDecision | None = None
    source_dpi: int = 0
    tallest_body: int = 0
    largest_item_edge: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def row(self, group: str, pdf: str) -> SourceRow:
        return self.rows.setdefault((group, pdf), SourceRow(group=group, pdf=pdf))

    def as_report(self) -> str:
        lines = [f"{self.written} of {self.total} items written", f"  bodies: {self.bodies}"]
        for reason, count in sorted(self.skipped.items(), key=lambda kv: -kv[1]):
            lines.append(f"  skipped {count:>4}  {reason}")
        if self.by_group:
            lines.append("  groups: " + ", ".join(f"{k}={v}" for k, v in sorted(self.by_group.items())))
        if self.by_category:
            lines.append("  categories: " + ", ".join(f"{k}={v}" for k, v in sorted(self.by_category.items())))
        lines += self._table()
        return "\n".join(lines)

    def _table(self) -> list[str]:
        """Per source PDF within each book, so one odd scan is visible at build time."""
        if not self.rows:
            return []
        lines = ["  per source PDF, in scan pixels:"]
        for (group, pdf), row in sorted(self.rows.items()):
            heights = ", ".join(str(h) for h in sorted(row.body_heights, reverse=True)) or "-"
            median = int(statistics.median(row.item_heights)) if row.item_heights else None
            lines.append(
                f"    {group:<10} {pdf:<34} bodies {len(row.body_heights):>2} (h {heights})"
                f"   items {len(row.item_heights):>4} (median h {median if median is not None else '-'})"
            )
        if self.scale is not None:
            lines.append(
                f"  scale: x{self.scale.factor} chosen by {self.scale.bound}"
                f" — target body height {self.scale.target_body_height_px}px,"
                f" item ceiling {self.scale.item_ceiling_px}px, source dpi {self.source_dpi}"
            )
            lines.append(
                f"         decided by tallest body {self.tallest_body or '-'}px"
                f" and largest item edge {self.largest_item_edge or '-'}px"
            )
        return lines


def new_build_id() -> str:
    """A fresh id for one build: when it ran, plus enough entropy to never repeat."""
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"


def _scaled(image: Image.Image, factor: float) -> Image.Image:
    """The image at the build's one factor, as RGBA. A factor of one is a no-op."""
    rgba = image.convert("RGBA")
    if factor >= 1.0:
        return rgba
    target = (max(1, round(rgba.width * factor)), max(1, round(rgba.height * factor)))
    return rgba.resize(target, Image.LANCZOS)


def _eligible(sidecar: Sidecar, min_quality: float, groups: set[str] | None) -> str | None:
    """Return a skip reason, or None when the item belongs in the catalog."""
    if not sidecar.is_classified:
        return "not classified"
    if not sidecar.is_qa_complete:
        return "QA not run"
    if not sidecar.accepted:
        return "rejected by QA"
    if sidecar.quality is not None and sidecar.quality < min_quality:
        return f"below --min-quality {min_quality}"
    if groups and sidecar.group not in groups:
        return "group not selected"
    return None


@dataclass
class _Candidate:
    """An eligible Item, measured but not yet written."""

    sidecar: Sidecar
    source_image: Path
    width: int
    height: int

    @property
    def longest_edge(self) -> int:
        return max(self.width, self.height)


def _gather(
    sidecar_root: Path, min_quality: float, groups: set[str] | None, summary: BuildSummary
) -> list[_Candidate]:
    """Pass one: which Items are in, and how big they are on the page."""
    candidates: list[_Candidate] = []
    for path, sidecar in iter_sidecars(sidecar_root):
        summary.total += 1

        reason = _eligible(sidecar, min_quality, groups)
        if reason:
            summary.skip(reason)
            continue

        source_image = path.parent / sidecar.image
        if not source_image.exists():
            summary.skip("image missing on disk")
            continue

        with Image.open(source_image) as image:
            width, height = image.size

        assert sidecar.category and sidecar.group
        candidates.append(_Candidate(sidecar, source_image, width, height))
        summary.by_category[sidecar.category] = summary.by_category.get(sidecar.category, 0) + 1
        summary.by_group[sidecar.group] = summary.by_group.get(sidecar.group, 0) + 1
        summary.row(sidecar.group, sidecar.source_pdf).item_heights.append(height)
    return candidates


def build_catalog(
    sidecar_root: Path,
    assets_dir: Path,
    min_quality: float = 0.90,
    groups: set[str] | None = None,
    target_body_height: int = DEFAULT_BODY_HEIGHT_PX,
    bodies_list: Path | None = None,
    source_root: Path | None = None,
    triage_dir: Path | None = None,
) -> BuildSummary:
    """Write `catalog.json` + scaled item PNGs into `assets_dir`.

    With `bodies_list`, also cut the listed Base Bodies (which needs
    `source_root` for the PDFs and `triage_dir` for their rotations) and write
    `bodies.json` + `bodies/<id>.png` beside the catalog. An item group that
    made it into the catalog with no body to dress is a `BodyError`.

    Nothing is written until the bodies are cut, because the factor every image
    is scaled by depends on the tallest of them (KTD4).
    """
    if bodies_list is not None and (source_root is None or triage_dir is None):
        raise ValueError("a bodies list needs both source_root and triage_dir")

    items_dir = assets_dir / ITEMS_SUBDIR
    items_dir.mkdir(parents=True, exist_ok=True)

    summary = BuildSummary()
    build_id = new_build_id()

    candidates = _gather(sidecar_root, min_quality, groups, summary)

    cuts: list[BodyCut] = []
    source_dpi: int | None = None
    listed_groups = {entry.group for entry in load_body_list(bodies_list)} if bodies_list else set()
    if listed_groups:
        assert bodies_list is not None and source_root is not None and triage_dir is not None
        _refuse_unbodied_groups(bodies_list, set(summary.by_group), listed_groups)
        cuts, source_dpi = build_bodies(bodies_list, source_root, sidecar_root, triage_dir)
        for cut in cuts:
            summary.row(cut.group, cut.source_pdf).body_heights.append(cut.image.height)
    if source_dpi is None:
        # The scale block names one DPI, so the sidecars have to agree on one.
        source_dpi = shared_dpi(sidecar_root)

    decision = compute_scale(
        body_heights=[cut.image.height for cut in cuts],
        item_edges=[candidate.longest_edge for candidate in candidates],
        target_body_height=target_body_height,
    )
    summary.scale = decision
    summary.source_dpi = source_dpi
    summary.tallest_body = max((cut.image.height for cut in cuts), default=0)
    summary.largest_item_edge = max((c.longest_edge for c in candidates), default=0)

    catalog_items: list[CatalogItem] = []
    for candidate in candidates:
        sidecar = candidate.sidecar
        out_name = f"{sidecar.item_id}.png"
        with Image.open(candidate.source_image) as image:
            written = _scaled(image, decision.factor)
            written.save(items_dir / out_name, optimize=True)
            width, height = written.size

        assert sidecar.category and sidecar.group and sidecar.quality is not None
        catalog_items.append(
            CatalogItem(
                id=sidecar.item_id,
                category=sidecar.category,
                group=sidecar.group,
                image=f"{ITEMS_SUBDIR}/{out_name}",
                width=width,
                height=height,
                quality=sidecar.quality,
            )
        )
        summary.written += 1

    if cuts:
        summary.bodies = _write_bodies(cuts, assets_dir, build_id, decision, source_dpi)

    catalog = {
        "version": CATALOG_VERSION,
        "min_quality": min_quality,
        "items": [item.to_dict() for item in sorted(catalog_items, key=lambda i: i.id)],
        "build_id": build_id,
        "scale": decision.to_dict(source_dpi),
    }
    (assets_dir / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _refuse_unbodied_groups(bodies_list: Path, item_groups: set[str], listed_groups: set[str]) -> None:
    """A group with items and no body is a build nobody can play; say so before writing."""
    unbodied = sorted(item_groups - listed_groups)
    if unbodied:
        raise BodyError(
            f"items were written for group(s) {', '.join(unbodied)} but {bodies_list} lists no body for them; "
            "nothing in that group could be dressed"
        )


def _write_bodies(
    cuts: list[BodyCut],
    assets_dir: Path,
    build_id: str,
    decision: ScaleDecision,
    source_dpi: int,
) -> int:
    """Write the cut bodies at the build's factor as `bodies.json` + `bodies/<id>.png`."""
    bodies_dir = assets_dir / BODIES_SUBDIR
    bodies_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for cut in cuts:
        out_name = f"{cut.id}.png"
        written = _scaled(cut.image, decision.factor)
        written.save(bodies_dir / out_name, optimize=True)
        records.append(
            {
                "id": cut.id,
                "image": f"{BODIES_SUBDIR}/{out_name}",
                "width": written.width,
                "height": written.height,
                "source_pdf": cut.source_pdf,
                "group": cut.group,
            }
        )
    bodies = {
        "version": BODIES_VERSION,
        "build_id": build_id,
        "scale": decision.to_dict(source_dpi),
        "bodies": records,
    }
    (assets_dir / "bodies.json").write_text(json.dumps(bodies, indent=2) + "\n", encoding="utf-8")
    return len(records)
