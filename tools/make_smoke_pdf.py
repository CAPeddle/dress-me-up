#!/usr/bin/env python3
"""Generate a synthetic sticker-book PDF for exercising the pipeline end to end.

There are no real scans on this machine, so this stands in for one:

    python tools/make_smoke_pdf.py
    python tools/extract_pdf.py content/pdfs/fantasy-smoke.pdf
    python tools/classify_and_qa.py
    python tools/build_catalog.py --min-quality 0.5

Shapes are drawn to land in known categories, so a classifier regression shows up
as a wrong category rather than something subtly off. Note that solid shapes fill
their whole bounding box and so trip the QA "page bleed" check — real stickers
have irregular outlines. Use a low --min-quality when smoke-testing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent

# (box, fill, expected category) — the expectation is documentation, and is what
# a human should check after a classifier change.
STICKERS = [
    ((150, 120, 500, 380), (200, 40, 40), "hat"),
    ((700, 140, 900, 420), (40, 90, 200), "hair"),
    ((300, 700, 640, 1150), (60, 160, 70), "top"),
    ((850, 780, 920, 1300), (120, 60, 160), "weapon"),
]
ELLIPSES = [((300, 1450, 560, 1650), (220, 160, 40), "shoes")]

PAGE_SIZE = (1240, 1754)


def build_page() -> Image.Image:
    page = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(page)
    for box, fill, _ in STICKERS:
        draw.rectangle(box, fill=fill)
    for box, fill, _ in ELLIPSES:
        draw.ellipse(box, fill=fill)
    return page


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "content" / "pdfs" / "fantasy-smoke.pdf")
    parser.add_argument("--pages", type=int, default=2)
    args = parser.parse_args(argv)

    if args.pages < 1:
        parser.error("--pages must be at least 1")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    pages = [build_page() for _ in range(args.pages)]
    pages[0].save(args.out, save_all=True, append_images=pages[1:])

    expected = [c for *_, c in STICKERS] + [c for *_, c in ELLIPSES]
    print(f"wrote {args.out} ({args.pages} pages x {len(expected)} stickers)")
    print("expected categories per page: " + ", ".join(expected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
