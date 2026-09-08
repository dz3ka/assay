# ADR-0050: The demo runs against the synthetic fixture repository, and says so first

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
M5 makes the repository something a stranger clones. The README's first instruction is going to be
a command, and whatever that command does is the impression Assay makes before anybody reads a
word of SPEC. The question this ADR answers is not how to write the script; it is **what the
script is allowed to point at.**

**Pointing it at real software does not work, and that is measured rather than assumed.** M1 mined
httpie: 743 commits examined, 0 valid tasks
([`m1-yield-httpie.md`](../milestones/m1-yield-httpie.md)). M2 re-mined it against pinned images:
40 commits, 3 candidates at the gate, 0 valid tasks
([`m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md)). Both are honest findings
about httpie and both are recorded as such. Neither is a demonstration. A first command that
prints an empty suite teaches a reader that the tool does not work, when what it actually showed
is that one repository's history does not carry provable red→green commits — a distinction the
reader has no way to make on their first minute.

**The fixture is the one target whose answer is known in advance.** `tests/fixture_repo.py` builds
a history written so each of the miner's verdicts fires exactly once: 11 commits examined, 7
candidates, 2 accepted, one witness under every rejection reason. CLAUDE.md already calls it a
first-class deliverable and forbids adjusting its expected yield to match a changed miner, so it
is the only target in the project whose numbers are a *specification* rather than an observation.
M3's oracle run used it for the same reason ([`m3-oracle-run.md`](../milestones/m3-oracle-run.md)).

**But a fixture is exactly the thing a demonstration can lie with.** Two tasks, a ground-truth
adapter at 100% and a null adapter at 0%: those are the numbers, and they are numbers about this
harness. A reader shown them without a frame will read them as an evaluation of software, which is
the failure mode this whole project exists to refuse (SPEC §5, CLAUDE.md's measurement rules), and
the specific mistake ADR-0042 caught the README making about a live run that had not happened.

**Where the demo can live is constrained, not chosen.** `src/` may not import `tests/`: the wheel
ships `src/assay` alone (`pyproject.toml`'s hatch target), so an `assay demo` subcommand could not
reach `build_fixture_repo` in an installed environment. SPEC §6 also fixes the command surface at
four, and ADR-0047 has just decided that the surface is what M5 freezes rather than what it grows.

## Decision
**One script, `scripts/demo.py`, against SPEC §9's fixture repository, with the frame printed
before the first subprocess starts.**

**It is a script and not a fifth subcommand.** `scripts/` is repository furniture, not shipped
surface, and it is the only place in the tree that may depend on both `assay` and `tests`. It is
shaped like `scripts/verify.py` — module docstring, `ROOT`, steps as argv tuples run through
`sys.executable` — because a reader who has met one has met the other.

**`FIXTURE_NOTICE` goes to stderr before anything runs, and it states rather than asks.** It names
the target as synthetic, gives the yield as a yield, cites both httpie runs with their real
numbers, and says that both adapters are oracles so nothing is spent. There is no prompt and no
`--yes`, which is the choice `HOST_EXECUTION_NOTICE` already made
([ADR-0013](0013-mining-runs-on-the-host-in-m1.md)): a confirmation nobody can answer breaks
scripted use, and what is being disclosed is a fact about the run rather than a decision the
reader is being asked to take.

**Five steps, SPEC §6's four commands in SPEC §6's order**, with `report` run twice so the demo's
artefact is the page in both prose formats. `demo_steps` is a pure function returning the argvs,
so `tests/cli/test_demo_steps.py` can put each of them through `build_parser()` without Docker.

**Zero flags.** Nothing about the run is the caller's to choose, because every choice would be a
way to get a different number out of a demonstration.

**The two values that could drift are read from `assay.cli.main` rather than typed:** the adapter
names come from `ORACLE_ADAPTERS` and the trial count from `DEFAULT_TRIALS`. `--trials` matters
most — the n in every `pass^n` caption is read against it, so a literal `5` here would keep
printing 5 after the house default moved. `--test-timeout-s 120` *is* a literal, deliberately: it
is a demo-local narrowing of `DEFAULT_TEST_TIMEOUT_S`, chosen to match M3's run.

**The rendered documents land in `build/demo/`**, which `.gitignore` already covers. `assay report`
writes to stdout and gains no `--out` ([ADR-0049](0049-the-report-states-its-redaction-and-carries-no-clock.md)),
so the script captures that stdout and writes it with `newline="\n"`. Files are overwritten;
nothing under the directory is deleted.

**It prints and it does not gate.** `scripts/verify.py` is the single definition of green
(`scripts/verify.py`'s docstring), and this script returns the exit code of whichever step stopped
it so a person can see what broke. CI does not run it.

**`scripts` joins the typecheck.** `scripts/verify.py:22` becomes
`("mypy", "--strict", "src", "tests", "scripts")` — measured green — because otherwise the demo
would be the only Python in a repository whose CLAUDE.md requires `mypy --strict` that nothing
checks.

## Alternatives considered
- **A fifth `assay demo` subcommand.** Rejected on two independent grounds: `src/` cannot import
  `tests/` in an installed wheel, and SPEC §6 publishes four commands in the milestone that
  freezes the surface (ADR-0047). A subcommand that only works from a git checkout is a surface
  that lies about itself.
- **Mine a real repository the reader supplies, or one cloned on the spot.** Rejected: it needs
  network, it needs that repository's toolchain to provision, and the two attempts on record
  produced 0 valid tasks. It also breaks the promise that the demo costs nothing and reaches
  nowhere.
- **Ship a committed suite and result set, and run only `report`.** Rejected: it would demonstrate
  the renderer, which is the one part of the pipeline nobody doubts, and it would skip the
  red→green gate — the thing this project is actually claiming. A demo that cannot fail is not
  evidence.
- **Print the numbers without the notice, and put the caveat in the README.** Rejected: the demo
  is what gets pasted into a chat window. The frame has to travel with the output, which is the
  same reason the report carries its interval caption inline rather than in documentation
  ([ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md)).
- **Give the demo a `--repo` flag so a curious reader can point it somewhere real.** Rejected:
  `assay mine` already is that flag. A demo whose target is configurable is a worse `assay mine`
  with a friendlier name.
- **Run one trial instead of five, to finish faster.** Rejected: pass^n over one trial is pass@1
  wearing a stricter name (`DEFAULT_TRIALS`'s own comment), and a demonstration that quietly
  weakens the headline statistic to save two minutes is teaching the wrong lesson about this tool.
- **Make CI run the demo as a second gate.** Rejected: two commands that can fail the build are two
  definitions of green, and the demo needs Docker and minutes for coverage `tests/score/` already
  has.
- **Write the artefacts somewhere tracked, or print them to stdout only.** Rejected: a tracked
  artefact means every demo run dirties the working tree, and stdout alone means the HTML page —
  the thing worth looking at — has to be redirected by hand.

## Consequences
**The demo takes minutes, and most of them are one commit.** `slow_lookup`'s red test sleeps for an
hour so `run_timed_out` has a witness, so `--test-timeout-s 120` is paid in full on every run. That
is the fixture doing its job, and the notice says so rather than leaving the wait unexplained.

**A flag renamed in `main.py` now fails a test rather than a demonstration.**
`tests/cli/test_demo_steps.py` parses all five argvs through `build_parser()`; it needs no Docker,
no fixture and no network, and it runs in the same package as the parser it guards.

**`scripts/` is now type-checked**, and anything added there later inherits `--strict`.

**The notice carries numbers, and numbers rot.** 11 commits, 2 tasks, 743, 40: the first two are
`tests.fixture_repo.EXPECTED_YIELD`, which CLAUDE.md pins, and the last two are milestone documents
that record completed runs and will not change. If the fixture's yield is ever deliberately
changed, this sentence changes with it.

**`scripts/` may import `tests/`, and that dependency is now load-bearing.** It is one-way and
stays that way: `src/` importing `tests/` remains forbidden, and the demo is the only consumer.
