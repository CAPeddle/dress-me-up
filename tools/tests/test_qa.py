from PIL import Image

from dressup_pipeline.qa import score_image
from dressup_pipeline.models import BBox, Sidecar
from dressup_pipeline.qa import qa_sidecar
from synthetic import make_item_image


def test_clean_cutout_scores_high():
    score, notes = score_image(make_item_image(300, 400))

    assert score >= 0.95
    assert notes == []


def test_fully_opaque_crop_is_flagged_as_background_bleed():
    score, notes = score_image(Image.new("RGBA", (300, 400), (100, 100, 100, 255)))

    assert score < 0.8
    assert any("background" in note for note in notes)


def test_tiny_item_is_flagged_and_penalised():
    score, notes = score_image(make_item_image(40, 50, margin=5))

    assert score < 0.9
    assert any("too small" in note for note in notes)


def test_extreme_aspect_ratio_is_penalised():
    tall = make_item_image(300, 2400, margin=20)

    _, notes = score_image(tall)

    assert any("aspect ratio" in note or "elongated" in note for note in notes)


def test_fully_transparent_image_scores_zero_ish():
    score, notes = score_image(Image.new("RGBA", (300, 400), (0, 0, 0, 0)))

    assert score < 0.3
    assert any("transparent" in note for note in notes)


def test_qa_sidecar_accepts_above_threshold(tmp_path):
    make_item_image(300, 400).save(tmp_path / "a.png")
    sidecar = Sidecar(item_id="a", source_pdf="a.pdf", page=0, bbox=BBox(0, 0, 300, 400), image="a.png")

    qa_sidecar(sidecar, tmp_path, min_quality=0.90)

    assert sidecar.accepted is True
    assert sidecar.quality >= 0.90


def test_qa_sidecar_records_a_missing_image_rather_than_crashing(tmp_path):
    sidecar = Sidecar(item_id="gone", source_pdf="a.pdf", page=0, bbox=BBox(0, 0, 10, 10), image="gone.png")

    qa_sidecar(sidecar, tmp_path, min_quality=0.90)

    assert sidecar.accepted is False
    assert sidecar.quality == 0.0
    assert "missing image gone.png" in sidecar.notes
