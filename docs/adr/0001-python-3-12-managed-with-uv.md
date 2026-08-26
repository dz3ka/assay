# ADR-0001: Assay is Python 3.12 managed with `uv`, not TypeScript

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
Assay is built in parallel with `dz3ka/portcall` and shares no code and no language with it, on
purpose (SPEC §12). Portcall is a single-shot diagnostic binary handed to a stranger's security
team, and that packaging constraint is what drove it to a compiled language. Assay is the
opposite shape: a long-running lab harness, run by the person who already owns the repository
it is measuring. Nobody has to be persuaded to install it.

What Assay does need is arithmetic that has to be right and has to be recognisable: Wilson score
intervals, McNemar's test, a paired bootstrap, Krippendorff's alpha (SPEC §4). That ecosystem is
Python-native, and the credibility of the whole project rests on those numbers rather than on
how the tool is delivered. The portfolio argument runs the same way — the pair covers the two
halves of the language split deliberately.

## Decision
Python, floor 3.12, with `uv` owning the interpreter, the dependency set and the lockfile.
`.python-version` pins 3.12, `pyproject.toml` declares `requires-python = ">=3.12"`, `uv.lock` is
committed, and CI installs with `uv sync --frozen --dev`. Local and CI checks run one target and
the same one — `uv run --frozen python scripts/verify.py` — which lints, format-checks,
type-checks under `mypy --strict` and runs the tests, in that order, stopping at the first
failure. Keeping it a single script is what stops the two from drifting apart.

## Alternatives considered
- **TypeScript.** Rejected: it is Portcall's language, and building two of the same thing teaches
  half as much (SPEC §12). The statistics would be hand-rolled or pulled from thinly maintained
  packages, in the one part of the codebase whose correctness is the deliverable.
- **Go or Rust.** Rejected: both buy the single-binary distribution property Assay has no use
  for, and pay for it with the same statistics gap. They would also make both projects compiled,
  collapsing the pairing the two repos exist to demonstrate.
- **A 3.11-or-older floor, for wider reach.** Rejected: PEP 695 `type` aliases are used
  throughout (`assay.core.canonical`, `assay.core.versioning`, `assay.results.models`) and are
  3.12 syntax. The floor is load-bearing, not aspirational.
- **`pip` + `venv` + `requirements.txt`, or Poetry.** Rejected: neither gives a single tool that
  resolves the interpreter *and* the dependency set from one lockfile, and `--frozen` is what
  makes "CI ran what I ran" checkable rather than hoped for.
- **No `.python-version`, floating on `>=3.12`.** Rejected: `>=` is a compatibility claim about
  what should work, not a statement of what the build environment is. Without the pin, CI moves
  onto a new interpreter the day one ships, and a failure there is indistinguishable from a code
  regression.

## Consequences
A contributor needs `uv` installed and nothing else; the interpreter comes with it. Every check
has exactly one entry point, so "green" means the same thing in a terminal and in a workflow.

The floor is a commitment: dropping to 3.11 later would mean rewriting every `type` alias, so
this is the version the project starts old on rather than the one it happens to be new on.

Deferred, not decided here: how Assay is distributed. The `assay` console script is declared in
`pyproject.toml` and resolves to `assay.cli.main:main`, but nothing is published to PyPI and no
wheel is built in CI. Publication is an M5 question (SPEC §7) and gets its own ADR if the answer
is anything other than "a plain wheel".
