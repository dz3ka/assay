# Assay

A harness that mines an evaluation suite from a repository's *own* git history and scores
AI coding tools on it. Every task is a commit that already happened: the code before it is
the starting state, the tests it shipped with are the oracle, and the diff it landed is the
known-good answer. It answers one question:

> On *this* codebase — its idioms, its test suite, its shape — is this tool actually any
> good, or is it only responding?

The point is not the score. The point is that the score is defensible: a task only enters a
suite if its tests provably fail before the fix and provably pass after it, and the report
refuses to name a winner it cannot separate.

**Status: M1 complete.** M0's schemas, adapter protocol, redaction boundary, report pipeline and
decision record landed, and `assay report` works end to end against a recorded result set.
`assay mine` and `assay validate` now run the red→green gate over a real local clone: the walk,
the test/source split, the proof that the tests fail at the parent and pass once the commit's own
diff is applied, and the yield accounting for everything discarded on the way. `assay run` is the
only command left that exits `3`. Mining has also been run by hand over a real repository:
[743 commits of httpie](docs/milestones/m1-yield-httpie.md) examined for **0 valid tasks**, and
that record explains why the zero is a fact about M1's provisioning rather than about httpie's
history. Two things are true and worth reading twice: mining runs the
target repository's build and test suite **on this machine, outside a sandbox** — the container is
M2 — and no interval printed today is a measured one.

## What it does today

**Four schemas, versioned from the start** — task, suite, result and attempt, as pydantic v2
models over canonical JSON. A document carries its own `schema_version`, and a version this
build does not support fails with a sentence rather than a parser dump. Cost is a `Decimal`
at exactly six decimal places; any other scale is refused rather than rounded
([ADR-0010](docs/adr/0010-money-is-a-decimal-at-six-decimal-places.md)).

**Content-addressed suites.** A suite file carries the SHA-256 digest of its own body, and a
result cites the digest it was measured against, so "which suite was that number from" is
answerable from the artifact alone. The digest is over the canonical encoding of the parsed
value, not the file's bytes, so a hand-written pretty-printed suite and the bytes
`save_suite` writes verify identically
([ADR-0007](docs/adr/0007-suites-are-content-addressed-and-versioned.md),
[ADR-0008](docs/adr/0008-pydantic-v2-over-canonical-json.md)).

**The `Adapter` protocol, plus the two adapters that bracket every real result.**
`GroundTruthAdapter` replays the known-good diff and should score perfectly; `NullAdapter`
returns an empty diff and should score zero. A harness where those two do not land at the
ends of the scale is measuring something other than what it claims.

**Mining and the red→green gate.** `assay mine --repo <clone> --out suite.json` walks
single-parent commits newest-first, splits each into the tests it changed and the source it
changed, checks the parent out into a throwaway worktree, and admits the commit as a task only if
the tests fail there and pass once the commit's own diff is applied — twice, so a flaky green is
caught rather than minted. What is discarded is counted under one of seven reasons, and the run
prints yield rather than a task count. Against the fixture repository the test suite builds for
itself, that reads `9 single-parent commits examined -> 2 valid tasks` and
`6 candidates reached the gate, 0 unprovisioned`. `assay validate` re-runs the same gate over a
suite that already exists and refuses it unless both recorded test sets are reproduced exactly
([ADR-0014](docs/adr/0014-revalidation-compares-recorded-sets-both-ways.md)).

The scope is narrow on purpose: one repository family (Python with pytest), commits whose fix is
anchored by tests that shipped with it, and — the part to read before pointing it anywhere —
mining a repository runs that repository's build and tests on your machine, as you, outside a
sandbox. `assay mine` says so on stderr before it runs anything, and
[ADR-0013](docs/adr/0013-mining-runs-on-the-host-in-m1.md) records what that costs and what M2's
container closes.

**The report pipeline.** Three renderers — text, JSON, and a single self-contained HTML file
with no external assets and no CDN. The refusal to declare a winner when confidence
intervals overlap is an invariant of the `Verdict` model, not a habit of the renderers: a
report that names a winner its intervals cannot separate is not a document Assay is able to
build ([ADR-0005](docs/adr/0005-no-winner-when-intervals-overlap.md)).

**The redaction boundary**, written before any real data path exists so nothing downstream
can bypass it. Task identifiers and paths become HMAC-SHA-256 tokens under a salt drawn
fresh per render and never persisted
([ADR-0009](docs/adr/0009-redaction-is-hmac-with-a-per-render-salt.md)).

## What it does not do

- **Not a leaderboard.** No hosted ranking, no submissions, no cross-repository table. The
  output is a report about one repository, for the people who work in it.
- **Not a SWE-bench competitor.** SWE-bench asks whether a tool is good in general, against
  a fixed public benchmark that models may well have trained on. Assay asks whether a tool
  is good *here*, against history that is usually private and certainly not public training
  data. Different question, different artifact.
- **Numbers are meaningful only for the repository they were mined from.** A pass^n of 0.62
  on your monorepo and a 0.71 on someone else's are not comparable, and Assay will not print
  them side by side. Yield is reported alongside them for the same reason: "1,847 commits
  examined → 213 valid tasks" is the honest form, and the task count alone is not.
- **It does not tell you whether a tool can run in your environment at all.** That is
  [portcall](https://github.com/dz3ka/portcall), the sibling project. Portcall answers *can
  this tool run here* — DNS, egress, proxies, TLS interception. Assay answers *is it any
  good here*. Portcall goes ahead of the deployment; Assay comes after it. They share no
  code.
- **Running, scoring and the sandbox are not built.** `assay run` exits `3` with a message
  naming the milestone that builds it, and there is no sandbox, no model call and no statistics
  yet — so nothing has yet been scored against a mined task. Mining and validation are built and
  narrow: one repository family, test-anchored commits, and execution on the host rather than in
  a container. The intervals `assay report` prints are placeholders — pass^n ±0.25, clamped —
  and all three renderers say so verbatim, above the fold, on every run. Real Wilson intervals
  land in M4, and deleting the stub is a follow-up pinned in ADR-0005.

## Trust properties

The subject of this project is measurement honesty, so these are load-bearing rather than
aspirational. The first five are enforced in code today. The sixth names the constraints
later milestones are being built against, and is listed as a constraint, not a capability.

1. **The repository under evaluation never leaves the machine.** No upload, no telemetry.
2. **Reports are redacted by default**, and there is still no opt-out flag at all. The salt
   is drawn per render, so two reports on the same suite share no token.
3. **Ranking reads executable signal only** — tests passing, no regression, build clean. LLM
   judges inform the report and never move the ranking
   ([ADR-0003](docs/adr/0003-rank-only-on-executable-signal.md)).
4. **Overlapping intervals mean no winner**, enforced by the schema rather than by editorial
   habit, so no output format can route around it.
5. **Suites are content-addressed**, so any number can be traced back to the exact suite it
   was measured on.
6. **Model-generated code will only ever run inside the sandbox**, and **networking is off
   inside a trial** except for an allowlisted model endpoint, with dependencies baked into
   the task image rather than installed mid-trial. Both are M2
   ([ADR-0006](docs/adr/0006-network-off-inside-a-trial.md)). Mining is not a trial and runs no
   model-generated code, but until that container exists it does run the *target repository's*
   own build and tests on the host, which is a different exposure and an accepted one
   ([ADR-0013](docs/adr/0013-mining-runs-on-the-host-in-m1.md)).

## Run

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run --frozen python scripts/verify.py
uv run --frozen assay --help
```

`scripts/verify.py` is the repository's single verify target: ruff lint, ruff format check,
`mypy --strict` over `src` and `tests`, then the test suite, in that order, stopping at the
first failure. CI runs exactly it, so local checks and CI cannot drift apart.

Render a report from the recorded fixture result set, in each of the three formats:

```bash
uv run --frozen assay report --results tests/fixtures/results_overlapping.json
uv run --frozen assay report --results tests/fixtures/results_overlapping.json --format json
uv run --frozen assay report --results tests/fixtures/results_overlapping.json --format html
```

The document goes to stdout and the placeholder-interval admission goes to stderr, so
`--format json > out.json` leaves a file a consumer can parse *and* a human who still saw
the admission. That fixture is the overlapping case, so its comparison reads:

```
  alpha vs beta: No winner: the pass^n confidence intervals overlap.
```

`tests/fixtures/results_disjoint.json` is the separable case, for the other branch.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | The command ran. |
| `1` | Assay refused: unreadable input, a schema version it does not support, a suite whose hash does not match its body, or a suite that no longer revalidates. |
| `2` | Bad invocation — argparse rejected the command line. |
| `3` | The command exists in the surface but is not implemented in this milestone. Only `assay run` reaches it now. |

`3` is its own code so a caller can tell "this milestone has not built that yet" from "that
went wrong", and neither of them reads as success.

## Why it is built this way

Every non-obvious decision has an ADR in [docs/adr/](docs/adr/) — the context, the choice,
the alternatives that lost, and the consequences. ADRs 0001–0007 are the seven decisions
`SPEC.md` §8 names; 0008–0012 are decisions M0's implementation forced that the spec did not
anticipate, and 0013–0019 are M1's — the host-execution posture, two rules about what an
accounting number is allowed to claim, and four the by-hand httpie run forced about timeouts,
provisioning, and what mining on the host cannot reach.

Start with [ADR-0002](docs/adr/0002-tasks-are-mined-not-authored.md) for why the tasks come
out of git history rather than out of someone's judgement about what a good test case looks
like, and [ADR-0004](docs/adr/0004-pass-caret-n-is-the-headline-metric.md) for why pass^n
leads and pass@1 is reported only for comparability — a tool that succeeds once in five
attempts has not solved your problem, it has sold you a lottery ticket.
[ADR-0005](docs/adr/0005-no-winner-when-intervals-overlap.md) shapes what you actually see in
a report more than any other decision here, and explains why the refusal lives in the type
that carries the claim rather than in the three renderers the spec pointed at.
[ADR-0001](docs/adr/0001-python-3-12-managed-with-uv.md) covers the language and toolchain.

## License

Apache-2.0. See [LICENSE](LICENSE).
