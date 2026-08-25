from PIL import Image

from dressup_pipeline.extract import cutout, find_item_regions
from dressup_pipeline.models import BBox


def test_finds_each_sticker_on_the_page(page_with_stickers):
    boxes = find_item_regions(page_with_stickers, min_area_frac=0.001)

    assert len(boxes) == 3


def test_regions_are_ordered_top_to_bottom_then_left_to_right(page_with_stickers):
    boxes = find_item_regions(page_with_stickers, min_area_frac=0.001)

    assert [b.y for b in boxes] == sorted(b.y for b in boxes)
    assert boxes[0].x < boxes[1].x  # the two top stickers share a row
    assert boxes[2].y > boxes[1].y  # the low sticker sorts last


def test_ignores_specks_below_the_area_threshold():
    page = Image.new("RGB", (600, 900), "white")
    page.putpixel((10, 10), (0, 0, 0))
    page.putpixel((11, 10), (0, 0, 0))

    assert find_item_regions(page) == []


def test_blank_page_yields_nothing():
    assert find_item_regions(Image.new("RGB", (600, 900), "white")) == []


def test_cutout_makes_paper_transparent_and_keeps_ink():
    page = Image.new("RGB", (100, 100), "white")
    for x in range(20, 60):
        for y in range(20, 60):
            page.putpixel((x, y), (10, 10, 200))

    result = cutout(page, BBox(0, 0, 100, 100))

    assert result.getpixel((5, 5))[3] == 0      # paper knocked out
    assert result.getpixel((40, 40))[3] == 255  # ink preserved


def test_threshold_segmenter_matches_the_function_it_wraps(page_with_stickers):
    from dressup_pipeline.extract import ThresholdSegmenter

    segmenter = ThresholdSegmenter(min_area_frac=0.001)

    assert segmenter.regions(page_with_stickers) == find_item_regions(
        page_with_stickers, min_area_frac=0.001
    )


def test_extract_uses_an_injected_segmenter(tmp_path):
    """The seam SAM will use: extract must not care how regions are found."""
    from dressup_pipeline.extract import extract_pdf

    page = Image.new("RGB", (400, 600), "white")
    for x in range(50, 150):
        for y in range(50, 150):
            page.putpixel((x, y), (20, 20, 20))
    pdf = tmp_path / "one-page.pdf"
    page.save(pdf)

    class TwoFixedRegions:
        """Deliberately disagrees with what thresholding would find."""

        def regions(self, image):
            return [BBox(0, 0, 80, 80), BBox(100, 100, 80, 80)]

    sidecars = extract_pdf(pdf, tmp_path / "out", dpi=72, segmenter=TwoFixedRegions())

    assert len(sidecars) == 2
    assert [s.bbox.as_tuple() for s in sidecars] == [(0, 0, 80, 80), (100, 100, 80, 80)]
    # And the page size still gets recorded, whoever found the regions.
    assert all(s.page_width > 0 and s.page_height > 0 for s in sidecars)
