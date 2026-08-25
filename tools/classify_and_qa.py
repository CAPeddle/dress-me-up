#!/usr/bin/env python3
"""Classify extracted items and score them, updating sidecars in place.

    python tools/classify_and_qa.py --min-quality 0.90
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dressup_pipeline.classify import HeuristicClassifier, classify_sidecar, shape_of
from dressup_pipeline.models import SIDECAR_SUFFIX, iter_sidecars
from dressup_pipeline.qa import qa_sidecar

REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sidecars", type=Path, default=REPO_ROOT / "content" / "sidecars")
    parser.add_argument("--min-quality", type=float, default=0.90)
    args = parser.parse_args(argv)

    if not args.sidecars.is_dir():
        parser.error(f"sidecar root does not exist: {args.sidecars}")

    classifier = HeuristicClassifier()
    accepted = rejected = 0

    for path, sidecar in iter_sidecars(args.sidecars):
        classify_sidecar(sidecar, shape_of(sidecar), classifier)
        qa_sidecar(sidecar, path.parent, args.min_quality)
        sidecar.write(path)
        if sidecar.accepted:
            accepted += 1
        else:
            rejected += 1

    print(f"{accepted} accepted, {rejected} rejected at --min-quality {args.min_quality}")
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
