# ADR-0031: An errored trial never leaves the denominator, so ADR-0028's verdict rests on legibility

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0028](0028-a-cgroup-kill-is-the-tools-failure.md) decided that a container killed at the
cgroup memory or CPU ceiling it was given — exit code 137 — scores `Outcome.FAILED` rather than
`Outcome.ERRORED`. **That decision is right, it is what the code does, and this record does not
move it.** What this record is about is two sentences of the argument underneath it.

The first is in 0028's Context: scoring the kill `ERRORED` "lifts a real failure out of the
denominator, and the tool that caused it is flattered by exactly the trials it lost". The second is
in its Alternatives considered, arguing against leaving 137 as `ERRORED`: doing so "would also make
a memory-hungry agent *cheaper* to be, since its worst trials would leave the denominator".

Both sentences assume an errored trial leaves the `pass^n` denominator. **In this codebase it does
not, and the opposite was settled before the metric was built.**
[ADR-0004](0004-pass-caret-n-is-the-headline-metric.md) says so in its Decision — errored and
not-scored trials stay in the denominator and are not passes, because excluding harness failures
would flatter whichever tool crashes most. The summary builder in
[`src/assay/report/model.py`](../../src/assay/report/model.py) says the same in its docstring and
then does it: a task counts toward `pass^n` only when *every* one of its outcomes is `PASSED`, each
task's own pass rate is divided by the number of trials that task has whatever those trials were,
and `trials` sums all of them. Nothing anywhere subtracts an outcome from a denominator.

An errored trial and a failed trial therefore move `pass@1`, `pass^n` and the trial count by
exactly the same amount, and a memory-hungry agent is priced identically either way. **0028's
arithmetic argument is not an overstatement. It is the reverse of a rule this project enforces in
code precisely so that no reader has to take it on trust**, which makes it the retroactive
rationalisation `docs/adr/README.md` and CLAUDE.md both warn a record must never become.

The ground that does hold is legibility, and it was available all along.
[ADR-0030](0030-an-out-of-band-exit-code-is-assays-malfunction.md) — the band 0028 carves 137 out
of — takes exactly that ground on purpose, saying in its own Context that the arithmetic is not
what is at stake and that what the third answer buys is a word a reader can tell apart from a
finding. This record does not restate 0030. It moves 0028 onto the same footing, because the two
records decide adjacent branches of one function and cannot rest on contradictory accounts of what
an outcome costs.

## Decision
**This record amends ADR-0028; it does not supersede it. ADR-0028 keeps Status `Accepted`, its text
is not edited, and its decision is unchanged: exit code 137 scores `Outcome.FAILED`, read after the
`timed_out` branch and before the exit-code band.** A cgroup kill scores exactly what it scored
yesterday, in the same function, at the same position.

**Two claims are withdrawn and may not be relied on**: the denominator sentence in 0028's Context,
and the "cheaper to be" sentence in its Alternatives considered. Where the truth about the
denominator is pinned, for anyone auditing either record: ADR-0004's Decision, and the summary
builder's docstring and body in `assay.report.model`.

**What survives is the whole ground, and it is sufficient on its own.**

- **A verdict is a word a reader sees.** Every task line in a rendered report carries its outcome,
  and `assay.report.render` writes that word into the text table and the HTML one. `failed` beside
  a task says the tool spent the memory or the CPU it was given and did not finish; `errored` says
  Assay malfunctioned and the trial is not evidence about the tool at all. Those are different
  facts about a run, and the only place in M2's output they are distinguishable is the word itself.
- **`ERRORED` is a category with real occupancy, so diluting it is not free.** ADR-0030 keeps
  docker's 125, 126 and 127 outside the band deliberately: they are the trials where nothing ran.
  A resource kill filed under the same word makes the one signal that tells a reader *not to trust
  this number* less trustworthy, by mixing into it a trial that was measured exactly as configured.
- **Under [ADR-0003](0003-rank-only-on-executable-signal.md) the ranking reads executable signal
  and nothing else,** and "the tool could not finish inside the resources it was given" is
  executable signal of the plainest kind. 0028 made that argument too, and it never depended on a
  denominator.
- **The load-bearing half of 0028 is untouched.** 137's non-ambiguity, the placement after
  `timed_out` so that Assay's own kill is never mistaken for the kernel's, the placement before the
  band so the rule is not dead code, and the narrowing of the band rule rather than its
  contradiction — none of that reasoning mentions the denominator, and none of it is amended here.

## Alternatives considered
- **Supersede ADR-0028 and restate the corrected record in full.** Rejected. Supersession is for a
  decision that changed, and this decision did not: the verdict, the branch and the ordering are
  all still what 0028 wrote. It would also mark as dead the record that
  `assay.sandbox.container`'s docstring and `tests/sandbox/test_container_policy.py` cite by
  number for a rule those sites still implement exactly, and it would relocate the ordering
  argument — the genuinely load-bearing half — into a second file for no reason connected to what
  was wrong. The index already carries the narrower relation for precisely this case: 0021 amends
  0019, 0023 amends 0018, 0025 amends 0019 and 0021.
- **Edit the two sentences in place, or add an erratum block to ADR-0028.** Rejected, and the
  erratum is the tempting middle. `docs/adr/README.md` states that ADRs are immutable once
  accepted; the rule earns its keep here rather than costing something, because a record's value is
  that it is evidence of the reasoning at the time the decision was made. An in-place correction
  leaves a record that looks as though it was always right, with no trace of what was believed, who
  checked it, or when — and this project's subject is measurement honesty, so a quietly repaired
  rationale is the worst available outcome even when the repair is correct.
- **Leave the wording alone: the decision is right and no code reads the sentence.** Rejected,
  though it is the cheapest option and nothing breaks tomorrow. The cost is that the file which
  *is* the reason 137 scores `FAILED` contains a claim a careful reader can check against the code
  and find false. That reader has two exits, and both are bad: distrust the record, and with it the
  next one; or trust the record and conclude the summariser is the thing that is wrong.
- **Make the code match ADR-0028 — drop errored trials from the denominator.** Rejected outright,
  and it is named here because it is what the unamended text invites. It is the exact flattery
  ADR-0004 refused, and CLAUDE.md's measurement rules forbid: a tool that crashes often would climb
  by crashing, and `pass^n` would stop meaning "every trial of this task passed". The unamended
  sentence is the only thing in the directory that reads as authority for it, which is the sharpest
  reason not to leave it standing.
- **Record the correction in the M2 milestone report or a retro instead of an ADR.** Rejected: a
  reader arrives at 0028 through the index or through a citation in the code, not through a
  milestone document, so the correction has to live where the index can point at it from the row
  next to 0028's own.

## Consequences
**This record changes no code, no test and no scoring behaviour.** `assay.score.score_report`
returns `FAILED` for 137 before it and after it; `pass@1`, `pass^n`, the Wilson intervals and every
renderer are byte-for-byte unaffected. The only edits it lands are its own file, its row in the
index, and the ADR count the index test asserts.

The cost of amending rather than editing is a real one and is accepted with open eyes: **0028's
text does not know it has been amended.** A reader who opens that file directly reads both wrong
sentences with nothing beside them, and the only signpost is the `amends 0028` relation in the
index row here. That is the same contract 0019 already has with 0021 and 0025, so the directory is
consistent rather than newly compromised — but it means the index is load-bearing navigation, not
decoration, and a future reader who greps the ADR text alone will miss the relation.

**One echo of the withdrawn claim is named rather than fixed.** `score_report`'s docstring in
`assay.score.executable` carries the same sentence — that scoring the kill `ERRORED` would lift a
real failure out of the denominator — for the same reason 0028 did. It is a comment, it moves no
number, and correcting it is a source edit this record deliberately does not bundle into a change
whose entire claim is that nothing executable moves. It should be corrected to the legibility
reading when that function is next opened, and this record is the authority for the correction.

If a later milestone gives errored trials a count of their own — a field on `ToolSummary`, or a
per-trial reason in a run's provenance, both of which M3 and M4 are the place for — the distinction
between the two words becomes arithmetic as well as legible, and the ground under 0028 only gets
firmer. Nothing here forecloses that; it settles what the ground is today.
