import pytest

from dressup_pipeline.models import BBox, Sidecar, SidecarError, iter_sidecars


def _sidecar(**overrides):
    base = dict(item_id="a-p000-i000", source_pdf="a.pdf", page=0, bbox=BBox(1, 2, 30, 40), image="a.png")
    return Sidecar(**{**base, **overrides})


def test_roundtrips_through_json(tmp_path):
    original = _sidecar(category="hat", group="knight", quality=0.93, accepted=True, notes=["small"])
    path = tmp_path / "a.sidecar.json"
    original.write(path)

    assert Sidecar.read(path) == original


def test_accepts_the_companion_category():
    """A creature placed on a character, not worn by it — see CONCEPTS.md."""
    _sidecar(category="companion", group="fantasy").validate()


def test_rejects_unknown_category():
    with pytest.raises(SidecarError, match="unknown category"):
        _sidecar(category="jetpack").validate()


def test_rejects_out_of_range_quality():
    with pytest.raises(SidecarError, match="outside 0..1"):
        _sidecar(quality=1.4).validate()


def test_malformed_json_names_the_file(tmp_path):
    path = tmp_path / "broken.sidecar.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(SidecarError, match="broken.sidecar.json"):
        Sidecar.read(path)


def test_completeness_flags_track_populated_fields():
    unclassified = _sidecar()
    assert not unclassified.is_classified
    assert not unclassified.is_qa_complete

    done = _sidecar(category="top", group="fantasy", quality=0.5, accepted=False)
    assert done.is_classified
    assert done.is_qa_complete  # rejected still counts as QA'd


def test_iter_sidecars_is_sorted_for_reproducible_builds(tmp_path):
    for item_id in ("c", "a", "b"):
        _sidecar(item_id=item_id).write(tmp_path / f"{item_id}.sidecar.json")

    assert [s.item_id for _, s in iter_sidecars(tmp_path)] == ["a", "b", "c"]
