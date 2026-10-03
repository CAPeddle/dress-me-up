---
artifact_contract: "ce-handoff/v1"
created_at: "2026-09-18T00:00:00Z"
title: "Self-contained pickup for dress-me-up — everything needed lives in this repo"
summary: "Supersedes the 2026-09-13 handoff. Written for a session opened from this repo with no access to the story-app session that did the work; names what moved, what a reboot destroyed, and what is still unrun."
keywords: ["dress-me-up", "pickup", "playtest-rig", "free-placement", "uncommitted", "never-compiled", "tailscale", "story-app"]
cwd: "/home/cpeddle/projects/personal/dress-me-up"
resume_focus: "Get to a first real playtest: compile the app for the first time, or run the built-but-unrun instrumented rig on the tablet."
repository: "CAPeddle/dress-me-up"
repo_root_sha: "d7a9304fc3fca678830df7db61b27e5c8ad5673d"
branch: "main"
head: "a42dc0864a6a8e7a6a9408b50e03d115c452abed"
---

# Self-contained pickup for dress-me-up

**Read this first if you are a fresh session opened in this repo.** The work described
here was done from a *different* repository's working directory (`~/projects/story-app`,
a sibling project by the same developer). Two consequences you cannot infer:

1. An episodic-memory search run from this repo's cwd **will not find that session**.
   Do not conclude the history is lost — it is captured here and in the files below.
2. This repo's Claude Code memory directory was empty until 2026-09-18. It now holds two
   notes (`story-app-sibling-project`, `android-testing-is-device-only`) copied across.

This supersedes `docs/handoffs/dress-up-direction-and-playtest-rig.md` (2026-09-13),
which is accurate except that it lists machine-local design files as intact; a reboot
on the 13th destroyed them. Read that one only for the fuller narrative of decisions.

## The one thing to hold onto

The user stated the product's value directly, and it invalidated the plan being built:
**a paper sticker is spent once placed, and cannot go on a different body.** Reuse,
combinations across bodies, and novelty are the product. She is *not* attached to these
particular books — theme and newness appeal, and she has not yet "done" the Fantasy w
Boy book. Everything since was shaped by that. It is the user's statement, not an
inference.

## Where everything is — all inside this repo, verified 2026-09-18

| What | Where | State |
|---|---|---|
| Content pipeline | `tools/dressup_pipeline/` | working, 95 tests pass |
| Page triage + rotation | `tools/dressup_pipeline/orientation.py`, `pagetype.py` | **staged, uncommitted** — see maturity below |
| What the scans contain | `docs/CONTENT-STRUCTURE.md` | the best orientation doc; read before touching the pipeline |
| Domain vocabulary | `CONCEPTS.md` | staged, uncommitted |
| Decision log | `docs/memory/decisions.md` | KTD-11..14 are *reconstructions*, labelled; KTD-15+ real |
| Captured learning | `docs/solutions/best-practices/thresholds-tuned-on-one-source-fail-on-the-next.md` | staged |
| Scans (source of everything) | `content/source/` | 18 PDFs, gitignored, present on this machine; originals in Google Drive folder "Dress me up" |
| **Playtest rig** | `playtest-rig/` | present, gitignored, untracked, **never run with the child** |
| Android app | `app/` | **never compiled** — no JDK or SDK on this machine |
| Toolchain installer | `scripts/setup-ubuntu.sh` | written, never run |
| Drive fetch | `scripts/fetch-drive-content.sh` | scans were moved by scp instead; script kept for re-pulls |

**16 paths are staged and uncommitted.** They are finished and tested. They were left
uncommitted only because the user had not asked for that commit; `git diff --cached
--name-only` lists them. Committing them is a decision, not a risk.

## Maturity, honestly

- `orientation.py` — **ready.** 102/102 against a hand survey, 0 destructive rotations
  across 104 real pages and 300 synthetic re-orientations, correction confirmed by eye.
  Read the `HEAD_180_DECISION` comment before touching the 180° branch; the asymmetric
  gate is measured, not guessed.
- `pagetype.py` — **not safe to run unsupervised.** Its docstring carries the honest
  numbers: 94% is in-sample; per book Fantasy 96.8%, Fantasy w Boy 97.2%, **Knight 25%**.
  Item-sheet precision 31/31, recall 31/35 — trust what it accepts, not what it rejects.
  The fix order is at the end of `docs/CONTENT-STRUCTURE.md`.
- `playtest-rig/` — **built, verified in a headless browser, never run for real.** Start
  with its `README.md`. Its `check_boundary.sh` prints `BOUNDARY OK` today, but the
  network-binding checks have only ever run on localhost; they must pass with the
  collector on the real Tailscale address before the child touches it.
- `app/` — **unverified first-draft Kotlin.** Expect real errors on the first build.

## Decisions, and whose

User-directed (chosen with the alternative in view):
- **Free placement, not snap points** — chosen after handling both in a prototype. The
  canvas already free-places any piece with no matching snap point, so a character with
  zero snap points works today. This removed the manual authoring step that had blocked
  the project since July. `app/src/main/assets/characters.json` is a placeholder and no
  longer blocks anything.
- Threshold segmentation now; SAM deferred (possibly on rented GPU).
- Pick base bodies from the hand survey, not from `pagetype.py`.
- The rig **moved into this repo** (2026-09-13), overturning its own "live outside any
  repo" rule, because `/tmp` does not survive a reboot. Distance was replaced by a
  stronger control: gitignored and untracked, asserted by C-1 in `playtest-rig/BOUNDARY.md`.
  Vindicated within hours — the machine rebooted and `/tmp` was wiped.

Mine, not the user's — verify before relying on them: one shared scale factor for doll
and items; the asymmetric 180° gate; tightening the rig's string validation from
warn-only to enforced; wiring the rig's Stop control.

## Findings you would otherwise re-derive

- **The bodies share one template.** 22 dolls, three PDFs, two books: height 609–635px
  (4.2% spread). Caveat: bounding boxes, not limb landmarks; 3 of 18 PDFs sampled.
- **The books print stickers at wear-size.** Doll 156mm; crowns 19–28mm; dresses
  80–90mm. Extracting doll and items **at the same DPI preserves relative scale for free.**
- **`app/src/main/kotlin/io/dressup/ui/CharacterCanvas.kt` has a real defect:**
  `ITEM_WIDTH_FRACTION = 0.28` gives a tiara and a ball gown the same width. Must become
  "preserve true size relative to the body". The user caught this by eye.
- **A threshold measured on one book is not a corpus property.** The "10–31 floating
  regions" claim was Fantasy-only; 13 of 35 real item sheets fall below the gate it
  produced. The learning doc above is the write-up.

## Lost in the reboot, and how to recover

- **Design canvas working files** (`Main.dc.html`, `StickerSheet.dc.html`,
  `TwoUp.dc.html`, `canvas.json`) — gone. The published canvas survives at
  `https://claude.ai/code/artifact/64f716e1-cd3d-4a5c-92df-fc8f676188bc` (three
  directions: A Wardrobe, B Sticker sheet, C Two-up). The `design` skill can re-extract
  working files from a published artifact if re-seeding is ever needed. **Not required
  for the playtest:** `playtest-rig/prototype.html` is a standalone port of all three.
- **Tailscale-served mockups and their server** — gone; trivially regenerable, and the
  rig's own collector serves the prototype anyway.

## Wrong paths — do not retry

- The **Drive MCP connector cannot move binaries** (base64 into context; scans are
  0.6–10.6MB). Use scp, or `scripts/fetch-drive-content.sh` with rclone.
- The bundled **`light-webserver.js` dies within seconds** of any tool call. Use `setsid`
  or hand over a self-contained HTML file.
- **Never run `scripts/fetch-drive-content.sh` under sudo** — it installs to
  `~/.local/bin`; as root everything lands in `/root`. It now refuses elevation.
- **`docs/ROADMAP.md` and `docs/TESTING.md` describe the lost original**, not this tree.
- **Do not hardcode tailnet addresses or the tablet's hostname in tracked files.** The
  rig's fingerprint gate caught exactly that in the previous handoff. The hostname
  carries a person's name. `tailscale status` gives both.

## Environment a fresh session must know

- **No JDK, no Android SDK, no adb on this machine.** Nothing under `app/` can be built
  until `scripts/setup-ubuntu.sh` is run (needs sudo for the JDK and udev rule).
- **The tablet has been offline since ~28 August.** Tailscale must be running on it. Its
  address and hostname come from `tailscale status` — deliberately not written here.
- **The rig runs at the tailnet address only** and refuses `0.0.0.0` without an override.
- Python for the pipeline: `tools/.venv/bin/python` (uv-managed, Python 3.12).

## Continuations — genuine forks, not a menu

1. **Run the playtest.** Tablet online → `playtest-rig/README.md` → collector on the
   real address → `check_boundary.sh` must print `BOUNDARY OK` → session. Open question
   the adversarial reviewer left: no counterbalancing of layout order, so one sitting
   cannot separate "better layout" from "seen when she was freshest". Plan a second
   sitting in reversed order.
2. **Compile the app for the first time.** `scripts/setup-ubuntu.sh`, then fix what a
   never-built Compose codebase throws. Fix `ITEM_WIDTH_FRACTION` while in there.
3. **Commit the 16 staged paths.** Finished work, tests green, waiting only on a decision.

Two earlier workflows sit parked mid-flight (a `ce-brainstorm` at Phase 2, a `ce-plan`
at its scoping gate on `characters.json`). Both were superseded by the free-placement
decision; discard them.

Skills that fit: `ce-work` for (2), `ce-commit` for (3), `ce-compound` if the playtest
teaches something worth keeping.
