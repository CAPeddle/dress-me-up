import pytest

from dressup_pipeline.classify import HeuristicClassifier, Shape, classify_sidecar, shape_of
from dressup_pipeline.models import BBox, Sidecar


def _sidecar(source_pdf="fantasy-book-1.pdf", bbox=BBox(0, 0, 100, 100), page=(1000, 1000)):
    return Sidecar(
        item_id="x", source_pdf=source_pdf, page=0, bbox=bbox, image="x.png",
        page_width=page[0], page_height=page[1],
    )


@pytest.mark.parametrize(
    "shape, expected",
    [
        (Shape(aspect=5.0, area_frac=0.02, centre_y=0.5), "weapon"),   # long and thin
        (Shape(aspect=0.2, area_frac=0.02, centre_y=0.5), "weapon"),   # thin the other way
        (Shape(aspect=0.6, area_frac=0.12, centre_y=0.5), "dress"),    # large full-body
        (Shape(aspect=1.4, area_frac=0.03, centre_y=0.10), "hat"),     # wide, top of sheet
        (Shape(aspect=0.9, area_frac=0.03, centre_y=0.10), "hair"),    # tall, top of sheet
        (Shape(aspect=1.0, area_frac=0.03, centre_y=0.90), "shoes"),   # bottom of sheet
        (Shape(aspect=1.0, area_frac=0.005, centre_y=0.5), "accessory"),  # tiny
        (Shape(aspect=1.0, area_frac=0.03, centre_y=0.45), "shield"),  # square mid-sheet
        (Shape(aspect=0.7, area_frac=0.03, centre_y=0.45), "top"),
        (Shape(aspect=0.7, area_frac=0.03, centre_y=0.70), "bottom"),
    ],
)
def test_category_rules(shape, expected):
    assert HeuristicClassifier().classify(_sidecar(), shape)[0] == expected


@pytest.mark.parametrize(
    "pdf_name, expected",
    [
        ("Fantasy-Set-3.pdf", "fantasy"),
        ("dress-me-up-knight.pdf", "knight"),
        ("PRINCESS_book.pdf", "princess"),
        ("scan-004.pdf", "misc"),
    ],
)
def test_group_comes_from_the_source_pdf_name(pdf_name, expected):
    shape = Shape(aspect=1.0, area_frac=0.03, centre_y=0.5)

    assert HeuristicClassifier().classify(_sidecar(source_pdf=pdf_name), shape)[1] == expected


def test_shape_of_is_page_relative():
    shape = shape_of(_sidecar(bbox=BBox(x=0, y=250, w=200, h=100), page=(1000, 1000)))

    assert shape.aspect == pytest.approx(2.0)
    assert shape.area_frac == pytest.approx(0.02)
    assert shape.centre_y == pytest.approx(0.30)


def test_classify_sidecar_stamps_the_result():
    sidecar = _sidecar(source_pdf="knight.pdf")

    classify_sidecar(sidecar, Shape(aspect=5.0, area_frac=0.02, centre_y=0.5))

    assert (sidecar.category, sidecar.group) == ("weapon", "knight")


def test_rejects_a_classifier_that_invents_a_category():
    class Rogue:
        def classify(self, sidecar, shape):
            return "jetpack", "misc"

    with pytest.raises(ValueError, match="unknown category"):
        classify_sidecar(_sidecar(), Shape(1.0, 0.03, 0.5), Rogue())


def test_shape_of_refuses_a_sidecar_with_no_recorded_page_size():
    stale = _sidecar(page=(0, 0))

    with pytest.raises(ValueError, match="no page dimensions recorded"):
        shape_of(stale)
