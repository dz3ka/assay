# ADR-0069: The result set is written after every task, and the objection to that is answered rather than dropped

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Bogdan Dzekic

> **Amended 2026-09-11 — one figure corrected, no decision changed.** The Context below says the
> discarded 2026-09-10 run "ran for over an hour" (and the Consequences weigh fourteen writes
> "against a run measured in hours"). **It ran 16 minutes 52 seconds.** The retained start and
> finish stamps are `2026-09-10T12:31:35Z` and `12:48:27Z`, the run log's own modification time
> falls inside that window, and at the rate measured on 2026-09-11 — 165 trials in 22 min 28 s —
> 105 trials is about 14 minutes, which fits the stamps and does not fit an hour. The hour is
> corroborated by nothing that was kept. **The original words are left as written**, per this
> directory's habit of withdrawing rather than deleting.
>
> **The decision is unaffected.** What this record decides — that the result set is written after
> every task — rests on 105 scored trials being lost to a single end-of-run write, and that loss
> is established two independent ways (`grep -cE '^\[ *[0-9]+/195\]'` over the retained log → 105;
> and the pre-registered arithmetic 7 tasks × 3 adapters × 5 trials = 105). Neither depends on how
> long the run took. The cost argument in the Consequences also survives the correction: fourteen
> writes of a document measured in tens of kilobytes is negligible against a run measured in *tens
> of minutes* just as it was against one measured in hours.
>
> Recorded in full, with the arithmetic, at
> [`docs/milestones/local-model-live-run.md`](../milestones/local-model-live-run.md) §3.

## Context

`run_run` used to write its output exactly once, after the last trial of the last task. The
docstring said so, and said why:

> Everything is accumulated in memory and written once. There is no append and no resume: a
> partially written result set is a report that would silently omit trials, and a run that has
> to be repeated is honest about it. The largest measured yield to date is two tasks.
> — `src/assay/cli/main.py`, before this record

That reasoning was correct when it was written and it is worth stating plainly why, because this
record overturns the decision and not the argument. A file holding three trials could mean "three
trials is all there were" or "the run died after three", and nothing in the document
distinguished them. Writing once made the file's existence a claim that the run had finished.
The last sentence is the other half: with a largest measured yield of two tasks, a repeat cost
minutes, so paying for a partial file bought nothing.

Both premises are gone.

**The denominator is in the file now.** ADR-0067 added `suite_task_count` and `unprovisioned`, so
a short file states what it was short *of* and names each task missing from it. The ambiguity the
old docstring guarded against is no longer expressible: three trials out of a thirteen-task suite
reads as three trials out of a thirteen-task suite, in the document, without a reader having to
know anything about the run that produced it.

**The yield is no longer two tasks.** The live `jd/tenacity` run of 2026-09-10 was thirteen tasks
and ran for over an hour. It ended on a task whose image would not build — and because the only
write was at the end, 105 already-scored trials went with it. The cheap repeat the old reasoning
assumed does not exist at this size, and "a run that has to be repeated is honest about it" is
honesty purchased with an hour of compute and no record at all of what was learned.

ADR-0068 decides how a task that cannot be provisioned is recorded. This record decides when the
file that records it is written.

## Decision

The result set is written in full at the end of **every** task, and once more before the first
task begins.

- `_snapshot()` (`src/assay/cli/main.py:1103`) is a closure over `results` and `unprovisioned`
  that builds the whole `ResultSet` as it stands. It is the only construction site in the
  function, so every write below writes the same shape.
- `write_result_set(out, _snapshot())` runs before the loop (`:1132`), so the path the caller was
  told to read exists from the start — empty, and already carrying the suite's denominator.
- `write_result_set(out, _snapshot())` runs unconditionally at the bottom of every iteration
  (`:1185`), after both the `except` and the `else` arm. There is no `continue` anywhere in the
  loop, so that line cannot be skipped.

**There is still no append and no resume.** Every write is the complete set so far, written
atomically by `write_result_set`, and a repeated run starts from nothing. That is the same
guarantee the old docstring made and this record keeps it: the file is never a fragment that has
to be stitched to another fragment, and no code reads an existing output file to decide what to
do next.

**A task is the unit of the write, not a trial.** The write is outside the adapter and trial
loops. Half a task's trials never reach the file, for ADR-0068's reason — they would be rendered
as `pass^n` over an n nobody ran — so the smallest thing that can appear in the file is a whole
task's worth of trials, or that task's name under `unprovisioned`.

**`ResultSet`'s coverage validator compares with `<=` for exactly this reason**
(`src/assay/results/models.py`, `_check_coverage`). An intermediate write covers fewer tasks than
the suite holds, and that is the normal state of a run in progress rather than a bad document.
Over-count is still refused, and so is a task counted as measured and unprovisioned at once.

**The docstring states the answer, not just the behaviour.** The replacement text quotes its own
predecessor's concern in substance and says what changed, so a reader who arrives at the function
with the old objection in mind meets the answer at the function rather than having to find this
record.

## Alternatives considered

**Keep writing once, and simply not crash.** The minimum ADR-0068 needs: catch the failure, keep
looping, write at the end. Rejected because it leaves every *other* way a run can die — an
interrupt, a full disk, a laptop lid, a docker daemon restart — costing the entire run's work.
The 2026-09-10 loss is the case that happened to have a catchable exception at its centre; it is
not the only case, and a fix that only covers that one is a fix for the last failure.

**Append trials to the file as they are scored.** Rejected. It makes the document a log rather
than a value, so every reader needs to know how to assemble one — and a half-written trial at the
tail is a parse error rather than a short file. It also breaks the property that the file is
always a valid `ResultSet`: `write_result_set` writes canonical bytes for one model, and an
appender would have to write its own framing and its own recovery rule for a torn write.

**Write after every trial rather than every task.** Rejected against ADR-0068's discard rule. A
per-trial write would put a task's partial trials in the file, which is exactly the state that
renders `pass^n` over the wrong n — and a crash would then leave a *published* partial task
rather than a task that is simply absent. The write cadence and the discard rule have to agree,
and the task is the unit both of them use.

**Resume: read the existing file on startup and skip tasks already in it.** Rejected as a
different feature with its own hazards. A resume has to decide whether the suite, the adapters,
the trial count and the tool version still match what the file was written under, and getting any
of those wrong silently mixes two runs into one result set — a reproducibility failure of exactly
the kind content addressing exists to prevent (SPEC §5.5). The file being complete-so-far is what
makes a resume *possible* later; this record does not build one.

**Write to a temporary path and rename only at the end.** Rejected: it is the write-once
behaviour with extra steps. The point is that the durable artefact exists while the run is alive,
not that it appears atomically at the end — and `write_result_set` is already atomic per write.

## Consequences

**An interrupted run keeps what it measured.** Ctrl-C after task nine of thirteen leaves nine
tasks' trials on disk, with the suite's denominator beside them, and `assay report` can read that
file. The trials that were in flight for task ten are lost, which is the task-shaped granularity
this record chose.

**The output path is no longer evidence that a run finished.** Anything reading a result set has
to read its coverage fields to know that — which is what ADR-0067 made possible and what ADR-0070
will make visible in the report. A reader who checks only for the file's existence will now
mistake a live or interrupted run for a complete one; nothing in this repo does that, and the
schema is the place that answer lives.

**The file is rewritten n+1 times per run rather than once.** For a thirteen-task run of five
trials and two adapters that is fourteen writes of a document measured in tens of kilobytes,
against a run measured in hours. The cost is not worth an optimisation, and a cheaper incremental
write is the append this record rejected.

**Write failures now surface during the run rather than after it.** A bad output path or a full
disk raises out of the first write, before any image is built, instead of after the last trial —
which is the same "fail in a second rather than after the first image" principle the adapter
construction above the loop already follows.

**The cadence is asserted, not documented.** `tests/cli/test_main.py` reads the output file back
at the start of every task and pins the sequence — nothing, then one task's trials, then two
tasks' — so a future edit that moves the write back outside the loop fails a test rather than
quietly restoring the behaviour that lost 105 trials.
