# Dress-me-up

A standalone, **offline Android tablet dress-up game**, based on the physical
"Dress Me Up" sticker books — starting content is a fantasy/knight character set.
Sideloaded on a Galaxy Tab S6 Lite. No network, no accounts, no analytics; the
app declares no permissions at all.

## Status: rebuilt vertical slice, not yet playable

The original working copy lived only on a laptop that was retired before anything
was pushed. The code, the scanned PDFs, the 219 QA'd items, `decisions.md`, and
the plan file are **gone**. What survived is the project memory Claude Code had
captured — architecture, build order, toolchain gotchas, and where work stopped.

This repo seeded that memory as a spec (`docs/`), and on 2026-08-25 a rebuild was
grafted in against it. So:

| | State |
|---|---|
| `tools/` — content pipeline | **real and tested**, 48 tests, chain verified end to end |
| `app/` — Kotlin/Compose | **never compiled** — written on a machine with no JDK or SDK |
| Scans / 219 items | **not recovered** — the PDFs are being sourced separately |
| `characters.json` | **placeholder** — the one manual step, unchanged since 2026-07-02 |

**Start here:** [`docs/session-bootstrap.md`](docs/session-bootstrap.md).

## Quickstart

```bash
./scripts/setup-ubuntu.sh          # JDK 21, Android SDK, udev rule, python venv
./scripts/setup-ubuntu.sh --check  # report only, change nothing
```

Content pipeline — scans in, catalog out:

```bash
tools/.venv/bin/python tools/make_smoke_pdf.py           # stand-in for a real scan
tools/.venv/bin/python tools/extract_pdf.py content/pdfs/*.pdf
tools/.venv/bin/python tools/classify_and_qa.py --min-quality 0.90
tools/.venv/bin/python tools/build_catalog.py --min-quality 0.90 --group fantasy
cd tools && .venv/bin/python -m pytest                   # 48 tests
```

App:

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## How the two halves meet

The pipeline writes `app/src/main/assets/catalog.json` plus downsampled item
PNGs. The app reads them. That is the entire contract — nothing else crosses.

## Contents

| Path | Purpose |
|---|---|
| [`docs/session-bootstrap.md`](docs/session-bootstrap.md) | Canonical start-here — current state and next step |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Recovered architecture and phases, plus current state |
| [`docs/TESTING.md`](docs/TESTING.md) | Why testing is on a physical tablet, not the emulator |
| [`docs/memory/decisions.md`](docs/memory/decisions.md) | KTD decisions — 11..14 are marked reconstructions |
| [`CLAUDE.md`](CLAUDE.md) | Guidance for Claude Code sessions |

---

*Seeded 2026-08-25 from Claude Code project memory recovered during a vault
migration; rebuild grafted in the same day.*
