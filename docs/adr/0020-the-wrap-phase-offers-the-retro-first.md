# ADR-0020: The wrap phase offers the retro first, not last

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context

The `/ship` pipeline's Phase 7 (`~/.claude/skills/ship/SKILL.md`) listed its wrap steps in this
order: Summary, Decision records, Map upkeep, Docs, Git, Retro. The retro bullet sat last.

The kit already knew that a retro run from a cleared thread is degraded — it loses first-hand
visibility into user redirections, tool friction, and sub-agent report-contract violations. Three
prior retros (`bosun-m3a-finalizers-teardown`, `m2-core-runner-closeout`, `m3b-push-and-pr`) paid
that cost, and the adopted fix was the clause "if the offer is accepted, run it now, in this
thread, before `/clear`." That fix assumes the retro bullet is *reached*.

M1 of this repository showed the second route to the identical cost. Across eleven sessions the
context guard fired inside the wrap chain every single time before execution got to the last
bullet, so the retro was deferred six consecutive times. M1's retro therefore exists only as
`~/agent-atlas/retros/2026-08-28-assay-m1.md`, a goal-level document reconstructed from the
handoff chain's own ledgers rather than from any live transcript — its provenance caveat says so
in the header. This was not a budget failure: the guard record for the goal shows two warns, one
clean at-budget stop, and zero hard trips. The budget discipline worked; the ordering defeated it.

Nothing in the four intervening steps gates retro eligibility. The eligibility triggers — more
than one review round, an implementer deviation report, an absorbed report-contract violation, a
forced mid-goal handoff — are all knowable the moment the Summary is written. Placing the cheapest
step behind four expensive ones made it the guaranteed casualty of any wrap phase that ran out of
budget.

## Decision

Move the Retro bullet in Phase 7 to immediately follow the Summary bullet, ahead of Decision
records, Map upkeep, Docs and Git, and prepend an imperative to it stating that the evaluation
happens there, why none of the later steps gate it, and what the old ordering cost.

The bullet's existing text is otherwise unchanged, including the run-before-`/clear` clause from
the earlier fix — the two remedies address different triggers of the same cost and both stand.

## Alternatives considered

- **Leave the order and rely on the budget discipline to reach the last bullet.** Rejected on the
  evidence: six consecutive attempts under a guard regime that was itself working correctly. A
  rule that is never executed is not a rule.
- **Auto-run the retro instead of offering it.** Rejected: it contradicts the standing "offer it,
  don't auto-run it" position, and a clean run genuinely needs no retro. The defect was placement,
  not the choice to ask.
- **Keep the retro last but exempt it from the context budget.** Rejected as incoherent — a retro
  is a full sub-agent pass over the session, the single most expensive wrap step. Exempting it
  from the budget would breach the ceiling the guard exists to hold.
- **Move the whole retro decision to Phase 0 of the next goal.** Rejected: it inverts the same
  failure. The next goal's opening session has no first-hand account of the previous one either,
  which is precisely the fidelity the reconstruction already lost.

## Consequences

A wrap phase that exhausts its budget now loses ADRs, map upkeep or docs — all of which are
recoverable from the tree by a later session — instead of the retro, which is not recoverable
once the thread is gone. That trade is deliberate: the discarded steps read state that still
exists, while the retro reads state that only exists in the live transcript.

The steps that now come after the retro are the ones a resuming session can pick up from a
handoff, so a mid-wrap stop stays cheap. The edited file lives outside this repository; this ADR
exists per the retro's adoption note, so the decision trail is legible from here even though the
change is in the global kit. It changes no Assay code, test or milestone status — M1 was verified
green before this was written.
