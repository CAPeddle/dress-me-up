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
| `tools/` — content pipeline | **real and tested**, chain verified end to end on the Fantasy scans |
| `web/` — web version | **playable**, served from this machine to the tablet; the platform decision waits on a playtest |
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
tools/.venv/bin/python tools/triage_pages.py content/pdfs/*.pdf      # rotation + page type per page
tools/.venv/bin/python tools/extract_pdf.py content/pdfs/*.pdf --triage
tools/.venv/bin/python tools/classify_and_qa.py --min-quality 0.90
tools/.venv/bin/python tools/build_catalog.py --min-quality 0.90 --group fantasy --body-height 1000
cd tools && .venv/bin/python -m pytest                   # pipeline + web tests
```

Web version — the same catalog, played in the tablet's browser over the home
network (no build step, no framework):

```bash
tools/.venv/bin/python web/serve.py --host <this machine's home-network address>
```

App:

```bash
./gradlew :app:testDebugUnitTest
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## How the two halves meet

The pipeline writes `app/src/main/assets/catalog.json` plus scaled item PNGs,
and beside them `bodies.json` plus the base-body PNGs, all at one shared scale
and stamped with one build id. The Android app reads the catalog; the web
version under `web/` reads both. That is the entire contract — nothing else
crosses.

## Contents

| Path | Purpose |
|---|---|
| [`docs/session-bootstrap.md`](docs/session-bootstrap.md) | Canonical start-here — current state and next step |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Recovered architecture and phases, plus current state |
| [`docs/TESTING.md`](docs/TESTING.md) | Why testing is on a physical tablet, not the emulator |
| [`docs/memory/decisions.md`](docs/memory/decisions.md) | KTD decisions — 11..14 are marked reconstructions |
| [`web/`](web/) | The web version: static files, `serve.py`, no recording code |
| [`CLAUDE.md`](CLAUDE.md) | Guidance for Claude Code sessions |

---

*Seeded 2026-08-25 from Claude Code project memory recovered during a vault
migration; rebuild grafted in the same day.*
