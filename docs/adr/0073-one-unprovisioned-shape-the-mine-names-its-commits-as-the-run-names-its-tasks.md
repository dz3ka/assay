# ADR-0073: One `unprovisioned` shape: the mine names its commits and their reasons, as the run names its tasks

- **Status:** Accepted
- **Date:** 2026-09-14
- **Deciders:** Bogdan Dzekic

## Context
Assay has one state for "no environment could be built for this, so nothing was measured", and
until this record it had two shapes for it.

**The run names what it could not measure.** [ADR-0067](0067-the-result-set-carries-its-own-denominator-and-names-what-it-could-not-measure.md)
gave `ResultSet` an `unprovisioned: Mapping[TaskId, str]`, task id to the failure's own sentence,
and rejected a bare count in so many words (`0067:105-108`): "A count discloses the shortfall's size
and withholds the only part a reader can act on." [ADR-0068](0068-one-unprovisioned-state-for-both-causes-and-a-partial-task-is-discarded-whole.md)
then folded both of the run's causes into that one state, on the ground that what a reader needs is
*which task* and *what sentence* (`0068:47-48`).

**The mine only counts.** `MiningYield.unprovisioned` has been an `int` since M1. The host seam that
produces it, `host_runner_for`, caught `EnvironmentSetupError` and returned `None` through
`RunnerFactory`, so the sentence the error carried was dropped at the one place it existed. The walk
printed `unprovisioned: <subject>` per commit and the yield printed `N unprovisioned`; nothing, on
either stream, said why. [ADR-0015](0015-a-rejection-reason-must-be-reachable.md) records that shape
as it shipped: the factory "returns `None`" (`0015:20`, `:46`) and the field "is that count" (`:32`).

**The reason is the finding, not a detail of it.** [ADR-0071](0071-the-setuptools-floor-is-declined-and-the-builds-it-would-have-rescued-are-reported.md)
closed a question five sessions had carried, and what closed it was the sentence two builds failed
with — `distutils` under an era pin — not the number two. A mining tally that could only have said
"2 unprovisioned" would not have let anyone reach that conclusion from Assay's own output.

**Nothing but Python importers depends on the int.** `MiningYield` is committed and exported from
`assay.mine`, but it is never serialised into a suite, carries no `schema_version`, and is not part
of `SuiteBody`. Changing its field type moves no content address and no document.

## Decision
**The mine's `unprovisioned` takes the run's shape. `MiningYield.unprovisioned` becomes
`Mapping[str, str]`, full commit sha to the failure's own words, empty by default. `ResultSet` is
not touched.** This was put to the user as a choice between the two shapes and ruled "Mapping wins"
on 2026-09-14.

**The reason is carried as a value from the seam to the yield, never reconstructed.**

- `assay.mine.protocols` gains `Unprovisioned`, a frozen dataclass with one field, `reason: str`, and
  `RunnerFactory` becomes `Callable[[Path], TestRunner | Unprovisioned]`.
- `host_runner_for` returns `Unprovisioned(str(error))` from its `except EnvironmentSetupError`. The
  reason is whatever the error said, verbatim, and may span several lines: `CommandFailedError`
  appends an excerpt.
- `run_gate` returns the factory's `Unprovisioned` unchanged. `MinedCommit.outcome`,
  `revalidate_suite` and `revalidates` carry `GateOutcome | Unprovisioned` where they carried
  `GateOutcome | None`; a trial in `assay.score` still scores such a workspace `FAILED`.
- `tally_yield` takes the `MinedCommit`s rather than their bare outcomes, because the sha is the
  key. A sha that arrives twice collapses to one entry, the partition comes up short, and
  `MiningYield`'s own validator refuses the yield. That refusal is the negative test.

**The partition's arithmetic does not change.** `_check_partition` counts `len(unprovisioned)` where
it counted the int, so accepted + rejected + unprovisioned = commits examined holds on exactly the
same numbers. The fixture's expected yield is built without the field, so it is the same partition
it was, and its exact-yield assertion is untouched.

**`assay mine` says why, once per commit, on stderr, in the run's words.** After a commit's
examined line, an unprovisioned commit gets `assay mine: <sha12> unprovisioned: <reason>`, the
counterpart of `assay run: <task> unmeasured: <reason>`. The yield document on stdout prints
`len(unprovisioned)` and is byte-identical to what it printed before. The reason is deliberately
**not** folded into `_examined_line` or `_verdict`: `assay validate` renders its rows through
`_verdict`, and its output is not this record's to change.

**This record amends ADR-0015 and ADR-0066; it supersedes neither.** 0015's rule stands — a
population no gate spoke about is named beside the counts, never minted as a rejection reason — and
only its carrier changes: `None` becomes `Unprovisioned`, and the count becomes a mapping whose size
is the count. 0015 is shipped, so it is not edited; its index row carries the mark, in the form
0042's row already uses. 0066 has not shipped, so it carries a dated blockquote as well, under the
rule `0072:103-109` states. It applies 0067 and 0068.

## Alternatives considered
- **The count wins: give `ResultSet` an int to match.** Rejected by the user ruling, and by
  `0067:105-108` before it. It would make the two shapes agree by deleting from the run the one
  part 0067 argued a reader can act on.
- **A set of shas with no reasons.** Rejected. It names the commits and still withholds the only
  thing 0071 needed. Carrying a reason costs one `str` per unprovisioned commit.
- **One generic alias, `Unprovisioned[K] = Mapping[K, str]`, shared by both models.** Rejected. The
  two keys are validated differently (`TaskId` is pattern-pinned, a sha is not a task id) and live in
  packages that do not import each other. An alias that joined them would add a dependency between
  them to share one line.
- **Rename the field, keeping an int `unprovisioned` beside a new `unprovisioned_reasons`.**
  Rejected. Two fields that must agree are a second partition to validate, and the int is derivable.
- **Return a bare `str` from the factory as the reason.** Rejected. It is the same signature change
  with no smaller diff, and a `str` is a value a factory could plausibly return by mistake. A named
  type says what it means.
- **Keep `None` and have the CLI's closure remember the last error it caught.** Rejected. It makes
  the factory impure, and the reason would be matched to its commit only by generator order, which
  is exactly the implicit pairing a value carried through removes.
- **A mine-owned exception that `run_gate` raises and the walk catches.** Rejected. It reverses
  `protocols.py`'s own rule — an unprovisionable workspace is an ordinary, countable outcome, the
  same kind of answer as `apply_patch`'s `False` — and it puts control flow where a value was enough.

## Consequences
**Python importers break, loudly, and nothing else does.** Code that reads
`MiningYield.unprovisioned` as an int, or a `RunnerFactory` that returns `None`, fails
`mypy --strict`. At runtime a factory still returning `None` makes the gate call `.run` on it and
raise, which ends the walk rather than miscounting it. No suite, result set or rendered report
changes, and no content address moves. Nothing outside this repository is known to import either
name.

**The two shapes now differ only in their key.** A mined commit is named by its full sha; a run's
task by its task id. Both map to the sentence that failed them, and both partitions count the
mapping's size.

**`assay validate` still does not print the reason.** Its rows say `unprovisioned` as before. The
reason now reaches `_revalidated_line` as part of the outcome, so printing it is a formatting change
if it is ever wanted; it was left out here because this record's subject is the mine's accounting.

**The environment asymmetry is untouched.** `assay mine` still provisions on the host and `assay
run` still scores in a pinned image. That gap, the CLI wiring and the re-mine remain 0066's
milestone. Only the shape of the mine's accounting moved into this goal.

**The change lands with its tests:** `MiningYield` naming each commit with its reason and refusing
a mapping that overruns the commits examined; `tally_yield` keying by sha, keeping the reason, and
refusing a sha counted twice; `run_gate` handing back the factory's own value; `host_runner_for`
carrying the setup error's sentence; and `assay mine` printing one reason line per unprovisioned
commit while its yield line still reads `N unprovisioned`.
