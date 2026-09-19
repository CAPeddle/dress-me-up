#!/usr/bin/env python3
"""Aggregate accepted sidecars into the app's catalog.json + item PNGs.

    python tools/build_catalog.py --min-quality 0.90 --group fantasy --group knight

Writes into app/src/main/assets/ by default — the only directory the app reads.
When tools/base_bodies.json lists any bodies (or --bodies names another list),
the same run cuts them from their triaged pages under --source and writes
bodies.json + bodies/<id>.png beside the catalog. A checkout holding none of the
scans the tracked list names skips that stage with a note and still writes the
catalog; an explicit --bodies is never skipped.

Every image in one build is scaled by one factor (KTD4), aimed at --body-height
for the tallest Base Body and bounded by the Item ceiling, so a crown and a gown
keep the sizes the page prints them at. The run reports the factor, the bound
that chose it, and a per-source-PDF table of the sizes that decided it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.bodies import BodyError, load_body_list, resolve_pdf
from dressup_pipeline.catalog import DEFAULT_BODY_HEIGHT_PX, BodiesSource, build_catalog
from dressup_pipeline.models import GROUPS

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SIDECARS = REPO_ROOT / "content" / "sidecars"
DEFAULT_ASSETS = REPO_ROOT / "app" / "src" / "main" / "assets"
DEFAULT_SOURCE = REPO_ROOT / "content" / "source"
DEFAULT_TRIAGE = REPO_ROOT / "content" / "triage"
DEFAULT_BODIES = Path(__file__).resolve().parent / "base_bodies.json"


def _default_bodies_list() -> Path | None:
    """The tracked list, when it has something in it; otherwise no bodies stage."""
    if DEFAULT_BODIES.is_file() and load_body_list(DEFAULT_BODIES):
        return DEFAULT_BODIES
    return None


def _list_applies_here(list_path: Path, source_root: Path) -> bool:
    """Does this checkout hold any of the scans the list names?

    Only ever asked of the *tracked* list, which ships with the repo and names
    one parent's scans. On a clone without them every entry is unresolvable, and
    the quickstart wants a catalog without bodies rather than exit 1. One entry
    resolving is enough: a list that half resolves is a list error, and the
    build should still fail on it the way it always has. An entry whose PDF is
    ambiguous under the root counts as unresolved here too, so a source tree
    that duplicates every listed scan skips the stage rather than failing —
    which is why the note says the PDFs could not be resolved, not that they
    are absent.
    """
    for entry in load_body_list(list_path):
        try:
            resolve_pdf(entry, source_root)
        except BodyError:
            continue
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sidecars", type=Path, default=DEFAULT_SIDECARS, help="sidecar root (default: content/sidecars)")
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS, help="asset output dir (default: app/src/main/assets)")
    parser.add_argument("--min-quality", type=float, default=0.90, help="reject items scoring below this (default: 0.90)")
    parser.add_argument("--group", action="append", choices=GROUPS, dest="groups", help="restrict to a group; repeatable")
    parser.add_argument("--body-height", type=int, default=DEFAULT_BODY_HEIGHT_PX, help=f"height the tallest Base Body is scaled to, in px (default: {DEFAULT_BODY_HEIGHT_PX})")
    parser.add_argument("--bodies", type=Path, default=None, help="base body list (default: tools/base_bodies.json when it lists any)")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="scan root the body PDFs live under (default: content/source)")
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE, help="triage manifests for the body pages (default: content/triage)")
    args = parser.parse_args(argv)

    if not args.sidecars.is_dir():
        parser.error(f"sidecar root does not exist: {args.sidecars}")
    if not 0.0 <= args.min_quality <= 1.0:
        parser.error("--min-quality must be between 0.0 and 1.0")
    if args.body_height <= 0:
        parser.error("--body-height must be a positive number of pixels")

    try:
        bodies_list = args.bodies if args.bodies is not None else _default_bodies_list()
        if bodies_list is not None and not bodies_list.is_file():
            parser.error(f"body list does not exist: {bodies_list}")
        # An explicit --bodies is a human naming these bodies, and is never skipped.
        if args.bodies is None and bodies_list is not None and not _list_applies_here(bodies_list, args.source):
            print(
                f"note: tracked body list {bodies_list} skipped: no PDF it lists could be resolved "
                f"under {args.source}; building catalog.json without bodies",
                file=sys.stderr,
            )
            bodies_list = None
        summary = build_catalog(
            sidecar_root=args.sidecars,
            assets_dir=args.assets,
            min_quality=args.min_quality,
            groups=set(args.groups) if args.groups else None,
            target_body_height=args.body_height,
            bodies=None if bodies_list is None else BodiesSource(bodies_list, args.source, args.triage),
        )
    except BodyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(summary.as_report())

    if summary.written == 0:
        print("\nno items written — the app will start with an empty catalog", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
