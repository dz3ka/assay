# ADR-0066: The provisioning asymmetry gets a milestone of its own, sequenced after the pre-registered run

- **Status:** Accepted
- **Date:** 2026-09-10
- **Deciders:** Bogdan Dzekic

> **Amended 2026-09-14 — by [ADR-0073](0073-one-unprovisioned-shape-the-mine-names-its-commits-as-the-run-names-its-tasks.md); the milestone is unchanged.**
> Two things below are no longer true as written. **First, the shape of the mine's `unprovisioned`
> accounting has moved into the local-model goal by user ruling.** The Context describes
> `unprovisioned` as a count on `MiningYield`; it is now a mapping from commit sha to the failure's
> own sentence, the shape `ResultSet.unprovisioned` has. What this record sequences stays here: the
> environment asymmetry itself — an image per candidate, the CLI wiring for a pinned mine, and the
> re-mine — is still this record's milestone. **Second, the claim in the Consequences that catching
> `CommandFailedError` around `_task_image` and continuing past it "would be a regression of this
> record" was overtaken before 0073.** [ADR-0068](0068-one-unprovisioned-state-for-both-causes-and-a-partial-task-is-discarded-whole.md)
> (`0068:39-46`) made `assay run` catch that failure per task and record the task as unprovisioned,
> by name and sentence, rather than end the run. **The original words are left as written.**

## Context

**The asymmetry, stated exactly.** `assay mine` provisions a candidate repository **on the host**:
`run_mine` hands the walk `runner_for=host_runner_for` as a literal, not a parameter
(`src/assay/cli/main.py:956`), and that factory provisions a `.venv` into the candidate's worktree
with `uv pip install -e . pytest` (`src/assay/host/venv.py:91`) — resolved against **today's**
package index under **today's** interpreter. `assay run` does the opposite: one pinned image per
task, built from a standalone checkout of the base commit with dependency resolution cut off at
that commit's own committer date (`_task_image`, `src/assay/cli/main.py:1181`,
[ADR-0021](0021-resolution-is-pinned-to-the-base-commit-era.md)).

So **the red→green gate that admits a task to a suite runs in a different environment from the one
that scores it.** The gate's verdict is not a property of a commit in the abstract — it is the
claim *these tests fail at this parent and pass once this diff is applied*, and that claim is only
ever true of some environment. Assay makes it in one environment and then sells it in another.
[ADR-0053](0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md) named this,
decided M5's public number on the host path deliberately, and left the wiring open in writing.

**Two work packages this month narrowed it, and how much matters.** ADR-0062 made the build context
a standalone checkout with a real `.git`, [ADR-0063](0063-what-the-context-excludes-and-its-history-enter-the-address.md)
put what that context excludes and carries into the image's address,
[ADR-0064](0064-the-measurement-image-carries-a-pinned-git.md) put a pinned `git` binary in the
image, and [ADR-0065](0065-a-throwaway-clone-writes-no-reflog-and-keeps-no-origin.md) trimmed what
the clone leaves behind. Between them, **both paths now see a real git repository**, which closes
exactly one class of divergence: a task can no longer pass the host gate on a git fact the scorer is
blind to. Everything else still differs — the interpreter, the index date, the extras policy
([ADR-0018](0018-provisioning-installs-the-runtime-set-and-pytest.md) stops at the host and
[ADR-0023](0023-the-image-installs-declared-test-extras.md) is the image's rule), and the entire
userland, since the image is `bookworm-slim` and the host is whatever the operator runs.

**The failure is loud, not silent, and that is what has made living with it survivable.** Nothing
guards the build in `assay run`: `_task_image` is called bare inside the trial loop
(`src/assay/cli/main.py:1107`), a non-zero `docker build` raises `CommandFailedError` unwrapped
(`src/assay/sandbox/image.py:422`), and it reaches `run_run`'s `except (AssayError, OSError)`
(`src/assay/cli/main.py:1138`), which prints one sentence and returns `EXIT_FAILED`. The run stops
and writes nothing. There is no bucket for it to be filed under quietly, either: `unprovisioned` is
a field of `MiningYield` (`src/assay/mine/models.py:222`), a *mining* tally, and `assay run` keeps
no such tally — and [ADR-0027](0027-the-context-must-be-the-commit-the-tag-claims.md) forbids the
sandbox factory from catching and counting there in any case, because "swallowing it would turn one
mis-composed run into a plausible-looking yield table with a quietly smaller numerator". **The risk
this asymmetry carries is therefore wasted runs, not wrong numbers.**

**That is not a hypothesis; it is how the setuptools-scm blocker surfaced.** All thirteen
`jd/tenacity` tasks passed the host gate and entered the pre-registered suite. Then all thirteen
task images failed to build ([ADR-0062](0062-the-build-context-is-a-standalone-checkout-the-workspace-is-not.md)),
and the run died with no figure attached. The design worked: an environment difference the gate
could not see became an error a human had to read, not a number a reader would have believed. That
is evidence *for* the loud-failure posture. It is not evidence that the asymmetry is harmless — it
is the bill for it, paid once, in a goal that had to stop and fix two image defects before it could
call a model.

**What closing it requires is already known, and it is small in code.** `sandbox_runner_for` already
satisfies `RunnerFactory` (`src/assay/sandbox/runner.py:134`) and already answers a runner for any
workspace it is handed. Three pieces are missing:

1. **A task-image build per candidate *parent*, before the gate speaks.** `run_gate` checks out
   `history.worktree(commit.parent)` and runs three test runs there (`src/assay/mine/pipeline.py:189`);
   the image has to exist before the first of them, because those runs are what decides whether the
   commit is a task at all. Not per accepted task — acceptance is the output of the thing the image
   is needed for.
2. **`unprovisioned` accounting for a candidate whose image will not build.** The bucket exists and
   its shape is already decided: ADR-0026 ruled that "a commit whose image cannot be built stays
   `unprovisioned`", counted beside the eight rejection reasons rather than as a ninth.
3. **CLI wiring**, since `run_mine`'s factory is a literal with no flag behind it.

ADR-0025's Consequences ("`assay mine` has no pinned-image path at all") and ADR-0053's ("Wiring the
pinned-image miner remains open, and is now written down as open") both already name it as never
built.

**What it costs is not the code — it is wall clock, per repository.** An image build per candidate
parent, cold, against host provisioning that `run_gate`'s own comment calls "seconds per candidate".
The nearest thing to a measurement this repository holds is M5 §3's walks at `--limit 200`:
**6, 47 and 69 candidates reached the gate** for `itsdangerous`, `python-dotenv` and `tenacity`
respectively ([`m5-yield-public-repos.md`](../milestones/m5-yield-public-repos.md) §3), so an image
per candidate parent means that many cold builds per repository at that limit.
`unverified:` **the wall clock.** The figures that motivated this decision — on the order of 200
candidates, hours per repository — are the architect's estimate, and neither a per-image build time
nor a total has ever been measured on this host. They are recorded here as an estimate and nothing
in this record rests on them being right; the argument holds at any build time above a few seconds.

**And it re-opens every published yield figure.** M5's 600 commits examined → 14 valid tasks was
measured on the host path with the shipped command, by ADR-0053's deliberate choice, and that record
says in its own Consequences that a pinned mine could lift both `still_red` and `unprovisioned`
outcomes. A pinned-image mine would therefore admit tasks the host path rejected, which changes the
table, the per-repository blocks, and the suite hashes underneath them — and a suite hash is an
address ([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)), not a label.

## Decision

**The host-versus-sandbox provisioning asymmetry will be closed. It gets its own milestone, and that
milestone is sequenced after the current local-model-adapter goal ships.** Three parts, and none of
them is conditional.

**1. It gets closed, not documented and lived with.** The standing recommendation across four
handoffs was to write an ADR deferring it indefinitely. That recommendation is overruled here. A
known measurement asymmetry left permanently open, in a project whose entire subject is whether a
number should be believed, is the thing this repository exists to refuse; an ADR that made peace
with it would be the most articulate possible way of not fixing it.

**2. It is a milestone, not a work package.** One work package of code, but hours of wall clock per
repository and a re-opening of every published yield figure — so it owns its own exit criteria, its
own re-mine, and the re-publication of the yields that come out of it, under the one-milestone-at-a-
time discipline `CLAUDE.md` sets. Its deliverables are the wiring *and* the restated figures, not
the wiring alone.

**3. It is sequenced after the scored run, and the reason is pre-registration.** The run is
pre-registered against the `jd/tenacity` suite recorded in
[`local-model-live-run.md`](../milestones/local-model-live-run.md) §1 — the clone HEAD, the
`--limit 200` walk, the 13 tasks and the suite hash
`sha256:f00d81732e3389728b44fd69bc479fcafba4b1085fdb12bfe33336bb3feb1106`, all fixed while no result
existed, together with a stop rule that publishes whatever pass^n comes out **including 0.000**.
Re-mining through the image path would produce **a different suite**: different tasks, a different
hash, a different denominator. That voids the pre-registration, and with it the stop rule that is the
only thing making the published result honest. **A pre-registration that can be revised after seeing
the data is not a pre-registration** — it is a rationalisation with a date on it, which is the exact
failure that document was written to prevent.

So the current goal scores against the suite it registered, on the host-path mine that produced it,
and the milestone re-mines and re-publishes afterwards as its own deliberate, disclosed act — with
both figures printed and the delta named, the pattern §1's "Pre-committed, in case it does not
reproduce" already sets for a hash that moves.

`unverified:` **that the pre-registered `suite_hash` reproduced bit-for-bit on a re-mine.** It was
reported as reproduced when this decision was taken, and it is not substantiable from the tree: the
hash's only source is M5's tenacity mine of 2026-09-07, §1 says so in its own words, and the live-run
document's closing line still reads "its content hash has not been re-derived since 2026-09-07". The
sequencing argument does not need it. A host-path re-mine reproducing or not reproducing says nothing
about whether an *image-path* mine would produce the same suite, and it plainly would not.

## Alternatives considered

**Defer it indefinitely, with an ADR that says so.** The standing architect recommendation, made
four times, and the cheapest option on the table: the failure is loud, ADR-0053 has already
disclosed the host path in the release document, and nothing published today is wrong because of it.
Rejected by the decider. Loudness bounds the damage to wasted runs; it does not make the gate and
the scorer agree, and it leaves Assay permanently admitting tasks under conditions it does not score
them under. This project is allowed to publish a limit it cannot reach
([ADR-0025](0025-the-one-widening-is-spent.md)); this is not one of those — the code to close it is
described in three bullets above and the only real obstacle is wall clock. Reporting a defect Assay
knows how to fix as though it were a reach limit is the inversion ADR-0062 refused, one layer up.

**Close it now, before the scored run.** The tempting order — fix the measurement, then measure.
Rejected: it voids the pre-registration described in the Decision. The suite would have to be
re-registered against the new mine before anything could be scored, and a pre-registration written
after the machinery that produces its subject has just changed under it carries none of the force
the first one has, because the person writing it has by then seen a great deal about how the new
path behaves. The stop rule is what makes a 0.000 publishable; spending it to arrive at a better
suite sooner is a bad trade in the one currency this repository counts.

**Fold it into the current goal as a footnote or an extra work package.** Rejected on three counts.
It is a milestone by size, not a fix: hours of wall clock per repository and a re-opening of every
published yield figure, which is not the shape of anything that belongs under "and also". It would
breach the one-milestone-at-a-time discipline in `CLAUDE.md`, which exists precisely to stop a goal
from acquiring a second goal on the way past. And it would put the re-mine *inside* the goal that
holds the pre-registration, which is the second alternative wearing a smaller hat.

## Consequences

**Until this milestone lands, every published yield figure in this repository is host-path mined,
and must be read that way.** M5 §3's 600 commits examined → 14 valid tasks, the three per-repository
blocks under it, and the `jd/tenacity` suite the live run is registered against are all products of
`assay mine` running the target's tests on the host, under today's index and today's interpreter.
ADR-0053 already made that a stated property of the release. What this record adds is the second
half: they were also produced in a different environment from the one `assay run` would score them
in, and that gap is now dated rather than open-ended.

**The M5 table needs re-mining or an explicit host-path-only label when the milestone lands, and
which of the two is the milestone's decision.** Both are honest. What is not honest is that table
standing unlabelled beside a pinned-image mine, with a reader left to work out which environment
produced which row.

**The loud-failure posture stays load-bearing in the meantime, and is now a decision rather than an
accident.** It is the only thing standing between this asymmetry and a run that quietly scores fewer
tasks than it was asked to. Any future change that catches `CommandFailedError` around `_task_image`
and continues past it would be a regression of this record, on the same reasoning ADR-0027 gives for
`SandboxError` in the runner factory.

**The milestone inherits a seam it must get exactly right, named here so it is not rediscovered.**
Inside a pinned *mine*, an unbuildable candidate's `CommandFailedError` has to be caught and counted
`unprovisioned` (ADR-0026), while a `SandboxError` from the build-context precondition must still
kill the walk (ADR-0027), because that one means Assay handed the build the wrong directory. Two
exception types, two opposite dispositions, at one call site. A factory that caught both would
convert Assay's own composition bugs into a plausible-looking yield.

**The scored run's honesty now rests on this sequencing, and the sequencing is on the record before
the number exists.** That ordering is the only thing that distinguishes this decision from choosing
the mining path after seeing what the suite scored.
