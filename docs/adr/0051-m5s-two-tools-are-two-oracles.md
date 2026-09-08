# ADR-0051: M5's "two tools" are two oracles, and the record says so before it prints a number

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
SPEC §7 grades M5 on four things: an HTML report, a README, a one-command demo, and **"published
results for two tools with intervals"**. The first three are code and prose that either exist or
do not. The fourth is a claim about what was measured, and it is the only exit criterion in the
project that money can block.

**Nothing in this repository has ever called a model.** That is not a new discovery; it is the
standing fact three milestone records already carry.
[`m3-oracle-run.md`](../milestones/m3-oracle-run.md) §2 says the naive baseline and the agentic
adapter are built, unit-tested against fakes, container-tested and never measured live.
[`m4-paired-statistics-and-cost.md`](../milestones/m4-paired-statistics-and-cost.md) §2 says M4
changed not one word of that. [ADR-0042](0042-the-readme-withdraws-the-promise-of-a-live-run.md)
withdrew the README's "the first live run is M4's" rather than re-dating it, and established that
**no milestone owns the live run.** M5's own scope ruling cut the paid run a third time. So the
question M5 has to answer is not whether to do the live run — that is settled and is not an
implementer's call — but **what a release is allowed to say when the exit criterion names two
tools and the run had none.**

**What the run does have is two oracles, and they are not nothing.** `ground-truth` replays the
recorded fix; `null` does nothing at all. Both go through the same path a real tool would take —
worktree, test-patch application, image build, container, test run, junit parse — so the outcomes
they produce are genuine executable signal, which is the only signal
[ADR-0003](0003-rank-only-on-executable-signal.md) permits a ranking to read. `_adapter_refusal`
(`src/assay/cli/main.py`) exempts exactly this pair from the naive-baseline requirement, and its
docstring gives the reason: the oracles answer from the task itself, so a run of the pair measures
the harness and has nothing to compare a baseline against. **This is a designed path, not a
workaround, and no code was changed to make the release run legal.**

**But CLAUDE.md is explicit about what the pair is for**: "End-to-end must include the ground-truth
adapter (perfect score) and a null adapter (zero). Those two bracket every real result." A bracket
is defined by not being a member of the set it bounds. Ground truth cannot fail and null cannot
pass, so neither one is evidence about any tool, and two adapters that between them can only
produce 1.000 and 0.000 are not a comparison however many intervals are printed beside them.

**The failure mode is specific and this project has already caught itself in it once.** Publishing
"results for two tools with intervals" and letting the exit criterion tick is ADR-0042's defect
with a new date on it: a sentence that is technically defensible, read by everyone arriving later
as the thing it resembles. The reader who is going to be misled is the one who sees a table of
pass^n figures with Wilson bands and a verdict line. By the time they reach a caveat below it,
they have already priced the repository. [ADR-0050](0050-the-demo-runs-against-the-fixture-and-says-so-first.md)
settled the same problem for the demo by putting `FIXTURE_NOTICE` on stderr before the first
subprocess starts; the milestone record inherits the problem and needs the same answer.

## Decision
**M5 publishes the two oracles' results, names them oracles, and states that no real tool has been
scored — in that order, with the disclosure before the first figure.**

**The exit criterion is recorded as met in letter and short in substance, and both halves are
written down.** Two adapters ran, five trials per task per adapter, two Wilson bands, a bootstrap
band on pass@1, an exact McNemar p, and a verdict produced by `decide_verdict` from those bands
alone. That is the machinery SPEC §7 asks for and it is fully exercised. What it is not is a
measurement of two tools, and `docs/milestones/m5-public-release.md` says so in its own words
rather than leaving the word "tools" to carry an implication the run cannot support.

**Ordering is the substance of this decision, not its presentation.** The milestone record's §2 —
what this milestone does NOT establish — sits above §3, the numbers. Any release surface that
prints these figures carries the same ordering: the frame travels with the output, because the
output is what gets quoted away from the document. This is [ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md)'s
rule about the interval caption applied one level up, and ADR-0050's `FIXTURE_NOTICE` ordering
applied to prose.

**The bracket is published as a bracket, and that is a real finding.** Ground truth perfect on
every trial of every task and null zero on every trial of every task is the strongest available
evidence that the scoring path measures what it claims to: the same code returns 1.000 for a diff
known to work and 0.000 for no diff at all. What it says about Claude Code, or about any tool, is
exactly nothing, and the record says exactly that.

**This extends ADR-0042 from the README to every published surface.** ADR-0042 bound the front
page: no dated promise about a milestone that has not shipped. The rule this record adds is its
mirror for results rather than plans — **a published number is described by what produced it, and
where the thing that produced it is not what the criterion names, the record says so before the
number rather than after it.**

## Alternatives considered
- **Call the two oracles tools and let the criterion tick.** Rejected, and it is the worst option
  on the table for the same reason ADR-0042 gave: it is the confident number nobody should trust,
  which CLAUDE.md names as worse than no harness at all, aimed at the release's description of
  itself. It also costs the one thing the oracles genuinely buy — a reader who believes the
  bracket is a comparison cannot use it as a bracket.
- **Print the numbers first and put the disclosure below them.** Rejected. The figures are what
  gets pasted into a chat window or a screenshot, and a caveat that arrives after the reader has
  formed a belief is doing the work of a footnote rather than a frame. The demo already decided
  this the other way for its own output, and a record whose ordering contradicts the script it
  documents is worse than either ordering chosen consistently.
- **Declare M5's fourth exit criterion unmet and hold the milestone open.** Rejected as an
  overstatement in the opposite direction. The machinery SPEC §7 grades is built, exercised end to
  end, and produced a real result set on real executable signal; saying it did not work would be
  as false as saying it measured two tools. It would also leave the milestone blocked on money
  rather than on code, with no work any implementer could do to close it.
- **Amend SPEC §7 to say "two adapters" instead of "two tools".** Rejected. Editing the criterion
  to match what was achieved is grading your own homework, and it would erase the gap this record
  exists to preserve. SPEC is the brief; the honest move is to leave the brief alone and record
  the shortfall against it.
- **Publish no results at all in M5, and ship the release as machinery only.** Rejected: the
  oracles' bracket is evidence about the harness and the harness is what M5 releases. Withholding
  a real measurement to avoid it being misread is understating past the point where the document
  informs anybody — and it would delete the one result that proves the scoring path is not a
  simulation.
- **Substitute a free or locally hosted model so that something answers a prompt.** Rejected: it
  changes what was measured without changing what may be claimed. The in-container allowlist
  targets `api.anthropic.com` and has never been exercised against it, `naive.py`'s cost path
  records what an API reported and would be recording something else, and a headline number
  produced by an unnamed substitute is a worse artefact than the absence of one.
- **Fold this into the README's release wording and write no record.** Rejected: this is the
  decision M5 will be judged on, and CLAUDE.md requires the record be written when the decision is
  made. A rule that lives only in one paragraph of one document is a rule that survives exactly
  until that paragraph is rewritten.

## Consequences
**Every number Assay publishes at M5 is about Assay.** The repository contains no
naive-versus-agentic comparison, no evidence that either adapter can solve a single mined task,
and no priced spend. That is the third consecutive milestone to say so, and saying it a third time
is the point rather than a repetition to be trimmed.

**A reader who wants to know which coding tool is better gets no answer from this release.** That
is the intended cost. The answer does not exist here, and supplying a shape that resembles one is
what this record refuses.

**The ordering rule binds the release surface, not just this document.** The README's results
wording, and any future page that prints a pass^n table, states what produced the figures above
the figures. That is a standard a reviewer can check by reading top to bottom.

**This record is not superseded by the live run when it happens.** What it forbids is publishing a
bracket as a comparison; a milestone that actually measures two tools satisfies it by describing
what it measured. The disclosure shrinks to a sentence about what the oracles are for, and the
oracles keep the job they were built for — bounding whatever the tools do.

**The exit criterion's shortfall stays visible in writing rather than in a reviewer's memory.**
`docs/milestones/m5-public-release.md` §2 is where it lives, and it is load-bearing: an edit that
trims it for length is an edit that changes what the release claims.
