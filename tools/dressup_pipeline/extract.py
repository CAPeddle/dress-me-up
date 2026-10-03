"""Stage 1 — scanned PDF -> per-item cutout PNGs + sidecars.

Sticker-book pages are mostly white with discrete stickers laid out on them, so
segmentation is deliberately simple: threshold away the paper, label what's left,
and keep blobs big enough to be a real sticker. No ML here — the scans are clean
enough that a threshold beats a model, and a deterministic stage is one an agent
can reason about from its output alone.

Extracting a PDF *replaces* that PDF's outputs rather than adding to them: every
`<stem>-p...` cutout and sidecar already in the output directory is swept away
first, so a page triage no longer calls an item sheet, or a cutout a re-run no
longer finds, cannot linger and be picked up by the catalog build. Downstream
fields (category, group, quality, accepted, notes) are carried across the sweep
for any item whose geometry comes back identical, and dropped for any that does
not — a different cutout is a different item and has to be classified and QA'd
again.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np
from PIL import Image
from scipy import ndimage

from .models import BBox, Sidecar, SidecarError, SIDECAR_SUFFIX

if TYPE_CHECKING:
    from .triage import Manifest

# A blob smaller than this fraction of the page is scanner noise or a stray mark.
DEFAULT_MIN_AREA_FRAC = 0.002
# Pixels at or above this luminance are treated as paper, not sticker.
DEFAULT_PAPER_THRESHOLD = 240
DEFAULT_DPI = 300


class ManifestCoverageError(ValueError):
    """A triage manifest does not have a row for every page of its PDF.

    Its own class rather than a bare ValueError so the CLI can report it as a
    message instead of a traceback without swallowing unrelated failures.
    """


def render_page(pdf_path: Path, page_no: int, dpi: int = DEFAULT_DPI) -> Image.Image:
    """Render one 0-indexed PDF page to an RGB image.

    Imported lazily so that the segmentation half of this module — the part with
    real tests — stays usable without PyMuPDF installed.
    """
    import pymupdf

    with pymupdf.open(pdf_path) as doc:
        if not 0 <= page_no < doc.page_count:
            raise IndexError(f"{pdf_path}: page {page_no} out of range (0..{doc.page_count - 1})")
        pix = doc[page_no].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def find_item_regions(
    image: Image.Image,
    min_area_frac: float = DEFAULT_MIN_AREA_FRAC,
    paper_threshold: int = DEFAULT_PAPER_THRESHOLD,
) -> list[BBox]:
    """Locate sticker-shaped blobs on a page, ordered top-to-bottom, left-to-right.

    Ordering is by reading position rather than blob size so that item ids stay
    stable when a rerun shifts a score slightly.
    """
    grey = np.asarray(image.convert("L"))
    ink = grey < paper_threshold

    # Close single-pixel gaps so a sticker's outline and its fill count as one blob.
    ink = ndimage.binary_closing(ink, structure=np.ones((3, 3)))

    labels, count = ndimage.label(ink)
    if count == 0:
        return []

    min_area = max(1, int(min_area_frac * grey.size))
    boxes: list[BBox] = []
    for y_slice, x_slice in ndimage.find_objects(labels):
        box = BBox(
            x=int(x_slice.start),
            y=int(y_slice.start),
            w=int(x_slice.stop - x_slice.start),
            h=int(y_slice.stop - y_slice.start),
        )
        if box.area >= min_area:
            boxes.append(box)

    boxes.sort(key=lambda b: (b.y, b.x))
    return boxes


class Segmenter(Protocol):
    """Finds item regions on a rendered page.

    The seam where SAM (or anything else) replaces thresholding — see KTD-16.
    A replacement only has to turn a page image into bounding boxes; the stages
    either side of it stay unchanged.

    A SAM-backed implementation would also carry a per-mask confidence, which is
    what the original project's `--min-quality` filtered on. Our QA scores the
    cutout instead, so the two numbers are not interchangeable.
    """

    def regions(self, image: Image.Image) -> list[BBox]:
        ...


class ThresholdSegmenter:
    """Default: threshold away the paper, label what is left, keep big blobs.

    Deterministic and dependency-light, which is why it is the default rather
    than the best available. It assumes clean, high-contrast scans on white
    paper — busy or coloured backgrounds will defeat it, and that is the point
    at which SAM earns its cost.
    """

    def __init__(
        self,
        min_area_frac: float = DEFAULT_MIN_AREA_FRAC,
        paper_threshold: int = DEFAULT_PAPER_THRESHOLD,
    ) -> None:
        self.min_area_frac = min_area_frac
        self.paper_threshold = paper_threshold

    def regions(self, image: Image.Image) -> list[BBox]:
        return find_item_regions(image, self.min_area_frac, self.paper_threshold)


def cutout(image: Image.Image, box: BBox, paper_threshold: int = DEFAULT_PAPER_THRESHOLD) -> Image.Image:
    """Crop `box` and knock the paper background out to transparency."""
    crop = image.crop((box.x, box.y, box.x + box.w, box.y + box.h)).convert("RGBA")
    pixels = np.array(crop)
    paper = pixels[:, :, :3].min(axis=2) >= paper_threshold
    pixels[paper, 3] = 0
    return Image.fromarray(pixels, mode="RGBA")


# -- re-running over an earlier extraction ------------------------------------

# Fields no later stage owns: extract writes these and may rewrite them freely.
_GEOMETRY = ("page", "bbox", "page_width", "page_height", "dpi")
# Fields classify and QA own. Extract never authors them; it only carries them
# across a re-run, and only when the cutout they describe has not moved.
_DOWNSTREAM = ("category", "group", "quality", "accepted", "notes")


def _clear_previous(out_dir: Path, stem: str) -> dict[str, Sidecar]:
    """Delete this PDF's earlier outputs from `out_dir`; return them by item id.

    Scoped by the `<stem>-p` prefix, so a directory shared with other PDFs keeps
    theirs — and a sibling book whose stem merely starts the same way ("book"
    against "book-two") is not caught, because the `-p` is part of the prefix.

    A sidecar too malformed to read is deleted on the strength of its name alone
    and simply has nothing to carry over: refusing to re-extract because of a
    file this run is about to replace would strand the corpus.
    """
    prefix = f"{stem}-p"
    previous: dict[str, Sidecar] = {}
    for path in sorted(out_dir.glob(f"*{SIDECAR_SUFFIX}")):
        try:
            sidecar = Sidecar.read(path)
        except SidecarError:
            if path.name.startswith(prefix):
                path.unlink(missing_ok=True)
            continue
        if not sidecar.item_id.startswith(prefix):
            continue
        previous[sidecar.item_id] = sidecar
        (out_dir / sidecar.image).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
    # Cutouts whose sidecar was already gone: a half-written run, or a rename.
    for image in sorted(out_dir.glob(f"{prefix}*.png")):
        image.unlink(missing_ok=True)
    return previous


def _carry_over(fresh: Sidecar, previous: dict[str, Sidecar]) -> None:
    """Restore classify/QA fields onto `fresh` if its cutout is the same one."""
    old = previous.get(fresh.item_id)
    if old is None or any(getattr(old, name) != getattr(fresh, name) for name in _GEOMETRY):
        return
    for name in _DOWNSTREAM:
        value = getattr(old, name)
        setattr(fresh, name, list(value) if isinstance(value, list) else value)


def _check_manifest_covers(manifest: Manifest, pdf_path: Path, page_count: int) -> None:
    """Refuse a manifest with no row for some page, before anything is touched.

    A manifest goes stale when its PDF is re-scanned with more pages; without
    this the page loop would raise a bare KeyError partway through, having
    already deleted the previous extraction.
    """
    missing = sorted(set(range(page_count)) - {page.page for page in manifest.pages})
    if missing:
        raise ManifestCoverageError(
            f"the triage manifest for {pdf_path.name} lists {len(manifest.pages)} page(s) "
            f"but the PDF has {page_count} (no row for page {', '.join(map(str, missing))}); "
            f"re-run tools/triage_pages.py {pdf_path}"
        )


def extract_pdf(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
    min_area_frac: float = DEFAULT_MIN_AREA_FRAC,
    paper_threshold: int = DEFAULT_PAPER_THRESHOLD,
    segmenter: Segmenter | None = None,
    manifest: Manifest | None = None,
) -> list[Sidecar]:
    """Extract every page of one PDF into cutouts + unclassified sidecars.

    With a triage `manifest`, each page is first turned upright as the manifest
    says and only pages it calls item sheets are cut; the sidecar then records
    the rotated page size, since that is the page the bbox lives on. Without one,
    every page is cut as scanned. A manifest missing a row for some page is
    refused up front, because a stale one would otherwise fail mid-run.

    Re-running is safe and total: this PDF's earlier outputs in `out_dir` are
    deleted before anything is written, so pages that are no longer item sheets
    and cutouts that are no longer found leave nothing behind for the catalog
    build to ingest. Where an item comes back with identical geometry its
    classify and QA fields come with it; where the geometry changed they do not,
    since the cutout those verdicts described no longer exists. Extract still
    authors only its own fields.
    """
    import pymupdf

    # Imported here rather than at the top: triage depends on this module for
    # render_page, and the extractor only needs rotate_page when handed a manifest.
    from .triage import rotate_page

    segmenter = segmenter or ThresholdSegmenter(min_area_frac, paper_threshold)

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count

    # Before the sweep, so a stale manifest costs nothing but the error.
    if manifest is not None:
        _check_manifest_covers(manifest, pdf_path, page_count)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    previous = _clear_previous(out_dir, stem)
    sidecars: list[Sidecar] = []

    for page_no in range(page_count):
        if manifest is not None and not manifest.is_item_sheet(page_no):
            continue
        page = render_page(pdf_path, page_no, dpi=dpi)
        if manifest is not None:
            page = rotate_page(page, manifest.rotation(page_no))
        for index, box in enumerate(segmenter.regions(page)):
            item_id = f"{stem}-p{page_no:03d}-i{index:03d}"
            image_name = f"{item_id}.png"
            cutout(page, box, paper_threshold).save(out_dir / image_name)

            sidecar = Sidecar(
                item_id=item_id,
                source_pdf=pdf_path.name,
                source_folder=pdf_path.parent.name,
                page=page_no,
                bbox=box,
                image=image_name,
                page_width=page.width,
                page_height=page.height,
                dpi=dpi,
            )
            _carry_over(sidecar, previous)
            sidecar.write(out_dir / f"{item_id}{SIDECAR_SUFFIX}")
            sidecars.append(sidecar)

    return sidecars
