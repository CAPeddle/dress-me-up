# Roadmap (vertical slice) — Dress-me-up

*Recovered verbatim in substance from Claude Code project memory, dated
2026-07-02. Reworded from memory-note style into a normal doc; content is
unchanged.*

## Goal

A standalone, offline Android tablet dress-up game, sourced from the
physical "Dress Me Up" sticker books. First content set: fantasy/knight.

## Build order: vertical slice first

Validate the full **pipeline → catalog → app → snap contract** before doing
exhaustive content QA. Then content completion, then app polish, then ship.

This was a deliberate decision, referenced in the original project as
`docs/memory/decisions.md` KTD-11 through KTD-14 — that file's actual
content was not captured in memory and has not survived. Treat the
reasoning above (avoid discovering an architecture problem after investing
in full content QA) as the best available reconstruction of *why*.

## Done as of 2026-07-02 (Phase 0–1)

- **`tools/build_catalog.py`** — aggregates accepted content sidecars into
  `app/src/main/assets/catalog.json` plus downsampled `items/` images.
  `--min-quality` provisionally accepts high-`quality_score` SAM
  (Segment Anything Model) items. A real run at `--min-quality 0.90`
  produced 219 fantasy/knight items, all PNGs downsampled to ≤512px.
- **Fresh Compose app compiles** (`./gradlew assembleDebug` green, APK
  ~36MB with assets bundled):
  - Data models + `CatalogRepository` (loads `catalog.json`)
  - `DressUpViewModel`
  - `CharacterCanvas` — long-press drag, category-snap, free-place, and
    tap-to-remove interactions
  - `SnapCalculator` — the snap-point math, unit tested (4 tests passing)

## The one remaining manual step (as of 2026-07-02)

Author `app/src/main/assets/characters.json`: pick a real base-body image
and place snap points in normalized 0–1 coordinates **by looking at the
image** — this is inherently a visual/manual task, not automatable. A
machine-picked placeholder existed only for mechanics smoke-testing, not
for real play. A guide for the expected format lived at
`app/src/main/assets/README.md` (not recovered). Once authored, test on a
physical tablet — see [`TESTING.md`](TESTING.md).

Completing this step is what turns the compiling-but-empty app into a real
playable vertical slice.

## Next after the slice

- **Phase 2 — content.** Extract the `Fantasy/` set (9 PDFs) plus remaining
  PDFs, classify, run real QA (as opposed to the provisional
  `--min-quality` heuristic used for the slice).
- **Phase 3 — app polish.** Character selector + group filtering (tracked
  as ticket **U12** in whatever tracker the original project used — not
  captured, likely local/informal given the project's scale).
- **Phase 4 — offline APK + device acceptance.** Final packaging and a full
  on-device acceptance pass.

## Toolchain (original, Windows)

JDK 21, Android SDK at `%LOCALAPPDATA%\Android\Sdk`, **build-tools 36.1.0**
(34.0.0 was corrupted on that install), Gradle 8.9 wrapper. `local.properties`
(gitignored) pointed at the SDK. See
[`session-bootstrap.md`](session-bootstrap.md) for the Ubuntu translation.
