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


def make_doll_page(size=(600, 800), dolls=((260, 60, 340, 760),), border=True):
    """A base-body page the way the scans are: dolls on a smooth colour wash.

    Each doll is (left, top, right, bottom) in pixels and is drawn the way the
    books print them: a filled, dark-outlined line figure -- head, torso,
    outstretched arms, two legs -- so it is tall, floats clear of the side edges
    and has the anatomy the orientation gates expect. The wash is a vertical
    gradient whose luminance sits within a few levels of the skin tone, so only
    the outlines separate doll from background, exactly as on the scans; a
    border strip runs off the left edge like the printed pages.
    """
    width, height = size
    page = Image.new("RGB", size)
    pixels = page.load()
    for y in range(height):
        t = y / max(1, height - 1)
        pixels_row = (int(205 - 30 * t), int(190 - 25 * t), int(225 - 20 * t))
        for x in range(width):
            pixels[x, y] = pixels_row
    draw = ImageDraw.Draw(page)
    if border:
        draw.rectangle([0, 0, int(width * 0.08), height], fill=(60, 110, 70))
    for left, top, right, bottom in dolls:
        w, h = right - left, bottom - top
        cx = (left + right) // 2
        skin = (226, 188, 160)
        line = dict(outline=(40, 30, 30), width=2)
        head_h = int(h * 0.14)
        torso_top = top + head_h - 2
        torso_bottom = top + int(h * 0.5)
        half = int(w * 0.25)
        draw.rectangle([cx - half, torso_top, cx + half, torso_bottom], fill=skin, **line)
        arm_top = torso_top + int(h * 0.03)
        draw.rectangle([left, arm_top, right - 1, arm_top + int(h * 0.07)], fill=skin, **line)
        leg_w = max(4, int(w * 0.1))
        draw.rectangle([cx - half, torso_bottom, cx - half + leg_w, bottom - 1], fill=skin, **line)
        draw.rectangle([cx + half - leg_w, torso_bottom, cx + half, bottom - 1], fill=skin, **line)
        draw.ellipse([cx - int(w * 0.3), top, cx + int(w * 0.3), top + head_h], fill=(45, 30, 25), **line)
    return page


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
                page_width=spec.get("page_size", (2480, 3508))[0],
                page_height=spec.get("page_size", (2480, 3508))[1],
                dpi=spec.get("dpi", 0),
                category=spec.get("category"),
                group=spec.get("group"),
                quality=spec.get("quality"),
                accepted=spec.get("accepted"),
            )
            sidecar.write(root / f"{item_id}{SIDECAR_SUFFIX}")
            built[item_id] = sidecar
        return root, built

    return _build
