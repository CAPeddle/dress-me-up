"""Stage 3 — score cutout quality so a build can filter on it.

The score is a weighted blend of independent, individually explainable measures.
Each returns 0..1 and each has a `notes` string when it drags the score down, so
a rejected item can always answer "why" without re-running anything.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .models import Sidecar

# Deliberately not equal: coverage and fringe are the two that actually correlate
# with an item looking wrong on a character, so they carry the most weight.
WEIGHTS = {"coverage": 0.35, "fringe": 0.35, "size": 0.20, "aspect": 0.10}

MIN_USEFUL_PX = 64  # below this an item is unusable at tablet scale
IDEAL_MIN_PX = 256
MAX_SANE_ASPECT = 6.0


def _coverage_score(alpha: np.ndarray) -> tuple[float, str | None]:
    """Fraction of the bounding box that is actually opaque.

    A very low value means the crop is mostly empty — usually a bad bbox. A value
    near 1.0 means nothing was knocked out, i.e. background bleed.
    """
    coverage = float((alpha > 0).mean())
    if coverage < 0.15:
        return coverage / 0.15, f"sparse cutout ({coverage:.0%} opaque)"
    if coverage > 0.98:
        return 0.2, "no background removed (possible page bleed)"
    return 1.0, None


def _fringe_score(alpha: np.ndarray) -> tuple[float, str | None]:
    """Penalise soft, halo-ish edges left behind by scanner antialiasing.

    Semi-transparent pixels should be a thin outline. When they are a large share
    of the opaque area the cutout has a visible white halo on the character.
    """
    opaque = int((alpha == 255).sum())
    partial = int(((alpha > 0) & (alpha < 255)).sum())
    if opaque == 0:
        return 0.0, "fully transparent cutout"
    ratio = partial / opaque
    if ratio <= 0.05:
        return 1.0, None
    score = max(0.0, 1.0 - (ratio - 0.05) / 0.25)
    return score, f"soft edges ({ratio:.0%} partial alpha)" if score < 0.8 else None


def _size_score(width: int, height: int) -> tuple[float, str | None]:
    shortest = min(width, height)
    if shortest < MIN_USEFUL_PX:
        return 0.0, f"too small ({width}x{height})"
    if shortest >= IDEAL_MIN_PX:
        return 1.0, None
    span = IDEAL_MIN_PX - MIN_USEFUL_PX
    return (shortest - MIN_USEFUL_PX) / span, f"small ({width}x{height})"


def _aspect_score(width: int, height: int) -> tuple[float, str | None]:
    aspect = max(width, height) / max(1, min(width, height))
    if aspect <= 3.0:
        return 1.0, None
    if aspect >= MAX_SANE_ASPECT:
        return 0.0, f"extreme aspect ratio ({aspect:.1f}:1)"
    return 1.0 - (aspect - 3.0) / (MAX_SANE_ASPECT - 3.0), f"elongated ({aspect:.1f}:1)"


def score_image(image: Image.Image) -> tuple[float, list[str]]:
    """Return a 0..1 quality score plus human-readable reasons for any deduction."""
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3]
    width, height = rgba.size

    # A cutout with nothing in it is worthless whatever its dimensions say, so
    # short-circuit rather than letting size and aspect award it partial credit.
    if not (alpha > 0).any():
        return 0.0, ["fully transparent cutout"]

    parts = {
        "coverage": _coverage_score(alpha),
        "fringe": _fringe_score(alpha),
        "size": _size_score(width, height),
        "aspect": _aspect_score(width, height),
    }

    score = sum(WEIGHTS[name] * value for name, (value, _) in parts.items())
    notes = [note for _, note in parts.values() if note]
    return round(min(1.0, max(0.0, score)), 4), notes


def qa_sidecar(sidecar: Sidecar, sidecar_dir: Path, min_quality: float) -> Sidecar:
    """Score one sidecar's image and stamp the verdict onto it, in place."""
    image_path = sidecar_dir / sidecar.image
    if not image_path.exists():
        sidecar.quality = 0.0
        sidecar.accepted = False
        sidecar.notes = [f"missing image {sidecar.image}"]
        return sidecar

    with Image.open(image_path) as image:
        score, notes = score_image(image)

    sidecar.quality = score
    sidecar.accepted = score >= min_quality
    sidecar.notes = notes
    return sidecar
