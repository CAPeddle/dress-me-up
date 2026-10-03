---
artifact_contract: "ce-handoff/v1"
created_at: "2026-09-19T19:52:41Z"
title: "Web version on the tablet; return here once the items are catalogued correctly"
summary: "The playable web version is built, reviewed, committed and served to the tablet; the first hands-on found many items mislabeled or badly cropped, so play is paused until a correction pass has fixed the catalogue and this point is resumed."
keywords: ["dress-me-up", "web-version", "tablet", "catalogue", "mislabeled", "cropping", "playtest", "feat/playable-web-version", "resume-point"]
cwd: "/home/cpeddle/projects/personal/dress-me-up"
resume_focus: "Pick the web version back up with a corrected catalogue: rebuild the assets, restart the plain server, redo the tablet smoke, then decide the drag-from-supply question and run the playtest."
repository: "CAPeddle/dress-me-up"
repo_root_sha: "d7a9304fc3fca678830df7db61b27e5c8ad5673d"
branch: "feat/playable-web-version"
head: "b1cb807608b099e5327dc05519e4fefcf74ffd95"
---

# Return point: web version on the tablet, catalogue needs correcting

This is the point to come back to after the catalogue-correction work
planned from the sibling handoff
`docs/handoffs/dress-up-catalogue-correction-service-planning.md`. It
supersedes `docs/handoffs/dress-up-web-version-built-and-reviewed.md`.

## Where things stand

The plan `docs/plans/2026-09-19-0736-feat-playable-web-version-plan.md` is
implemented end to end. Every unit, the simplification pass, the
`ce-code-review` run and its seven fixes, and the four findings of the
separate Codex review at
`docs/reviews/2026-09-19-playable-web-version-review.json` are committed on
this branch: eighteen commits above `origin/main`, none pushed, tree clean.
The last three (`92ea0b6`, `1610142`, `b1cb807`) are the Codex fixes:
idempotent re-extraction, the DPI-0 refusal, the stored-item bound, the
purity-scan verbs, the docs. Full suite: 310 passing. The plan's Definition
of Done rows still open are the parent's own: tablet smoke (started, see
below), triage confirmation from `content/triage/*.png`, the boundary gate
re-run on the home address with the collector up, and the merge to `main`
(push and PR only on the user's request).

## The tablet session, and why play is paused

The user (2026-09-19 evening) opened the plain build on the tablet in
Chrome. Three observations, in their words as near as recorded:

1. "There is no drag function." Correct as built: the supply is tap-to-hand
   (R16, KTD6), only placed Items drag. I explained the three regions
   (left pager of bodies, right supply by category, bottom hand) and the
   sequence tap tile, tap body, drag placed Item. Whether a *placed* Item
   drags on the tablet is still unconfirmed; the user had not tried it when
   the conversation moved on. If it does not, that is a defect, not design.
2. "The interaction is not intuitive." Recorded as the first real product
   finding. My offer, not yet decided by the user: add a press-and-hold drag
   from a supply tile straight onto the body, keeping the hand for the
   multi-body flow and keeping a plain swipe as scroll. Deferred until the
   catalogue is fixed and, ideally, until the child has been watched.
3. "A large percentage of the items are mislabeled and aren't cropped
   correctly." This is the reason for the pause and for the sibling handoff.
   It matches what the build session already saw (handoff
   `dress-up-web-version-built-and-reviewed.md`, "Real-content
   observations"): the heuristic classifier mis-slots many Items and the
   threshold segmenter welds some neighbouring stickers into one cutout.

The user's decision: build a tool that lets them say what is wrong with each
item, correct or reprocess, and then return here with a correct catalogue.

## Machine-local state (not in git)

- The plain server is running detached from any session, started by a
  worker at the user's request: `web/serve.py --host <home-network
  address>` on the wired interface, PID 3647375 at the time of writing, log
  at `/tmp/dress-me-up-serve.log`. Find it again with `ss -ltnp | grep
  8777`; stop it with `kill <pid>`. It will not survive a reboot. Never
  write the address into a tracked file; `ip -4 -o addr show` and the
  default route give it.
- The built content in `app/src/main/assets/`: `catalog.json` (253 Items),
  `bodies.json` (17 bodies), same build id, scale factor 0.3858. This is
  what the tablet is currently seeing and what the correction work replaces.
- The corpus: `content/sidecars/` holds 333 sidecars across three PDF
  output directories, 253 accepted at 0.90, all group `fantasy`, categories
  by heuristic only (hair 97, accessory 64, hat 58, top 55, shield 23,
  weapon 22, dress 14). `content/triage/` holds manifests, two overrides
  and contact sheets for the Fantasy set. Sources under
  `content/source/Fantasy/` (and `Fantasy w Boy/`).
- The review run artifacts under `/tmp/compound-engineering-1000/` and the
  scratch dir are OS-managed and not needed.

## What resuming here looks like (my reading, in order)

1. Confirm the correction work landed: sidecars carry corrected
   category/group and re-cut images where needed; whatever mechanism the
   correction service settled on is respected by `classify_and_qa.py` so a
   re-run does not undo it (today `classify_sidecar` overwrites
   category/group unconditionally, so this is the thing to check first).
2. Rebuild: `tools/.venv/bin/python tools/build_catalog.py --min-quality
   0.90 --group fantasy --body-height 1000`. A new build id is minted, so
   the tablet's saved dolls reset by design (store keys on build id).
3. Restart the plain server on the home address (kill the old PID first;
   the port is shared) and redo the smoke on the tablet: bodies and Items
   render, crown head-sized, gown shoulder to ankle.
4. Decide the drag-from-supply question with the user, then the recorded
   playtest per `playtest-rig/README.md` (boundary check first, collector on
   the same address). The backup/sync question for
   `~/dress-up-playtest-logs/` is still unanswered.
5. Ship on request: `ce-commit` is the local rule while the branch carries
   the user's pre-existing unpushed commits; push or PR only when asked.

## Standing constraints (all the user's)

No addresses or the tablet's hostname in tracked files. `playtest-rig/`
stays gitignored and nothing from it is copied into `app/` or `web/`. The
app declares no permissions. Never run `scripts/fetch-drive-content.sh`
under sudo. Delegate implementation units to Opus subagents and verify
(memory `delegate-to-opus-then-verify`). Pipeline output from tests goes to
tmp dirs, never `content/` or `app/src/main/assets/`.

## Open items carried from the review, unchanged

Drag has no timeout fallback (device observation wanted). The
extract/triage import cycle is dodged by a lazy import. The Drive folder
trailing-space mismatch in `scripts/fetch-drive-content.sh` settles itself
on the next fetch. The Kotlin decoder ignores unknown keys in source but
has never compiled here.

Relevant skills: `ce-work` for the drag-from-supply change if chosen,
`ce-commit`, `ce-compound` (the CSP-blocked `wait_for_function` string
predicate and the sidecar re-run design are worth writing up).
