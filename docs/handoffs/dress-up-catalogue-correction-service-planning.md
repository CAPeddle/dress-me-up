---
artifact_contract: "ce-handoff/v1"
created_at: "2026-09-19T19:52:41Z"
title: "Start planning the catalogue-correction service (label and re-crop the extracted items)"
summary: "The user wants a small hosted website on this machine that shows each extracted item, lets them type what is wrong with it, and feeds those corrections back into the pipeline so items are relabeled or reprocessed; nothing is designed yet, this handoff carries the facts a brainstorm and plan need."
keywords: ["dress-me-up", "catalogue", "correction", "curation", "relabel", "recrop", "sidecars", "classify", "segmenter", "web-tool", "planning"]
cwd: "/home/cpeddle/projects/personal/dress-me-up"
resume_focus: "Brainstorm then plan the catalogue-correction service: what the parent sees, what they can say about an item, where corrections are stored, and how the pipeline honours them on relabel or reprocess."
repository: "CAPeddle/dress-me-up"
repo_root_sha: "d7a9304fc3fca678830df7db61b27e5c8ad5673d"
branch: "feat/playable-web-version"
head: "b1cb807608b099e5327dc05519e4fefcf74ffd95"
---

# Planning start: the catalogue-correction service

Sibling of `docs/handoffs/dress-up-return-with-corrected-catalogue.md`,
which is where the web version waits. This one starts new work; nothing
below is designed, planned or begun.

## What the user asked for (their words, 2026-09-19)

"A large percentage of the items in the game at the moment are mislabeled
and aren't cropped correctly." They want "a tool that helps refine what the
artifacts are": "a hosted web site on this Z2 [this machine], serves up the
artifacts and allows me to type in what's wrong with each item. The server
accepts them and then we either relabel or re process it." Afterwards they
return to the web version with the items catalogued correctly.

Everything else in this document is my reading of the code and the corpus,
offered as planning input, not as decisions.

## The two kinds of wrong, and which stage owns each

- **Mislabeled** is the classify stage. `tools/dressup_pipeline/classify.py`
  `HeuristicClassifier._category` (lines 63-80) slots an item from its
  bounding-box geometry relative to the page (`shape_of`, line 39) and
  `_group` (82-94) from folder then filename. There is no image
  understanding, which is why hats come out as torsos. **There is no human
  override today**: `classify_sidecar` (line 105) sets `category` and
  `group` unconditionally, so any correction written straight into the
  sidecar is undone by the next `classify_and_qa.py` run. The service's
  corrections therefore need their own field or file that classify reads
  and respects. The precedent in this repo is triage's
  `content/triage/<stem>.overrides.json` (`{"pages": {"6": "base_body"}}`),
  read by `dressup_pipeline/triage.py` as `confirmed` beside the machine
  `verdict`.
- **Badly cropped** is the extract stage. `tools/dressup_pipeline/extract.py`
  `ThresholdSegmenter.regions` (line 115 on) thresholds paper away and
  keeps connected blobs above `min_area_frac`; two stickers touching, or a
  drop shadow bridging them, become one cutout ("welded"), and a light-inked
  sticker can lose its edge. `Segmenter` is a Protocol (line 99) so a
  different segmenter is a seam, not a rewrite (KTD-16). Item ids are
  positional (`<stem>-pNNN-iNNN`), so a re-cut page renumbers its items;
  as of commit `92ea0b6` a re-extraction replaces that PDF's outputs and
  carries classify/QA fields only where geometry is identical. A correction
  keyed to an item id therefore does not survive a re-cut of that page
  unless it is keyed to something stabler (page plus bbox, or a content
  hash).

## The corpus the tool would serve (machine-local, gitignored)

`content/sidecars/<pdf-stem>/<id>.png` plus `<id>.sidecar.json` (KTD-12;
fields in `tools/dressup_pipeline/models.py` lines 60-90: geometry from
extract, `category`/`group` from classify, `quality`/`accepted`/`notes`
from QA; `notes` is a free list of strings QA already uses for reasons like
"small (111x172)"). Today: 333 sidecars over three PDF output directories,
253 accepted at 0.90, all group `fantasy`, 109 MB. Page renders are not
kept; `extract.render_page(pdf, page, dpi)` re-renders on demand from
`content/source/<Set>/<stem>.pdf`. Contact sheets per verdict exist for
pages, not items, in `content/triage/`.

Downstream, `tools/build_catalog.py` reads accepted sidecars into
`app/src/main/assets/` (contract: `CatalogItem` in `models.py` line 155,
`CatalogItemDto` in Kotlin, `web/js/catalog.js`); the web version shows
items grouped by category in `CATEGORIES` order.

## Existing pieces worth reusing or copying the shape of

- `web/serve.py`: a standard-library static server that requires
  `--host`, refuses any wildcard bind (also by the bound address), serves
  two roots read-only with a CSP header, and 405s every write. The
  correction service needs writes, so it is not this file, but its posture
  (one explicit home address, no dependencies, tests in
  `tools/tests/web/test_serve.py`) is the house style.
- `playtest-rig/collector.py` (gitignored, not to be copied into `app/` or
  `web/`) is the one thing in the tree that accepts POSTs; `review.js` and
  `review.html` there render local data into a page. Shape only.
- `tools/triage_pages.py` writes contact sheets with PIL; an item contact
  sheet per category would be a cheap first view.
- `docs/solutions/best-practices/thresholds-tuned-on-one-source-fail-on-the-next.md`
  and `docs/CONTENT-STRUCTURE.md`: why a heuristic tuned on Fantasy will
  not carry to Knight, which argues for human labels as the source of truth
  rather than better thresholds.

## Questions the brainstorm should settle (my list)

1. What the parent can *say*: free text only (as asked), or free text plus
   the two structured verdicts the pipeline can act on (a category from
   `CATEGORIES`, and "this is two stickers" / "the crop is wrong")?
   Free text alone needs a human or an agent to turn it into an action.
2. Where corrections live so the sidecar rule holds: a per-item field the
   classify stage honours, or a corrections file per PDF beside the triage
   overrides. And what they are keyed by, given re-cuts renumber items.
3. What "reprocess" means for a bad crop: manual bbox editing in the
   browser, a re-cut of the page with different segmenter parameters, a
   split of one welded cutout, or a swap to a better segmenter (SAM is the
   named experiment in KTD-16). Each has a very different cost.
4. Whether the same tool also takes the triage confirmation the plan's R7
   still owes (pages, not items), since the parent is already looking.
5. Scope of "hosted": home-network only, one explicit address, like
   `serve.py`; no accounts, nothing on the tablet; whether the parent uses
   it from the tablet or the desktop changes the touch-target rules.
6. Whether corrections are tracked in git (they are hand-authored, like
   `tools/base_bodies.json`) or stay machine-local like the corpus.

## Constraints that carry over (the user's)

Never write a network address or the tablet's hostname into a tracked
file. Nothing from `playtest-rig/` is copied into `app/` or `web/`. The
Android app declares no permissions and is untouched. Sidecar stages only
add fields (CLAUDE.md, "Sidecars are the pipeline's unit of state"; the
re-extraction exception is documented there). Delegate implementation
units to Opus subagents and verify (memory `delegate-to-opus-then-verify`).
Tests use tmp dirs. Engineering posture: modular but earned, no framework
for its own sake.

## Where to start

`ce-brainstorm` with the user's request above as the feature description,
then `ce-plan`. Read first: `CLAUDE.md` (Architecture and Constraints),
`tools/dressup_pipeline/classify.py` lines 53-115, `extract.py` lines
99-140 and 145-215, `models.py` lines 60-130, `web/serve.py` lines 1-60.
The web version branch is the base; whether this work goes on the same
branch or its own is the user's call.
