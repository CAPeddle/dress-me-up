"""Stage 4a — cut the Base Bodies named in a tracked list out of their pages.

A body page is not an item sheet. Stickers sit on white paper and lift off with
a luminance threshold; a doll is printed on a decorated page — a smooth colour
wash with a border running off the edge — and a threshold welds it into the
wash. So this stage does not segment: it asks the orientation module, which
already finds figures on exactly these pages by local contrast, for its figure
regions, and cuts along the figure's own connected-component mask.

Which pages hold bodies is a human decision, recorded once in
`tools/base_bodies.json`. Every entry names a PDF by basename, a 0-indexed page,
a stable id, and optionally which figure on the page (left to right) when the
page holds more than one. A two-doll page with no ordinal is refused rather than
guessed, because the guess would silently lose a doll.

Bodies and items must share one physical scale (KTD4), so the page is rendered
at whatever DPI the sidecars beside the build were extracted at, and the stage
refuses to run when those sidecars disagree among themselves.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from .extract import DEFAULT_DPI, render_page
from .models import GROUPS, BBox, iter_sidecars
from .orientation import find_figure_regions
from .triage import Manifest, manifest_path, rotate_page

# A second figure at least this tall relative to the tallest is another doll,
# not a decoration, and the list must say which one is meant.
RIVAL_HEIGHT_FRAC = 0.8

# The figure mask comes back from working scale, so its edge is blocky; a small
# blur turns the steps into a soft edge without moving it.
EDGE_BLUR_PX = 1.5


class BodyError(ValueError):
    """The body list, its pages, or the sidecars beside it cannot be honoured."""


@dataclass(frozen=True)
class BodyEntry:
    """One line of the tracked list."""

    id: str
    pdf: str
    page: int
    group: str
    region: int | None = None


@dataclass
class BodyCut:
    """One body as cut from its page, at the page's full render resolution."""

    id: str
    group: str
    source_pdf: str
    page: int
    image: Image.Image


# -- the list -------------------------------------------------------------------


def load_body_list(path: Path) -> list[BodyEntry]:
    """Read `base_bodies.json`; refuse duplicate ids and groups the app has no name for."""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[BodyEntry] = []
    seen: set[str] = set()
    for raw in data.get("bodies", []):
        try:
            entry = BodyEntry(
                id=str(raw["id"]),
                pdf=str(raw["pdf"]),
                page=int(raw["page"]),
                group=str(raw["group"]),
                region=None if raw.get("region") is None else int(raw["region"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BodyError(f"{path}: malformed body entry {raw!r}: {exc}") from exc
        if entry.id in seen:
            raise BodyError(f"{path}: body id {entry.id!r} appears more than once")
        if entry.group not in GROUPS:
            raise BodyError(f"body {entry.id!r}: unknown group {entry.group!r} (expected one of {', '.join(GROUPS)})")
        seen.add(entry.id)
        entries.append(entry)
    return entries


def resolve_pdf(entry: BodyEntry, source_root: Path) -> Path:
    """Find the entry's PDF anywhere under the source root by its basename."""
    matches = sorted(source_root.rglob(entry.pdf))
    if not matches:
        raise BodyError(f"body {entry.id!r}: PDF {entry.pdf!r} not found under {source_root}")
    if len(matches) > 1:
        raise BodyError(f"body {entry.id!r}: PDF {entry.pdf!r} is ambiguous under {source_root}: {', '.join(map(str, matches))}")
    return matches[0]


# -- scale ------------------------------------------------------------------


def shared_dpi(sidecar_root: Path) -> int:
    """The one DPI every sidecar under the root was extracted at.

    An unrecorded DPI (0, from a sidecar older than the field) is a value like
    any other: a corpus that mixes it with a real value cannot be trusted to
    share one scale, and the odd sidecars are named so they can be re-extracted.
    With no sidecars at all there is nothing to agree with, and the extractor's
    default stands in.
    """
    by_dpi: dict[int, list[str]] = {}
    for _, sidecar in iter_sidecars(sidecar_root):
        by_dpi.setdefault(sidecar.dpi, []).append(sidecar.item_id)
    if not by_dpi:
        return DEFAULT_DPI
    if len(by_dpi) == 1:
        return next(iter(by_dpi))
    majority = max(by_dpi, key=lambda dpi: len(by_dpi[dpi]))
    odd = ", ".join(
        f"{item_id} (dpi {dpi})" for dpi, ids in sorted(by_dpi.items()) if dpi != majority for item_id in ids
    )
    raise BodyError(
        f"sidecars under {sidecar_root} disagree on dpi: most are {majority}, but {odd}; "
        "re-extract the odd ones so every image in the build shares one scale"
    )


# -- finding and cutting --------------------------------------------------------


def choose_figure(figures: list[BBox], entry: BodyEntry) -> BBox:
    """The figure the entry means: its ordinal if it gives one, else the tallest.

    Without an ordinal, a rival figure nearly as tall as the tallest is refused
    rather than dropped, because that is what a two-doll page looks like.
    """
    where = f"body {entry.id!r} ({entry.pdf} page {entry.page})"
    if not figures:
        raise BodyError(f"{where}: no figure found on the page")
    if entry.region is not None:
        if not 0 <= entry.region < len(figures):
            raise BodyError(f"{where}: region {entry.region} is out of range; the page has {len(figures)} figure(s)")
        return figures[entry.region]

    tallest = max(figures, key=lambda f: f.h)
    rivals = [f for f in figures if f is not tallest and f.h >= RIVAL_HEIGHT_FRAC * tallest.h]
    if rivals:
        raise BodyError(
            f"{where}: {len(figures)} figures of similar height "
            f"(heights {', '.join(str(f.h) for f in figures)}); set \"region\" to the one meant, counting from the left"
        )
    return tallest


def cut_body(image: Image.Image, box: BBox, mask: np.ndarray) -> Image.Image:
    """Crop the box and keep only the figure's own pixels: alpha 0 everywhere else.

    The alpha is the connected-component mask, not a paper threshold — the
    background here is a colour wash, and a threshold would keep all of it.
    """
    crop = image.crop((box.x, box.y, box.x + box.w, box.y + box.h)).convert("RGBA")
    pixels = np.array(crop)
    if mask.shape != (box.h, box.w):
        raise ValueError(f"mask {mask.shape} does not match box {box.h}x{box.w}")
    alpha = ndimage.gaussian_filter(mask.astype(np.float32), EDGE_BLUR_PX)
    pixels[:, :, 3] = np.clip(np.rint(alpha * 255), 0, 255).astype(np.uint8)
    pixels[~mask & (pixels[:, :, 3] == 0), :3] = 0
    return Image.fromarray(pixels, mode="RGBA")


# -- the whole stage --------------------------------------------------------------


def build_bodies(
    entries: list[BodyEntry],
    source_root: Path,
    sidecar_root: Path,
    triage_dir: Path,
) -> tuple[list[BodyCut], int]:
    """Cut every body in the list, in list order; return them with the DPI used."""
    dpi = shared_dpi(sidecar_root)
    if not entries:
        return [], dpi

    cuts: list[BodyCut] = []
    # Both caches are per distinct PDF: the recursive glob behind `resolve_pdf`
    # and the manifest read each happen once however many bodies a page-mate list
    # takes from the same book.
    pdfs: dict[str, Path] = {}
    manifests: dict[Path, Manifest] = {}
    for entry in entries:
        if entry.pdf not in pdfs:
            pdfs[entry.pdf] = resolve_pdf(entry, source_root)
        pdf = pdfs[entry.pdf]
        if pdf not in manifests:
            path = manifest_path(triage_dir, pdf)
            if not path.is_file():
                raise BodyError(
                    f"body {entry.id!r}: no triage manifest for {pdf.name} at {path}; "
                    f"run tools/triage_pages.py {pdf} --out {triage_dir} first"
                )
            manifests[pdf] = Manifest.read(path)
        try:
            rotation = manifests[pdf].rotation(entry.page)
            page = render_page(pdf, entry.page, dpi=dpi)
        except (KeyError, IndexError) as exc:
            raise BodyError(f"body {entry.id!r}: {pdf.name} has no page {entry.page}: {exc}") from exc
        page = rotate_page(page, rotation)

        regions = find_figure_regions(page)
        chosen = choose_figure([box for box, _ in regions], entry)
        mask = next(mask for box, mask in regions if box is chosen)
        cuts.append(
            BodyCut(
                id=entry.id,
                group=entry.group,
                source_pdf=pdf.name,
                page=entry.page,
                image=cut_body(page, chosen, mask),
            )
        )
    return cuts, dpi
