# What the scans actually contain

*Established 2026-08-25 by inspecting the Fantasy set, then **corrected the same
day** by a 108-page hand survey of all three books. The corrected numbers are
below; the superseded ones are called out because the mistake is instructive.*

## The assumption that was wrong

The pipeline was built to treat **every page as a sheet of cut-out items**. That
is false. Only about a third of pages are. The rest are paper-doll base bodies and
illustration plates, and running the extractor over them produces garbage items —
cropped torsos and chunks of scenery — that then have to be QA'd back out.

## The three page types

Hand-labelled across all 18 PDFs (102 unique pages; 6 survey rows were duplicates):

| Type | Count | What it is |
|---|---|---|
| **Base body** | 63 | One or two dolls in underwear on a decorative background. The paper-doll bases. |
| **Item sheet** | 35 | Loose outfits, hats, crowns, weapons, boots, mermaid tails, even a saddled horse. The actual catalog content. |
| **Illustration** | 10 | Fully-dressed characters posed together — inspiration plates, not cuttable. Visually similar to item sheets and the main risk of false positives. |

The corpus also contains **duplicate pages**: `…075945` p6 and `…170805` p0 are
the same physical page scanned into two PDFs. Any per-page metric double-counts
them.

Whole PDFs tend to be one type: `…080438` is bodies then 10 item pages;
`…081623` is 10 item pages end to end; `…075945` is 12 body pages.

## The signal that separates them — and how far it actually goes

**Page decoration bleeds off the page edge. Items float in white space.** Counting
regions clear of a 2% margin is the strongest single signal available.

⚠️ **The original claim here — "item sheets: 10–31 floating regions" — was true of
Fantasy only, and generalising it was wrong.** Measured across all three books:

| Book | Item-sheet floating regions |
|---|---|
| Fantasy | 10–31 |
| Fantasy w Boy | 3–26 |
| Knight | 4–6 |

In the other two books the cut-outs **touch each other** and merge into one
region, so **13 of 35 real item sheets fall at or below a ≥8 threshold**. Raising
render DPI does not fix it (tested at 100/150/200/300) because the items are
genuinely in contact on the page.

The lesson is about method, not thresholds: a signal measured on one book was
written up as a property of the corpus. Anything derived from a single book should
be treated as a hypothesis until a second one is checked.

### Two failure modes behind almost every error

1. **The segmenter merges things.** A doll whose hair overlaps a dark sky welds
   into the background; twenty items touching each other weld into one blob. Until
   regions survive contact, a floating count measures the *scan*, not the page.
2. **The margin rule tests proximity, not bleed.** One page loses ~20 items
   because its blob starts 5 px above the 2% line without ever running off the
   page. The rule should require actual contact with the scanned-content edge.

Related: these scans do not fill the mediabox — art occupies roughly the top 60%
with white below — so page area overstates the denominator and every area-based
fraction is deflated. Crop to scanned content before computing them.

## What this changes

1. **Page triage comes first.** Extraction should route by page type instead of
   running one path over everything. This is new work the roadmap never had.
2. **Border-touching regions are decoration.** Discarding them removes most of
   what QA was previously catching after the fact.
3. **Rotation is real.** `…170658` pages 0–1 are scanned landscape — the doll lies
   horizontal. Needs detection and correction, or those pages yield nothing.
4. **Expected yield.** ~22 item pages × ~13 regions ≈ **280 candidate items from
   Fantasy alone**, before QA. The original project's 219 accepted items look
   consistent with that, which is reassuring about both corpora.

## The blocking step is unblocked

`characters.json` needed "a real base-body image", and it was the one thing
standing between a compiling app and a playable one since 2026-07-02.

There are now **~13 base bodies in one PDF alone** (`…075945`), each a
front-facing full-length doll, arms clear of the torso, on a plain white centre.
That is close to the ideal case for snap-point authoring. Pick one, cut it out,
and place the points.

---

## Status of the two triage modules (2026-08-25)

> **2026-09-19.** The stage now exists as `tools/triage_pages.py`. It writes one
> manifest per PDF to `content/triage/<stem>.json` (rotation, verdict,
> confidence per page, plus a `confirmed` slot) and a contact sheet per verdict.
> Confirmations go in a hand-written `content/triage/<stem>.overrides.json` —
> `{"pages": {"3": "item_sheet"}}`, 0-indexed — and are merged into the manifest
> on every run, so re-triaging never loses them; a confirmation always wins over
> the verdict. `tools/extract_pdf.py --triage` follows the manifest: it rotates
> each page and cuts only confirmed item sheets or unconfirmed pages the
> classifier accepted, which is the item-sheet-only mode described below.

Both were built against the survey and then checked by agents who did not write
them, adjudicating every disagreement by looking at the page.

### `orientation.py` — ready

- 102/102 agreement with the human survey; 0 destructive rotations across 104
  real pages and 300 synthetic re-orientations. Correction verified by eye.
- Finds sideways pages by local-contrast segmentation rather than brightness
  thresholding — decorative backgrounds are smooth colour washes that a
  brightness threshold welds the doll into.
- The 180 branch is gated at `HEAD_180_DECISION = 0.56`, deliberately above the
  0.5 midpoint: measured `head_position` over all 61 corpus figures spans
  0.239–0.416, so a genuinely inverted page scores ≥0.584 and the gap in between
  falls back to "leave it alone". No upside-down page exists to validate against,
  so the branch stays conservative by construction.
- Known gaps: a sideways page with *no figure* is a coin flip (returns 90); skew
  of a few degrees is neither corrected nor reported.

### `pagetype.py` — **not ready to run unsupervised**

94% accuracy, but that number is in-sample: every threshold was fitted to the
same 102 pages it was then scored on. What the aggregate hides:

| Book | Accuracy |
|---|---|
| Fantasy (thresholds derived here) | 96.8% |
| Fantasy w Boy | 97.2% |
| **Knight** | **25%** — all 3 item sheets lost |

- **Item-sheet precision is 31/31.** What it *accepts* is trustworthy.
- **Item-sheet recall is 31/35.** What it *rejects* is not — four real item
  sheets were routed to a non-extractable type, losing ~35 cuttable items.
- The "zero illustrations misfiled as item sheets" safety property is **luck, not
  design**: the deciding threshold sits 0.0035 from the nearest counterexample.
- **Confidence is not usable as a review filter.** 21 of 24 low-confidence flags
  are on correct pages, while 3 of 6 real errors ride at confidence 0.75–0.80.

**Use it in item_sheet-only mode**, with a human confirming every non-item_sheet
verdict on books other than Fantasy. Fix in this order: (1) stop trusting
connectivity — split merged blobs before counting; (2) make the margin rule test
bleed rather than proximity, and crop to scanned content first; (3) drop the "one
big floating mass = a base body" premise, which Knight's full-figure suits of
armour defeat outright; (4) rebuild the confidence signal; (5) re-label a
genuinely held-out book before quoting an accuracy figure again.
