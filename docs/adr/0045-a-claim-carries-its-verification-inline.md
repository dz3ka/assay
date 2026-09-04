# ADR-0045: A claim written into a brief carries its verification inline

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context

The `/ship` pipeline's Sub-agent hygiene section (`~/.claude/skills/ship/SKILL.md`) already carried
a rule against handing sub-agents unverified facts: *check every identifier, path, file:line and "X
pins this" claim against the tree before the brief goes out*. It was adopted after the first such
failure and has been in force ever since.

It has been violated four times across three retros, all of them after adoption:

- `2026-08-28-assay-m1-close-m2-start.md` — a design-reviewer brief asserted the stat grid was
  `.stats` (flex) when it is `.scores` (grid).
- `2026-09-01-assay-m2.md` — "171 candidates" was copied from a published milestone doc into a
  sub-agent brief; the true figure was 127.
- `2026-09-04-assay-m4.md` — a claim that a boundary was "structurally enforced by an AST dependency
  test" when no such test existed, plus a "892 passed" test figure that was never reconciled.

The pattern is consistent and it is not carelessness about *whether* to verify. The rule says to
check, and the orchestrator writing these briefs believed it had. What the prose form permits is a
claim that reads as verified — a specific number, a named mechanism — while carrying nothing that
says *how* anyone knows it. Once such a sentence is written down it is indistinguishable, to the
next reader and to its own author a session later, from one that was actually measured. The rule
had no artifact to check itself against.

The rule-of-three gate is met on repeat count. `2026-09-01-assay-m2.md` had already named the
intended escalation, twice, as moving "from prose to mechanical enforcement" on a third occurrence.

## Decision

Append to the same Sub-agent hygiene bullet a requirement that any quantitative claim, or any "X is
enforced/pinned by Y" claim, written into a sub-agent brief, a handoff, or `ship-status.json` must
carry its verification **inline, next to the claim** — the exact command or file:line that produced
it. A claim with no inline citation is unverified by definition, however confidently it reads, and
must be re-derived before use.

This is a format requirement, not a new obligation to verify. The obligation was already there; what
changes is that compliance is now visible on the face of the sentence.

## Alternatives considered

- **Leave it as prose and rely on the existing rule.** Rejected on the evidence: four violations of
  that exact rule, by the agent that had just read it. A rule with no observable output cannot be
  audited, not even by its author.
- **True mechanical enforcement — a hook that greps outgoing briefs for bare figures.** This is what
  the assay-m2 retro actually named, and it is not what was adopted; see Consequences. Rejected for
  now as unimplementable at acceptable cost: briefs are free prose passed in-process to sub-agents,
  with no chokepoint a hook can sit on, and a regex for "a number without a nearby backtick" would
  fire on nearly every line of ordinary English.
- **Require a verification appendix at the end of each brief.** Rejected: it separates the claim
  from its evidence, which is the same failure in a tidier layout. The whole point is adjacency —
  a reader must not have to cross-reference to see that a figure is naked.
- **Push the check onto the sub-agent — let it re-derive what it is told.** Rejected: it inverts the
  cost. One orchestrator citation is cheap; re-derivation by every recipient is not, and a sub-agent
  briefed with a false fact usually cannot tell that it should doubt it.

## Consequences

A brief, handoff or status file can now be audited for this failure without re-deriving anything —
a claim either shows its command or it does not, and that is visible at a glance. The cost is
verbosity in briefs, accepted as small against the cost of a sub-agent working from a false premise.

**This stops short of what the escalation called for, and the record should say so.** The assay-m2
retro asked for mechanical enforcement; this is a checkable format, which is a strictly weaker
remedy — it makes a violation *visible* but nothing rejects one. If a fifth occurrence lands under
this rule, the honest conclusion is that prose remedies have been exhausted for this failure class
and the next proposal must be a hook or a template with no free-text path, not a third rewording.

This edits the global kit only. It changes no Assay code, test, schema or milestone status; it is
recorded here per the adoption note in `~/agent-atlas/retros/2026-09-04-assay-m4.md`, so that the
decision trail stays legible from the repository whose retro produced it — the same reason
[ADR-0020](0020-the-wrap-phase-offers-the-retro-first.md) lives here.
