"""The repair queue: the rejections a person recorded, read back as work.

These tests pin two things the queue exists for. A rejection has to stay
distinguishable by *kind* (R14) — a welded pair and a thing that was never a
costume are different jobs, and a queue that blurs them makes the reviewer look
at all of them again. And a correction whose cutout has moved has to surface as
lost labelling rather than as a gap nobody notices (R9): that is the failure the
whole geometry-keyed design (KTD2) trades for, so it is the one the report has to
name out loud.

Nothing here asks the queue to repair anything (R15). It reads and prints, so the
last test pins that the corpus is untouched afterwards.
"""

import json

import pytest

import repair_queue as repair_queue_cli
from dressup_pipeline.corrections import REJECTION_KINDS, corrections_path
from dressup_pipeline.models import SIDECAR_SUFFIX

# Enough of a sidecar to be a real item; the queue only ever reads geometry, but
# a corpus of half-processed items would hide a matcher bug behind a skip.
DONE = {"category": "hat", "group": "fantasy", "quality": 0.95, "accepted": True}


def _run(tmp_path, root, capsys, corrections=None):
    """The CLI over a corpus, at the directory `sidecar_corpus` writes labels into."""
    code = repair_queue_cli.main([
        "--sidecars", str(root),
        "--corrections", str(corrections if corrections is not None else tmp_path / "corrections"),
    ])
    out, err = capsys.readouterr()
    return code, out, err


def report_mentions_no_kind(out):
    """No kind heading appears, so an empty queue cannot read as a populated one."""
    return not any(kind in out for kind in REJECTION_KINDS)


# -- grouping by kind ---------------------------------------------------------


def test_rejections_are_grouped_by_kind(tmp_path, sidecar_corpus):
    """A welded pair and a thing that was never dress-up are separate jobs (R14)."""
    root, _ = sidecar_corpus([
        {"item_id": "welded", "rejection": "multi_item", **DONE},
        {"item_id": "sticker-of-a-cat", "rejection": "not_an_item", **DONE},
        {"item_id": "half-a-hat", "rejection": "bad_crop", **DONE},
        {"item_id": "fine", "correction": "hat", **DONE},
    ])

    report = repair_queue_cli.build_repair_report(
        corrections_dir=tmp_path / "corrections", sidecar_root=root
    )

    assert {kind: len(entries) for kind, entries in report.by_kind.items()} == {
        "multi_item": 1,
        "not_an_item": 1,
        "bad_crop": 1,
    }
    assert [entry.item_id for entry in report.by_kind["multi_item"]] == ["welded"]
    assert [entry.item_id for entry in report.by_kind["not_an_item"]] == ["sticker-of-a-cat"]
    # The item somebody filed is not repair work, however odd its cutout looked.
    assert "fine" not in {entry.item_id for entries in report.by_kind.values() for entry in entries}


def test_the_queue_reports_every_kind_the_vocabulary_allows(tmp_path, sidecar_corpus):
    """Read from REJECTION_KINDS, so a kind added to the record is queued too."""
    root, _ = sidecar_corpus([
        {"item_id": f"rejected-{kind}", "rejection": kind, **DONE} for kind in REJECTION_KINDS
    ])

    report = repair_queue_cli.build_repair_report(
        corrections_dir=tmp_path / "corrections", sidecar_root=root
    )

    assert set(report.by_kind) == set(REJECTION_KINDS)


def test_a_multi_item_rejection_is_queued_for_segmentation_not_a_re_render(tmp_path, sidecar_corpus, capsys):
    """The heading has to say what the later work is, because the obvious guess is wrong.

    docs/solutions/best-practices/thresholds-tuned-on-one-source-fail-on-the-next.md
    records that re-rendering at 100..300 DPI does not part stickers that touch on
    the paper. A queue that just said "4 bad cutouts" would invite that sweep.
    """
    root, _ = sidecar_corpus([{"item_id": "welded", "rejection": "multi_item", **DONE}])

    code, out, _ = _run(tmp_path, root, capsys)

    assert code == 0
    assert "multi_item" in out
    assert "segment" in out.lower()


# -- the pages cluster --------------------------------------------------------


def test_the_report_names_the_source_pdf_and_page_of_every_rejection(tmp_path, sidecar_corpus, capsys):
    """Grouped by PDF and page, so the pages worth pointing a segmenter at stand out."""
    root, _ = sidecar_corpus([
        {"item_id": "a", "source_pdf": "20260509081050.pdf", "page": 3, "rejection": "multi_item", **DONE},
        {"item_id": "b", "source_pdf": "20260509081050.pdf", "page": 3, "rejection": "multi_item", **DONE},
        {"item_id": "c", "source_pdf": "20260509081050.pdf", "page": 3, "rejection": "multi_item", **DONE},
        {"item_id": "d", "source_pdf": "20260509081623.pdf", "page": 7, "rejection": "multi_item", **DONE},
    ])

    code, out, _ = _run(tmp_path, root, capsys)

    assert code == 0
    # The busy page is named once, with its count, rather than three times.
    assert "20260509081050 p3" in out
    assert out.count("20260509081050 p3") == 1
    assert "20260509081623 p7" in out
    assert "3" in out.split("20260509081050 p3")[1].split("\n")[0]
    # The stem is the PDF as a correction records it, never this machine's path.
    assert str(root) not in out


def test_one_pdf_page_holds_its_rejections_together(tmp_path, sidecar_corpus, capsys):
    """Interleaved pages still print as two blocks, which is the whole clustering point."""
    root, _ = sidecar_corpus([
        {"item_id": "a", "source_pdf": "early.pdf", "page": 0, "rejection": "multi_item", **DONE},
        {"item_id": "b", "source_pdf": "late.pdf", "page": 0, "rejection": "multi_item", **DONE},
        {"item_id": "c", "source_pdf": "early.pdf", "page": 0, "rejection": "multi_item", **DONE},
    ])

    code, out, _ = _run(tmp_path, root, capsys)

    assert code == 0
    assert out.count("early p0") == 1 and out.count("late p0") == 1
    lines = [line for line in out.splitlines() if "early" in line or "late" in line]
    assert [line.strip().split()[0] for line in lines] in (["early", "late"], ["late", "early"])


# -- the unmatched report (R9, AE1) -------------------------------------------


def test_a_correction_whose_cutout_moved_is_reported_as_unmatched(tmp_path, sidecar_corpus, capsys):
    """AE1. A re-extraction nudged one bbox; that label is lost work, and says so.

    The corrections for the items whose geometry did not change still apply — that
    half of AE1 is asserted here too, because a matcher that reported *everything*
    as unmatched would otherwise pass this test.
    """
    root, built = sidecar_corpus([
        {"item_id": "moved", "rejection": "multi_item", **DONE},
        {"item_id": "still-there", "rejection": "bad_crop", **DONE},
        {"item_id": "filed", "correction": "hat", **DONE},
    ])
    moved = built["moved"]
    old_box = f"[{moved.bbox.x},{moved.bbox.y},{moved.bbox.w},{moved.bbox.h}]"
    moved.bbox.x += 1  # what a re-extraction does when the segmenter finds a different edge
    moved.write(root / f"moved{SIDECAR_SUFFIX}")

    report = repair_queue_cli.build_repair_report(
        corrections_dir=tmp_path / "corrections", sidecar_root=root
    )
    code, out, _ = _run(tmp_path, root, capsys)

    assert [correction.rejection for correction in report.unmatched] == ["multi_item"]
    assert [entry.item_id for entry in report.by_kind["bad_crop"]] == ["still-there"]
    # The cutout that moved is not repair work: nobody has ruled on what it became.
    assert "multi_item" not in report.by_kind
    assert code == 0
    assert "unmatched" in out and old_box in out
    # And the report says what the lost correction had said, not merely that one is lost.
    assert "multi_item" in out.split("unmatched corrections")[1]


def test_an_unmatched_correction_names_the_category_it_was_filed_under(tmp_path, sidecar_corpus, capsys):
    """A lost *label* is lost work too, and re-filing it needs to know which slot."""
    root, built = sidecar_corpus([{"item_id": "moved", "correction": "shoes", **DONE}])
    built["moved"].bbox.y += 4
    built["moved"].write(root / f"moved{SIDECAR_SUFFIX}")

    code, out, _ = _run(tmp_path, root, capsys)

    assert code == 0
    assert "shoes" in out.split("unmatched corrections")[1]


def test_a_rejection_whose_whole_pdf_has_vanished_is_unmatched_not_queued(tmp_path, sidecar_corpus, capsys):
    """The case `load_corrections` reads every file for: a stem the corpus no longer has.

    A lookup driven by the stems on disk would never open this PDF's file, and a
    whole pass of labelling would go unreported.
    """
    root, _ = sidecar_corpus([
        {"item_id": "gone", "source_pdf": "retired.pdf", "rejection": "multi_item", **DONE},
        {"item_id": "here", "source_pdf": "kept.pdf", "rejection": "bad_crop", **DONE},
    ])
    (root / f"gone{SIDECAR_SUFFIX}").unlink()

    report = repair_queue_cli.build_repair_report(
        corrections_dir=tmp_path / "corrections", sidecar_root=root
    )
    code, out, _ = _run(tmp_path, root, capsys)

    assert [correction.source_pdf for correction in report.unmatched] == ["retired"]
    assert set(report.by_kind) == {"bad_crop"}
    assert code == 0
    assert "retired" in out.split("unmatched corrections")[1]


# -- the empty and absent cases ----------------------------------------------


def test_a_corpus_with_no_rejections_reports_an_empty_queue_and_exits_zero(tmp_path, sidecar_corpus, capsys):
    """Nothing to repair is the good outcome, not a failure and not silence."""
    root, _ = sidecar_corpus([
        {"item_id": "a", "correction": "hat", **DONE},
        {"item_id": "b", "correction": "top", **DONE},
    ])

    code, out, err = _run(tmp_path, root, capsys)

    assert code == 0
    assert report_mentions_no_kind(out)
    assert "no rejections" in out
    assert err == ""


def test_an_unlabelled_corpus_reports_an_empty_queue_and_exits_zero(tmp_path, sidecar_corpus, capsys):
    """The real tree today: sidecars extracted, nobody through them yet."""
    root, _ = sidecar_corpus([{"item_id": "a", **DONE}, {"item_id": "b", **DONE}])

    code, out, err = _run(tmp_path, root, capsys)

    assert code == 0
    assert report_mentions_no_kind(out)
    assert err == ""


def test_a_corrections_directory_that_does_not_exist_is_an_empty_queue(tmp_path, sidecar_corpus, capsys):
    """Before the first labelling pass there is no directory; that is not an error."""
    root, _ = sidecar_corpus([{"item_id": "a", **DONE}])

    code, out, err = _run(tmp_path, root, capsys, corrections=tmp_path / "never-labelled")

    assert code == 0
    assert report_mentions_no_kind(out)
    assert err == ""


# -- the error paths ---------------------------------------------------------


def test_a_malformed_correction_file_exits_non_zero_and_names_the_file(tmp_path, sidecar_corpus, capsys):
    """Half an hour of labelling with a typo in it is to be fixed, not worked around."""
    root, _ = sidecar_corpus([{"item_id": "a", "correction": "hat", **DONE}])
    broken = corrections_path(tmp_path / "corrections", "hand-edited.pdf")
    broken.write_text('{"corrections": [', encoding="utf-8")

    code, out, err = _run(tmp_path, root, capsys)

    assert code == 1
    assert str(broken) in err
    # No half-report: a queue built from a file that may be missing records is
    # worse than none, because it reads as the whole of the work left.
    assert out == ""


def test_a_record_naming_another_pdf_exits_non_zero_and_names_the_file(tmp_path, sidecar_corpus, capsys):
    """A record pasted into the wrong PDF's file would label a different scan's page."""
    root, built = sidecar_corpus([{"item_id": "a", "rejection": "multi_item", **DONE}])
    stray = corrections_path(tmp_path / "corrections", "somebody-elses-book.pdf")
    stray.write_text(
        json.dumps({"corrections": [{
            "source_pdf": "fantasy-book-1",
            "page": 0,
            "bbox": {"x": 1, "y": 2, "w": 3, "h": 4},
            "page_width": built["a"].page_width,
            "page_height": built["a"].page_height,
            "dpi": built["a"].dpi,
            "category": "hat",
            "rejection": None,
        }]}),
        encoding="utf-8",
    )

    code, _, err = _run(tmp_path, root, capsys)

    assert code == 1
    assert str(stray) in err


def test_a_malformed_sidecar_exits_non_zero_and_names_it(tmp_path, sidecar_corpus, capsys):
    """A sidecar that cannot be read is a hole in the matching, so it is not skipped."""
    root, _ = sidecar_corpus([{"item_id": "a", "rejection": "multi_item", **DONE}])
    (root / f"broken{SIDECAR_SUFFIX}").write_text("{not json", encoding="utf-8")

    code, _, err = _run(tmp_path, root, capsys)

    assert code == 1
    assert "broken" in err


def test_a_sidecar_root_that_does_not_exist_is_a_usage_error(tmp_path, capsys):
    """Refuse rather than report every label in the tracked files as lost work."""
    with pytest.raises(SystemExit) as exit_info:
        repair_queue_cli.main([
            "--sidecars", str(tmp_path / "nope"), "--corrections", str(tmp_path / "corrections"),
        ])

    assert exit_info.value.code != 0
    assert str(tmp_path / "nope") in capsys.readouterr().err


# -- R15: it reports, it repairs nothing -------------------------------------


def test_the_queue_changes_nothing_on_disk(tmp_path, sidecar_corpus, capsys):
    """R15. No cutout is re-made, no bbox edited, no correction file rewritten."""
    root, _ = sidecar_corpus([
        {"item_id": "welded", "rejection": "multi_item", **DONE},
        {"item_id": "filed", "correction": "hat", **DONE},
    ])

    def snapshot():
        return {
            path.relative_to(tmp_path).as_posix(): path.read_bytes()
            for path in sorted(tmp_path.rglob("*"))
            if path.is_file()
        }

    before = snapshot()
    code, _, _ = _run(tmp_path, root, capsys)

    assert code == 0
    assert snapshot() == before
