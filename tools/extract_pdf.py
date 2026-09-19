#!/usr/bin/env python3
"""Extract sticker cutouts + sidecars from one or more scanned PDFs.

    python tools/extract_pdf.py content/pdfs/*.pdf
    python tools/extract_pdf.py content/source/Fantasy/*.pdf --triage

With --triage, each PDF's manifest from tools/triage_pages.py drives extraction:
pages are turned upright as the manifest says and only item sheets are cut.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.extract import DEFAULT_DPI, DEFAULT_MIN_AREA_FRAC, extract_pdf
from dressup_pipeline.triage import Manifest, manifest_path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRIAGE_DIR = REPO_ROOT / "content" / "triage"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "content" / "sidecars")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI)
    parser.add_argument("--min-area-frac", type=float, default=DEFAULT_MIN_AREA_FRAC)
    parser.add_argument(
        "--triage",
        type=Path,
        nargs="?",
        const=DEFAULT_TRIAGE_DIR,
        default=None,
        metavar="DIR",
        help=f"follow the triage manifests in DIR (default when given bare: {DEFAULT_TRIAGE_DIR})",
    )
    args = parser.parse_args(argv)

    total = 0
    for pdf in args.pdfs:
        if not pdf.is_file():
            parser.error(f"no such PDF: {pdf}")
        manifest = None
        if args.triage is not None:
            path = manifest_path(args.triage, pdf)
            if not path.is_file():
                parser.error(f"{pdf.name}: no triage manifest at {path}; run tools/triage_pages.py first")
            manifest = Manifest.read(path)
        sidecars = extract_pdf(
            pdf, args.out / pdf.stem, dpi=args.dpi, min_area_frac=args.min_area_frac, manifest=manifest
        )
        print(f"{pdf.name}: {len(sidecars)} items")
        total += len(sidecars)

    print(f"\n{total} items extracted to {args.out}")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
