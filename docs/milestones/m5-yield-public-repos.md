# M5 public-repo yield: three small pytest libraries, mined with the shipped command

**Run date:** 2026-09-07 · **Assay at:** M5 working tree (on `98e6ea8`) · **Milestone:** M5

## 1. The bound, stated before the answer

This document measures **how far Assay's miner reaches into public Python repositories it was not
built against**. It is not a survey of those repositories and it is not a benchmark. Everything in
this section — the selection rule, the three repositories, the walk limit — was fixed **before the
first mine run happened**, and is written here in the order it was decided, so that no threshold in
it can have been chosen after seeing a number.

**Selection rule, verbatim as recorded:**

> small single-package pytest-based libraries with pinned dev dependencies and no service
> dependencies.

**The three repositories, chosen under that rule:**

| repository | why it fits the rule |
|---|---|
| `pallets/itsdangerous` | one package, pytest, dev dependencies pinned in-repo, no services |
| `theskumar/python-dotenv` | one package, pytest, pinned dev requirements, no services |
| `jd/tenacity` | one package, pytest, pinned test dependencies, no services |

**The walk limit: `--limit 200` per repository.** One number, the same for all three, fixed in
advance. The limit exists because the walk runs the target repository's own test suite three times
per candidate on the host, so a full history is hours; 200 is what fits the release window.

**A zero yield was the expected result, and would have been published as one.** Every public
repository Assay had mined before today yielded zero
([ADR-0019](../adr/0019-m1-cannot-mine-unpinned-test-dependencies.md),
[ADR-0025](../adr/0025-the-one-widening-is-spent.md)), and a third zero would have been a finding
about Assay's reach, recorded as such and not quietly dropped. Choosing the repositories or the
limit *after* seeing the yield is precisely the failure this project exists to prevent, which is
why they are above the results and not below them. The result below is not zero. **Disclosure:
this paragraph is the only one in §1 whose wording was touched after the runs** — its tense, and
this sentence. The selection rule, the three repositories and the limit are byte-unchanged from
what was written before the first clone was made.

**How this was run.** The shipped `assay mine`, from the working tree, on the host path
([ADR-0053](../adr/0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md)) — not
a script written for this document, and not the pinned per-task image, which `assay mine` has never
been wired to. Every figure below carries the exact command that produced it
([ADR-0045](../adr/0045-a-claim-carries-its-verification-inline.md)).

## 2. What was run

The three clones were made into a scratch directory outside this repository and were never
modified. Their HEADs are recorded because a yield figure that cannot be re-derived is not a
measurement:

```
git clone https://github.com/pallets/itsdangerous.git
git clone https://github.com/theskumar/python-dotenv.git
git clone https://github.com/jd/tenacity.git
git -C <clone> rev-parse HEAD
```

| repository | clone HEAD | commits (non-merge) | examined range (newest → oldest) |
|---|---|---:|---|
| `itsdangerous` | `672971d66a2ef9f85151e53283113f33d642dabd` | 677 (436) | `584138c73af1` 2025-06-14 → `a6766130ed64` 2021-01-01 |
| `python-dotenv` | `a00cb2eed0704cd6d2071b2004c37e95ccc86ee5` | 438 (431) | `a00cb2eed070` 2026-08-17 → `b5b8ae20d0bc` 2020-02-15 |
| `tenacity` | `3e58094d3bc414975aad9eadf343a32bdb3b89b3` | 615 (515) | `3e58094d3bc4` 2026-09-01 → `98f7da70f867` 2020-12-16 |

`itsdangerous`'s newest *examined* commit is not its HEAD because its HEAD is a merge, and the walk
asks git for `--no-merges`: a merge is never examined and is never counted as a rejection
([ADR-0015](../adr/0015-a-rejection-reason-must-be-reachable.md)).

One command per repository, differing only in the three paths and the name:

```
uv run --frozen assay mine --repo <clones>/itsdangerous  --out <suites>/itsdangerous.json  --name itsdangerous  --limit 200
uv run --frozen assay mine --repo <clones>/python-dotenv --out <suites>/python-dotenv.json --name python-dotenv --limit 200
uv run --frozen assay mine --repo <clones>/tenacity      --out <suites>/tenacity.json      --name tenacity      --limit 200
```

All three exited 0. `--test-timeout-s` was left at its default of 300. The wall clock in §3 is
`time` around each of those three commands, run one at a time on an otherwise idle machine.

## 3. The yield

**600 single-parent commits examined → 14 valid tasks.**

Per repository, as the command printed it on stdout — these three blocks are its literal output:

```
200 single-parent commits examined -> 1 valid tasks
6 candidates reached the gate, 0 unprovisioned; merges and the root commit are not examined at all
rejected: no_test_changes 193, no_source_changes 1, patch_did_not_apply 0, already_green 3, still_red 1, no_tests_executed 1, unstable_green 0, run_timed_out 0
```
```
200 single-parent commits examined -> 0 valid tasks
47 candidates reached the gate, 0 unprovisioned; merges and the root commit are not examined at all
rejected: no_test_changes 147, no_source_changes 6, patch_did_not_apply 0, already_green 0, still_red 0, no_tests_executed 47, unstable_green 0, run_timed_out 0
```
```
200 single-parent commits examined -> 13 valid tasks
69 candidates reached the gate, 0 unprovisioned; merges and the root commit are not examined at all
rejected: no_test_changes 126, no_source_changes 5, patch_did_not_apply 0, already_green 6, still_red 50, no_tests_executed 0, unstable_green 0, run_timed_out 0
```

The same figures as a table. The eight rejection reasons are the eight members of
`GateRejection` (`src/assay/mine/models.py:113-120`), named here exactly as the command prints
them; `unprovisioned` is not one of them — it counts a commit no environment could be built for,
which the gate therefore never spoke about:

| | `itsdangerous` | `python-dotenv` | `tenacity` | total |
|---|---:|---:|---:|---:|
| commits examined | 200 | 200 | 200 | **600** |
| candidates reaching the gate | 6 | 47 | 69 | 122 |
| **accepted (valid tasks)** | **1** | **0** | **13** | **14** |
| `no_test_changes` | 193 | 147 | 126 | 466 |
| `no_source_changes` | 1 | 6 | 5 | 12 |
| `patch_did_not_apply` | 0 | 0 | 0 | 0 |
| `already_green` | 3 | 0 | 6 | 9 |
| `still_red` | 1 | 0 | 50 | 51 |
| `no_tests_executed` | 1 | 47 | 0 | 48 |
| `unstable_green` | 0 | 0 | 0 | 0 |
| `run_timed_out` | 0 | 0 | 0 | 0 |
| *unprovisioned* (not a rejection) | 0 | 0 | 0 | **0** |
| wall clock | 0m36.7s | 4m19.3s | 10m12.2s | 15m08.2s |

Yield is **14 / 600 = 2.3%** of examined commits, and **14 / 122 = 11.5%** of the commits that
reached the gate. Both denominators are given because neither alone is the yield.

The suites those runs wrote, by content address
(`python -c "import json;print(json.load(open(PATH))['suite_hash'])"` on each output file):

| suite | tasks | `suite_hash` |
|---|---:|---|
| `itsdangerous` | 1 | `sha256:ef04854c1de7d9125f094fa7f42fe1eeaaf252946134d0855c11b8efd17e1bb1` |
| `python-dotenv` | 0 | `sha256:0b5b47772c22e1e9c45728495ba7dd4d74d68d0cd76359226014b6b93d805c63` |
| `tenacity` | 13 | `sha256:f00d81732e3389728b44fd69bc479fcafba4b1085fdb12bfe33336bb3feb1106` |

## 4. What this is, and what it is not

**This is the first non-zero yield Assay has produced on a repository it was not built against.**
Before today the only public repository it had mined was httpie, twice, for zero both times
(ADR-0019, ADR-0025). That is the whole of the news, and it is smaller than it sounds: it is one
repository at 0.5%, one at 0% and one at 6.5%, over 200 commits each.

**`unprovisioned` was 0 in all three runs.** That is the figure that separates this result from the
httpie ones: at the 743-commit httpie scale run, 125 commits could not be given an environment at
all (ADR-0025). Here the host path provisioned every one of the 600 commits it walked. The
selection rule asked for exactly that property — small, single-package, pinned dev dependencies, no
services — so this is the rule being satisfied rather than a new capability.

**What must not be concluded from this.**

- **This is not a measurement of those three repositories' quality.** A commit rejected
  `no_test_changes` is a commit that changed no test file. That is the overwhelming majority here
  (466 of 600) and it describes releases, docs, CI config, type annotations and refactors — normal,
  healthy commits that this miner has no way to turn into a task. Nothing in this table is a
  criticism of anybody's repository.
- **This is not a general claim about open-source Python.** Three repositories were chosen against
  a stated rule that selects for the narrow shape this miner can reach. They are not a sample of
  anything, and 2.3% is not an estimate of a population parameter. There is no interval on it
  because there is no population it would be an interval over.
- **This is not a claim about `assay mine` on repositories outside the rule.** ADR-0019's reach
  limit is unrepealed: the host path resolves a historical commit's dependencies against today's
  index under today's interpreter, and a repository whose test dependencies are unpinned still
  cannot be mined this way. Nothing here was measured that bears on that.
- **These 14 tasks have not been re-validated or scored.** No `assay validate` re-check and no
  `assay run` was performed against any of them. They passed the red→green gate once, at mining
  time, which is what "valid task" means and is all it means here.
- **The number is a floor on the host path, not a ceiling on Assay.** A pinned-image mine could
  reach commits this walk rejected. It has never been wired into `assay mine`, so what it would
  yield is unmeasured and is not estimated here (ADR-0053).

**Two shapes in the accepted set are worth naming rather than leaving for a reader to find.**

The `itsdangerous` task (`itsdangerous-7f4dcf83a07b`, from `access sha1 lazily`, 2024-04-16)
records 41 `fail_to_pass` node ids and an empty `pass_to_pass`. Reading its stored patches shows
why: the test patch adds `from itsdangerous.signer import _lazy_sha1`, and `_lazy_sha1` is defined
by the ground-truth patch — so at the base commit the whole test module fails to import, and every
test in it is red. That is a genuine red→green under the gate's definition, and it is also a
coarser one than "this assertion failed": a tool solving it has to make a module importable, not
just make one behaviour correct. Two of `tenacity`'s thirteen have the same shape by their counts
(138 and 19 `fail_to_pass` against 0 `pass_to_pass`); the cause there was not investigated, and is
not asserted.

That shape is not a defect in the gate — a test that cannot import at the base commit did fail
there and does pass after the fix — but a report that quoted "14 valid tasks" without it would be
overstating how targeted those tasks are.

## 5. Reproducing this

Clone the three repositories, check out the HEADs in §2, and run the three commands in §2 from a
checkout of this repository. The rejection counts should reproduce exactly: the walk is
deterministic given a commit range, which the M1/M2 re-mine of httpie established independently
(`m1-yield-httpie.md`'s erratum). The wall clock will not reproduce — it is a property of the
machine, and it is reported to say what this costs, not as a measurement of Assay.

The suite hashes above should also reproduce, since `repo_url` here is each repository's declared
`origin` rather than a host path
([ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md)).
