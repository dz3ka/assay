# ADR-0006: Network is off inside a trial; dependencies are baked into the task image

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
A task is "these tests fail; make them pass". If the trial has a network, one of the tools under
evaluation will eventually `pip install` its way to a passing test — and one will. At that point
the eval is measuring a tool's ability to install its way out of the problem, which is a real
capability and not the one the report claims to be about.

There is a sharper version of the same risk. The tasks are mined from a repository's own history
(SPEC §3), so for any public repository the fix is upstream, in the very commit the task was
derived from. A tool with a network can fetch the answer. The gate that makes mined tasks
trustworthy does not survive contact with an open socket.

## Decision
Dependencies are installed once, when the task image is built. The trial itself runs with
networking disabled apart from an allowlisted model endpoint (SPEC §5.3), and that is one of the
non-negotiables in CLAUDE.md rather than a setting.

The mechanism is M2's: the sandbox and its network policy land there, and M2's exit criterion is
that the network is *provably* off during trials, asserted by a test that tries to reach it
(SPEC §7, §9). Nothing at M0 runs a trial, so this ADR is recorded now because it constrains what
M0 is allowed to build, not because M0 implements it.

What M0 already does to hold the line is a matter of what it left out. The `Adapter` protocol is
copied verbatim from SPEC §6 and gives an adapter three arguments — the task, a workspace path
and a budget — none of which is a place to request or configure network access. `Budget` caps
wall clock, tokens, tool calls and money, and carries no network field. So the policy is not the
adapter's to negotiate: an adapter that needed an exception would have to reopen this ADR rather
than pass a keyword argument. Neither M0 adapter opens a socket.

## Alternatives considered
- **Leave the network on and accept the noise.** Rejected: it silently changes what is being
  measured, and on a public repository it admits the ground-truth commit itself.
- **Leave it on, log the traffic, and discount runs that used it.** Rejected: the judgement of
  which request was legitimate is made after the fact by whoever reads the log, and "the tool
  fetched documentation" and "the tool fetched the fix" are the same HTTP request.
- **Disable everything, including the model endpoint.** Rejected: nearly every tool worth
  evaluating is a hosted model. An eval that can only score local models scores nothing anyone is
  currently buying.
- **Allow an install step inside the trial but outside the timer.** Rejected: the split is
  unenforceable. An agentic tool's first tool call is indistinguishable from setup, so the
  boundary would be drawn by the tool under test.
- **Rely on the task image having every dependency a tool might want.** Rejected: it is the same
  policy stated as a hope. Baking the *repository's* dependencies in is a bounded, checkable job;
  anticipating an agent's wants is not.

## Consequences
A task image must be built with the repository's dependencies pre-installed, so a repository
whose dependency install is not reproducible offline is harder to mine. That is a genuine cost
and it is paid deliberately — it also surfaces a fact about the repository worth knowing.

Any tool that needs a network-fetched auxiliary service cannot be evaluated in the shape M2
builds. That is a limitation to state in a report, not to work around.

Deferred: the allowlist itself. How the model endpoint is expressed, whether it is per-adapter,
and how egress is restricted are M2 design questions this ADR does not settle beyond "one
endpoint, allowlisted, and everything else refused".
