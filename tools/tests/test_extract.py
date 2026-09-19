import pytest
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


# -- triage manifest + dpi ---------------------------------------------------


def _one_page_pdf(tmp_path, name="one-page.pdf", size=(400, 600)):
    """A portrait page with one dark square; enough for the threshold segmenter."""
    page = Image.new("RGB", size, "white")
    for x in range(50, 150):
        for y in range(50, 150):
            page.putpixel((x, y), (20, 20, 20))
    pdf = tmp_path / name
    page.save(pdf)
    return pdf


def _manifest(*verdicts):
    from dressup_pipeline.triage import Manifest, PageVerdict, TRIAGE_DPI

    pages = [
        PageVerdict(page=i, rotation=rot, verdict=verdict, confidence=0.8, reason="test", confirmed=confirmed)
        for i, (verdict, rot, confirmed) in enumerate(verdicts)
    ]
    return Manifest(pdf="x.pdf", source_folder="t", triage_dpi=TRIAGE_DPI, pages=pages)


def test_sidecar_records_the_dpi_it_was_extracted_at(tmp_path):
    from dressup_pipeline.extract import extract_pdf
    from dressup_pipeline.models import Sidecar

    pdf = _one_page_pdf(tmp_path)

    sidecars = extract_pdf(pdf, tmp_path / "out", dpi=72)

    assert sidecars and all(s.dpi == 72 for s in sidecars)
    on_disk = Sidecar.read(tmp_path / "out" / f"{sidecars[0].item_id}.sidecar.json")
    assert on_disk.dpi == 72


def test_sidecar_rejects_a_negative_dpi():
    from dressup_pipeline.models import Sidecar, SidecarError

    sidecar = Sidecar(item_id="a", source_pdf="a.pdf", page=0, bbox=BBox(0, 0, 1, 1), image="a.png", dpi=-1)

    with pytest.raises(SidecarError, match="dpi"):
        sidecar.validate()


def test_sidecar_without_a_dpi_field_still_loads():
    from dressup_pipeline.models import Sidecar

    data = {"item_id": "a", "source_pdf": "a.pdf", "page": 0, "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}, "image": "a.png"}

    assert Sidecar.from_dict(data).dpi == 0


def test_manifest_rotation_is_applied_before_segmentation(tmp_path):
    from dressup_pipeline.extract import extract_pdf

    pdf = _one_page_pdf(tmp_path, size=(400, 600))
    plain = extract_pdf(pdf, tmp_path / "plain", dpi=72)

    turned = extract_pdf(pdf, tmp_path / "turned", dpi=72, manifest=_manifest(("item_sheet", 90, None)))

    assert len(turned) == len(plain) == 1
    # The recorded page is the ROTATED one, so width and height swap...
    assert (turned[0].page_width, turned[0].page_height) == (plain[0].page_height, plain[0].page_width)
    # ...and the square that sat top-left now sits top-right. Tolerance because
    # the segmenter's closing pads a box by a pixel along one axis.
    assert turned[0].bbox.x > turned[0].page_width // 2
    assert turned[0].bbox.y == pytest.approx(plain[0].bbox.x, abs=2)
    assert turned[0].bbox.x + turned[0].bbox.w == pytest.approx(plain[0].page_height - plain[0].bbox.y, abs=2)


def test_zero_rotation_page_extracts_exactly_as_without_a_manifest(tmp_path):
    from dressup_pipeline.extract import extract_pdf

    pdf = _one_page_pdf(tmp_path)
    plain = extract_pdf(pdf, tmp_path / "plain", dpi=72)

    manifested = extract_pdf(pdf, tmp_path / "with", dpi=72, manifest=_manifest(("item_sheet", 0, None)))

    assert [s.to_dict() for s in manifested] == [s.to_dict() for s in plain]


def test_unconfirmed_illustration_is_skipped_and_confirmed_item_sheet_is_cut(tmp_path):
    from dressup_pipeline.extract import extract_pdf

    page = Image.new("RGB", (400, 600), "white")
    for x in range(50, 150):
        for y in range(50, 150):
            page.putpixel((x, y), (20, 20, 20))
    pdf = tmp_path / "three.pdf"
    page.save(pdf, save_all=True, append_images=[page, page])

    manifest = _manifest(
        ("illustration", 0, None),          # rejected, unconfirmed -> skipped
        ("illustration", 0, "item_sheet"),  # rejected, confirmed by hand -> cut
        ("item_sheet", 0, None),            # accepted -> cut
    )
    sidecars = extract_pdf(pdf, tmp_path / "out", dpi=72, manifest=manifest)

    assert sorted(s.page for s in sidecars) == [1, 2]
    assert not list((tmp_path / "out").glob("*-p000-*"))


def test_extract_without_a_manifest_is_unchanged_apart_from_dpi(tmp_path):
    """Regression guard: no flag, no rotation, no skipping — every page is cut."""
    from dressup_pipeline.extract import extract_pdf

    page = Image.new("RGB", (400, 600), "white")
    for x in range(50, 150):
        for y in range(50, 150):
            page.putpixel((x, y), (20, 20, 20))
    pdf = tmp_path / "two.pdf"
    page.save(pdf, save_all=True, append_images=[page])

    sidecars = extract_pdf(pdf, tmp_path / "out", dpi=72)

    assert [s.page for s in sidecars] == [0, 1]
    for s in sidecars:
        record = s.to_dict()
        assert record.pop("dpi") == 72
        assert record["page_width"] == 400 and record["page_height"] == 600
        assert set(record) == {
            "item_id", "source_pdf", "page", "bbox", "image", "source_folder",
            "page_width", "page_height", "category", "group", "quality", "accepted", "notes",
        }


# -- CLI --------------------------------------------------------------------


def test_cli_triage_flag_requires_a_manifest_per_pdf(tmp_path, capsys):
    import extract_pdf as cli

    pdf = _one_page_pdf(tmp_path)
    (tmp_path / "triage").mkdir()

    with pytest.raises(SystemExit):
        cli.main([str(pdf), "--out", str(tmp_path / "out"), "--triage", str(tmp_path / "triage")])

    assert "one-page.json" in capsys.readouterr().err


def test_cli_triage_flag_drives_extraction_from_the_manifest(tmp_path):
    import extract_pdf as cli
    from dressup_pipeline.models import iter_sidecars

    page = Image.new("RGB", (400, 600), "white")
    for x in range(50, 150):
        for y in range(50, 150):
            page.putpixel((x, y), (20, 20, 20))
    pdf = tmp_path / "two.pdf"
    page.save(pdf, save_all=True, append_images=[page])
    triage = tmp_path / "triage"
    triage.mkdir()
    _manifest(("illustration", 0, None), ("item_sheet", 90, None)).write(triage / "two.json")

    assert cli.main([str(pdf), "--out", str(tmp_path / "out"), "--dpi", "72", "--triage", str(triage)]) == 0

    sidecars = [s for _, s in iter_sidecars(tmp_path / "out")]
    assert [s.page for s in sidecars] == [1]
    assert (sidecars[0].page_width, sidecars[0].page_height) == (600, 400)
    assert sidecars[0].dpi == 72
