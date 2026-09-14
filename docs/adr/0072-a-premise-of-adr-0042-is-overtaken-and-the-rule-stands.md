# ADR-0072: Two premises of ADR-0042 are overtaken by the local baseline's run, and its rule stands

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0042](0042-the-readme-withdraws-the-promise-of-a-live-run.md) corrected the README's "What
it does not do" section at the close of M4. It withdrew the sentence "The first live run is M4's",
and it bound one narrow rule: **the README makes no dated promise about a milestone that has not
shipped** (`0042:55-60`). That rule is right, the README still keeps it, and this record does not
move it. What this record is about is two statements of fact the rule was argued alongside, both
true when 0042 was written and both false since 2026-09-11.

**The first is in 0042's Context** (`0042:8-12`): the section is where a reader is told "that the
numbers printed today come from the two oracles that bracket a result without being one". **The
second is in its Decision** (`0042:62-66`): the bootstrap band and the exact McNemar p are "stated
never to have been computed over a run that called a model".

**A run that no milestone owns has since called one.**
[`local-model-live-run.md`](../milestones/local-model-live-run.md) §4 records it, and every figure
here is quoted from that section rather than re-derived. It recorded **165 trials — 11 tasks × 3
adapters × 5 trials** (`local-model-live-run.md:329`): `ground-truth`, `null`, and `naive-local`,
the naive baseline pointed at a model served by a daemon on this machine, one raw model call per
trial and no agent loop. The report's coverage line reads **"11 of 13 tasks measured; 2 could not be
provisioned"** (`:363`). The local baseline passed **0 of 55 trials, pass@1 = 0.000, pass^n =
0.000** (`:381`), and the renderer named `ground-truth` over each of the other two with **exact
McNemar p = 0.0010** printed beside it (`:406`) — one of those two comparisons is over an adapter
that called a model.

So the numbers this repository prints now come from three adapters rather than two oracles, and
the band and the p have both been computed over a run in which a model was called. Neither of
0042's two statements can be read as true of the tree.

**The README was corrected the same day, and the correction had no record behind it.** Its limits
section now opens "No real tool has been scored yet — a baseline has." (`README.md:147`), and a few
lines below it retires what 0042 said beside its withdrawal. That edit also reached
[ADR-0055](0055-the-readme-is-a-release-document-not-a-changelog.md), which enumerates what the
README keeps. Clause 1 has the status block name the published results as the two oracles
(`0055:53-58`); the README now says "the two oracles and one local baseline" (`README.md:22`).
Clause 2 keeps "no real tool has been scored, by any milestone including this one" (`0055:60-66`);
the README now states a baseline has been scored beside it. An enumerated clause of an accepted
record, narrowed on the front page with nothing written down, is the silent edit 0042 itself
refused (`0042:74-79`).

**What the run did not change matters as much, because each survival sits next to a retired
sentence and will otherwise read as an oversight.** The run names no tool: under
[ADR-0060](0060-the-local-baseline-is-exempt-and-does-not-discharge-the-rule.md) `naive-local` is
exempt from being asked for a baseline and does not supply one, and the refusal that enforces it is
`if named - ORACLE_ADAPTERS - {LOCAL_NAME} and NAIVE_NAME not in named:` at
`src/assay/cli/main.py:921`. The metered naive adapter and the agentic Claude Code adapter still
have never called a model (`README.md:154-157`). And no milestone owned the run.

## Decision
**This record amends ADR-0042 and ADR-0055; it supersedes neither. Both keep Status `Accepted`,
neither file is edited, and 0042's decision is unchanged:** the README makes no dated promise about a
milestone that has not shipped, and no milestone owns the live run.

**Two statements of 0042 are overtaken and may not be relied on as written.**

- **`0042:8-12`, "the numbers printed today come from the two oracles".** The form that survives is
  the one the README now carries: the results this repository publishes are the two oracles and one
  local baseline, and no number printed describes a tool.
- **`0042:62-66`, the band and the p "never … computed over a run that called a model".** Retired
  outright. The form that survives is 0042's own Consequences at `0042:106-109`: no report in this
  repository has ever computed either over a *tool* that called a model.

**That second survival is deliberate, and its reason is ADR-0060.** The retired sentence and the
surviving one are nearly the same words, and the difference is one noun: `:62-66` says *a run*,
`:106-109` says *a tool*. The p at `local-model-live-run.md:406` was computed on a run in which
`naive-local` called a model, which retires the first. `naive-local` is not a tool, which keeps the
second. A reader who finds one retired and its neighbour standing is reading the line 0060 draws.

**ADR-0055's clause heads stand; what is amended is the content under two of them.** The status
block still names the milestone and the shape of the published results and nothing else — the shape
is now three adapters. The block's other half, that no model has been called in any milestone, is
still literally true, since no milestone owns the run; the README replaces it with the wider true
statement that a model has now been called. "What it does not do" still keeps that no real tool has been scored, and that
clause is still literally true; what the README adds beside it is that a baseline has been.
[ADR-0061](0061-the-local-baseline-is-the-substitute-adr-0051-rejected.md) is what lets a local
baseline appear among published results at all, named on every attempt and every row, so this
amendment applies it rather than widening what may be claimed.

**The overtaken paragraphs are left standing rather than rewritten.** They were correct on the
evidence of their day, and a record whose value is evidence of the reasoning at the time cannot be
edited into hindsight without destroying the thing it is for — the reason
[ADR-0054](0054-a-premise-of-adr-0050-is-overtaken-and-the-decision-stands.md) gave for 0050.

**This record binds no new general rule.** It settles what two sentences may still be read as, and
nothing else.

## Alternatives considered
- **Supersede ADR-0042.** Rejected. 0042 anticipated this moment in its own Consequences: when the
  run happens the README states a measured result, "and this record needs no superseding, because
  what it forbids is a promise rather than a report" (`0042:97-100`). The rule is alive and the
  README obeys it; `Superseded` in the index would point a reader away from the record that still
  governs the section.
- **Do nothing, on the strength of that same sentence.** Rejected. `0042:97-100` pre-authorises not
  superseding for the promise clause; it says nothing about 0042's statements of fact going false,
  which is a different failure with its own precedent — 0054, indexed `amends 0050`. And ADR-0055's
  clauses were narrowed on the front page with no record behind it, in a repository whose subject is
  measurement honesty.
- **Write a dated `> **Amended**` blockquote into 0042's own file, citing ADR-0059 as precedent.**
  Rejected. 0059 is a record amended by its own author inside the goal that had not yet shipped it,
  which is no licence for a later record to edit a shipped one. No third-party amendment here has
  taken that route: `grep -c '^> \*\*Amended'` over all ten records later ADRs amend (0018, 0019,
  0021, 0025, 0028, 0035, 0050, 0051, 0053 and 0062) returns 0 for each. The convention is named in
  `tests/docs/test_adr_index.py:320` — "not edited, on the immutability pattern 0054 and 0061 set"
  — and the carrier is the index row, in the form 0035's row already uses: `amended by 0043`.
- **Delete or rewrite the two sentences in 0042.** Rejected as the exact harm 0042 rejected at
  `0042:74-79`: a correction with no trace asks a returning reader to doubt their memory rather than
  the document.
- **Bind a standing rule: a run no milestone owns still gets a record of its own, and the README's
  limits section narrows only to the exact width of what ran.** Deferred, not adopted. It was argued
  on the ground that ADR-0066's provisioning work would be the next run no milestone owns, and
  [ADR-0066](0066-the-provisioning-asymmetry-gets-a-milestone-not-a-deferral.md) says the opposite
  at `0066:106`: "It is a milestone, not a work package." 0042's milestone-shaped rule reaches it by
  construction. The rule's second half is already bound twice, by 0055's clause 2 and by
  [ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md)'s general form, that an omission
  is stated rather than left silent. **The trigger to revisit is the first actual run no milestone
  owns that 0042's rule demonstrably fails to reach** — not a run anticipated to.
- **Record the correction in `local-model-live-run.md` only.** Rejected for the reason 0054 gave:
  a reader reaches 0042 through the index or the README's link, not through a record of a run, so
  the correction has to live where the index can point at it from the row beside 0042's own.

## Consequences
**This record changes no code and no behaviour.** It lands its own file, its index row, a ` ·
amended by 0072` on 0042's index row, the ADR count the index test asserts, one citation in
`local-model-live-run.md`, and one narrowed clause in the README where it described what 0042 had
said.

**0042's text does not know it has been amended, and that cost is accepted.** A reader who opens
the file directly reads both overtaken sentences with nothing beside them. The index is the
signpost, and here it is marked from both sides, as 0035's row is. **0055's row is left alone**:
its clause heads survive, and the amendment of their content lives in this text. A reader who opens
0055 directly finds no pointer here, which is the same contract 0050 has with 0054.

**Nothing here closes the underlying gap.** The repository still contains no naive-versus-agentic
comparison and no evidence the agentic adapter can solve a mined task, and `0042:116-120` stands
exactly as written. The metered and agentic adapters are where they were when 0042 was accepted.

**The run's figures are cited for what they overtake, not promoted into a result.** 0 of 55 over
11 tasks mined from one repository, at n=5, is a finding about one small model served on this one
machine, and `local-model-live-run.md` §4 carries its limits in its own words. Nothing in this
record widens it, and the p it quotes compares a baseline with its bracket, never two tools.

**The deferred rule is named with its trigger so it is not carried as an open question.** Until a
run arrives that no milestone owns and 0042's rule fails to reach, there is nothing for it to
govern, and a rule written for a case that has not happened is the forward statement 0042 exists
to keep off the page.
