#!/usr/bin/env python3
"""Extract sticker cutouts + sidecars from one or more scanned PDFs.

    python tools/extract_pdf.py content/pdfs/*.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.extract import DEFAULT_DPI, DEFAULT_MIN_AREA_FRAC, extract_pdf

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "content" / "sidecars")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--min-area-frac", type=float, default=DEFAULT_MIN_AREA_FRAC)
    args = parser.parse_args(argv)

    total = 0
    for pdf in args.pdfs:
        if not pdf.is_file():
            parser.error(f"no such PDF: {pdf}")
        sidecars = extract_pdf(pdf, args.out / pdf.stem, dpi=args.dpi, min_area_frac=args.min_area_frac)
        print(f"{pdf.name}: {len(sidecars)} items")
        total += len(sidecars)

    print(f"\n{total} items extracted to {args.out}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
