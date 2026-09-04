# ADR-0042: The README withdraws its promise of a live run, and M4 ships machinery only

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
The README's "What it does not do" section is the one part of this repository written to
understate. It is where a reader is told that no real tool has been scored, that the two adapters
which could call a model never have, and that the numbers printed today come from the two oracles
that bracket a result without being one — each limitation stated before a reader can discover it,
which is the only form of that sentence worth writing.

Two of its clauses were about the future rather than the present. One read **"The first live run
is M4's."** The other read **"The paired significance test and pass@1's bootstrap interval land in
M4."** Both were written at the close of M3, when the two real adapters had just been built and
container-tested and the only thing between this repository and a measured comparison was money.
Naming the next milestone was the natural way to say *not yet, but soon*, and at the time it was
an accurate forecast of the intent.

M4's scope was then set by a ruling that made the first clause false: **no paid live run, and no
model is called at any point in the milestone.** The statistics M4 owes SPEC §7 — a paired
significance test, a bootstrap interval on pass@1, cost per solved task — are validated against
hand-computed fixtures and against the free result sets the ground-truth and null adapters already
produce. That is a real milestone with real exit criteria, and it is not a live run. The milestone
the README named as the one that would finally call a model arrived, and called nothing.

This is a documentation edit and it is still worth a record, because of which document it is in.
The README is public from M0, and the repository's subject is telling a working AI feature apart
from a merely responding one; a paragraph overstating what has been measured is the project's own
failure mode printed on its front page. It is also a failure this project knows about elsewhere:
`docs/adr/README.md` forbids an ADR that reads as a capability the code does not have, because a
record is not a roadmap. The README carried no such rule, and the broken sentence is exactly the
shape that rule prevents — a future tense written once, graded by nobody, and read as a present
tense by everyone arriving after the milestone it names.

The second clause is a different case and does not need withdrawing. The paired test and the
bootstrap band did land in M4, as machinery. What that clause needs is a tense and a limit: what
landed is code with hand-checked fixtures behind it and not a number about any tool, and a reader
told a significance test "landed" will reasonably assume something was found significant.

## Decision
**The README states what has happened and what has not, and names no milestone as the owner of the
live run. The "first live run is M4's" claim is withdrawn in the README's own text rather than
deleted quietly, and the paired test and the bootstrap band are described in the past tense as
machinery, with the basis they were validated against named and the negative stated.**

The withdrawal is visible. The section now says that M4 did not change the standing fact that no
real tool has been scored, that this section used to say the first live run was M4's, and that no
milestone owns the live run. A reader who saw the old sentence and comes back can see it was
retired on purpose; a reader arriving today learns the same thing at the cost of one clause. A
silent deletion would leave those two readers holding different beliefs about the same repository,
which is the reason the correction is written down at all.

The rule this generalises is narrow, and it is the whole of what the record binds: **the README
makes no dated promise about a milestone that has not shipped.** A capability the code does not
have is described as absent, not as scheduled. SPEC.md §7 holds the milestone plan, where a
forward statement reads as one, and that is the right home for it. This does not forbid the README
from naming a milestone in the past tense — most of the document does — only from spending a
future one as though it had already been collected.

What replaces the second clause carries its own limit rather than borrowing the reader's trust:
the bootstrap band and the exact McNemar p are stated to have been validated against hand-computed
fixtures and the two oracles' free results, and stated never to have been computed over a run that
called a model. That is what a reader needs in order to price the milestone correctly, and it is
shorter than the misunderstanding it prevents.

## Alternatives considered
- **Re-date the promise: "the first live run is M5's."** The obvious edit, and rejected because it
  is the instrument that just failed with a new number in it. Nothing about M5 makes the money
  appear, no exit criterion anywhere grades the claim, and a second failure would teach a reader
  that this repository's forward statements are aspirations — retroactively discounting the ones
  meant literally. The defect is the promise, not the date on it.
- **Delete both sentences silently.** Rejected. The README is public from M0 and has been read in
  its promising form; a deletion with no trace is indistinguishable from never having overstated,
  and it asks a returning reader to doubt their own memory rather than the document. ADR-0035
  settled the general form of this for the report — an omission or an asymmetry is stated, never
  left silent — and a repository that applies that rule to its output but not to its README is
  applying it only where it is cheap.
- **Keep the sentence and call M4's fixture-and-oracle validation a live run.** Rejected, and the
  worst option on the table. It is the confident number nobody should trust, which CLAUDE.md names
  as worse than no harness at all, aimed here at the harness's own description of itself. The
  oracles are free precisely because nothing answers them.
- **Weaken it to "a live run is planned."** Rejected as the promise with the date filed off. It is
  still a claim about the future that no milestone grades, and "planned" invites a reader to price
  in a result that does not exist while committing the repository to nothing it has to deliver.
  The honest version of that sentence is the absence of the run, which the README now states.
- **Leave it until the live run happens, since the README will be rewritten then anyway.**
  Rejected because it makes the document's correctness contingent on an event that may never
  occur, and the window in which the statement is false is exactly the window in which the
  repository is being read by people deciding whether to trust it.
- **Add a roadmap section listing what each remaining milestone will contain.** Rejected as the
  same defect multiplied by the milestones left, and SPEC.md §7 already carries the milestone list
  where a reader expects a plan rather than a report.

## Consequences
**The README no longer contains a claim a milestone can falsify.** What it now says about the
future is the absence of the live run, and that stays true until the run happens — at which point
the README states a measured result, and this record needs no superseding, because what it forbids
is a promise rather than a report.

**A reader who wants to know when the live run happens gets no answer, and that is the intended
cost.** There is no answer to give. A date supplied for the reader's comfort is what this record
refuses, and the blank is doing the work: it is what the repository knows about its own schedule.

**M4's numbers are still the oracles'.** The bootstrap band and the McNemar p are real code with
hand-computed fixtures behind them, and no report in this repository has ever computed either over
a tool that called a model. The same statement is owed at greater length by M4's milestone record,
and this record is what makes it an obligation rather than a courtesy.

**The rule binds the milestones that follow.** A milestone that adds machinery says machinery in
the README, and a milestone that measures something says what it measured. The cheap edit at the
end of a milestone — the one nobody schedules, because it costs nothing and breaks no test — is
where a document like this decays, so the standard is written down where a reviewer finds it.

**Nothing here closes the underlying gap.** The repository still contains no naive-versus-agentic
comparison and no evidence that either adapter can solve a single mined task, and M4 leaves that
exactly where M3 did. This record makes the front page say so accurately; it does not make it say
less than the truth, which would be its own kind of dishonesty, and it is no substitute for the
run.
