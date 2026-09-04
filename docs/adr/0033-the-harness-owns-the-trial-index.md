# ADR-0033: The trial number is the harness's, passed to the adapter rather than read back out of it

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
SPEC §4 runs each task n times per tool, five by default, and reports `pass@1` and `pass^n` over
those trials. Every attempt therefore records which of the n it came from, and every result records
it a second time: `Attempt.trial_index` and `Result.trial_index`, in
[`src/assay/results/models.py`](../../src/assay/results/models.py). The two are required to agree,
by the same validator that requires the task id and the adapter name to agree — a result whose
attempt belongs to another trial attributes a measurement to a trial that did not produce it, which
SPEC §5.5 forbids.

SPEC §6 fixes `Adapter.run`'s three arguments — the task, the workspace, the budget — and titles
the interface "keep it this small". None of the three carries a trial number, so an adapter has no
way to know which trial it is running. M0's two oracles said so in a comment and hard-coded 0,
deferring the question to "the n-trial runner that owns that numbering", which is M3. This is M3.

Two defects fall out of that shape, and both are invisible until the number matters.

The first is that the agreement between attempt and result is not checked. `run_trial` builds the
result by reading `attempt.trial_index` — it copies the number out of the very thing the validator
then compares it against. The task-id and adapter-name clauses are real comparisons, because those
two come from the task the call set up and the adapter it called. The trial clause compares a value
with itself and cannot fail through this path. It is not a weak check; it is unreachable code.

The second is that `run_trial`'s docstring promises a `ValidationError` "if the adapter's attempt
names a different trial than the one this call drove". No call can keep that promise, because the
call does not drive a trial number at all — it adopts whichever one the attempt claims. The
docstring describes the behaviour the harness should have and does not.

Underneath both sits the thing M3 actually needs: with the number owned by the adapter, an n-trial
run is not expressible. Five trials of one task through either oracle produce five attempts stamped
0 and therefore five results claiming to be the same trial — indistinguishable in a result set that
counts each of them as another trial. `tests/score/test_end_to_end.py` runs one trial per task per
oracle for exactly this reason, and says so in its own docstring.

## Decision
**`Adapter.run` takes a fourth argument, `trial_index: int`, keyword-only, and SPEC §6's code block
is edited to match the widened signature.** `run_trial` takes the same argument, also keyword-only,
and does two things with it: it hands the number to the adapter, and it names the result from the
number it was given. Nothing reads `attempt.trial_index` on the way to building a result.

The harness owns the number because the harness is the only party that has it. Which of five trials
this is, is a fact about the loop the caller is running, not about the task, the workspace or the
tool; an adapter told a task and a directory could only invent it or count its own invocations.

Keyword-only, rather than a fourth positional, for two reasons. It cannot be transposed with
`budget` by an adapter author who writes the parameters in a different order, since a keyword
argument matches by name at every call site. And it reads as what it is: the three positional
arguments are the trial's material — what to fix, where, and under what ceiling — while this one is
its label.

What this buys is that the validator's third clause becomes reachable and starts doing work: it now
compares the number the harness drove with the number the adapter recorded, and an adapter that
stamps a trial it was not asked to run is refused loudly at the boundary instead of filing its
result under a trial nobody ran. The oracles, which knew the answer before they started, become the
first two adapters that record the number rather than claim one.

## Alternatives considered
- **Re-stamp the attempt inside `run_trial` — copy it with the right index before recording it.**
  Rejected, and it is the tempting shortcut because it needs no change to the protocol at all. It
  kills the third clause permanently rather than leaving it unreachable: an attempt rewritten to
  agree with the result agrees by construction, for ever, and no adapter can ever be caught
  misnumbering. It is also the harness editing the tool's own evidence before recording it. An
  attempt is what the adapter returned; a field of it silently corrected on the way to the store is
  the kind of quiet repair [ADR-0031](0031-an-errored-trial-never-leaves-the-denominator.md) refused
  in a document, and data is a worse place to do it than prose.
- **Drop `trial_index` from `Attempt` and keep it only on `Result`.** Rejected for cost, not for
  correctness — it is arguably the cleaner model, since the number is a property of the run's
  bookkeeping rather than of the work the tool did, and it would remove the disagreement this record
  is about by removing one of the two places the number lives. What it costs is a `result_set`
  schema v2 and a migration, plus three hand-written JSON fixtures rewritten, to delete a field no
  consumer has complained about. CLAUDE.md treats these schemas as API once public. Deferred rather
  than refused: if a later milestone opens `result_set` v2 for a reason of its own, this rides along
  with it.
- **Ride the per-trial `Budget` — add the number to the object the adapter is already handed.**
  Rejected, and this is the smallest change available, which is why it is named. Every field on
  `Budget` is a `max_*` ceiling: what the trial may spend, in wall clock, tokens, tool calls and
  money. An identity is not a ceiling, and a type that holds both stops being a budget and becomes
  a bag of per-trial miscellany — the next caller with a per-trial value would have no reason not to
  put it there too. `Budget` is also a `SchemaModel`, frozen and `extra="forbid"` like every other
  document in the tree, so widening it changes a serialisable shape to carry a value that is not a
  limit.
- **Let each adapter count its own invocations.** Rejected. It makes the number a property of an
  object's lifetime rather than of the run: an adapter constructed once per suite and one
  constructed once per task would number identically-shaped runs differently, and neither would
  agree with the harness after a trial that raised before the adapter was reached. The number a
  report files a result under has to come from the thing that decided to run the trial.

## Consequences
Every adapter that will ever exist implements one more argument — the M3 naive baseline and agentic
adapters included — and SPEC's "keep it this small" interface is one argument bigger than it was.
That is the honest cost: it is paid once per tool ever added, and this record is the bar the fifth
argument has to clear.

A misnumbering adapter now fails loudly where it used to be recorded silently. That is a new way for
a third-party adapter to break a run, and it is the point of the change rather than a side effect of
it: the failure is a `ValidationError` naming both numbers, at the moment the result is built, with
nothing measured under the wrong trial.

`Attempt` still records a number that `Result` also records, so the duplication SPEC's schemas were
written with survives. What changes is that it is now checked rather than assumed — the two values
have independent origins, which is the only condition under which comparing them means anything.

The proof that the clause is reachable is a test rather than an argument, and it is the one the
change was written against: an adapter that hard-codes trial 0, driven as trial 3, raises rather
than records. Beside it sits the run that could not previously be written down — five trials of one
task, numbered 0 through 4, each result naming its own. Both live on fakes in `tests/score`, so the
property is checked without git, docker or a model.

`assay run` can now drive trials 0..n-1 over one task and get n distinguishable results, which is
what the rest of M3 is built on. The end-to-end bracket still runs a single trial per task per
oracle, because an oracle answers every trial of a task identically and four more container starts
would buy no evidence; it now names that trial 0 explicitly rather than inheriting it from an
adapter's constant.
