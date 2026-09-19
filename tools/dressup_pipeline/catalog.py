"""Stage 4 — aggregate accepted sidecars into the app's catalog + assets.

This is the pipeline/app contract. `catalog.json` and the downsampled PNGs beside
it are the only things the app ever sees; everything upstream is working material
that stays out of the APK.

Given a body list, the same build also writes `bodies.json` and `bodies/<id>.png`
(KTD3). Both files carry one `build_id`, so a reader can tell that its bodies and
its items came out of the same run rather than from two builds that no longer
share a scale.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .bodies import BodyError, build_bodies, load_body_list
from .models import CatalogItem, Sidecar, iter_sidecars

CATALOG_VERSION = 1
BODIES_VERSION = 1
ITEMS_SUBDIR = "items"
BODIES_SUBDIR = "bodies"
# Items render at a fraction of a 2000x1200 tablet screen; 512px is already
# generous and keeps the APK from ballooning past sideload-friendly sizes.
DEFAULT_MAX_PX = 512


@dataclass
class BuildSummary:
    """What a build did, and — more importantly — what it left out and why."""

    total: int = 0
    written: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)
    by_group: dict[str, int] = field(default_factory=dict)
    bodies: int = 0

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_report(self) -> str:
        lines = [f"{self.written} of {self.total} items written", f"  bodies: {self.bodies}"]
        for reason, count in sorted(self.skipped.items(), key=lambda kv: -kv[1]):
            lines.append(f"  skipped {count:>4}  {reason}")
        if self.by_group:
            lines.append("  groups: " + ", ".join(f"{k}={v}" for k, v in sorted(self.by_group.items())))
        if self.by_category:
            lines.append("  categories: " + ", ".join(f"{k}={v}" for k, v in sorted(self.by_category.items())))
        return "\n".join(lines)


def new_build_id() -> str:
    """A fresh id for one build: when it ran, plus enough entropy to never repeat."""
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(2)}"


def downsample(image: Image.Image, max_px: int = DEFAULT_MAX_PX) -> Image.Image:
    """Fit the image inside a max_px box, preserving aspect. Never upscales."""
    rgba = image.convert("RGBA")
    if max(rgba.size) <= max_px:
        return rgba
    scale = max_px / max(rgba.size)
    target = (max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale)))
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


def build_catalog(
    sidecar_root: Path,
    assets_dir: Path,
    min_quality: float = 0.90,
    groups: set[str] | None = None,
    max_px: int = DEFAULT_MAX_PX,
    bodies_list: Path | None = None,
    source_root: Path | None = None,
    triage_dir: Path | None = None,
) -> BuildSummary:
    """Write `catalog.json` + downsampled item PNGs into `assets_dir`.

    With `bodies_list`, also cut the listed Base Bodies (which needs
    `source_root` for the PDFs and `triage_dir` for their rotations) and write
    `bodies.json` + `bodies/<id>.png` beside the catalog. An item group that
    made it into the catalog with no body to dress is a `BodyError`.
    """
    if bodies_list is not None and (source_root is None or triage_dir is None):
        raise ValueError("a bodies list needs both source_root and triage_dir")

    items_dir = assets_dir / ITEMS_SUBDIR
    items_dir.mkdir(parents=True, exist_ok=True)

    summary = BuildSummary()
    catalog_items: list[CatalogItem] = []
    build_id = new_build_id()

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
            resized = downsample(image, max_px)
            out_name = f"{sidecar.item_id}.png"
            resized.save(items_dir / out_name, optimize=True)
            width, height = resized.size

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
        summary.by_category[sidecar.category] = summary.by_category.get(sidecar.category, 0) + 1
        summary.by_group[sidecar.group] = summary.by_group.get(sidecar.group, 0) + 1

    listed_groups = {entry.group for entry in load_body_list(bodies_list)} if bodies_list else set()
    if listed_groups:
        assert bodies_list is not None and source_root is not None and triage_dir is not None
        summary.bodies = _write_bodies(
            bodies_list, source_root, sidecar_root, triage_dir, assets_dir, build_id,
            item_groups=set(summary.by_group), listed_groups=listed_groups,
        )

    catalog = {
        "version": CATALOG_VERSION,
        "min_quality": min_quality,
        "items": [item.to_dict() for item in sorted(catalog_items, key=lambda i: i.id)],
        "build_id": build_id,
    }
    (assets_dir / "catalog.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _write_bodies(
    bodies_list: Path,
    source_root: Path,
    sidecar_root: Path,
    triage_dir: Path,
    assets_dir: Path,
    build_id: str,
    item_groups: set[str],
    listed_groups: set[str],
) -> int:
    """Cut the listed bodies and write `bodies.json` + `bodies/<id>.png`; return the count."""
    unbodied = sorted(item_groups - listed_groups)
    if unbodied:
        raise BodyError(
            f"items were written for group(s) {', '.join(unbodied)} but {bodies_list} lists no body for them; "
            "nothing in that group could be dressed"
        )

    cuts, _ = build_bodies(bodies_list, source_root, sidecar_root, triage_dir)
    bodies_dir = assets_dir / BODIES_SUBDIR
    bodies_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for cut in cuts:
        out_name = f"{cut.id}.png"
        cut.image.save(bodies_dir / out_name, optimize=True)
        records.append(
            {
                "id": cut.id,
                "image": f"{BODIES_SUBDIR}/{out_name}",
                "width": cut.image.width,
                "height": cut.image.height,
                "source_pdf": cut.source_pdf,
                "group": cut.group,
            }
        )
    bodies = {"version": BODIES_VERSION, "build_id": build_id, "bodies": records}
    (assets_dir / "bodies.json").write_text(json.dumps(bodies, indent=2) + "\n", encoding="utf-8")
    return len(records)
