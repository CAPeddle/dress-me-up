---
artifact_contract: "ce-handoff/v1"
created_at: "2026-09-13T00:00:00Z"
title: "Dress-up screen direction, and the playtest rig built to settle it"
summary: "Free placement chosen over snapping; three layout directions built and published; an instrumented playtest rig exists but lives only in /tmp and has never been run with the child."
keywords: ["dress-me-up", "playtest", "free-placement", "page-triage", "instrumentation", "tailscale", "uncommitted"]
cwd: "/home/cpeddle/projects/personal/dress-me-up"
resume_focus: "Decide how to reach a first real playtest: the rig is built but unrun, and the Android app has never been compiled."
repository: "CAPeddle/dress-me-up"
repo_root_sha: "d7a9304fc3fca678830df7db61b27e5c8ad5673d"
branch: "main"
head: "0dda9af9803631d6c8628ce08b4716891a97e451"
---

# Dress-up screen direction, and the playtest rig built to settle it

## Objective

Get this to something the 7-year-old will actually play with. The session turned on
one thing she values, stated by the user directly: **a paper sticker is spent once it
is placed, and the same piece cannot go on a different body.** Reuse, combination
across bodies, and novelty are the product. She is *not* attached to these particular
books — the theme and newness are what appeal, and she has not yet "done" the
Fantasy w Boy book.

That reframing is the user's, not an inference, and it invalidated the plan I had
been building: I had assumed faithful reproduction of the paper mechanic.

## Current state, by maturity

**Committed and pushed** — two commits only (`d7a9304` seed, `0dda9af` graft).

**Complete, staged, NOT committed** (17 paths; `git status --short`). 95 tests pass.
- `tools/dressup_pipeline/orientation.py` — sideways-page detection. Ready. 102/102
  against a hand survey, 0 destructive rotations across 104 real pages and 300
  synthetic re-orientations. Read the `HEAD_180_DECISION` comment (~line 85) before
  touching the 180° branch; the asymmetric gate is deliberate and measured.
- `tools/dressup_pipeline/pagetype.py` — page triage. **NOT safe to run
  unsupervised.** Its docstring now carries the honest numbers: 94% is in-sample,
  and per book it is Fantasy 96.8%, Fantasy w Boy 97.2%, **Knight 25%**. Item-sheet
  precision 31/31, recall 31/35 — what it accepts is trustworthy, what it rejects is
  not. Use item_sheet-only mode with a human confirming every rejection.
- `tools/dressup_pipeline/classify.py` + `models.py` — `group` now derives from the
  containing folder, because real scans are timestamp-named (`20260509081623.pdf`).
  Without this every item silently classified as `misc`.
- `docs/CONTENT-STRUCTURE.md` — what the scans actually contain. The single most
  useful orientation document; read it before touching the pipeline.
- `docs/solutions/best-practices/thresholds-tuned-on-one-source-fail-on-the-next.md`
  — why a threshold measured on one book must not be quoted as a corpus property.
- `CONCEPTS.md` — domain vocabulary (Sidecar, Item Sheet, Base Body, Snap Point…).

**Not started:** the app has **never been compiled**. There is no JDK and no Android
SDK on this machine. `scripts/setup-ubuntu.sh` was written for it and has never been
run. Everything about the Kotlin in `app/` is unverified first-draft code.

## Decisions, and whose they are

User-directed, each chosen with the alternative visible:
- **Free placement, not snap points.** Chosen after handling both in a prototype.
  This matters more than it sounds: the canvas already free-places any piece with no
  matching snap point, so a character definition with no snap points works today —
  it removes the manual authoring step that had blocked the project since July.
- Threshold segmentation now; **SAM deferred** to a possible rented-GPU experiment.
- **scp** for moving scans, over an rclone/OAuth tunnel.
- Pick base bodies from the **hand survey**, not from `pagetype.py`.
- A **clickable** prototype over static mockups.

My calls, not the user's — verify before relying on them:
- One shared scale factor for doll and items (see Findings).
- The asymmetric 180° gate in `orientation.py`.
- Tightening the rig's string validation from warn-only to enforced.

## Findings that change what you would otherwise do

- **The bodies share one template.** 22 dolls across three PDFs and two books:
  height 609–635px, 4.2% spread. One set of coordinates would plausibly serve all
  63. Caveat: I measured bounding boxes, not limb landmarks, and sampled 3 of 18
  PDFs.
- **The books print stickers at wear-size.** Doll 156mm; crowns 19–28mm (12–18% of
  body height); dresses 80–90mm (52–58%). So extracting doll and items **at the same
  DPI preserves correct relative scale for free** — nothing needs hand-sizing.
- **`app/src/main/kotlin/io/dressup/ui/CharacterCanvas.kt` has a real defect.**
  `ITEM_WIDTH_FRACTION = 0.28` renders every item at a fixed fraction of canvas
  width, so a tiara and a ball gown arrive the same width. Must become "preserve true
  size relative to the body". The user caught this by eye in a prototype.

## The playtest rig, and what is still ephemeral

`playtest-rig/` (664K, 12 files) — **now in this repo, gitignored and untracked.**
Event taxonomy
(`EVENTS.md`, 24 event types), privacy rules (`BOUNDARY.md`) with an executable gate
(`check_boundary.sh`), a local collector, a standalone port of all three layouts, and
a parent-facing review page. Start with its `README.md`.

It was originally kept under `/tmp`, outside any repo, and `BOUNDARY.md` C-1 made that
distance the containment mechanism. The project owner overturned that on 2026-09-13:
`/tmp` does not survive a reboot, and losing the rig costs more than the separation
bought. **Distance was replaced with a stronger property — the rig is gitignored and
untracked, so it cannot enter a commit even by accident.** C-1 now asserts exactly
that, and the fingerprint grep (C-3) that catches a copy into `app/` keeps full force.
Read `playtest-rig/BOUNDARY.md` §2 before moving or copying any of it.

Still machine-local and lost on reboot, under
`/tmp/claude-1000/-home-cpeddle-projects-story-app/d4ed5013-0a6c-4f97-8b13-606dfb556524/scratchpad/`:
- `design/` — the `.dc.html` working files and `canvas.json` behind the published
  canvas. Re-seeding the canvas requires these; the published artifact does not.
- `serve/` — the mockups served over Tailscale.

Published design canvas (durable, independent of this machine):
`https://claude.ai/code/artifact/64f716e1-cd3d-4a5c-92df-fc8f676188bc` — three
directions: A Wardrobe (category rail), B Sticker sheet (pieces where the page puts
them, a new sheet as the novelty event), C Two-up (two bodies, one shared pile).

A plain `python3 -m http.server` was bound to this host's Tailscale address (port
8420), serving `serve/` to the tailnet only. It will not survive a reboot. The target
tablet was last seen 16 days before this handoff and must be online with Tailscale
running before anything reaches it. Get both addresses with `tailscale status`;
they are deliberately not written down here, because this file is committed.

## Wrong paths — already tried, do not retry

- **The Drive MCP connector cannot move binaries.** It returns files as base64 into
  the model's context; the smallest scan is ~600KB, the largest 10.6MB.
- **The bundled `light-webserver.js` helper dies within seconds**, three times. It
  binds its lifetime to the launching tool call. Use `setsid`, or just hand the user
  a self-contained HTML file.
- **Do not run `scripts/fetch-drive-content.sh` with sudo** — it installs to
  `~/.local/bin` and authorises against the user's own Drive; as root both land in
  `/root`. The script now refuses to run elevated.
- **`docs/ROADMAP.md` and `docs/TESTING.md` describe the LOST original project**,
  not this tree. `KTD-11..14` in `docs/memory/decisions.md` are labelled
  reconstructions. Do not cite them as history.

## Verification performed

95 tests pass. Orientation correction confirmed by rendering the corrected page and
looking at it, not by trusting the returned angle. The rig's two CSP blockers were
found by two independent verifiers and fixed — both failed *silently* (a blank screen
for the child; every event dropped unless the page was opened at a literal IP). The
boundary gate passes, but **its network-binding checks were run on localhost** and
must be re-run with the collector on its real Tailscale address before the child uses
it. That is the one genuinely unticked check.

Outstanding rig issues I fixed after the workflow: `Rig.stop()` was wired to nothing
while `BOUNDARY.md` promised the child that stop works; enum membership was
unenforced despite the "no open strings" claim; the review tool computed a warm-up
correction and then ranked on uncorrected numbers.

## Open threads, and plausible continuations

Two workflows are parked mid-flight: a `ce-brainstorm` at Phase 2 (approaches drafted
but never presented — free placement was settled instead by prototype), and a
`ce-plan` holding at its scoping-synthesis gate on `characters.json`. Neither is
blocking; both are superseded by the free-placement decision and can be discarded.

Continuations, as genuine forks:

1. **Run the playtest.** The rig is built and unrun. Needs: tablet online, the
   boundary gate re-run on the real address, and a decision on the reviewer's
   remaining point — there is no counterbalancing of layout order, so one child in
   one sitting cannot separate "better layout" from "seen when she was freshest".
2. **Make the app real.** Run `scripts/setup-ubuntu.sh`, compile for the first time,
   and fix what a never-compiled Compose codebase throws. Free placement means
   `characters.json` no longer blocks this.
3. **Commit what is staged.** 17 paths of finished, tested work sit uncommitted.

Useful skills here: `ce-work` for (2), `ce-commit` for (3), `ce-compound` if the
playtest teaches something worth keeping.
