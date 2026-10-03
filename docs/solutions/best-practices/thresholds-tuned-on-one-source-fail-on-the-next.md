---
title: Thresholds tuned on one source fail on the next
date: 2026-08-25
category: best-practices
module: content_pipeline
problem_type: best_practice
component: tooling
severity: high
root_cause: missing_validation
resolution_type: documentation_update
applies_when:
  - Tuning a threshold or heuristic against a hand-labelled corpus
  - Quoting an accuracy figure for a classifier scored on the data it was fitted to
  - The corpus is drawn from several distinct sources such as books, vendors, scanners, or devices
  - Acting on a numeric margin or safety figure reported by another agent or tool
  - Writing a measured range into documentation as a property of the dataset
symptoms:
  - Aggregate accuracy of 94% concealed one source scoring 25%
  - 13 of 35 item sheets fell below a threshold derived from a single source
  - A range measured on one book was documented as a property of the whole corpus
  - A reported safety margin of 0.024 did not match the 0.084 measured directly
related_components:
  - documentation
  - testing_framework
tags:
  - calibration
  - validation
  - held-out-data
  - in-sample-accuracy
  - heuristics
  - thresholds
  - cross-source-validation
  - content-pipeline
---

# Thresholds tuned on one source fail on the next

## Context

The content pipeline turns scans of physical "Dress Me Up" sticker books into an
app catalog. Pages come in three kinds — paper-doll base bodies, sheets of loose
cut-out items, and full-bleed illustration plates — and only the item sheets are
worth extracting. A page classifier was needed to route them.

The separating signal looked clean. Page decoration bleeds off the paper edge
while real cut-outs float in white space, so counting regions that clear a 2%
margin should tell the types apart. Measured on the Fantasy book — 9 PDFs, 62
pages, the first set to come off Drive — item sheets produced 10–31 floating
regions and everything else produced 0–4. That gap is wide, unambiguous, and was
written straight into `docs/CONTENT-STRUCTURE.md` as a property of *the corpus*,
then hardened into `ITEM_SHEET_FLOATING = 8` at
`tools/dressup_pipeline/pagetype.py:72`.

Both steps were wrong in the same way, and the second inherited the first.

A hand survey of all three books (102 unique pages) showed the range is a fact
about Fantasy alone:

| Book | Item-sheet floating regions |
|---|---|
| Fantasy | 10–31 |
| Fantasy w Boy | 3–26 |
| Knight | 4–6 |

In the other two books the cut-outs **touch each other on the paper** and merge
into a single region. Rendering at higher DPI does not recover them — tested at
100, 150, 200 and 300 — because the contact is physical, not a sampling artifact.
**13 of 35 real item sheets fall at or below the ≥8 gate.**

The accuracy number hid it. The classifier scored 96/102 ≈ 94%, but every
threshold in the module had been fitted to those same 102 hand-labelled pages, so
the score measured the fit rather than the classifier. Splitting the same result
by book is all it took:

| Book | Accuracy |
|---|---|
| Fantasy (where the thresholds came from) | 96.8% |
| Fantasy w Boy | 97.2% |
| **Knight** | **25%** — 3 of 4 pages wrong, every item sheet lost |

## Guidance

**A threshold derived from one source is a hypothesis about that source. It earns
the word "corpus" only after a second source confirms it.**

Four practices follow, all cheap:

**1. Stratify every accuracy number by source before quoting it.** One aggregate
figure over a pooled corpus will hide a total failure on any source small enough
to be outvoted. Knight is 4 pages out of 102; at 25% accuracy it moves the
aggregate by less than two points while losing 100% of its extractable content.
The per-source breakdown costs one `groupby` and is the difference between "94%"
and "unusable on a third of the books".

**2. Say "in-sample" out loud, or hold something out.** If the constants were
tuned against the labels you are now scoring against, the number is a restatement
of the tuning. Either reserve a source before tuning starts, or label the figure
in-sample everywhere it appears — including in the module docstring, which is
where the next engineer will actually read it.

**3. Manufacture held-out data when the corpus cannot supply it.** Where a case
is absent from real data, synthesise it. `tools/tests/test_orientation.py:32`
defines a `rotate_cw` helper and parametrizes the detector over 90/180/270
(`tools/tests/test_orientation.py:72-81`), asking it to recover an orientation
that was applied artificially. That converts "we have no upside-down page" from a
blind spot into a test.

**4. Re-measure a reported number before acting on it.** A quantity quoted in a
report is not the same as the quantity in the code, even when both carry the same
name.

**Report the asymmetric metric, not the symmetric one.** Precision and recall
diverged sharply here: item-sheet precision was 31/31 while recall was 31/35.
What the classifier *accepts* is trustworthy; what it *rejects* is not. A single
"94% accurate" collapses that distinction and hides which direction the errors
run — and the directions cost very different amounts.

## Why This Matters

The failure is quiet, which is what makes it expensive. A classifier that is
wrong loudly gets fixed. This one reported 94% and would have been run across the
corpus on the strength of it, silently dropping every Knight item sheet — roughly
35 cuttable items — into a page type the extractor never opens. Nothing would
have errored. The catalog would simply have been short, and the shortfall would
have been discovered much later, when someone wondered why the knight book
contributed no armour.

Two related traps showed up in the same module and are worth naming because both
manufacture false confidence:

**A safety property can hold by luck.** The classifier misfiled zero
illustrations as item sheets, which is the expensive direction — it feeds
uncuttable art into the catalog — and the docstring at
`tools/dressup_pipeline/pagetype.py:32` originally presented that as deliberate. It was
not robust: the deciding threshold `FLOATING_MASS_FRAC = 0.035`
(`tools/dressup_pipeline/pagetype.py:82`) sits about 0.0035 from the nearest
counterexample. The comment above it concedes the gap is "3.0% to 3.9%, so this
threshold is tight by construction". A property with a margin that thin is an
observation about the sample, not a guarantee.

**A confidence signal can be anti-correlated with correctness.** The module
exposes `needs_review` at `tools/dressup_pipeline/pagetype.py:114`, gated on
`LOW_CONFIDENCE = 0.4` (line 93). In practice 21 of its 24 low-confidence flags
landed on pages that were *correct*, while 3 of the 6 genuine errors rode at
confidence 0.75–0.80. A reviewer working that queue does 21 units of pointless
work and still misses half the mistakes. A confidence signal that has not been
checked against actual outcomes is decoration.

**Retracted claims outlive their retraction.** The single-book range was
corrected in `docs/CONTENT-STRUCTURE.md` first, and for a while that was the only
place carrying the correction. The same claim stayed live in the module's own
docstring — the likeliest place an engineer would actually look — asserting that
discarding border-touching regions "splits a clean item sheet (10-31 floating
regions) from a base body or an illustration (0-4)" with no mention that this was
Fantasy only, and reporting "95/101 correct" without flagging it as in-sample.

Both are now fixed at `tools/dressup_pipeline/pagetype.py:16-22` (the per-book
spread and why higher DPI does not recover it) and `:32-48` (the in-sample label,
the per-book accuracy split, and the precision/recall asymmetry). The lesson
stands regardless: a correction filed in one place is not a correction. **When a
measurement is retracted, grep for it everywhere it was asserted** — docstrings,
comments, test names, commit messages — because each surviving copy is a future
engineer's first source.

## When to Apply

Apply this whenever a constant is derived from measured data rather than chosen
from a specification. Specifically:

- The corpus arrives in natural groups — per book, per scanner, per customer, per
  region, per source system — and a threshold is fitted across the pool.
- The number of groups is small enough that one can be entirely outvoted in an
  aggregate. Three books, where one is 4 pages of 102, is precisely this shape.
- The physical process behind the data can differ between groups. Here, whether
  the printer left white space between cut-outs is a per-book decision that
  changes the signal completely, and no amount of resolution recovers it.
- A validation report hands you a number to act on that you did not measure
  yourself.

It applies with less force when the threshold comes from a specification (a
protocol limit, a documented API bound) rather than from fitting, though even
then a spot-check against real data is cheap.

## Examples

**Before — a measurement generalised past its evidence.** The docstring still
carries this framing at `tools/dressup_pipeline/pagetype.py:12-14`:

> *How many regions float clear of the page edge.* Page decoration bleeds off the
> edge; real cut-outs sit in white space. Discarding border-touching regions
> splits a clean item sheet (10-31 floating regions) from a base body or an
> illustration (0-4) without looking at the picture at all.

Stated as a property of pages in general. It is a property of one book.

**After — the corrected form**, now in `docs/CONTENT-STRUCTURE.md`, keeps the
per-book spread visible so the next reader cannot inherit the overreach:

```markdown
⚠️ The original claim here — "item sheets: 10–31 floating regions" — was true of
Fantasy only, and generalising it was wrong. Measured across all three books:

| Book          | Item-sheet floating regions |
| Fantasy       | 10–31 |
| Fantasy w Boy | 3–26  |
| Knight        | 4–6   |
```

**Before — one pooled number.**

```
accuracy: 96/102 = 94.1%
```

**After — the same result, split by source.** Nothing new was computed; the
grouping alone exposes the failure:

```
Fantasy        60/62 = 96.8%
Fantasy w Boy  35/36 = 97.2%
Knight          1/4  = 25.0%    <- every item sheet lost
```

**Before — acting on a number from a report.** A validation pass flagged the
orientation module's 180° branch as sitting "0.024 away from firing" on two
Knight pages, and recommended a rewrite of the head-position cue to fix it.

**After — re-measuring the quantity the code actually uses.** Sweeping
`head_position` across all 61 figures the module finds in the corpus gave a range
of **0.239–0.416** against a 0.5 flip: roughly 0.084 of headroom, with nothing
within 0.06 of the boundary. The reported 0.024 belonged to a different
sub-quantity. The measurement supported a smaller and better fix — an asymmetric
gate rather than a rewritten cue — recorded at
`tools/dressup_pipeline/orientation.py:85-91`:

```python
# Returning 180 is the only way this module can corrupt an upright page, and no
# upside-down page exists in the corpus to validate it against. So the bar for
# 180 is deliberately higher than the bar for 0: measured over all 61 figures in
# the corpus, head_position spans 0.239-0.416, meaning a genuinely inverted page
# would score >= 0.584. Gating at 0.56 keeps every inverted page while leaving a
# 0.14-wide dead band above anything real, where the answer falls back to 0.
HEAD_180_DECISION = 0.56
```

The branch itself is asymmetric on purpose
(`tools/dressup_pipeline/orientation.py:195-198`): between 0.5 and the gate the
figure reads as inverted by the letter of the cue but not by enough to act on, so
the answer falls back to "leave the page alone". Note the comment records the
measured range that justifies the constant — a later reader can check whether the
justification still holds on a new book instead of guessing what 0.56 meant.

**The test-suite contrast is the sharpest example in the tree.**
`tools/tests/test_orientation.py` builds synthetic pages, turns them through
90/180/270 and asserts they come back
(`tools/tests/test_orientation.py:72-81`) — held-out cases the corpus does not
contain. `tools/tests/test_pagetype.py` asserts against pages drawn from the same
labelled set the thresholds were fitted to, references "Fantasy w Boy" exactly
once (line 229) and Knight not at all. One suite manufactures evidence it lacks;
the other confirms the fit. The suites pass together — 95 tests green at the time
of writing — which is precisely why passing tests were not enough to catch this.

## Status

The classifier is usable in **item_sheet-only mode**: its item-sheet precision is
31/31, so what it accepts can be trusted, while every non-item_sheet verdict on a
book other than Fantasy needs a human look. Fix order recorded in
`docs/CONTENT-STRUCTURE.md`: stop trusting connectivity (split merged blobs before
counting), make the margin rule test bleed rather than proximity, drop the "one
big floating mass = a base body" premise that Knight's full-figure suits of armour
defeat, rebuild the confidence signal, and re-label a genuinely held-out book
before quoting an accuracy figure again.

All of the above is staged but uncommitted at the time of writing. The repository
carries two prior commits — `Seed: recover Dress-me-up project memory as a rebuild
spec` and `feat: graft rebuilt vertical slice onto the recovery seed` — and the
triage modules are part of neither.

**Which claims here you can re-check, and which you cannot.** Every code citation
above is verifiable against the tree, and was. The survey numbers are not: the
hand-labelling that produced them (the 102 page labels, the per-book accuracies,
precision and recall, the confidence-flag counts) has no artifact checked into the
repository, so a future reader can confirm they are arithmetically consistent and
that they agree with `docs/CONTENT-STRUCTURE.md`, but cannot re-derive them without
repeating the labelling pass. Treat them as reported rather than reproducible — and
note that this is itself an instance of the lesson: a number with no artifact behind
it is one nobody can check later.

## Related

- `docs/CONTENT-STRUCTURE.md` — the canonical write-up of what the scans contain,
  now carrying the corrected per-book table, the two root-cause failure modes
  (merged regions, and a margin rule that tests proximity rather than bleed), and
  the fix order for the classifier.
- `docs/memory/decisions.md` — KTD-16 records the related measurement mismatch
  inherited from the lost original: its `--min-quality` filtered SAM mask
  confidence while this pipeline scores the cutout, so "219 items at 0.90" is not
  a target this pipeline reproduces. Same class of error, different vintage.
