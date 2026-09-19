---
artifact_contract: "ce-handoff/v1"
created_at: "2026-09-19T14:12:17Z"
title: "Web version built, reviewed, fixes applied; shipping tail and tablet check remain"
summary: "All eight plan units are implemented on branch feat/playable-web-version with a code-review pass folded in; what remains is ce-work's residual-work gate, final validation, the local-commit handoff, and the parent's own checks on the tablet."
keywords: ["dress-me-up", "web-version", "ce-work", "code-review", "playtest-rig", "feat/playable-web-version", "shipping", "tablet"]
cwd: "/home/cpeddle/projects/personal/dress-me-up"
resume_focus: "Finish ce-work Phase 3-4 for docs/plans/2026-09-19-0736-feat-playable-web-version-plan.md: residual work gate, final validation, ce-commit handoff (local only), then the parent's tablet checks."
repository: "CAPeddle/dress-me-up"
repo_root_sha: "d7a9304fc3fca678830df7db61b27e5c8ad5673d"
branch: "feat/playable-web-version"
head: "cad98b763fb247243335ae7caf057c3fe4f8b7a0"
---

# Web version built, reviewed, fixes applied

Written mid-`ce-work` so the session could be compacted. It supersedes
`docs/handoffs/dress-up-web-version-plan-ready.md` (plan-ready state) and, for
the rig, `docs/handoffs/dress-up-self-contained-pickup.md`. Read this, then the
plan's Goal Capsule and Definition of Done (lines 14-24 and 550-565), then only
what you need.

## Where the run stopped

`ce-work` on the plan was invoked standalone (user: "Confirmed, start
implementation"). Phases 0-2 are complete and Phase 3 is most of the way
through. The tree is clean at HEAD; twelve commits sit on this branch above
`origin/main` (`git log --oneline origin/main..HEAD`), none pushed.

Done, in order: U1, U4 (parallel wave), U2, U5, U3, U6's tracked part, U7 and
U8 (gitignored rig), a simplification pass (`ce-simplify-code`, committed as
`refactor: simplification pass ...`), a full `ce-code-review` run, and its seven
confirmed findings applied (`fix(review): apply findings #1 #2 #3 #5 #7 #8 #9`).

Not yet done, in the shipping workflow's order
(`ce-work/references/shipping-workflow.md`, Phase 3 steps 4-6 and Phase 4):

1. **Residual Work Gate**: record the review's unapplied concerns (below); none
   blocks the outcome.
2. **Final Validation** checklist and the Post-Deploy Monitoring section
   (`No additional operational monitoring required`: a home-network static
   server run by hand).
3. **Ship**: the branch carries the user's pre-existing unpushed commits, so the
   rule is `ce-commit` locally (everything is already committed; nothing to
   add), say what stayed local, and push or open a PR only on request. Do not
   push without being asked.

## The code-review receipt (needed by the ship gate)

`ce-code-review mode:agent` completed: `status: complete`, verdict
`Ready with fixes`, run id `20260919-131805-54a3c40d`, artifacts at
`/tmp/compound-engineering-1000/ce-code-review/20260919-131805-54a3c40d/`
(machine-local, OS-managed; `review.json` is the receipt). Nine reviewers:
correctness, project-standards, testing, maintainability, learnings, security,
api-contract, frontend races, and a Codex adversarial peer. Seven findings, all
validator-confirmed, all applied and committed. Requirements completeness:
every R and U met or by design outside the diff (R11, R12, U7, U8 live in the
gitignored rig).

**Peer caveat to tell the user (not yet told in a final message):** the Codex
peer could not run local filesystem commands in its sandbox and instead
reached the repository through a GitHub connector configured in the user's
Codex, listing their repositories and fetching base-commit files from GitHub.
It saw none of the unpushed branch, returned zero findings, and gets no
corroboration credit. That connector egress is outside the in-tree read scope
the pass is meant to have; the user may want that connector disabled for
review runs.

## Unapplied review concerns (for the Residual Work Gate)

From `review.json` `residual_risks` and `testing_gaps`; my reading of each:

- `web/js/store.js` bounds `body` against the body count but not `item`
  against the item count; a hand-edited catalog under an unchanged build id
  would crash boot. Low incidence; a one-line guard plus a test. Not applied.
- `web/js/gesture.js` drags have no timeout fallback; if a device drops
  pointerup, pointercancel and lostpointercapture, the game goes dead until
  reload. Unverified on the tablet; worth watching in the first sitting.
- Resize during a live drag: the fix stops the transform being wiped, but the
  commit still anchors to the post-resize frame while the pixels sat on the
  pre-resize one, so a resize-then-release jumps. Rare on a tablet held in
  landscape; the fix worker left it to the user because it changes commit
  semantics three tests pin.
- `bodies.py` `resolve_pdf` uses the hand-authored basename as a glob
  (`rglob`); a literal `p.name == entry.pdf` match would be stricter. The list
  is tracked and owner-edited, so robustness, not attack surface.
- Body-list entries are not filtered by `--group`, and bodies land in the
  Android assets dir by default (packaged into the APK though the Kotlin app
  never reads them). Accepted for now; documented in README.
- `extract.py --triage` on a manifest with fewer pages than the PDF raises a
  bare `KeyError` mid-run. A named error would be kinder.
- The purity scan's verb fingerprints are case-sensitive and skip PUT/PATCH;
  same-origin GET remains a permitted channel by design (R8).
- `CLAUDE.md`'s contract paragraph still names two ends of the per-item
  contract while `web/js/catalog.js` is a third consumer.
- `scripts/fetch-drive-content.sh` folder-name trailing-space mismatch
  (pre-existing, unverifiable without Drive).
- Testing gaps: ambiguous-PDF branch, extract re-run over classified sidecars
  (would wipe classification fields; a real sidecar-rule hazard worth a test
  and possibly a guard), symlink escape in serve tests, Knight-book coverage.
- Maintainability: `extract.py` imports `rotate_page` lazily from `triage.py`
  to dodge a cycle; moving that helper to a lower module would remove the
  cycle. Demoted to advisory.

## What exists now, by maturity

- **Pipeline** (complete, tested): `tools/triage_pages.py` and
  `dressup_pipeline/triage.py` (manifests, overrides, contact sheets);
  `extract_pdf.py --triage`; `dressup_pipeline/bodies.py` (body cutting via the
  orientation module's `find_figure_regions` seam); `catalog.py` two-pass build
  with `compute_scale`, `BodiesSource`, `ScaleDecision`, per-PDF table, stale
  bodies removal; `build_catalog.py --body-height` (`--max-px` gone), skips the
  tracked body list with a note when none of its PDFs are present.
- **Content** (machine-local, gitignored): `content/triage/` manifests for all
  nine Fantasy PDFs plus two overrides (075945 p6 and 170805 p0 confirmed as
  base bodies); `content/sidecars/` 333 items at 300 dpi, 253 accepted at 0.9;
  `app/src/main/assets/` holds catalog.json, bodies.json, 253 items, 17 bodies
  at factor 0.3858 (item ceiling bound). `tools/base_bodies.json` (tracked)
  lists the 17.
- **Web** (complete, tested, 283 tests total with pipeline): `web/index.html`,
  `css/game.css`, `js/main.js`, `catalog.js`, `gesture.js`, `hand.js`,
  `store.js`, `names.js`, `serve.py`. Tests under `tools/tests/web/`
  (Playwright 1.63 installed in `tools/.venv`; Chromium downloaded; no sudo was
  needed).
- **Rig** (gitignored, complete per U7/U8, verified by `playtest-rig/test_rig.py`
  43/43, `test_review.py` 30/30, and `check_boundary.sh --host <addr>` passing
  on loopback and on the home address): `playtest.html`, three-root
  `collector.py` with per-run token, observer `instrument.js`, amended
  `BOUNDARY.md`/`EVENTS.md`/`check_boundary.sh`, rewritten `review.js`/`README.md`,
  `fixtures/*.ndjson`. Logs go to `~/dress-up-playtest-logs/` (0700, exists,
  empty).

## Decisions and whose

- User: build web as if product; tracked app plus detachable instrumentation;
  self-marked done star; engineering posture (modular but earned); delegate
  units to Opus subagents and verify (saved as a memory).
- User (this run): commit the pre-existing staged work first, plus plan and
  handoffs, on a feature branch.
- Mine, worth the user's eye: (a) the rig's C-3 copy detector now excludes
  `tools/tests/web/test_plain_build_purity.py`, because KTD10's tracked purity
  test must name the rig marker to scan for it, which contradicts C-3 as KTD9
  left it (U7 worker's forced amendment, stated in C-3's text). (b) The Codex
  peer connector egress above. (c) Drop rules I read into R5: releasing a
  dragged Item over the hand carries it, over the supply removes it, outside
  every region reverts. (d) The store also keys on `build_id`: a content rebuild
  starts her dolls fresh, since item indices are meaningless across builds.
- Product observation from the U5 worker, untouched because KTD6 is settled: a
  tap on a placed Item with a non-empty hand does nothing, so once a gown
  covers the body she must tap bare body or off-body to place the next Item.

## Real-content observations for the parent

- AE2 holds on real content (screenshot in the scratch dir, machine-local):
  the smallest hat sits head-sized, the gown covers shoulder to ankle.
- The heuristic category classifier mis-slots many items (the first "hat"
  tiles are torsos and skirts) and several tiles are two stickers welded by
  the segmenter. Both are pre-existing classifier/segmenter limits the plan
  defers; they will be visible in the supply during the sitting.
- Triage on Fantasy lost no item sheets; ten illustration verdicts are dressed
  group plates except the two single-doll pages overridden. The parent's own
  confirmation (R7) is still theirs to do from `content/triage/*.png`.

## Blocked on the user or the tablet

- Plain serve smoke on the tablet (`tools/.venv/bin/python web/serve.py --host
  <home-network-address>`, then the printed URL on the tablet): tablet was
  offline all session.
- The deferred question: is the home directory under a backup or sync tool?
  `~/dress-up-playtest-logs/` must be excluded if so.
- Push and PR: only on request.

## Wrong paths, do not retry

- Do not rerun `ce-code-review` to re-apply the same findings.
- Do not commit anything under `playtest-rig/` or write addresses or the
  tablet's hostname into tracked files.
- Do not extend `playtest-rig/prototype.js`; it stays on disk, unreferenced.
- Do not run pipeline output into `content/` or `app/src/main/assets/` from
  tests; use tmp dirs.

## Machine-local, fragile

- `/tmp/compound-engineering-1000/ce-code-review/20260919-131805-54a3c40d/`
  (review receipt), `/tmp/claude-1000/.../scratchpad/` (AE2 screenshots, U2/U3
  scratch builds), `/tmp/compound-engineering-1000/ce-brainstorm/...` (grounding
  dossier with unredacted addresses). All lost on reboot; none needed to
  continue.

Relevant skills: `ce-work` (resume its Phase 3-4 from the state above),
`ce-commit`, `ce-compound` (the sidecar re-run hazard and the connector egress
are worth writing up).
