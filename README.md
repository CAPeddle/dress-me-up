# Dress-me-up

A standalone, **offline Android tablet dress-up game**, based on the physical
"Dress Me Up" sticker books — starting content is a fantasy/knight character
set.

## Status: seed only, no code yet

This repository does **not** contain the app. The original working copy
(and its `docs/memory/decisions.md`, `~/.claude/plans/...` plan file, and
`characters.json` progress) lived only on a previous laptop and was never
pushed to GitHub before that machine was retired. What survived is the
distilled project memory Claude Code had captured for it — architecture
decisions, build order, toolchain gotchas, and exactly where work stopped.

This repo packages that memory as a durable seed so the project can be
**rebuilt from a clear spec** on a new machine, instead of rebuilt from
nothing (or from a hazier human memory of what was decided and why).

**Start here:** [`docs/session-bootstrap.md`](docs/session-bootstrap.md).

## Contents

| File | Purpose |
|---|---|
| [`docs/session-bootstrap.md`](docs/session-bootstrap.md) | Canonical start-here doc — read this first on a new machine |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Architecture, build order, phases, current state |
| [`docs/TESTING.md`](docs/TESTING.md) | Why testing happens on a physical tablet, not the emulator |

---

*Seeded 2026-08-25 from Claude Code project memory recovered during a vault
migration. No source code, no `characters.json`, no `decisions.md` content
survived — only what's captured in these docs.*
