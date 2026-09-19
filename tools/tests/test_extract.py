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


# -- re-extraction is a replacement, not an addition -------------------------


def _multi_page_pdf(tmp_path, name, pages=2, size=(400, 600)):
    """`pages` copies of the one-dark-square page in a single PDF."""
    page = Image.new("RGB", size, "white")
    for x in range(50, 150):
        for y in range(50, 150):
            page.putpixel((x, y), (20, 20, 20))
    pdf = tmp_path / name
    page.save(pdf, save_all=True, append_images=[page] * (pages - 1))
    return pdf


class _FixedRegions:
    """A segmenter that returns exactly the boxes it was built with."""

    def __init__(self, *boxes):
        self.boxes = list(boxes)

    def regions(self, image):
        return self.boxes


def _annotate(path, **fields):
    """Do to a sidecar on disk what classify and QA do: add their own fields."""
    from dressup_pipeline.models import Sidecar

    sidecar = Sidecar.read(path)
    for name, value in fields.items():
        setattr(sidecar, name, value)
    sidecar.write(path)


QA_FIELDS = dict(
    category="hat", group="fantasy", quality=0.93, accepted=True, notes=["checked by hand"]
)


def test_rerun_drops_a_page_triage_no_longer_calls_an_item_sheet(tmp_path):
    """The stale-page leak: a re-verdicted page must not leave cutouts behind."""
    from dressup_pipeline.extract import extract_pdf

    pdf = _multi_page_pdf(tmp_path, "book.pdf")
    out = tmp_path / "out"
    first = extract_pdf(pdf, out, dpi=72, manifest=_manifest(("item_sheet", 0, None), ("item_sheet", 0, None)))
    assert sorted(s.page for s in first) == [0, 1]

    again = extract_pdf(pdf, out, dpi=72, manifest=_manifest(("base_body", 0, None), ("item_sheet", 0, None)))

    assert [s.page for s in again] == [1]
    assert not list(out.glob("book-p000-*"))
    assert sorted(p.name for p in out.glob("book-p001-*")) == [
        "book-p001-i000.png",
        "book-p001-i000.sidecar.json",
    ]


def test_rerun_keeps_classify_and_qa_fields_when_the_cutout_is_unchanged(tmp_path):
    from dressup_pipeline.extract import extract_pdf
    from dressup_pipeline.models import Sidecar, SIDECAR_SUFFIX

    pdf = _one_page_pdf(tmp_path)
    out = tmp_path / "out"
    (first,) = extract_pdf(pdf, out, dpi=72)
    path = out / f"{first.item_id}{SIDECAR_SUFFIX}"
    _annotate(path, **QA_FIELDS)

    (again,) = extract_pdf(pdf, out, dpi=72)

    for name, value in QA_FIELDS.items():
        assert getattr(again, name) == value, name
    on_disk = Sidecar.read(path)
    assert on_disk.category == "hat" and on_disk.notes == ["checked by hand"]


def test_rerun_at_a_different_dpi_does_not_carry_the_old_verdicts_over(tmp_path):
    """A different cutout is a different item: it has to be classified again."""
    from dressup_pipeline.extract import extract_pdf
    from dressup_pipeline.models import SIDECAR_SUFFIX

    pdf = _one_page_pdf(tmp_path)
    out = tmp_path / "out"
    (first,) = extract_pdf(pdf, out, dpi=72)
    _annotate(out / f"{first.item_id}{SIDECAR_SUFFIX}", **QA_FIELDS)

    (again,) = extract_pdf(pdf, out, dpi=144)

    assert again.item_id == first.item_id  # same slot, different geometry
    assert again.bbox.as_tuple() != first.bbox.as_tuple()
    assert (again.category, again.group) == (None, None)
    assert (again.quality, again.accepted) == (None, None)
    assert again.notes == []


def test_rerun_leaves_another_pdfs_outputs_in_the_same_directory_alone(tmp_path):
    """Scoping is by `<stem>-p`, so a stem that merely starts the same survives."""
    from dressup_pipeline.extract import extract_pdf
    from dressup_pipeline.models import SIDECAR_SUFFIX

    book = _one_page_pdf(tmp_path, name="book.pdf")
    sibling = _one_page_pdf(tmp_path, name="book-two.pdf")
    out = tmp_path / "out"
    extract_pdf(book, out, dpi=72)
    (kept,) = extract_pdf(sibling, out, dpi=72)
    _annotate(out / f"{kept.item_id}{SIDECAR_SUFFIX}", **QA_FIELDS)

    extract_pdf(book, out, dpi=72)

    assert (out / f"{kept.item_id}.png").is_file()
    assert (out / f"{kept.item_id}{SIDECAR_SUFFIX}").is_file()
    assert (out / f"{kept.item_id}{SIDECAR_SUFFIX}").read_text().count("checked by hand") == 1


def test_rerun_removes_files_a_run_that_finds_fewer_regions_would_strand(tmp_path):
    from dressup_pipeline.extract import extract_pdf

    pdf = _one_page_pdf(tmp_path, name="book.pdf")
    out = tmp_path / "out"
    extract_pdf(pdf, out, dpi=72, segmenter=_FixedRegions(BBox(0, 0, 80, 80), BBox(100, 100, 80, 80)))
    # A cutout whose sidecar never got written, as a half-finished run leaves it.
    (out / "book-p000-i009.png").write_bytes(b"")

    again = extract_pdf(pdf, out, dpi=72, segmenter=_FixedRegions(BBox(0, 0, 80, 80)))

    assert len(again) == 1
    assert sorted(p.name for p in out.iterdir()) == ["book-p000-i000.png", "book-p000-i000.sidecar.json"]


# -- a manifest that no longer matches its PDF -------------------------------


def test_a_manifest_short_of_pages_is_refused_before_anything_is_deleted(tmp_path):
    from dressup_pipeline.extract import ManifestCoverageError, extract_pdf

    pdf = _multi_page_pdf(tmp_path, "book.pdf", pages=3)
    out = tmp_path / "out"
    extract_pdf(pdf, out, dpi=72, manifest=_manifest(*[("item_sheet", 0, None)] * 3))
    before = sorted(path.name for path in out.iterdir())

    with pytest.raises(ManifestCoverageError) as excinfo:
        extract_pdf(pdf, out, dpi=72, manifest=_manifest(("item_sheet", 0, None)))

    message = str(excinfo.value)
    assert "book.pdf" in message and "1 page" in message and "3" in message
    assert "triage_pages.py" in message
    # The refusal happens before the sweep, so the last good extraction stands.
    assert sorted(p.name for p in out.iterdir()) == before


def test_cli_reports_a_stale_manifest_as_a_message_not_a_traceback(tmp_path, capsys):
    import extract_pdf as cli

    pdf = _multi_page_pdf(tmp_path, "two.pdf")
    triage = tmp_path / "triage"
    triage.mkdir()
    _manifest(("item_sheet", 0, None)).write(triage / "two.json")

    with pytest.raises(SystemExit):
        cli.main([str(pdf), "--out", str(tmp_path / "out"), "--dpi", "72", "--triage", str(triage)])

    err = capsys.readouterr().err
    assert "two.pdf" in err and "triage_pages.py" in err
