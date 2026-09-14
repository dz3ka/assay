# ADR-0070: The report publishes its coverage on every render, and the tasks it could not measure are tokens like every other identifier

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Bogdan Dzekic

## Context

ADR-0067 gave `ResultSet` a denominator — `suite_task_count` — and a map of the tasks a run
could not provision. ADR-0068 decided what goes in that map and ADR-0069 decided when the file
holding it is written. All three stop at the file. Nothing rendered.

That leaves the harness in the exact position CLAUDE.md names as a failure:

> **Report yield, not just totals.** "1,847 commits examined → 213 valid tasks" is the honest
> form. Never report the task count alone.

The live `jd/tenacity` run of 2026-09-10 is the case. Thirteen tasks were mined; one task's image
would not build. Before this record, `assay report` on that run's output would print pass^n,
pass@1, two Wilson bands, a paired test and a costs table — every one of them over twelve tasks —
under a heading that said `Suite: sha256:…` and nothing else. A reader has the digest, so the
result is *attributable*; they do not have the denominator, so it is not *interpretable*. The
document reads as a complete run of twelve. There is no sentence anywhere on the page a careful
reader could use to discover otherwise, and the fields that would tell them are sitting in the
result set the renderer was handed.

The second force is the redaction boundary. The unprovisioned task is the one task in the suite
with no trials anywhere in the document, so the coverage line is the *only* place its identifier
can appear — and therefore the only place it can leave the machine unhashed. `redact()` is total
by construction (`src/assay/report/redact.py`): it names every field rather than copying a report
wholesale, so a field added to the schema fails to compile there until someone classifies it.
That guarantee is what makes the shape of this change a decision rather than a detail.

## Decision

`Report` gains three flat fields, derived in `build_report` from the result set it already
takes, rendered in both prose formats on every report, and hashed on the way out.

- **`suite_tasks: int`, `measured_tasks: int`, `unprovisioned_tasks: tuple[str, ...]`**
  (`src/assay/report/model.py`), immediately after `tasks`. `measured_tasks` counts *distinct
  task ids* among the results, not results: `tasks` is a trial log at one line per result
  (ADR-0031), and counting it would multiply the coverage by the trial depth.
- **Derived, not passed.** `build_report(rs, summaries, prices)` keeps its signature and
  `run_report` (`src/assay/cli/main.py`) gains no argument. The denominator travels inside the
  result set for ADR-0067's reason, and a coverage a caller has to remember to supply is a
  coverage some caller supplies wrongly.
- **`unprovisioned_tasks` is sorted.** A mapping's insertion order is the order the run happened
  to fail in, which is not something a reader of the rendered line can see and not something two
  runs of the same suite would agree on.
- **`redact()` names all three.** The counts pass through unchanged — a denominator is not
  repo-derived text, and hashing it would delete the claim rather than protect it. Each id is
  hashed with `hash_token(policy, "ident", …)`, **the same kind `_redact_task_line` gives a trial
  line's id**, so one task is one string wherever the document names it. That is what lets a
  reader take the token on the coverage line and confirm it appears nowhere in the trial log.
- **`str`, not `TaskId`.** The tuple holds tokens after redaction, and a token does not match the
  mined-task id pattern. This is the same reason `TaskLine.task_id` is not pinned either
  (`src/assay/report/model.py`, the comment above it).
- **Both prose formats print it, always.** `_coverage_statement()` is one render-local sentence
  read by `render_text` and `render_html`, so the two formats cannot word the same fact
  differently. `render_json` carries the three fields and no prose, like every other sentence in
  this layer (ADR-0008).
- **The sentence claims only what it knows.** `ResultSet._check_coverage` compares with `<=`, so
  a run in progress has tasks that are neither measured nor unprovisioned yet (ADR-0069). The
  line states the two counts and names the unprovisioned; it does not describe the remainder as
  anything, because the report does not know what happened to it.

> **Amended 2026-09-14 — the remainder is counted, and still given no cause.** The bullet above
> stands as written on 2026-09-11 in its second half and is overtaken in its first. Saying nothing
> about the remainder was itself a claim: "1 of 5 tasks measured; 1 could not be provisioned"
> reads as two counts that account for the suite, which is the absence-as-a-claim this record's
> own second alternative refuses. `_coverage_statement()` now appends
> `; N have no result and no recorded failure in this file` (`has` when N is 1) in both branches
> whenever `suite_tasks - measured_tasks - len(unprovisioned_tasks)` is positive. The clause names
> no task, so it has nothing to redact, and it names no cause: a killed run's file and a running
> one's are the same bytes, so a `pending` field or a `complete: bool` on the schema would add a
> word and no fact. `Report`, `redact()` and the JSON document are unchanged — a consumer has the
> three fields and the subtraction — and a complete run's line is byte-identical to before.

## Alternatives considered

**A `Coverage` sub-model holding the three fields.** The tidier schema, and rejected on the
strength of the one property `redact()` has. Field-by-field naming is not a style there; it is
the stated guarantee that a field added later cannot pass through unredacted, because the
construction fails to compile until it is classified. A nested model defeats exactly that:
`coverage=report.coverage` type-checks, reads as deliberate, and ships a raw repository
identifier inside a page whose own sentence says every identifier on it is a token (ADR-0058,
ADR-0009). The compile-time check would still be green. The flat fields are three lines of
schema buying a guarantee that a sub-model would quietly cancel.

**Print the coverage line only when something was unprovisioned.** Rejected as the unexplained
blank ADR-0035 refuses by name, and rejected twice over because the costs section already
answered this question the other way (ADR-0046): a section that appears only when it has bad news
in it makes its *absence* the report's way of claiming completeness. The complete run says "5 of
5 tasks measured; none were left unprovisioned", which costs one line and leaves nothing for a
reader to infer from silence.

**Count the unprovisioned tasks without naming them.** Rejected: the reader's next question is
which ones, and on a redacted report the names are tokens the trial log also prints, so naming
them is what makes the claim checkable rather than a number to be trusted. A bare count is the
same shape of assertion as a pass rate with no interval.

**Derive `measured_tasks` from `len(report.tasks)`.** Rejected — it is wrong, not merely
indirect. Five trials of one task would render as five tasks measured, and the error flatters the
run in precisely the direction this record exists to prevent.

**Put the reason beside each unprovisioned task on the page.** Deferred, not rejected. The
sentences ADR-0068 records (`the image would not build`, a red→green gate that failed at base)
are repo-derived prose whose redaction kind is not obvious — `message`, most likely, but a build
log excerpt is not a commit subject and the boundary should not acquire a fourth kind by
accident. The result set keeps the reasons; the report names the tasks. A record for the reasons
is owed when a renderer needs them.

## Consequences

**No report can show a rate without its denominator.** Both prose formats print the line above
every number, in the header block with the suite hash and the redaction sentence, and the JSON
carries the three fields. A run of twelve out of thirteen cannot be read as a run of twelve
without the reader ignoring a line that says otherwise.

**The one task with no trials is the one task a reader can check.** Its token is an `ident` token
like every id in the trial log, so "this task is not in the log" is something a recipient of a
redacted report can verify rather than accept. Two reports on the same suite still share no
token, because the salt is per render (ADR-0009).

**`Report` gains three required fields, and every construction site had to supply them.** There
are two in `src/` — `build_report` and `redact` — and the test helpers that build reports by
hand. A stored report from before this change does not load; none exist, because a report is
rendered and never persisted as JSON by anything in this repo (ADR-0008 addresses suites and
results, not reports).

**The renderers now depend on coverage being truthful.** They print what `build_report` derived,
and `build_report` copies what the result set recorded. `ResultSet._check_coverage` is what makes
that chain sound — it refuses a set whose counts contradict its results — so the validator is now
load-bearing for a claim on the rendered page rather than only for the file.

**What is still not on the page: why.** Each unprovisioned task is named and none of them says
what went wrong, which is one question further than this record goes. The honest reading of the
line is "these were not measured", not "these failed", and that is what it says.
