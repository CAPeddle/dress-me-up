#!/usr/bin/env python3
"""Triage scanned PDFs: one manifest per PDF, plus a contact sheet per verdict.

    python tools/triage_pages.py content/source/Fantasy/*.pdf [--out content/triage] [--dpi N]

Writes <out>/<stem>.json (the manifest) and <out>/<stem>.<verdict>.png for every
verdict class that has pages, so rejections can be checked at a glance. A re-run
replaces that PDF's sheets rather than adding to them, so a class that emptied
since the last run loses its sheet. If <out>/<stem>.overrides.json exists —
{"pages": {"3": "item_sheet"}}, 0-indexed — its confirmations are merged into the
manifest on every run. A bad override (unknown page, unknown verdict) stops the
run before anything is written.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.pagetype import PAGE_TYPES
from dressup_pipeline.triage import (
    TRIAGE_DPI,
    OverrideError,
    contact_sheet,
    load_overrides,
    manifest_path,
    overrides_path,
    triage_pdf,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def sheet_path(triage_dir: Path, pdf_path: Path, verdict: str) -> Path:
    """Where one verdict class's contact sheet for `pdf_path` lives."""
    return triage_dir / f"{pdf_path.stem}.{verdict}.png"


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
        # The upright pages the verdicts were taken from, kept as triage renders
        # them so the contact sheets below need no second pass over the PDF.
        rendered: list[tuple[int, object]] = []
        manifest = triage_pdf(pdf, dpi=args.dpi, on_page=lambda page_no, image: rendered.append((page_no, image)))

        overrides = overrides_path(args.out, pdf)
        if overrides.is_file():
            try:
                manifest.apply_overrides(load_overrides(overrides))
            except OverrideError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

        manifest.write(manifest_path(args.out, pdf))

        # Clear this PDF's sheets before writing the new set. A sheet is what a
        # person reads a verdict class off, so one left behind by a class that
        # emptied since the last run asserts pages this manifest no longer puts
        # there. Enumerating the verdicts rather than globbing <stem>.*.png
        # keeps the manifest and the hand-authored overrides out of reach.
        for verdict in PAGE_TYPES:
            sheet_path(args.out, pdf, verdict).unlink(missing_ok=True)

        upright = dict(rendered)
        by_verdict: dict[str, list[tuple[int, object]]] = {}
        for page in manifest.pages:
            by_verdict.setdefault(page.verdict, []).append((page.page, upright[page.page]))
        for verdict, pages in by_verdict.items():
            contact_sheet(pages).save(sheet_path(args.out, pdf, verdict))

        counts = Counter(page.verdict for page in manifest.pages)
        confirmed = sum(page.confirmed is not None for page in manifest.pages)
        summary = ", ".join(f"{verdict}={n}" for verdict, n in sorted(counts.items()))
        print(f"{pdf.name}: {len(manifest.pages)} pages ({summary}); {confirmed} confirmed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
