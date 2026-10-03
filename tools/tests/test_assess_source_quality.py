"""The assessor has to discriminate correctly before real scans arrive."""

from PIL import Image, ImageDraw

from assess_source_quality import assess_image, blockiness, paper_uniformity, sharpness
import numpy as np


def _page(size=(1240, 1754)) -> Image.Image:
    page = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(page)
    draw.rectangle([150, 120, 500, 380], fill=(200, 40, 40))
    draw.ellipse([300, 700, 640, 1150], fill=(60, 160, 70))
    draw.ellipse([300, 1450, 560, 1650], fill=(220, 160, 40))
    return page


def _degraded(page: Image.Image, tmp_path, quality=15) -> Image.Image:
    """Round-trip through aggressive JPEG at half resolution — a bad phone capture."""
    small = page.resize((page.width // 2, page.height // 2), Image.LANCZOS)
    path = tmp_path / "degraded.jpg"
    small.save(path, "JPEG", quality=quality)
    return Image.open(path).convert("RGB")


def test_blockiness_flags_jpeg_compression(tmp_path):
    page = _page()

    clean = blockiness(np.asarray(page.convert("L")))
    compressed = blockiness(np.asarray(_degraded(page, tmp_path).convert("L")))

    assert compressed > clean


def test_paper_uniformity_penalises_speckled_background():
    clean = _page()
    speckled = np.asarray(clean.convert("L")).astype(np.int16)
    rng = np.random.default_rng(0)
    speckled = np.clip(speckled + rng.integers(-25, 25, speckled.shape), 0, 255).astype(np.uint8)

    assert paper_uniformity(speckled) > paper_uniformity(np.asarray(clean.convert("L")))


def test_sharpness_drops_when_an_image_is_blurred():
    from PIL import ImageFilter

    page = _page()
    blurred = page.filter(ImageFilter.GaussianBlur(radius=3))

    assert sharpness(np.asarray(blurred.convert("L"))) < sharpness(np.asarray(page.convert("L")))


def test_assessment_reports_items_the_real_segmenter_finds():
    result = assess_image(_page(), "synthetic")

    assert result.items == 3
    assert result.megapixels > 2.0
    assert 0.0 <= result.median_item_quality <= 1.0


def test_a_clean_source_beats_a_degraded_one_on_the_decisive_metric(tmp_path):
    page = _page()

    clean = assess_image(page, "clean")
    degraded = assess_image(_degraded(page, tmp_path), "degraded")

    # Both should still find the stickers; the degraded one should cut them worse.
    assert clean.items == degraded.items == 3
    assert clean.median_item_quality >= degraded.median_item_quality
    assert degraded.blockiness > clean.blockiness
