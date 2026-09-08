# ADR-0053: The public-repo yield is measured with the shipped command on the host path

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
M5 publishes a number Assay has never published: what its miner yields on public repositories it
was not built against. Two mechanisms could produce that number, and they do not produce the same
one.

**The shipped command runs on the host.** `run_mine` (`src/assay/cli/main.py:901`) opens a
temporary worktree root and calls `mine_suite` with `runner_for=host_runner_for`
(`src/assay/cli/main.py:927`) — a literal, not a parameter. `host_runner_for`
(`src/assay/cli/main.py:702`) provisions a `.venv` into the worktree with `uv` and returns a
`PytestHostRunner`, or `None`, which the walk counts as `unprovisioned`. There is no flag, no
environment variable and no argument on `run_mine` that changes that. So every environment the
gate sees is resolved against **today's** package index under **today's** interpreter, which is
exactly the reach limit [ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md) recorded
after the httpie run and [ADR-0013](0013-mining-runs-on-the-host-in-m1.md) accepted the exposure
of.

**The pinned per-task image, which lifts that limit, was never wired into `mine`.**
[ADR-0021](0021-resolution-is-pinned-to-the-base-commit-era.md)'s epoch-pinned resolution and
[ADR-0023](0023-the-image-installs-declared-test-extras.md)'s declared test extras are real and
measured — inside a post-fix image httpie collects 1028 tests where M1 collected none
([ADR-0025](0025-the-one-widening-is-spent.md)). But the only call site in the CLI that hands the
miner a sandbox runner is `run_run`'s trial loop (`src/assay/cli/main.py:1091`,
`runner_for=sandbox_runner_for(image, …)`). `assay mine` has never had it, and this record adds
none.

**The gap is not a missing flag.** `sandbox_runner_for` (`src/assay/sandbox/runner.py:134`) takes
an `image_tag` — an image that already exists, built when the task was mined. A pinned-image
*mine* would have to build one image per walked commit **before** the gate can speak about it,
because the gate's three test runs are what decides whether the commit is a task at all. On a
200-commit walk that is up to 200 image builds; ADR-0025's own scale run measured 124 of 126
attempted builds failing. Wiring it is a pipeline with its own failure taxonomy, its own caching
question and its own wall clock — a milestone of work, and M5 is the release milestone, not that
one.

**M2 produced its scale number with `wp8_remine.py`, an uncommitted script**
(`docs/milestones/m2-yield-httpie-pinned.md:35`, `:51`, `:452` — the document says so in its own
words: *"Not `assay mine`. There is no wiring for a pinned-image mine and this run added none"*).
That was honest and correctly disclosed for an internal milestone record. Repeating it for the
**public release document** would publish a headline figure nobody outside this machine could
re-derive, since the tool that produced it does not ship — the precise failure
[ADR-0045](0045-a-claim-carries-its-verification-inline.md) exists to prevent, arriving at the
one document most likely to be quoted.

## Decision
**The public-repo yield in [`m5-yield-public-repos.md`](../milestones/m5-yield-public-repos.md) is
measured by the shipped `assay mine`, on the host path, and by nothing else. The pinned-image
miner stays unwired, and that is published as a stated reach limit rather than patched inside
M5.**

Four things follow from that, and all four are on the face of the document:

1. **Every figure carries its command.** The invocation is `uv run --frozen assay mine --repo
   <clone> --out <suite> --name <slug> --limit 200`, spelled per repository beside the number it
   produced, with the clone's HEAD sha. A reader with the same clone runs the same command from a
   release checkout and gets the same walk.
2. **The selection rule and the limit are fixed before the first run and stated before the first
   result** — *small single-package pytest-based libraries with pinned dev dependencies and no
   service dependencies*, at `--limit 200`, over `pallets/itsdangerous`,
   `theskumar/python-dotenv` and `jd/tenacity`. A threshold chosen after the number is how an
   honest zero becomes a dishonest one, and this repository's whole subject is that difference.
3. **Whatever comes out is published, zero included.** ADR-0019 and ADR-0025 both make zero the
   expected outcome, and both record one; a third would be a finding about Assay's reach, stated
   plainly and without apology.
4. **The published number is a floor on the host path, not a ceiling on Assay.** It bounds what
   the shipped command reaches today. It is not evidence about what a pinned-image mine would
   yield, and the document must not be read as though it were.

**This amends [ADR-0025](0025-the-one-widening-is-spent.md) rather than superseding it.** 0025
spent the one allowed widening on the task image and closed the door on a second patch. It did
not say where that widening lives. This record says it: **in `assay run`'s images, and not in
`assay mine`** — so a yield measured with the shipped command is measured under M1's environment
model even at M5, and the widening 0025 spent does not apply to it.

## Alternatives considered
- **Wire `sandbox_runner_for` into `run_mine` behind a `--pinned` flag.** Rejected on scope, not
  on merit: it is the right long-term shape and it is a build-per-candidate pipeline (see
  Context), landing untested machinery in the release milestone to move one published number.
- **Commit `wp8_remine.py` into `scripts/` and publish its output.** Rejected: the script has no
  tests, no `mypy --strict` coverage and no argument contract, and committing it to make one
  figure citable would put an unproven mining path in the public surface at the milestone that
  freezes that surface.
- **Run the unpinned-but-uncommitted script anyway and disclose it, as M2 did.** Rejected for a
  release document specifically. A disclosure is enough when the reader is the author; it is not
  enough for a figure whose reproduction recipe is the artifact.
- **Mine httpie a third time instead of new repositories.** Rejected: it measures the same
  repository ADR-0019 and ADR-0025 already measured twice, and answers nothing about reach.
- **Scout several repositories, then publish the ones that yielded.** Rejected outright, and this
  is the one rejection that is not about cost. Selecting on the outcome makes the number
  meaningless in the exact way this project exists to expose; the rule, the repositories and the
  limit were written down before the first clone was made.
- **No limit, or a much larger one.** Rejected: the walk runs the target's own suite three times
  per candidate on the host, so a full history is hours per repository. A stated limit that fits
  the window is honest; an unstated one that quietly truncated would not be.
- **Publish nothing if the yield is zero.** Rejected under the standing rule that a zero is
  published as a finding about the miner. A results section that only ever appears when it is
  flattering is not a measurement.

## Consequences
**The number is reproducible by a stranger.** Clone, checkout the sha, run one shipped command.
That is the property the release document trades scale for.

**The number under-states Assay's ceiling, and the document says so.** A repository the host path
cannot provision counts `unprovisioned`, and a repository whose historical closure resolves to
2026 releases fails the gate as `still_red` — both are M1 model artifacts that a pinned-image
mine could lift. Reporting the floor as though it were the ceiling would be the overstatement
this project treats as fatal; reporting it as a floor is the honest form.

**`assay mine`'s host execution is now a published property of the release, not an M1 leftover.**
It appears in the command's own `HOST_EXECUTION_NOTICE`, in ADR-0013, in ADR-0019 and now in a
release document, so anyone pointing it at a repository they do not trust has been told three
times.

**Wiring the pinned-image miner remains open, and is now written down as open.** ADR-0025 left it
implied; this names it as the work a later milestone would do, with the shape it would take —
build per walked commit, before the gate, with its own failure taxonomy — so the next person does
not have to rediscover why it is not a flag.
