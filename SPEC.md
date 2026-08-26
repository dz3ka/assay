# Assay — evaluate AI coding tools on *your* codebase

**Status:** scoped, not started. This document is the build brief.
**Owner:** Bogdan Džekić (dzeka)
**Repo:** `github.com/dz3ka/assay` (to be created, public from M0)
**Runs alongside:** `dz3ka/portcall`. Shares no code and no language with it, deliberately — see §12.

---

## 1. What this is

A harness that builds an evaluation suite **out of a repository's own git history**, runs
candidate AI coding tools against it inside a sandbox, and scores them on whether the
repository's own tests pass — without the code ever leaving the machine it lives on.

The question it answers is not *"which model is best?"* It is:

> On **this** codebase — our frameworks, our conventions, our build, our fifteen years of
> history — which of these tools actually works, how reliably, and at what cost per solved
> task?

## 2. Why it exists

SWE-bench, SWE-bench Verified, Aider's leaderboard and the rest measure public, curated tasks.
They are useful and this project does not compete with them. But an enterprise buyer in a POC
never asks "how did it score on SWE-bench." They ask "will it work on our monorepo," and there
is no public answer, because:

- Their code is private and cannot be shipped to a leaderboard.
- Their stack is unusual in ways no public benchmark samples — internal frameworks, a bespoke
  build, a language mix nobody benchmarks.
- Public numbers are contaminated for any repo that predates a model's training cutoff. Their
  private code is not, which makes an in-house eval *more* trustworthy, not less.

An FDE running a POC has to answer that question by feel, over a two-week trial, from
anecdotes. Assay turns it into a measurement.

**It is the natural second half of Portcall.** Portcall answers *can this tool run here?*
Assay answers *is it any good here?* Those are the two questions of every enterprise POC, in
that order. Together they are an FDE's first two weeks, made repeatable.

## 3. The core idea: mine tasks from git history

A merged commit that changes source code **and** has tests that went red-to-green is a
ground-truthed task, for free, in the codebase's own idiom. For a commit `C` with parent `P`:

1. Check out `P`.
2. Apply **only** the test-file changes from `C`.
3. **Verify the tests fail.** If they pass, the task is invalid — discard it.
4. Apply the non-test changes from `C` (the ground truth). **Verify the tests now pass.** If
   they don't, the task is invalid — discard it.
5. What survives is a task: a repo state, a set of failing tests, and a known-good diff.

The tool under evaluation sees the repo at step 2 plus a prompt. It passes if, after its diff
is applied, the target tests pass **and** the pre-existing suite does not regress.

That red-to-green gate at steps 3 and 4 is the whole trustworthiness story. Most mined
candidates will fail it — flaky tests, environment drift, tests that don't actually cover the
change. **Report the yield rate honestly** (`1,847 commits examined → 213 valid tasks`). The
yield number is more persuasive than the task count.

### Task types

| Type | Mined from | Verification | Priority |
|---|---|---|---|
| **Test-anchored fix** | commit changing source + tests, red→green | run the tests | **M1 — build only this** |
| Feature implementation | commit adding a module with new tests | run the tests | M5+ |
| Refactor preservation | commit changing source, no test changes | full suite must stay green | M5+ |
| Code navigation | static analysis of the code graph | deterministic string match | v2 |

That last one is a *retrieval* eval rather than a generation eval — "where is X defined, what
calls Y" with deterministic answers. It is cheap, it needs no model to grade, and it is
directly the problem Sourcegraph and Glean sell against. Worth building in v2, and worth
naming in the README as planned so a reader sees you know the distinction.

## 4. Scoring

Four tiers, in descending order of how much they should be trusted. The report shows all four
and never blends them into one number.

1. **Executable, objective.** Target tests pass. Pre-existing suite doesn't regress. Build
   succeeds. Type-check clean. Binary, cheap, unarguable — this is the primary signal and the
   only thing tools are ranked on.
2. **Cost and latency.** Input/output tokens, wall clock, tool-call count, retries. Report
   **cost per solved task**, which is the number a buyer actually wants and which almost no
   public benchmark puts on the front page.
3. **Diff distance to ground truth.** Reported, never ranked on. A tool that solves the task
   differently from the human is not wrong.
4. **LLM-as-judge**, for what cannot be executed. Rubric-based, ≥3 judges, and the report
   states inter-judge agreement (Krippendorff's alpha). A judge from the same model family as
   the tool under test is flagged in the output. If agreement is poor, the criterion is
   dropped rather than reported weakly.

### Reliability, not best-of-n

Every task runs **n trials per tool** (default 5) because these systems are nondeterministic.
Report both:

- **pass@1** — the conventional number, for comparability.
- **pass^n** — *all n trials succeeded.* This is the enterprise number. A buyer rolling a tool
  out to 300 engineers does not care that it works one time in five; pass@k rewards retrying,
  pass^n measures whether you can depend on it.

Leading with pass^n is unusual, defensible, and exactly the judgment an FDE is hired for.

### Statistical honesty

- Wilson score intervals on every proportion (not the normal approximation — n is small).
- Paired comparison across tools on identical tasks: McNemar's test, or a paired bootstrap.
- **When intervals overlap, the report says so and declares no winner.** Publishing
  *"Tool A 61%, Tool B 58%, not significant at n=213×5"* is a stronger signal than a
  leaderboard, and it is the thing that will make an engineer at one of your five companies
  take you seriously.

## 5. Trust properties

Same posture as Portcall, for the same reason — this is meant to run inside a customer's
environment on a customer's private repository.

1. **The repository never leaves the machine.** No upload, no telemetry. Model API calls send
   only what the task prompt and the tool's own context assembly include, and the report states
   exactly what was transmitted.
2. **Sandboxed execution.** Model-generated code runs in a container, never on the host.
3. **Network off during trials.** Dependencies are installed once when the task image is
   built; the trial itself runs with networking disabled apart from an allowlisted model
   endpoint. Otherwise a tool can `pip install` its way to a passing test — and one will.
4. **Redacted reports by default.** File paths, identifiers and commit messages are hashed in
   the emitted report, so results can be shared with a vendor when the code cannot.
5. **Deterministic and re-runnable.** Task suites are content-addressed and versioned, so a
   result can be reproduced and a regression can be attributed.

## 6. Architecture

```
assay
├─ cli/            commands: mine · validate · run · report
├─ mine/           git history walk, test-file detection, candidate extraction
├─ validate/       the red→green gate; yield accounting
├─ suite/          task schema, content-addressed suite files, versioning
├─ sandbox/        container lifecycle, resource limits, network policy
├─ adapters/       one per tool under evaluation
├─ score/          executable scoring, cost accounting, judges
├─ stats/          Wilson intervals, McNemar, bootstrap, agreement
└─ report/         json (canonical) · html (single self-contained file) · text
```

### Adapter interface — keep it this small

```python
class Adapter(Protocol):
    name: str
    version: str

    def run(self, task: Task, workspace: Path, budget: Budget) -> Attempt:
        """Workspace is a repo checked out at the task's base state, tests already
        failing. Return the diff produced, plus token and latency accounting."""
```

Anything drivable headlessly can be an adapter: an agentic CLI, an editor in a batch mode, a
raw model API.

**Ship a naive baseline adapter in M3 and keep it in every report.** One call to a raw model
with the failing test and the relevant file, no agent loop, no retrieval. Most benchmark
write-ups omit the baseline that would embarrass the sophisticated tools. Including it is
cheap, honest, and immediately marks the project as serious.

## 7. Milestones

Each lands green with ADRs before the next begins. These are deliberately smaller than
Portcall's, because the two are being built in parallel.

| # | Scope | Exit criteria |
|---|---|---|
| **M0** | Skeleton: CLI, task schema, suite format, adapter protocol, results store, CI | `assay --help` works; a hand-written task round-trips through the schema; CI green |
| **M1** | `mine` + `validate` — test-anchored fixes only | Produces a valid suite from a real public repo, with the red→green gate enforced and yield reported |
| **M2** | `sandbox` + executable scoring | Ground-truth diffs score 100%; empty diffs score 0%; network is provably off during trials |
| **M3** | Two adapters (naive baseline + one agentic tool), n-trial runs | pass@1 and pass^n produced end to end for both |
| **M4** | `stats` + cost accounting | Wilson intervals, paired significance test, cost per solved task; overlapping intervals suppress any winner claim |
| **M5** | Public release | HTML report, README, one-command demo on a public repo, published results for two tools with intervals |

M0–M5 is the publishable unit. v2 is the navigation/retrieval task type, refactor-preservation
tasks, and contamination flagging against published model cutoffs.

## 8. Decisions to record as ADRs

1. **Python, managed with `uv`.** Chosen over TypeScript because the statistics and reporting
   ecosystem is Python-native and this runs in a lab rather than being handed to a security
   team — so the packaging constraint that drove Portcall to a compiled binary does not apply
   here. It also deliberately covers the other half of the language pair.
2. **Tasks are mined, not authored.** Hand-written tasks encode the author's assumptions;
   mined tasks encode the repository's reality. The red→green gate is what makes that safe.
3. **Rank only on executable signal.** Judges inform, they do not rank.
4. **pass^n is the headline metric, pass@1 is reported for comparability.** Reliability is
   what an enterprise buys.
5. **No winner declared when confidence intervals overlap.** Enforced in the report renderer,
   not left to the reader.
6. **Network disabled inside trials; dependencies baked into the task image.** Otherwise the
   eval measures the model's ability to install its way out of the problem.
7. **Suites are content-addressed and versioned**, so results are reproducible and regressions
   are attributable to a task-set change rather than a tool change.

## 9. Testing

- **Unit** — diff splitting (test vs source), the red→green gate, Wilson intervals and
  McNemar against known values, cost accounting.
- **Fixtures** — a small purpose-built git repository committed to the repo, with a history
  containing: valid red→green commits, a flaky test, a commit whose tests pass before the fix
  (must be rejected), and a commit whose ground truth does not fix the tests (must be
  rejected). The miner must produce exactly the expected yield from it. **This fixture repo is
  the proof the gate works** and is worth as much as the miner itself.
- **Sandbox tests** — assert that a trial cannot reach the network, cannot write outside its
  workspace, and is killed at its resource limit.
- **End-to-end** — mine, validate, run the ground-truth adapter (which replays the known-good
  diff) and assert a perfect score; run a null adapter and assert zero.

## 10. Demo

One command against a small, well-tested public Python repo: mine a suite, show the yield,
run the naive baseline and one agentic tool at n=5, and render the report — with the
confidence intervals visibly overlapping on at least one comparison, and the report correctly
refusing to name a winner. That refusal is the most memorable thing in the demo.

## 11. Naming

`assay` — a test performed on a sample to determine its composition and quality. Precise,
short, and the verb form works in the CLI (`assay run`). Alternatives if npm/PyPI is taken:
`provingground`, `drydock`, `sounding`.

## 12. Running in parallel with Portcall

They are being built at the same time, so they are kept deliberately disjoint:

- **Different languages** — TypeScript and Python. No shared library, no shared build, no
  version coupling. Neither can block the other.
- **Different shapes** — Portcall is a single-shot diagnostic binary handed to a stranger;
  Assay is a long-running lab harness. Building two of the same thing would teach half as much.
- **One narrative** — on the portfolio they are a pair, and the pairing is the point: *can it
  run here* and *is it any good here*. Say that on both READMEs and on the site.
- **Ship order** — if time gets tight, Portcall M5 ships first. It is closer to the FDE job
  description and it is the one a hiring manager grasps in ten seconds.
