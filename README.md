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

**Status: M0–M5 complete — the publishable unit in [`SPEC.md`](SPEC.md) §7 has shipped.** All four commands are built and the
pipeline runs end to end, from a git history to a redacted report. What each milestone measured
lives in [`docs/milestones/`](docs/milestones/) — one record per milestone, each stating at length
what it does and does not establish — rather than being summarised here, because the summary was a
lossy second copy of those documents and it drifted
([ADR-0055](docs/adr/0055-the-readme-is-a-release-document-not-a-changelog.md)).

**The results this repository publishes are the two oracles.** `ground-truth` replays the recorded
fix and scores 1.0; `null` returns an empty diff and scores 0.0; between them they bracket every
real result precisely by not being one. **No model has been called in any milestone, on any path,
by any adapter** — no API key has been read and nothing has been spent
([ADR-0051](docs/adr/0051-m5s-two-tools-are-two-oracles.md)). Every command works, and nothing has
been graded by one. Those are two different sentences and both are true here.

Mining has been run by hand over real repositories three times, and all three runs are on the
record. M1 walked [743 commits of httpie](docs/milestones/m1-yield-httpie.md) for **0 valid
tasks**. M2's pinned per-task images [walked it again](docs/milestones/m2-yield-httpie-pinned.md) —
a 40-commit pilot first, then the full 743 under the same harness — and it is still **743 commits
examined → 0 valid tasks**: for httpie the pinned image did not lift the reach limit
[ADR-0019](docs/adr/0019-m1-cannot-mine-unpinned-test-dependencies.md) recorded, and that negative
result is the finding. What moved is where the failure is counted. **125 of those 743 commits
(16.8%) came back `unprovisioned`** — a commit no environment could be built for, which is not
one of the eight rejection reasons and is not evidence about httpie: it is a sentence about
Assay, counted and reported separately and never folded into the rejection set
([ADR-0026](docs/adr/0026-the-image-residue-is-reported-not-counted.md)).

M5 then pointed the shipped `assay mine` at three other libraries, and got this project's first
non-zero yield on software it was not built against: **600 single-parent commits examined → 14
valid tasks** ([`m5-yield-public-repos.md`](docs/milestones/m5-yield-public-repos.md)). Four things
are true of that number, and they belong in the same breath as the number rather than in a
footnote under it. The three repositories were chosen under a rule written down before the first
clone existed — small single-package pytest libraries with pinned dev dependencies and no service
dependencies — and that rule selects for the shape this miner already reached, so **it is a reach
limit sidestepped by advance selection, not a reach limit lifted**. ADR-0019 is unrepealed: a
repository whose test dependencies are unpinned still cannot be mined this way, and nothing in the
run bears on one. Three repositories chosen that way are not a sample of anything, so 2.3% is not
an estimate of any population and carries no interval. And **those 14 tasks have never been
re-validated or run by any tool** — they passed the red→green gate once, at mining time, which is
what "valid task" means and all it means. That Assay can mine a suite is demonstrated; that it has
mined a suite worth running is not.

Two things are still true and worth reading twice: the container holds *trials*, so a mining walk
runs the target repository's build and test suite **on this machine, outside a sandbox** — and no
interval printed today describes a tool that called a model.

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
caught rather than minted. What is discarded is counted under one of eight reasons, and the run
prints yield rather than a task count. Against the fixture repository the test suite builds for
itself, that reads `11 single-parent commits examined -> 2 valid tasks` and
`7 candidates reached the gate, 0 unprovisioned`. `assay validate` re-runs the same gate over a
suite that already exists and refuses it unless both recorded test sets are reproduced exactly
([ADR-0014](docs/adr/0014-revalidation-compares-recorded-sets-both-ways.md)).

The scope is narrow on purpose: one repository family (Python with pytest), commits whose fix is
anchored by tests that shipped with it, and — the part to read before pointing it anywhere —
mining a repository runs that repository's build and tests on your machine, as you, outside a
sandbox. `assay mine` says so on stderr before it runs anything, and
[ADR-0013](docs/adr/0013-mining-runs-on-the-host-in-m1.md) records what that costs and what M2's
container does not close: a trial runs inside it, a mining walk does not.

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
- **It has mined very few real repositories, and only ones that fit.** Four in all: httpie, walked
  twice for **0 valid tasks** out of 743 commits both times, and three small pytest libraries
  chosen in advance against a written rule, for **14 valid tasks** out of 600 commits
  ([`m5-yield-public-repos.md`](docs/milestones/m5-yield-public-repos.md)). That rule selects for
  the shape the miner already reaches, so the second result sidesteps
  [ADR-0019](docs/adr/0019-m1-cannot-mine-unpinned-test-dependencies.md)'s reach limit rather than
  lifting it, and a repository whose test dependencies are unpinned still cannot be mined here.
  None of those 14 tasks has been re-validated or scored by anything since. `assay mine` also runs
  the host path only — M2's pinned per-task image was never wired into it
  ([ADR-0053](docs/adr/0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md)) —
  so 14 is a floor on that path rather than a measurement of Assay's reach.
- **It does not tell you whether a tool can run in your environment at all.** That is
  [portcall](https://github.com/dz3ka/portcall), the sibling project. Portcall answers *can
  this tool run here* — DNS, egress, proxies, TLS interception. Assay answers *is it any
  good here*. Portcall goes ahead of the deployment; Assay comes after it. They share no
  code.
- **No real tool has been scored yet.** `assay run` is built and exercised end to end, but only by
  the two oracles: ground truth scores 1.0 and null 0.0 over a suite mined from the synthetic
  fixture repository, which brackets every real result without being one. The naive baseline and
  the agentic Claude Code adapter are built, unit-tested on fakes and container-tested, and **have
  never called a model** — so this repository contains no naive-vs-agentic comparison and no
  evidence that either adapter can solve anything.
  **Neither M4 nor M5 changed that.** This section used to say the first live run was M4's; M4
  called no model and spent nothing, and neither did M5, so the promise is withdrawn here rather
  than quietly deleted
  ([ADR-0042](docs/adr/0042-the-readme-withdraws-the-promise-of-a-live-run.md)), and no milestone
  owns the live run. Mining and validation stay narrow: one repository family, test-anchored
  commits, and a walk that runs on the host rather than in a container. The interval
  `assay report` prints around pass^n is a real Wilson band over tasks; M4 gave pass@1 its own
  by a different method, a seeded percentile bootstrap over tasks, and the report names both
  methods rather than printing two bands as though one procedure produced them. M4's paired
  significance test — exact McNemar over the tasks two tools disagree on — landed the same way.
  Both were validated against hand-computed fixtures and the two oracles' free results, and
  neither has ever been computed over a run that called a model.

## Trust properties

The subject of this project is measurement honesty, so these are load-bearing rather than
aspirational. All six are enforced in code today: the sixth was a constraint later milestones
were being built against until M2's container turned it into one more thing with tests behind it.

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
6. **Model-generated code only ever runs inside the sandbox**, and **a trial has no network at
   all** — `--network none` rather than a filter — with dependencies installed when the task
   image is built rather than mid-trial
   ([ADR-0006](docs/adr/0006-network-off-inside-a-trial.md)). The sandbox tests assert the
   negatives: no name resolves, no raw address answers, nothing outside the trial's one writable
   directory can be written, and the container is killed at its memory and wall-clock ceilings.
   They fail rather than skip when Docker is absent, because a trust property nobody ran is not
   one ([ADR-0024](docs/adr/0024-the-sandbox-tests-fail-without-docker-they-do-not-skip.md)).
   M3's allowlisted model endpoint is the adapter's business and stays outside the container.
   Mining is not a trial and runs no model-generated code, but it does run the *target
   repository's* own build and tests on the host, which is a different exposure and an accepted
   one ([ADR-0013](docs/adr/0013-mining-runs-on-the-host-in-m1.md)).

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

### Demo — the whole pipeline in one command

```bash
uv run --frozen python scripts/demo.py
```

Mine a suite, revalidate it, score it with the two oracles, and render the report twice, as text
and as HTML: SPEC §6's four commands in SPEC §6's order, with no flags, no model, no API key and
nothing spent. It needs a running Docker daemon and writes both documents under `build/demo/`. It
was timed twice on one developer machine — Windows 11, Docker server 29.7.2, both task images
already in the local cache — at **206 s** and **204.1 s**, most of it spent on the one fixture
commit whose red test is written never to finish. That is what it cost on that machine, not a
promise about yours, and the cold case — no task images, no layer cache, a base image still to
pull — is slower by an unmeasured amount: no number for it is published here.

**It runs against a synthetic repository, and it says so on stderr before the first step.** The
target is the fixture `tests/fixture_repo.py` builds into a temporary directory: a history authored
so that each of the miner's verdicts fires exactly once, which is why its yield is a specification
this repository's tests enforce rather than an observation about software. The two tasks it
produces measure this harness and say nothing about any tool
([ADR-0050](docs/adr/0050-the-demo-runs-against-the-fixture-and-says-so-first.md),
[ADR-0054](docs/adr/0054-a-premise-of-adr-0050-is-overtaken-and-the-decision-stands.md)). The run
recorded for M5, with the report it produced, is in
[`m5-public-release.md`](docs/milestones/m5-public-release.md).

Render a report from the recorded fixture result set, in each of the three formats:

```bash
uv run --frozen assay report --results tests/fixtures/results_overlapping.json
uv run --frozen assay report --results tests/fixtures/results_overlapping.json --format json
uv run --frozen assay report --results tests/fixtures/results_overlapping.json --format html
```

The document goes to stdout and a successful run says nothing on stderr, so
`--format json > out.json` leaves a file a consumer can parse. That fixture is the
overlapping case, so its comparison reads:

```
  alpha vs beta: No winner: the pass^n confidence intervals overlap.
```

`tests/fixtures/results_disjoint.json` is the separable case, for the other branch.

Score a mined suite, five trials per task per adapter, and report on what it wrote:

```bash
uv run --frozen assay run --suite suite.json --repo <clone> --out results.json \
  --adapter ground-truth --adapter null
uv run --frozen assay report --results results.json
```

Every trial happens in a container: the tool works in one and the tests are run in a second with
no network interface at all, so `assay run` needs a Docker daemon where `assay mine` does not.
Naming a real tool — `--adapter agentic` — also requires `--adapter naive`, because the report
has to carry the one-raw-model-call baseline the tool is meant to beat, and both read the model
API key from `ASSAY_MODEL_API_KEY` in the environment. It is never a flag: a command line is
readable by every process on the machine.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | The command ran. |
| `1` | Assay refused: unreadable input, a schema version it does not support, a suite whose hash does not match its body, or a suite that no longer revalidates. |
| `2` | Bad invocation — argparse rejected the command line. |

Those three are all of them, and each one has a command that produces it. `1` and `2` are separate
so a caller can tell "Assay refused the input" from "the command line was wrong", and neither reads
as success.

## Why it is built this way

Every non-obvious decision has an ADR in [docs/adr/](docs/adr/) — the context, the choice,
the alternatives that lost, and the consequences. ADRs 0001–0007 are the seven decisions
`SPEC.md` §8 names; 0008–0012 are decisions M0's implementation forced that the spec did not
anticipate, and 0013–0019 are M1's — the host-execution posture, two rules about what an
accounting number is allowed to claim, and four the by-hand httpie run forced about timeouts,
provisioning, and what mining on the host cannot reach. 0020 is about how this repository is
worked rather than about the tree — the wrap phase offers the retro first — and 0021–0031 are
M2's: six on what a task image installs, what it still cannot reach, and how it proves it holds
the commit its address claims; one on why the sandbox tests fail rather than skip when Docker is
absent; and four on the edges of an executable verdict — a trial killed at its cgroup ceiling, a
selector no runner would accept, an exit code pytest could not have produced, and why an errored
trial never leaves the denominator. 0032–0048 are M3's and M4's: what counts as a test change, who
owns the trial index, where the one interval and then the second one come from, the fence that
keeps outbound network in a single module, the two real adapters and the model behind them, and
what a cost line and a refusal each have to say when they have nothing to report. 0049–0056 are
M5's — what a published report may not carry, what the one-command demo points at and why that
survives a yield it did not expect, what produced the public-repo figure, the shape of this
document, and why the exit-code table above lists three codes rather than four.

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
