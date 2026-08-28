# ADR-0013: Mining runs the target repository on the host, and M1 accepts the exposure

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Bogdan Dzekic

## Context
Proving a commit red at its parent and green at itself means running that repository's tests, and
there is no version of the product that does not. M1 runs them **on the host**: a throwaway git
worktree, an ephemeral `.venv` beside it, and the invoking user's own account. The container SPEC
§5.2 requires is M2's, and the sequencing was settled when M1 was scoped — this record is not
re-opening it.

What was never written down is what the choice costs while it stands. Assay's subject is
measurement honesty, and a posture a user can only discover by reading `src/` is not one they
were told.

The exposure is concrete. [`provision_venv`](../../src/assay/host/venv.py) runs `uv venv` and then
`uv pip install -e .` **inside the untrusted worktree**, so a `setup.py` or a PEP 517 build backend
executes as the invoking user before a single test has been selected. Three mitigations are real
and are enforced rather than intended: [`assay.host.process`](../../src/assay/host/process.py)
starts every child without a shell, without the ambient environment
([`minimal_env`](../../src/assay/host/process.py), so the developer's model API keys are dropped),
under a timeout that kills the whole process group; and a test asserts that no module outside
`assay.host` imports `subprocess`.

Two holes are open by construction, and both were checked against the tree rather than assumed:

- `HOME` and `USERPROFILE` are on the allowlist ([`host/process.py:42-52`](../../src/assay/host/process.py))
  because git needs a user identity to commit at all. A build hook can therefore read `~/.ssh`
  and `~/.aws`.
- uv needs the network on a cold cache ([`host/venv.py:20-23`](../../src/assay/host/venv.py)
  records the measurement: `--offline` succeeds only once the wheels are cached). So the hook has
  a channel out as well as something to send - and **nothing in M1 restricts a child's network at
  any point**, so priming the cache narrows nothing. `minimal_env` filters variables, not sockets.

## Decision
M1 mines on the host, the residual risk above is **accepted**, and the surface says so before it
runs anything: a stderr banner from both commands that execute target code, and one sentence
carried verbatim in the README and in `assay mine --help` (`HOST_EXECUTION_SENTENCE`,
[`cli/main.py:133`](../../src/assay/cli/main.py)). The threat model M1 claims is therefore narrow
and stated: *a repository you would already run locally*.

It is a statement, not a gate. There is no `--yes` flag and no prompt.

## Alternatives considered
- **Bring M2's container forward.** Rejected: it makes M1 a container milestone. Nothing about the
  gate rule — the part that is actually novel — would be proved sooner, and the milestone
  discipline in CLAUDE.md exists to stop exactly this trade.
- **Skip the editable install and run the target's tests on Assay's own interpreter.** Rejected:
  the measurement would become a property of Assay's lockfile rather than of the repository being
  mined, which is the reason `venv.py` exists at all.
- **Drop `HOME`/`USERPROFILE` from the allowlist.** Rejected because it defends nothing while
  reading as a defence: on POSIX a hook recovers the home directory from the password database
  (`pwd.getpwuid`), so the paths stay reachable, and git loses its identity in exchange.
- **Scan the target's build hooks before running them.** Rejected: deciding what arbitrary Python
  does is not a static question, and a scanner that passes a hostile hook is worse than no scanner
  because the banner would then be a reassurance.
- **Prompt for confirmation.** Rejected: a prompt nobody can answer breaks the scripted use this
  surface exists for, and the host/container decision is settled rather than the user's to make.

## Consequences
A hostile target repository can read the invoking user's secrets during `assay mine` and send them
somewhere. Nothing in M1 prevents it, no test asserts otherwise, and this record is where that is
admitted rather than a footnote nobody wrote.

The banner and the sentence are M2's deletion trigger: when the container lands, the wording
changes in the same commit that changes the posture. `HOST_EXECUTION_SENTENCE` is spelled once and
pinned in the README by a drift test (`tests/docs/test_readme.py`) — [ADR-0012](0012-the-task-id-pattern-is-spelled-twice.md)'s
device, for the same reason — so the two documents cannot disagree about what Assay just did to
your machine.
