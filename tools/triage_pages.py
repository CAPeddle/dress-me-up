#!/usr/bin/env python3
"""Triage scanned PDFs: one manifest per PDF, plus a contact sheet per verdict.

    python tools/triage_pages.py content/source/Fantasy/*.pdf [--out content/triage] [--dpi N]

Writes <out>/<stem>.json (the manifest) and <out>/<stem>.<verdict>.png for every
verdict class that has pages, so rejections can be checked at a glance. If
<out>/<stem>.overrides.json exists — {"pages": {"3": "item_sheet"}}, 0-indexed
— its confirmations are merged into the manifest on every run. A bad override
(unknown page, unknown verdict) stops the run before anything is written.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.extract import render_page
from dressup_pipeline.triage import (
    TRIAGE_DPI,
    OverrideError,
    contact_sheet,
    load_overrides,
    manifest_path,
    overrides_path,
    rotate_page,
    triage_pdf,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "content" / "triage")
    parser.add_argument("--dpi", type=int, default=TRIAGE_DPI)
    args = parser.parse_args(argv)

    for pdf in args.pdfs:
        if not pdf.is_file():
            parser.error(f"no such PDF: {pdf}")

    args.out.mkdir(parents=True, exist_ok=True)
    for pdf in args.pdfs:
        manifest = triage_pdf(pdf, dpi=args.dpi)

        overrides = overrides_path(args.out, pdf)
        if overrides.is_file():
            try:
                manifest.apply_overrides(load_overrides(overrides))
            except OverrideError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

        manifest.write(manifest_path(args.out, pdf))

        by_verdict: dict[str, list[tuple[int, object]]] = {}
        for page in manifest.pages:
            image = rotate_page(render_page(pdf, page.page, dpi=args.dpi), page.rotation)
            by_verdict.setdefault(page.verdict, []).append((page.page, image))
        for verdict, pages in by_verdict.items():
            contact_sheet(pages).save(args.out / f"{pdf.stem}.{verdict}.png")

        counts = Counter(page.verdict for page in manifest.pages)
        confirmed = sum(page.confirmed is not None for page in manifest.pages)
        summary = ", ".join(f"{verdict}={n}" for verdict, n in sorted(counts.items()))
        print(f"{pdf.name}: {len(manifest.pages)} pages ({summary}); {confirmed} confirmed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
