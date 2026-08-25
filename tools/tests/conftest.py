import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dressup_pipeline.models import BBox, Sidecar, SIDECAR_SUFFIX


@pytest.fixture
def page_with_stickers():
    """A synthetic sticker sheet: white paper with three solid blobs on it."""
    page = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle([50, 40, 250, 200], fill=(200, 30, 30))     # top-left
    draw.rectangle([320, 60, 520, 220], fill=(30, 120, 200))   # top-right
    draw.ellipse([200, 500, 420, 720], fill=(40, 160, 60))     # centre-low
    return page


def make_item_image(width=300, height=400, alpha=255, margin=40):
    """An RGBA cutout: transparent margin around a solid, fully opaque body."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([margin, margin, width - margin, height - margin], fill=(180, 60, 90, alpha))
    return image


@pytest.fixture
def sidecar_corpus(tmp_path):
    """Build a small on-disk corpus and return (root, {item_id: Sidecar})."""

    def _build(specs):
        root = tmp_path / "sidecars"
        root.mkdir(exist_ok=True)
        built = {}
        for spec in specs:
            item_id = spec["item_id"]
            image_name = f"{item_id}.png"
            make_item_image(*spec.get("size", (300, 400))).save(root / image_name)
            sidecar = Sidecar(
                item_id=item_id,
                source_pdf=spec.get("source_pdf", "fantasy-book-1.pdf"),
                page=spec.get("page", 0),
                bbox=BBox(0, 0, *spec.get("size", (300, 400))),
                image=image_name,
                page_width=spec.get("page", (2480, 3508))[0],
                page_height=spec.get("page", (2480, 3508))[1],
                category=spec.get("category"),
                group=spec.get("group"),
                quality=spec.get("quality"),
                accepted=spec.get("accepted"),
            )
            sidecar.write(root / f"{item_id}{SIDECAR_SUFFIX}")
            built[item_id] = sidecar
        return root, built

    return _build
