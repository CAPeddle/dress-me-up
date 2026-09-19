---
artifact_contract: "ce-handoff/v1"
created_at: "2026-09-19T11:07:07Z"
title: "Web version plan is written and reviewed; next step is ce-work"
summary: "A brainstorm and a deepened, document-reviewed implementation plan for a playable web version of the game now exist in docs/plans; nothing has been implemented, the tablet is offline, and sixteen earlier pipeline paths are still staged and uncommitted."
keywords: ["dress-me-up", "web-version", "playtest-rig", "plan-ready", "ce-work", "uncommitted", "boundary", "catalog-scale"]
cwd: "/home/cpeddle/projects/personal/dress-me-up"
resume_focus: "Start ce-work on docs/plans/2026-09-19-0736-feat-playable-web-version-plan.md, content units first."
repository: "CAPeddle/dress-me-up"
repo_root_sha: "d7a9304fc3fca678830df7db61b27e5c8ad5673d"
branch: "main"
head: "a42dc0864a6a8e7a6a9408b50e03d115c452abed"
---

# Web version plan is written and reviewed; next step is ce-work

This handoff was written so the session could be compacted before implementation starts. It supersedes `docs/handoffs/dress-up-self-contained-pickup.md` (2026-09-18) for direction, and that file remains the account of what the rebuild and the playtest rig are. Read this one, then the plan, then only what the plan points at.

## What the user decided this session, in their words or with the alternative in view

- **Why the rig failed.** She had it in hand, asked what she had to do, asked why dragging did not work, asked why the sizes were off, then got bored. User's direct account.
- **How she plays on paper.** Stacks a few stickers on her fingers and pages through mannequins looking for the fit, or builds one mannequin up completely; sometimes a story and a name; stops when the mannequins are complete. User's direct account, and the basis of the two first-class flows in the plan.
- **Platform.** Build the web version as if it could become the product and decide between a WebView shell and a Kotlin port after she has played it. Chosen over committing to either now.
- **Approach.** A tracked web app with recording as a detachable layer, chosen over growing the gitignored rig and over playing unrecorded first.
- **Completion.** She marks a body done herself with a tappable star; chosen over a category rule and over no mark.
- **Engineering posture.** Separation of concerns, practical design patterns, modular design for testability and swappable technology, and nothing added for its own sake; every seam must name its principle. Stated by the user during review; now a section of the plan and a project memory note.
- Confirmed via scoping checkpoints rather than chosen against a menu: real pipeline content over hand-picked cut-outs; persistence between sessions; the hand model for carrying; drop rules; the boundary document amended rather than carried unchanged; home-network serving on a pinned address with one shared port.

## What exists now, by maturity

- **`docs/plans/2026-09-19-0736-feat-playable-web-version-plan.md`** — complete, untracked. A unified plan: Product Contract (R1 to R19, five flows, eight acceptance examples), Planning Contract (KTD1 to KTD13, two diagrams, System-Wide Impact, Engineering posture), eight implementation units U1 to U8, Verification Contract, Definition of Done. Deepened once and document-reviewed once; both passes are folded in, nothing pending except one deferred question (below). Start from its Goal Capsule.
- **`CONCEPTS.md`** — staged from the previous session and modified again here (unstaged): added Hand, Page Triage, Plain Build, Playtest Build, and the note that "mannequin" is the family's word for Base Body.
- **Sixteen staged, uncommitted paths** from before this session (orientation, page type, content structure doc, the thresholds learning, and more). Finished and tested, 95 tests pass. Still waiting only on a decision to commit. `git status --short` lists them.
- **`playtest-rig/`** — gitignored, untouched this session. Its README still hardcodes a Tailscale address and a stale scratch path for the boundary check; U7 of the plan rewrites it.
- **Nothing under `web/` exists yet.** No code was written this session.
- **Project memory** gained `engineering-principles-modular-but-earned.md`. Machine-local.
- **Grounding dossier** at `/tmp/compound-engineering-1000/ce-brainstorm/web-poc-20260918/grounding.md`, machine-local and lost on reboot; the plan's Sources section carries everything from it that matters, and it contains unredacted addresses, so do not copy it into the repo.

## Findings from research and review that the plan rests on

All are recorded in the plan with file pointers; listed here so the next agent knows they were verified, not assumed.

- Page triage (`orientation.py`, `pagetype.py`) is tested but wired to nothing; U1 builds the stage.
- The catalog cannot carry Base Bodies; U2 makes the pipeline emit `bodies.json` beside `catalog.json` from a hand-kept page list. The Kotlin reader ignores unknown keys, so the catalog's shape can gain a scale block safely.
- The catalog build shrinks each image independently to 512px, destroying relative size; U3 replaces it with one shared factor bounded so no image exceeds the old ceiling, keeping the Android memory arithmetic true.
- The rig's drag broke because one global gesture record was overwritten by any second finger. The new engine keys state by pointer id and allows one live gesture.
- The rig's instrument only classifies taps; the old page reported placements and drags itself. The plan makes the instrument its own drag observer from annotations, so the app never calls it.
- Browser storage is keyed to the exact address and port; both servers share one port and the address is assumed pinned by DHCP reservation, with a home-screen shortcut on the tablet.
- The boundary document needs amendments: home-network reachability is the intended posture, the per-session token binds a log to one page load and is not a secret, integer indices replace content id strings in the log, no text input anywhere the recorder can see, storage allowed only in the app under one key, logs in `~/dress-up-playtest-logs/`.

## Open, blocked, or fragile

- **Deferred question:** whether this machine's home directory is under a backup or sync tool. The boundary forbids log copies in a synced folder. Only the user knows.
- **The tablet has been offline** on Tailscale for 22 days as of 2026-09-19; the plan no longer needs Tailscale, but the tablet must be on the home network for any session.
- **Content is a prerequisite** for the playable version to mean anything: U1 to U3 then U6, with the parent confirming triage rejections. The classifier is only trustworthy on the Fantasy book.
- **No Android toolchain exists** on this machine and none is needed for this plan.
- **Playwright** needs one network download plus system libraries that require sudo on Ubuntu.
- **Cross-model review was skipped** deliberately: a Codex route is installed, but sending the plan to a third party was not confirmed by the user. Offer it rather than run it.

## Wrong paths, do not retry

- Do not extend `playtest-rig/prototype.js` into the product; the plan rejects that with reasons.
- Do not put instrumentation, storage APIs, text inputs, addresses, or the rig marker under `web/`; the tracked purity test and the extended boundary scans fail on them by design.
- Do not hardcode tailnet addresses or the tablet's hostname in tracked files; the hostname carries a person's name.
- Do not trust `docs/ROADMAP.md` or `docs/TESTING.md` for this tree; they describe the lost original.

## Next steps

One path, in order: run `ce-work` on the plan. It is executable as it stands, with no launch-blocking question. Commit the sixteen staged paths and the plan first if a clean tree is wanted; that is a decision the user has not yet made, not a blocker.

Relevant skills: `ce-work` for the plan, `ce-commit` for the staged paths, `ce-compound` if implementation teaches something worth keeping.
