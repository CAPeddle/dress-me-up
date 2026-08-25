# Decisions

Numbered `KTD-n`, append-only. A superseded decision is marked, not deleted.

## ⚠️ Provenance warning — read before citing KTD-11..14

The original `docs/memory/decisions.md` **did not survive** the loss of the
Windows machine. Its existence and the IDs KTD-11..14 are attested by the
recovered project memory (`docs/ROADMAP.md`), but **the reasoning text was never
captured**.

What appears below for KTD-11..14 is a **reconstruction written on 2026-08-25**
from the surrounding roadmap text and from how the code was described. It is a
best-available inference, not recovered history. Do not cite it as "what was
decided and why" — cite it as "what we now believe was decided, and the reason
that best fits the evidence". If a reconstruction turns out to conflict with how
the code actually behaved, the code wins and the entry gets rewritten.

KTD-15 onward are decisions genuinely made on the new machine and are not
reconstructions.

---

## KTD-11 — Vertical slice before exhaustive content QA *(reconstructed)*

**Decision:** Prove the whole chain — PDF → sidecar → catalog → app → snap —
before QA'ing the full corpus.

**Reconstructed why:** The expensive risk is the pipeline/app contract being
wrong, not any individual item being ugly. A contract break found after QA'ing
hundreds of items wastes all of that work. The roadmap states the decision
directly; this rationale is inferred.

## KTD-12 — Sidecars as the pipeline's unit of state *(reconstructed)*

**Decision:** One JSON sidecar per extracted item, beside its PNG. Stages only
ever add fields.

**Reconstructed why:** Inferred from the roadmap's description of
`build_catalog.py` "aggregating accepted content sidecars". A stage can be re-run
alone, a half-processed corpus stays valid, and an item can explain its own fate.
The original may have chosen this for different reasons.

## KTD-13 — Snap logic is a pure function outside the UI *(reconstructed)*

**Decision:** `SnapCalculator` takes normalized coordinates and returns a
placement, knowing nothing about Compose.

**Reconstructed why:** The roadmap records `SnapCalculator` as separately unit
tested (4 tests) while the rest of the app was not, which only makes sense if it
was deliberately isolated from the UI. Given KTD-14, testability without a device
is the obvious motive.

## KTD-14 — Physical device only, so batch UI work *(reconstructed)*

**Decision:** All testing on a physical Galaxy Tab S6 Lite over `adb`. No
emulator.

**Reconstructed why:** `docs/TESTING.md` records this as recovered feedback — the
emulator did not work reliably on the original machine. **Consequence:** no live
UI feedback loop; batch UI changes into device sessions.

---

## KTD-15 — Rebuilt from the seed spec, not recovered (2026-08-25)

**Decision:** This tree is a fresh rebuild. The app code, the scanned PDFs, the
219 QA'd items, `decisions.md`, and the plan file are **gone** — the Windows
machine was retired before anything was pushed.

**Consequence:** Nothing here is the original code. Where this rebuild and the
recovered roadmap disagree, the roadmap describes the lost original and this tree
describes what now exists; neither is automatically right.

## KTD-16 — Threshold segmentation now, SAM as an experiment (2026-08-25)

**Decision:** The extract stage uses luminance thresholding plus connected-
component labelling. The original used **SAM (Segment Anything Model)**, and its
`--min-quality` filtered SAM's own `quality_score`.

**Why:** SAM needs a model download and realistically a GPU, which this machine
does not have. Thresholding runs anywhere, is deterministic, and is testable
without fixtures — enough to prove the contract, which is what KTD-11 asks for.

**Important:** `--min-quality 0.90` in this tree is **not** the same measurement
as the original's `--min-quality 0.90`. Ours is a composite of coverage, edge
fringe, size, and aspect (see `dressup_pipeline/qa.py`); theirs was SAM mask
confidence. The recovered "219 items at 0.90" is therefore not a target this
pipeline can be expected to reproduce.

**Open:** SAM is to be trialled later, possibly on rented GPU. `Segmenter` in
`dressup_pipeline/extract.py` exists so it can be swapped in without touching the
stages around it.

## KTD-17 — Repo lives at `~/projects/personal/dress-me-up` (2026-08-25)

**Decision:** This path, matching the convention in `docs/session-bootstrap.md`.

**Why:** Claude Code hashes the absolute project path for its per-project memory,
so moving the tree silently orphans that memory. An earlier scaffold at
`~/projects/dress-me-up` was grafted in here and deleted.
