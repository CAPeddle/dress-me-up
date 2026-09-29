import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dressup_pipeline.corrections import Correction, corrections_path, write_corrections
from dressup_pipeline.extract import DEFAULT_DPI
from dressup_pipeline.models import BBox, Sidecar, SIDECAR_SUFFIX
from synthetic import make_item_image


@pytest.fixture
def page_with_stickers():
    """A synthetic sticker sheet: white paper with three solid blobs on it."""
    page = Image.new("RGB", (600, 900), "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle([50, 40, 250, 200], fill=(200, 30, 30))     # top-left
    draw.rectangle([320, 60, 520, 220], fill=(30, 120, 200))   # top-right
    draw.ellipse([200, 500, 420, 720], fill=(40, 160, 60))     # centre-low
    return page


def corrections_root(tmp_path):
    """Where the catalogue tests' corrections live: one directory per test.

    Named here rather than in each test so the `sidecar_corpus` fixture and the
    build under test cannot drift apart on which directory holds the labelling.
    """
    path = tmp_path / "corrections"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture
def corrections_dir(tmp_path):
    return corrections_root(tmp_path)


@pytest.fixture
def sidecar_corpus(tmp_path):
    """Build a small on-disk corpus and return (root, {item_id: Sidecar}).

    A spec's `correction` names the category a person filed the item under and
    `rejection` the kind they rejected it as; either writes a real corrections
    file beside the corpus, which is the only thing the catalogue build accepts.
    Specs carrying neither stand for items nobody has ruled on yet.
    """

    def _build(specs):
        root = tmp_path / "sidecars"
        root.mkdir(exist_ok=True)
        corrections_dir = corrections_root(tmp_path)
        built = {}
        filed = {}
        for index, spec in enumerate(specs):
            item_id = spec["item_id"]
            image_name = f"{item_id}.png"
            size = spec.get("size", (300, 400))
            make_item_image(*size).save(root / image_name)
            sidecar = Sidecar(
                item_id=item_id,
                source_pdf=spec.get("source_pdf", "fantasy-book-1.pdf"),
                page=spec.get("page", 0),
                # Its own box per spec, offset by position unless one is given: a
                # correction is matched on geometry (KTD2), so one shared origin
                # made every same-sized item a single identity and no test could
                # label one of them and leave its neighbour alone.
                bbox=spec.get("bbox", BBox(index, index, *size)),
                image=image_name,
                page_width=spec.get("page_size", (2480, 3508))[0],
                page_height=spec.get("page_size", (2480, 3508))[1],
                dpi=spec.get("dpi", DEFAULT_DPI),
                category=spec.get("category"),
                group=spec.get("group"),
                quality=spec.get("quality"),
                accepted=spec.get("accepted"),
            )
            sidecar.write(root / f"{item_id}{SIDECAR_SUFFIX}")
            built[item_id] = sidecar
            if spec.get("correction") or spec.get("rejection"):
                correction = Correction.for_sidecar(
                    sidecar, category=spec.get("correction"), rejection=spec.get("rejection")
                )
                filed.setdefault(sidecar.source_pdf, []).append(correction)
        for source_pdf, corrections in filed.items():
            write_corrections(corrections_path(corrections_dir, source_pdf), corrections)
        return root, built

    return _build
