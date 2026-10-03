#!/usr/bin/env python3
"""Compare candidate source scans — PDF vs JPG — on what actually matters here.

    python tools/assess_source_quality.py content/pdfs/*.pdf content/raw/*.jpg

The Drive archive holds both scanner-app PDFs and raw phone JPGs of the same
pages. Which to feed the pipeline is an empirical question, so this measures it
rather than guessing.

The decisive metric is `items` — how many item regions the real segmenter finds.
A source that looks sharper but yields fewer clean cutouts is the worse source.
Everything else is diagnostic: it explains *why* one wins.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.extract import DEFAULT_PAPER_THRESHOLD, cutout, find_item_regions
from dressup_pipeline.qa import score_image


@dataclass
class Assessment:
    """One page from one source, measured."""

    label: str
    width: int
    height: int
    megapixels: float
    sharpness: float
    blockiness: float
    paper_uniformity: float
    items: int
    median_item_quality: float

    @staticmethod
    def header() -> str:
        return (
            f"{'source':<34} {'pixels':>11} {'MP':>5} {'sharp':>7} "
            f"{'block':>6} {'paper':>6} {'items':>5} {'q50':>5}"
        )

    def row(self) -> str:
        return (
            f"{self.label[:34]:<34} {self.width}x{self.height:>5} "
            f"{self.megapixels:>5.1f} {self.sharpness:>7.0f} {self.blockiness:>6.2f} "
            f"{self.paper_uniformity:>6.2f} {self.items:>5} {self.median_item_quality:>5.2f}"
        )


def sharpness(grey: np.ndarray) -> float:
    """Variance of the Laplacian — the standard focus measure. Higher is sharper.

    Sensitive to resolution, so only compare it between images of similar size;
    a downscaled copy of the same page will score differently.
    """
    return float(ndimage.laplace(grey.astype(np.float64)).var())


def blockiness(grey: np.ndarray) -> float:
    """Estimate JPEG 8x8 block artifacts.

    Compares the average step across block boundaries against the average step
    inside blocks. ~1.0 means no blocking; higher means visible compression
    structure, which survives into cutout edges as a ragged outline.
    """
    g = grey.astype(np.float64)
    diff = np.abs(np.diff(g, axis=1))
    if diff.shape[1] < 16:
        return float("nan")

    columns = np.arange(diff.shape[1])
    on_boundary = (columns % 8) == 7
    boundary = diff[:, on_boundary].mean()
    interior = diff[:, ~on_boundary].mean()
    return float(boundary / interior) if interior > 0 else float("nan")


def paper_uniformity(grey: np.ndarray, threshold: int = DEFAULT_PAPER_THRESHOLD) -> float:
    """Std-dev of the paper background. Lower is cleaner.

    This is what the threshold segmenter fights: speckle, shadow gradients, and
    show-through from the reverse of the page all raise it.
    """
    paper = grey[grey >= threshold]
    return float(paper.std()) if paper.size else float("nan")


def assess_image(image: Image.Image, label: str) -> Assessment:
    grey = np.asarray(image.convert("L"))
    boxes = find_item_regions(image)

    scores = []
    for box in boxes:
        score, _ = score_image(cutout(image, box))
        scores.append(score)

    return Assessment(
        label=label,
        width=image.width,
        height=image.height,
        megapixels=image.width * image.height / 1e6,
        sharpness=sharpness(grey),
        blockiness=blockiness(grey),
        paper_uniformity=paper_uniformity(grey),
        items=len(boxes),
        median_item_quality=float(np.median(scores)) if scores else 0.0,
    )


def assess_path(path: Path, dpi: int, max_pages: int) -> list[Assessment]:
    if path.suffix.lower() == ".pdf":
        from dressup_pipeline.extract import render_page

        import pymupdf

        with pymupdf.open(path) as doc:
            pages = min(doc.page_count, max_pages)
        return [
            assess_image(render_page(path, n, dpi=dpi), f"{path.name} p{n}")
            for n in range(pages)
        ]

    with Image.open(path) as image:
        return [assess_image(image, path.name)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+", type=Path, help="PDFs and/or images")
    parser.add_argument("--dpi", type=int, default=300, help="PDF render DPI (default: 300)")
    parser.add_argument("--max-pages", type=int, default=2, help="pages per PDF (default: 2)")
    args = parser.parse_args(argv)

    results: list[Assessment] = []
    for source in args.sources:
        if not source.is_file():
            print(f"skipping missing file: {source}", file=sys.stderr)
            continue
        try:
            results.extend(assess_path(source, args.dpi, args.max_pages))
        except Exception as exc:  # a bad source should not kill the comparison
            print(f"skipping {source.name}: {exc}", file=sys.stderr)

    if not results:
        print("nothing to assess", file=sys.stderr)
        return 1

    print(Assessment.header())
    print("-" * len(Assessment.header()))
    for result in results:
        print(result.row())

    print(
        "\nsharp = Laplacian variance (higher = sharper; only comparable at similar size)"
        "\nblock = JPEG 8x8 blocking (1.0 = none, higher = more compression structure)"
        "\npaper = background std-dev (lower = cleaner paper)"
        "\nitems = regions the real segmenter found;  q50 = their median QA score"
        "\n\nPrefer the source with the most items at the highest q50 — the rest is diagnosis."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
