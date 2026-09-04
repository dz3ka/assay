# ADR-0034: Wilson intervals land in M3, and the placeholder apparatus is deleted rather than flipped

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
SPEC §7 assigns the `stats` package to M4: Wilson intervals, a paired significance test, and
cost per solved task. M0 needed an interval anyway, because
[ADR-0005](0005-no-winner-when-intervals-overlap.md) put the no-winner rule in the schema from
the first milestone, and a rule about overlapping intervals is untestable without intervals. So
M0 invented one: `stub_interval`, a fixed ±0.25 band around pass^n clamped to [0, 1], with the
report carrying `intervals_are_placeholders` and all three renderers printing
`STUB_INTERVAL_NOTICE` verbatim above the numbers while that flag was true. ADR-0005 pinned the
follow-up in writing: when the real computation lands, those three symbols and the function die
in the same change.

M3 is the milestone that forces the question early. Its exit criterion is pass@1 and pass^n
produced end to end for two real adapters, and n trials per task per tool is the whole point of
the run. A number produced by a real tool against real mined tasks, printed under a caption
saying the uncertainty around it was invented, is exactly the confident-untrustworthy document
CLAUDE.md refuses to publish — and the honest interval is not hard. Wilson is one closed-form
expression over two integers; it is smaller than the placeholder apparatus that stands in for
it. Deferring it to M4 would mean M3's headline measurement, the first real one this project
takes, is the only one ever reported without a real band.

That leaves what to do with the M0 apparatus. `intervals_are_placeholders` is a required field
of a public schema, and CLAUDE.md treats result and task schemas as API — but a report is
neither. [ADR-0008](0008-pydantic-v2-over-canonical-json.md) settled that an interval is a
float and floats have no stable canonical encoding, so a report is rendered rather than hashed:
it is not content-addressed, not stored, and not loaded back by the harness. Nothing reproduces
from it. The only consumer of a rendered report is a person, and whatever they pipe it into on
the day.

## Decision
**Wilson lands in M3, in a new `assay.stats` package, and the M0 placeholder apparatus is
deleted in the same change rather than flipped to a permanent `False`.** All four symbols go:
the `intervals_are_placeholders` field, `_STUB_HALF_WIDTH`, `STUB_INTERVAL_NOTICE` and
`stub_interval`, along with the stderr print in the CLI that carried the notice and the
renderer branches that printed it. SPEC's M4 row keeps the paired significance test, the
bootstrap and cost accounting, and loses the Wilson line to M3.

The deletion is one change, not two, because the renderer tests assert the notice verbatim.
That was deliberate — ADR-0005 built them as the tripwire that fires when a measured interval
is still captioned as invented — and a tripwire is only useful if the change that trips it also
disarms it. Splitting the arithmetic from the deletion would leave the suite red between two
commits, which is the state CLAUDE.md's milestone discipline exists to prevent.

A flag that can only ever hold one value is not a smaller change than deleting it. It is a dead
branch in three renderers, a field every future report has to set, four tests pinning text that
can never print again, and a reader's question — *when is this true?* — with no answer. The
half-measure costs more than the deletion and reads as live wiring.

## Alternatives considered
- **Keep the field, flip it to `False` for ever.** Rejected. It is the smallest diff and the
  worst outcome: `Report` would carry a boolean no code path can set true, the renderers would
  keep a branch nothing reaches, and the four tests that pin the notice would be testing a
  string no report can contain. "No half-measures" in the engineering standards is exactly
  this case — a dead flag that reads as a live one.
- **Replace it with a successor field, `interval_method: "wilson"`.** Rejected, and this is the
  tempting one, because a report that names its own arithmetic sounds strictly more honest. It
  has one possible value today. A field with one value is a constant with a serialisation cost:
  every report writes it, every consumer must ignore it, and nothing ever branches on it. It
  earns its place the moment M4 makes the confidence level or the method configurable, and it
  is cheap to add then — a report is not versioned, precisely because ADR-0008 made it a
  rendered document.
- **Defer Wilson to M4 as SPEC §7 schedules it, and ship M3's real numbers under the
  placeholder caption.** Rejected. M3 is the milestone that first measures something real, and
  the caption would be false in the direction that matters: it says the number below it was
  invented when it was not, and the interval genuinely was invented when it says so. Either way
  the report lies about its own arithmetic for one whole milestone, over the only numbers this
  project exists to produce.
- **Put `wilson_interval` in `assay.report`, where its only caller lives.** Rejected. SPEC's
  module tree names `stats` as a package of its own, and the reason survives contact: a
  statistic that can reach a result set is a statistic that will eventually be handed one and
  asked to decide what the numerator was. `stats` imports nothing from Assay, so deciding what
  counts as a success stays in `summarise`, which is the only function that knows.
- **Take the interval from a statistics library rather than writing eleven lines.** Rejected on
  the standards' dependency rule. `statsmodels` brings a numeric stack for one closed-form
  expression; the expression itself is checkable against a hand-computed table, which is what
  CLAUDE.md's measurement rules ask for, and a dependency cannot be checked that way.

## Consequences
The report schema loses a field and no migration is written, because a report is rendered and
never read back ([ADR-0008](0008-pydantic-v2-over-canonical-json.md)). A consumer that parsed
`intervals_are_placeholders` out of a JSON report sees it disappear. That is the cost, it is
accepted rather than mitigated, and the field's own meaning is what makes it acceptable: it
said "these numbers are invented", so a consumer branching on it was branching on a temporary
admission that was always going to end.

ADR-0005's pinned follow-up is discharged here, one milestone earlier than it expected. The
tripwire fired as designed: the renderer tests failed the moment the real band replaced the
stub, and this change is what disarms them.

The two hand-written result fixtures had to be re-derived, and that is the part worth
recording. `tests/fixtures/results_disjoint.json` demonstrated the winner branch with two
tasks, because a ±0.25 band around 0.0 and 1.0 does not overlap. Under Wilson it does: the
bracket separates only when the task count exceeds z² ≈ 3.84, so the fixture grew to five
tasks. The invented band was not merely uninformative — it declared a winner on evidence that
cannot support one, which is the exact failure ADR-0005 exists to prevent, sitting inside the
apparatus built to demonstrate the prevention. The two-task case is now a test in its own
right, asserting no winner.

The renderers no longer print anything above the numbers, and the CLI's `report` command writes
nothing to stderr on success. RULING 4's stream split — document to stdout, admission to stderr
— was a consequence of prose that could not live inside the canonical document; with the
admission gone, stderr goes back to meaning that something went wrong.

M4 inherits a smaller job and a working seam: the significance test and the bootstrap land
beside `wilson_interval` in a package that already exists, already has a test file built on
hand-computed values, and already proves it imports nothing from the rest of the tree.
