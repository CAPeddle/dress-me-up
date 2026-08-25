# Session bootstrap — Dress-me-up

Read this before touching anything else. It tells you what exists, what doesn't,
and the one concrete next step.

*Updated 2026-08-25: a rebuild was grafted into this repo. The seed-only status
this file previously described is out of date — see below.*

## What actually exists right now

- **A rebuilt vertical slice**, grafted in on 2026-08-25 from a scaffold that was
  written against this repo's own spec. Not the original code — the original is
  gone (KTD-15).
  - `tools/` — the content pipeline. **Real and tested: 48 passing tests**, and
    the full chain has been run end to end against a synthetic sticker sheet.
  - `app/` — Kotlin/Compose. **Never compiled.** This machine had no JDK and no
    Android SDK when it was written, so treat every `.kt` file as unreviewed
    first-draft code and expect real errors on the first build.
- **The recovered docs** — [`ROADMAP.md`](ROADMAP.md), [`TESTING.md`](TESTING.md).
  These describe the **lost original**, not this tree. Where the two disagree,
  neither is automatically right.
- **[`memory/decisions.md`](memory/decisions.md)** — KTD-11..14 are
  *reconstructions*, clearly marked as such; their original text never survived.
  KTD-15 onward are real decisions made on this machine.

Still missing: the scanned PDFs, the 219 QA'd items, and a real
`characters.json`.

## Path convention

This repo lives at `~/projects/personal/dress-me-up` (KTD-17). Keep it there —
Claude Code hashes the absolute project path for per-project memory, so moving
the tree silently orphans it.

## Toolchain (Ubuntu)

**Run [`../scripts/setup-ubuntu.sh`](../scripts/setup-ubuntu.sh).** It installs
JDK 21, the Android SDK cmdline-tools into `~/Android/Sdk`, platform-tools,
`android-34`, build-tools, writes `local.properties`, adds the udev rule, and
builds the Python venv. Re-runnable; `--check` reports without changing anything.

Notes it encodes, so you do not have to remember them:

- **build-tools:** tries **34.0.0** first (matches `compileSdk 34`) and falls
  back to **36.1.0**. The original pinned 36.1.0 only because 34.0.0 was
  corrupted in its Windows SDK install — probably install-specific, so this tries
  the clean version first and warns if the result disagrees with
  `app/build.gradle.kts`.
- **Gradle:** the wrapper is committed (8.9). No `gradle wrapper` step needed.
- **JDK:** the app targets Java 17 bytecode, so JDK 21 runs the build fine.

## Testing

Physical **Galaxy Tab S6 Lite over `adb`**, never the emulator — see
[`TESTING.md`](TESTING.md). The udev rule the setup script installs is what makes
`adb devices` see the tablet on Linux; you still have to accept the RSA prompt on
the tablet itself.

## First concrete task

The slice from the roadmap's step 1–2 now exists. What remains, in order:

1. **Run `scripts/setup-ubuntu.sh`**, then `./gradlew :app:testDebugUnitTest`.
   This is the first time the Kotlin will ever have been compiled — fixing what
   that surfaces is the immediate job, and it is not expected to be clean.
2. **Get the scans in.** They live in Google Drive. Drop the PDFs into
   `content/pdfs/` (gitignored), then:
   `tools/.venv/bin/python tools/extract_pdf.py content/pdfs/*.pdf`
   → `classify_and_qa.py` → `build_catalog.py`.
   With no PDFs, `tools/make_smoke_pdf.py` generates a synthetic stand-in that
   exercises the whole chain.
3. **Hand-author `app/src/main/assets/characters.json`** — pick a real base body
   and place snap points in normalized 0–1 coordinates *by looking at the image*.
   Guide: `app/src/main/assets/README.md`. Still the single manual step between a
   compiling app and a playable one. Still not automatable.
4. **Test on the tablet** per `TESTING.md`.

## Known divergences from the original

- **Segmentation.** The original used **SAM**, and its `--min-quality` filtered
  SAM's mask confidence. This tree thresholds and scores the cutout instead, so
  `--min-quality 0.90` here is **a different measurement** — the recovered "219
  items at 0.90" is not a number this pipeline can be expected to reproduce.
  `Segmenter` in `dressup_pipeline/extract.py` is the seam SAM drops into; trying
  it (possibly on rented GPU) is an open experiment. KTD-16.
- **`app/src/main/assets/items/`** is gitignored while the only content is
  synthetic. Revisit once real scans are extracted: the scans are not in git, so
  the generated assets are what a future clone would need in order to build.
