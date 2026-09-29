# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Offline Android tablet dress-up game for a 7-year-old, sideloaded on a Galaxy Tab
S6 Lite. Content comes from scans of physical "Dress Me Up" sticker books. No
network, no accounts, no analytics — the app declares no permissions at all.

Spun off from `story-app` (a separate repo, also on this machine). They share a
target device and an offline-sideload posture and nothing else: story-app
generates flat-vector paper-doll parts, this one ingests scans.

Lives at `~/projects/personal/dress-me-up` and must stay there — Claude Code
hashes the absolute path for per-project memory (KTD-17).

## Read this first: what has and has not been verified

This tree was **rebuilt from the spec in `docs/`** — the original was lost with a
retired laptop (KTD-15). Consequences that will bite otherwise:

- **The Python pipeline is real and tested.** 48 tests pass, and the full chain
  has been run end to end on a synthetic PDF.
- **The Kotlin has never been compiled.** It was written on a machine with no JDK
  and no Android SDK. Treat every `.kt` file as unreviewed first-draft code:
  expect import and API-surface errors on the first build. Do not describe the
  app as working. Run `scripts/setup-ubuntu.sh` first.
- **`content/` is empty.** The scans and the 219 QA'd items did not survive.
  `build_catalog.py` produces an empty catalog until real PDFs land under
  `content/source/<Set>/`; `tools/make_smoke_pdf.py` writes a synthetic stand-in
  to `content/pdfs/` instead.
- **`docs/ROADMAP.md` and `docs/TESTING.md` describe the LOST ORIGINAL**, not
  this tree. Where they disagree with what is on disk, neither is automatically
  right — check before "fixing" code to match a doc.
- **KTD-11..14 in `docs/memory/decisions.md` are reconstructions**, not recovered
  text. They are labelled. Do not cite them as history.

## Commands

Environment (run this first — it is the whole toolchain in one script):

```bash
./scripts/setup-ubuntu.sh          # JDK 21, SDK, build-tools, udev, venv
./scripts/setup-ubuntu.sh --check  # report state, change nothing
```

Pipeline:

```bash
cd tools && .venv/bin/python -m pytest        # pipeline + web tests

tools/.venv/bin/python tools/make_smoke_pdf.py            # synthetic stand-in for a scan
tools/.venv/bin/python tools/triage_pages.py content/source/<Set>/*.pdf   # manifests + contact sheets -> content/triage/
tools/.venv/bin/python tools/extract_pdf.py content/source/<Set>/*.pdf --triage   # rotate + cut only item sheets
tools/.venv/bin/python tools/classify_and_qa.py --min-quality 0.90
tools/.venv/bin/python tools/correct_server.py        # the labelling pass -> tools/corrections/
tools/.venv/bin/python tools/build_catalog.py --group fantasy --body-height 1000
tools/.venv/bin/python tools/repair_queue.py          # what was rejected, and labels that lost their item
```

**The catalogue accepts only human labels.** `correct_server.py` serves a wall of
every extracted item on loopback; filing them writes `tools/corrections/<stem>.corrections.json`,
and `build_catalog.py` includes exactly the items carrying one of those labels,
under the category a person filed. So an un-corrected corpus builds an empty
catalog and exits non-zero naming the missing labelling — that is the ordinary
state of a corpus nobody has been through, not a failure. `--min-quality` no
longer gates anything: QA's verdict became advisory, and the build reports what
it would have excluded instead of applying it. The classifier still writes
`category` onto each sidecar, but that is a suggestion which only orders the
wall.

Real scans live under `content/source/<Set>/` (`Fantasy`, `Knight`, ...) because
`HeuristicClassifier._group` takes the group from the containing folder first —
scanner apps name files by timestamp, so the folder is usually the only place the
theme survives. The filename is the fallback, which is how the smoke PDF at
`content/pdfs/fantasy-smoke.pdf` still classifies, and how a PDF labelled by hand
with its theme works from any folder. Substitute whichever path the PDFs are in.

App (needs the setup script to have run):

```bash
./gradlew :app:testDebugUnitTest    # SnapCalculator
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Requires `local.properties` with `sdk.dir=...` (gitignored).

## Architecture

**One contract, one direction.** The pipeline writes
`app/src/main/assets/catalog.json` plus downsampled item PNGs; the app reads
them. Nothing else crosses. `CatalogItemDto` in `CatalogRepository.kt` and
`CatalogItem` in `dressup_pipeline/models.py` are the two ends of that contract,
and `web/js/catalog.js` (with `web/js/main.js`) is a third consumer reading the
same two files — change one, change all three. `bodies.json` plus `bodies/` is
the second file of that contract, written by the same build; both files carry
the same `build_id` and the same `scale` block, so a reader can refuse a
mismatched pair rather than draw a board at two different scales.

**Sidecars are the pipeline's unit of state** (KTD-12). Every extracted item gets
`<id>.png` plus `<id>.sidecar.json` beside it. Stages only ever *add* fields:
extract writes geometry, classify adds category/group, QA adds quality/accepted/
notes, build reads. So any stage can be re-run alone, a half-processed corpus is
still valid, and a rejected item can always explain itself. Never make a stage
rewrite a field an earlier stage owns. Extract is the one stage that also
*removes*: re-extracting a PDF replaces all of that PDF's outputs, so a page
triage no longer calls an item sheet, and a cutout a re-run no longer finds,
disappear instead of lingering for the catalog build to ingest. Downstream
fields survive that only where the item comes back with identical geometry —
same page, bbox, page size and DPI. A cutout that moved is a different item and
has to be classified and QA'd again.

**Human labels live beside the sidecar, never on it** (`dressup_pipeline/corrections.py`).
A correction is keyed by source PDF stem plus those same five geometry fields, so
`classify_sidecar` keeps its unconditional write and the additive rule needs no
exception. The five fields alone are not unique — two scans of one physical page
share byte-identical boxes — which is why the stem is part of the key. A
correction whose geometry matches nothing is kept and reported, never dropped.

**Page dimensions live in the sidecar, not on the CLI.** `shape_of()` classifies
from geometry relative to the page, and passing those dimensions separately made
it possible to classify against the wrong page size and silently mis-slot every
item. It refuses to run on a sidecar with no recorded page size instead.

**`SnapCalculator` is pure and canvas-free** (KTD-13). Normalized 0..1 in,
placement out; it knows nothing about Compose. All the fiddly correctness lives
there precisely because it is the part testable without a device. Coordinates are
normalized everywhere above the UI — `CharacterCanvas` converts to pixels at the
edge and nowhere else.

**Segmentation is swappable.** `Segmenter` in `dressup_pipeline/extract.py` is a
protocol; `ThresholdSegmenter` is the default. The original used **SAM**, and its
`--min-quality` filtered SAM's mask confidence — ours scores the cutout, so the
same flag means a different thing and "219 items at 0.90" is not a target this
pipeline reproduces (KTD-16). Swapping SAM in should touch nothing but this seam.

**No DI framework.** One dependency edge (repository → ViewModel), wired by a
factory in `MainActivity`. Adding Hilt for that would be more machinery than the
problem needs.

## Constraints

- **Offline, permissionless.** No `INTERNET`, no analytics, no storage access.
  Assets are the only content source.
- **Device-only testing** (KTD-14). No emulator. Everything goes to a physical
  tablet over `adb`, so there is no live UI feedback loop — batch UI changes into
  device sessions, and push verification into headless tests wherever possible.
- **Memory budget.** 4 GB tablet. Decoded 512px bitmaps are ~1 MB each, so the
  catalog is never fully decoded — `DressUpScreen` preloads `TRAY_PRELOAD` (48)
  items. Windowed loading tied to scroll position is Phase 3 work. The
  `CatalogRepository` bitmap cache is currently unbounded; that needs a cap
  before the catalog gets large. The 512px edge is enforced by the catalog
  build's one shared scale factor: no item is ever written past it (base bodies
  take the same factor toward their own `--body-height` target, so a body may be
  taller).
- **Touch targets ≥ 56dp.** Tray items are 96dp.
- `buildToolsVersion = "36.1.0"` is pinned because build-tools 34.0.0 was
  corrupted in the original *Windows* SDK install. It is a workaround, not a
  decision — `setup-ubuntu.sh` installs 34.0.0 first and warns if the pin
  disagrees. Drop the pin if 34.0.0 works here.

## The blocking manual step

`app/src/main/assets/characters.json` must be hand-authored against a real base
body — snap points placed by eye in normalized 0..1 coordinates. The checked-in
file is a **placeholder** with a symmetric guess and references a base image that
does not exist. It exercises mechanics; it will not look right.

Guide: `app/src/main/assets/README.md`. This is the single step between a
compiling app and a playable one, and it cannot be automated — that is why it is
still open.

## Conventions

Decisions are recorded as `KTD-n` in `docs/memory/decisions.md`, append-only;
supersede rather than delete. Cite the ID instead of restating the decision.

`docs/solutions/` holds documented solutions to past problems (bugs, best
practices, workflow patterns), organised by category with YAML frontmatter
(`module`, `tags`, `problem_type`). Relevant when implementing or debugging in
an area something has already been written about.

`CONCEPTS.md` at the repo root is the shared domain vocabulary — entities, named
processes, and status concepts. Relevant when orienting to the codebase or
discussing domain concepts.
