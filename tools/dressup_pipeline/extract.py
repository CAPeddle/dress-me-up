"""Stage 1 — scanned PDF -> per-item cutout PNGs + sidecars.

Sticker-book pages are mostly white with discrete stickers laid out on them, so
segmentation is deliberately simple: threshold away the paper, label what's left,
and keep blobs big enough to be a real sticker. No ML here — the scans are clean
enough that a threshold beats a model, and a deterministic stage is one an agent
can reason about from its output alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image
from scipy import ndimage

from .models import BBox, Sidecar, SIDECAR_SUFFIX

# A blob smaller than this fraction of the page is scanner noise or a stray mark.
DEFAULT_MIN_AREA_FRAC = 0.002
# Pixels at or above this luminance are treated as paper, not sticker.
DEFAULT_PAPER_THRESHOLD = 240
DEFAULT_DPI = 300


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


def extract_pdf(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = DEFAULT_DPI,
    min_area_frac: float = DEFAULT_MIN_AREA_FRAC,
    paper_threshold: int = DEFAULT_PAPER_THRESHOLD,
    segmenter: Segmenter | None = None,
) -> list[Sidecar]:
    """Extract every page of one PDF into cutouts + unclassified sidecars."""
    import pymupdf

    segmenter = segmenter or ThresholdSegmenter(min_area_frac, paper_threshold)

    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    sidecars: list[Sidecar] = []

    for page_no in range(page_count):
        page = render_page(pdf_path, page_no, dpi=dpi)
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
            )
            sidecar.write(out_dir / f"{item_id}{SIDECAR_SUFFIX}")
            sidecars.append(sidecar)

    return sidecars
