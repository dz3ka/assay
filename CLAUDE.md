# Assay — working agreement

Read `SPEC.md` first. It is the brief; this file is how to work on it.

## What this project is for

Assay is a portfolio-critical build. It exists to demonstrate that its author can tell whether
an AI feature is genuinely working rather than merely responding — the exact judgment a
forward-deployed engineer is hired for. The rigour *is* the deliverable. A harness that
produces a confident number nobody should trust is worse than no harness.

It is built in parallel with `dz3ka/portcall` and shares no code with it. If a change here
would require a change there, you have taken a wrong turn.

## Milestone discipline

- Work one milestone at a time, M0 → M5, in the order in SPEC.md §7.
- A milestone is done when its exit criteria pass and CI is green.
- Do not start the next milestone with the previous one red or partially landed.
- Never mark a milestone complete with skipped tests or a TODO in a code path.

## Architecture decision records

Every non-obvious decision gets an ADR in `docs/adr/NNNN-title.md`, numbered sequentially,
following the format used in `dz3ka/bosun` and `dz3ka/tollgate`. Write it when the decision is
made, not retroactively — context, decision, rejected alternatives, and why.

SPEC.md §8 lists seven decisions that need writing up as ADRs 0001–0007 during M0.

## Non-negotiables

These come from SPEC.md §5 and are not to be relaxed for convenience:

- The repository under evaluation never leaves the machine. No upload, no telemetry.
- Model-generated code only ever runs inside the sandbox, never on the host.
- Networking is disabled inside a trial except for an allowlisted model endpoint. Dependencies
  are installed when the task image is built, not during the trial.
- Reports are redacted by default.
- Suites are content-addressed, so any result can be reproduced.

If a feature seems to require breaking one of these, it is out of scope — say so rather than
working around it.

## Measurement rules

This is where the project is won or lost. These are enforced in code, not left to discipline:

- **Rank only on executable signal.** Tests passing, no regression, build clean. Judges inform
  the report; they never move the ranking.
- **Every mined task passes the red→green gate** — tests provably fail at the base state and
  provably pass once the ground-truth diff is applied. A task that cannot demonstrate both is
  discarded, and the discard is counted.
- **Report yield, not just totals.** "1,847 commits examined → 213 valid tasks" is the honest
  form. Never report the task count alone.
- **n trials per task per tool**, default 5. Report pass@1 *and* pass^n. pass^n leads.
- **Wilson intervals on every proportion.** Never the normal approximation.
- **The report renderer refuses to declare a winner when intervals overlap.** This is a code
  path with a test, not an editorial habit.
- **Always include the naive baseline adapter** in every report — one raw model call, no agent
  loop. If the sophisticated tool cannot beat it, that is the finding.
- Never let a judge from the same model family as a tool under test grade it without flagging
  it in the output.

## Code conventions

- Python 3.12+, `uv` for dependency and environment management.
- Full type annotations; `mypy --strict` in CI. No bare `Any` in committed code.
- Mining, validation and scoring are pure functions over explicit inputs. All I/O — git,
  containers, model APIs — lives behind adapters so the logic is fixture-testable.
- Statistics functions are tested against hand-computed known values, not against themselves.
- Task and result schemas are versioned from M0. Once public, treat them as API.

## Testing

- The fixture git repository (SPEC.md §9) is a first-class deliverable. Build it in M1 and
  keep the expected-yield assertion exact — if the miner's yield changes, that is a
  deliberate decision with an ADR, not a test to update.
- Sandbox tests must assert the negative cases: no network, no writes outside the workspace,
  killed at the resource limit.
- End-to-end must include the ground-truth adapter (perfect score) and a null adapter (zero).
  Those two bracket every real result.

## Public from the start

The repo is public from M0. Write commit messages that explain *why*, in the style used in
`dz3ka/bosun`.

The README states what Assay does not do: it is not a public leaderboard, it does not compete
with SWE-bench, and its numbers are only meaningful for the repository they were mined from.
Understating is fine; overstating is fatal for a project whose entire subject is measurement
honesty.
