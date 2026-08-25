# Session bootstrap — Dress-me-up

Read this before touching anything else. It tells you what exists, what
doesn't, and the one concrete next step.

## What actually exists right now

- **This seed repo.** Docs only: [`ROADMAP.md`](ROADMAP.md) (architecture +
  build order + current state) and [`TESTING.md`](TESTING.md) (why the
  physical tablet, not the emulator).
- **Nothing else.** No app code, no `catalog.json`, no `characters.json`, no
  `decisions.md` (referenced in the roadmap as KTD-11..14, content not
  recovered — treat those IDs as "a decision was made here, re-derive the
  reasoning from the roadmap text around it if it matters").

Everything below is a **spec to rebuild from**, not a working checkout.

## Recommended path convention

Clone this repo to `~/projects/personal/dress-me-up` on the new machine.
This mirrors the convention already established for sibling personal
projects (`trader` at `~/projects/personal/trader`, `android_racer` at
`C:\projects\personal\android_racer` on Windows) — keeping it consistent
matters if you ever use Claude Code's per-project memory again, since it
hashes the absolute path.

## Toolchain (Ubuntu)

The original build ran on Windows. Known-good versions, translated to
Ubuntu equivalents:

- **JDK 21** — `sudo apt install openjdk-21-jdk` (the original used JDK 21
  OpenLogic on Windows; any JDK 21 distribution should work).
- **Android SDK** — install via `cmdline-tools` to `~/Android/Sdk` (Ubuntu's
  usual default; the Windows original used `%LOCALAPPDATA%\Android\Sdk`).
  Pin **build-tools 36.1.0** — the original notes that 34.0.0 was corrupted
  on the Windows install and 36.1.0 is what actually worked. Worth trying
  34.0.0 fresh on Ubuntu since that may have been an install-specific
  corruption, but don't be surprised if you reach for 36.1.0 again.
- **Gradle** — no wrapper exists yet (no `gradlew` was carried over). Use
  Gradle 8.9 to match what the original project pinned once you scaffold
  the project (`gradle wrapper --gradle-version 8.9`).
- **`local.properties`** (gitignored) must point `sdk.dir` at the SDK path.

## Testing — new Ubuntu-specific step

The original testing method transfers directly: physical **Galaxy Tab S6
Lite over `adb`**, never the emulator (see
[`TESTING.md`](TESTING.md)). One thing to check that's new on Linux: `adb
devices` may show the tablet as `unauthorized` or not at all until a udev
rule is added for the device vendor ID — if so, add a rule under
`/etc/udev/rules.d/51-android.udev.rules` and reload udev
(`sudo udevadm control --reload-rules`), then reconnect and accept the
USB-debugging RSA prompt on the tablet. This wasn't a concern on Windows.

## First concrete task

There is no playable slice to resume — the app itself doesn't exist here.
Per [`ROADMAP.md`](ROADMAP.md), the build order was deliberately
**vertical-slice first**: pipeline → catalog → app → snap contract, before
any content-completion work. Re-scaffold in that order rather than jumping
to content or polish:

1. Fresh Compose Android project (models + `CatalogRepository` +
   `DressUpViewModel` + `CharacterCanvas` + `SnapCalculator`, per the
   architecture in `ROADMAP.md`).
2. `tools/build_catalog.py` — aggregates accepted content sidecars into
   `app/src/main/assets/catalog.json` + downsampled `items/`.
3. Hand-author `app/src/main/assets/characters.json` — pick a real
   base-body image, place snap points in normalized 0–1 coordinates by
   *looking* at it. This was the single remaining manual step before the
   original had a real playable slice, and it still is.
4. Test on the physical tablet per `TESTING.md`.

## What's deliberately not here

- Source content (the "Dress Me Up" sticker book scans/PDFs) — not part of
  Claude's memory capture, recover from wherever the physical books were
  scanned, if that archive still exists.
- The actual `decisions.md` reasoning behind KTD-11..14 — only referenced,
  never captured verbatim.
