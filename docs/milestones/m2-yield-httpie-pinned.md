# M2 pinned-image re-mine: httpie/httpie — a 40-commit pilot, run twice

**Run date:** 2026-09-01 · **Assay at:** M2 working tree (on `3642870`) · **Milestone:** M2, the
re-mine ADR-0019 asked for

This run exists to answer one question: **does M2's pinned per-task image lift the reach limit
[ADR-0019](../adr/0019-m1-cannot-mine-unpinned-test-dependencies.md) recorded against M1?**

It answers it on **40 commits, not on httpie's history.** Read the bound before the answer.

> **Two runs are recorded here, and the second one is the answer.** Everything above the
> *"The post-fix re-mine"* heading is the **pre-fix** run: the pinned image before it resolved
> dependencies as of the commit and before it installed declared test extras.
> That run measured the defect. The fix — [ADR-0021](../adr/0021-resolution-is-pinned-to-the-base-commit-era.md)
> and [ADR-0023](../adr/0023-the-image-installs-declared-test-extras.md), the one widening allowed
> in advance — landed afterwards, and **[the post-fix re-mine](#the-post-fix-re-mine) at the bottom
> of this document is what answers the question in the title.** The pre-fix sections are kept
> unedited because a measurement that was superseded is still a measurement, and rewriting it would
> destroy the evidence the decision was made on.

## The bound, stated first

The M1 run examined 743 commits. This one examines **40** — the newest 40 non-merge commits from
the same pinned HEAD, which is **2.4% of the repository's 1690 non-merge commits** and **5.4% of
what M1 examined**. Three of the 40 reached the gate.

Everything below is a claim about **three candidates**. It is enough to show that a blocker is
still present — one candidate would be — and it is *not* enough to put a yield number on httpie,
to compare a yield against M1's, or to say anything about the 1650 commits nobody walked. Where
this document says the reach limit did not lift, that is a statement supported by three
observations of one mechanism, and it is written that way on purpose.

## What was run

Not `assay mine`. **There is no wiring for a pinned-image mine and this run added none:**
`run_mine` (`src/assay/cli/main.py:429`) hardcodes `host_runner_for`, and `sandbox_runner_for`
(`src/assay/sandbox/runner.py:133`) closes over a single fixed image tag. The only existing
composition of the two halves is `tests/score/test_end_to_end.py:108,130`, and this run copied it
into a **scratch harness outside the repository** — a `RunnerFactory` that, for each workspace,
builds the base commit's image and hands the tag to `sandbox_runner_for`:

```python
with history.worktree(base_sha) as clean:  # a clean checkout, not the patched workspace
    tag = build_task_image(context=clean, base_commit=base_sha, timeout_s=900)
return sandbox_runner_for(tag, limits=LIMITS, out_root=out_root)(workspace)
```

```
git clone https://github.com/httpie/httpie.git <clone>
git -C <clone> checkout --detach 5b604c37c6c67e18e7c3e9aee6c88a8c22b98345
uv run --frozen python wp8_remine.py --repo <clone> --limit 40 --test-timeout-s 300 ...
```

| | |
|---|---|
| Target | `https://github.com/httpie/httpie.git`, cloned fresh, never modified |
| Clone HEAD | `5b604c37c6c67e18e7c3e9aee6c88a8c22b98345` — M1's, so the range is the same range |
| History size | 1797 commits, 1690 non-merge — both identical to M1's record |
| Range examined | newest-first from `5b604c37c6c6` (2024-12-17) to `7512ca7e47f3` (2023-05-20) |
| Commits examined | **40 of 1690** — the walk *completed*; the bound was chosen, not hit |
| Execution | sandboxed, one pinned task image per base commit, `--network none` inside every run |
| Container limits | 2048 MB, 2 CPUs, 1024 pids — generous deliberately: `assay run` does not exist yet, so no production ceiling is on record, and a candidate discarded for being squeezed would be ADR-0019's rejected widening pointed the other way |
| Test timeout | 300 s per run, as M1 |

## The yield

**40 commits examined → 0 valid tasks.** 3 candidates reached the gate; none was accepted.

| outcome | count | share of examined |
|---|---:|---:|
| `no_test_changes` | 35 | 87.5% |
| `no_source_changes` | 2 | 5.0% |
| `patch_did_not_apply` | 0 | — |
| `already_green` | 0 | — |
| `still_red` | 0 | — |
| `no_tests_executed` | **3** | **7.5%** |
| `unstable_green` | 0 | — |
| `run_timed_out` | 0 | — |
| *unprovisioned* (not a rejection; a commit no environment could be built for) | 0 | — |
| **accepted** | **0** | **0.0%** |

3 commits (7.5%) reached the gate as candidates. Not one was accepted. The three, with the base
commit each image was built from:

| commit | base | subject |
|---|---|---|
| `10b7d317d03c` | `3de7c82077ab` | Migrate setup.py to setup.cfg (#1553) |
| `3524ccf0baa9` | `8ac44b57ce0d` | Drop dependency on the abandoned python-lazy-fixture |
| `011402152c69` | `30a6f73ec806` | Rename repo from `httpie/httpie` to `httpie/cli` |

`011402152c69` is one of the five candidates M1's document named for reproducing its diagnosis, so
at least one observation here is the same commit M1 looked at, seen through the new execution
model.

**Every image built.** Three images, **7–8 seconds each**, and no `unprovisioned` commits: M1's
provisioning step, which was the thing that could fail per commit, is not where this stops.

## Did ADR-0019's reach limit lift?

**No. On the evidence of three candidates, it did not.**

ADR-0019 named two layers. They have moved differently, and the difference is the finding.

**Layer 1 — the missing test dependencies — is unchanged, and it is now the blocker.** The task
image installs `-e /workspace` plus `pytest` (`src/assay/sandbox/image.py`,
`render_base_dockerfile` — the recipe was a `_DOCKERFILE` constant on the day this run happened and
became a function when ADR-0021 gave it a cutoff to render), which
is [ADR-0018](../adr/0018-provisioning-installs-the-runtime-set-and-pytest.md)'s runtime set,
carried from host provisioning into the image unchanged. httpie declares its test dependencies in
a `test` extra, so inside the pinned image, verbatim:

```
ImportError while loading conftest '/workspace/tests/conftest.py'.
tests/conftest.py:4: in <module>
    from pytest_httpbin import certs
E   ModuleNotFoundError: No module named 'pytest_httpbin'
```

pytest exits 4 having collected nothing and writes no junit report — exactly the "nothing ran"
shape M2 defined its eighth rejection member by. **The image did not touch layer 1, because layer 1
was never about pinning.** It is about which dependency groups get installed, and that decision
lives in ADR-0018, not in the image.

**Layer 2 — resolver drift — has changed shape but has not gone.** M1's document records that
installing `-e .[test]` cleared layer 1 and left the tests still not running, dying inside a modern
`jsonschema_specifications`. Repeating M1's own step-5 probe **inside the pinned image** (a
diagnostic build, never a proposed fix — see the honest-reporting note below) shows that specific
artifact is gone: `jsonschema_specifications` now imports cleanly. What is there instead:

```
103 tests collected, 22 errors in 1.45s
ERROR tests/test_uploads.py - AttributeError: 'CallSpec2' object has no attribute ...
```

That is the era's `pytest-lazy-fixture` against today's pytest. **One resolver-drift artifact was
exchanged for another** — precisely what M1 predicted would happen if the install were widened —
and it happens here for a reason worth naming plainly:

> **The task image pins the base image and the commit. It does not pin the dependency
> resolution.** `uv pip install -e /workspace pytest` still resolves against the **present-day**
> index, at build time. ADR-0019's root cause — *provisioning a historical commit against the
> present-day package index* — is therefore only **half** addressed. What M2 changed is that the
> resolution is performed once and frozen into an image, so a trial is reproducible and needs no
> network ([ADR-0006](../adr/0006-network-off-inside-a-trial.md)). What M2 did not change is
> *which* closure gets frozen: today's, not the commit's.

Both halves matter and only one of them was M2's job. The pinned image does what SPEC §5.2 asked of
it. It is not, on this evidence, a fix for httpie.

### What did improve, measurably

**The accounting.** All three candidates are counted as `no_tests_executed`, the member
[ADR-0017](../adr/0017-still-red-stays-merged-until-m2-pins-the-environment.md) deferred and M2
split out. Under M1 the same three would have landed in `still_red` — indistinguishable, in the
tally, from candidates whose fix genuinely failed. M1's document flagged that as a known limitation
of its accounting; the table above no longer has it. A reader can now tell "the fix did not work"
from "no test ran" without reading a paragraph of prose, which was the whole point of paying for a
new rejection reason.

That is a real M2 result. It is a result about Assay's honesty, not about httpie's yield.

## Two things measured here that correct the record

**1. M1's candidate count is arithmetically wrong in its own document.**
[`m1-yield-httpie.md`](m1-yield-httpie.md) states "171 commits (23.0%) reached the gate as
candidates", but its own table partitions 743 as 572 + 127 + 44, which leaves **127** candidates
(17.1%) — the same figure its `still_red` row carries. Re-walking the identical range with this
run's harness reproduces the pre-gate half of that table exactly (743 examined, 572
`no_test_changes`, 44 `no_source_changes`, **127** reaching the gate), which is a useful
independent check that the walk is deterministic across M1 and M2. `171` appears to be a
transposition of `127`. The conclusions M1 drew do not depend on which figure is right — every
candidate was discarded either way — but the number should not be quoted at 171. This document does
not edit M1's: correcting a published measurement is a change with its own decision to record.

**2. The cost estimate that set this bound was wrong by more than an order of magnitude.** The
40-commit walk took **44.2 seconds end to end**, three cold image builds included. The full
743-commit re-walk was costed at 6–11 hours of image building, and the bound was chosen to avoid
that; at the measured 7–8 s per image and roughly 14 s per candidate, 127 candidates is about **half
an hour**. The estimate was high because it assumed a cold build would dominate each candidate. In
fact BuildKit reuses the base layers across commits, and a candidate that exits 4 having run nothing
costs almost no container time at all — the very failure being measured is what makes it cheap. **A
full re-walk of M1's range is affordable and is the obvious follow-up**, and it should be run before
any yield figure for httpie is quoted from either milestone.

## Reproducing this

1. Clone httpie and detach at `5b604c37c6c67e18e7c3e9aee6c88a8c22b98345`.
2. Compose `build_task_image` with `sandbox_runner_for` into a `RunnerFactory` and pass it to
   `mine_suite` with `limit=40`, `timeout_s=300` — the shape at
   `tests/score/test_end_to_end.py:108,130`. The factory builds the image from **a clean worktree
   of the base commit, which it opens itself** — the `with history.worktree(base_sha) as clean:`
   above — and never from the workspace it was handed: that workspace has the task's `test_patch`
   applied, so an image built from it would carry the base commit's address over a patched tree.
   As first published this step did not say so, and since
   [ADR-0027](../adr/0027-the-context-must-be-the-commit-the-tag-claims.md) it would not merely be
   wrong: `build_task_image` now refuses a context that is not the commit its tag claims, so the
   recipe without the clean worktree raises `SandboxError` instead of measuring anything.
3. Observe three candidates, all `no_tests_executed`.
4. Run `pytest tests/` inside any of the three task images. Observe exit 4 and the `pytest_httpbin`
   conftest ImportError.
5. For layer 2 only, rebuild one image with `-e "/workspace[test]"` and collect again. Observe
   `jsonschema_specifications` importing cleanly, and 22 `CallSpec2` collection errors in its place.

## Honest-reporting notes

- Reported as yield, never as a bare task count, per CLAUDE.md's measurement rules — and the
  denominator here is 40, small enough that the bound is stated before the yield rather than after
  it.
- **Nothing was widened to make anything pass.** ADR-0019 forbids it, and the `-e "/workspace[test]"`
  image in step 5 is a *diagnostic probe*: built under a throwaway tag, never used to mine, not
  proposed as a fix. It is M1's own step-5 recipe re-run under M2's execution model, and its result
  is reported as an observation about layer 2 rather than as a route around it.
- The zero was not tuned away. No gate threshold, selector rule, timeout or resource limit was
  changed to manufacture a task.
- **No yield figure for httpie should be published from this run, and none from M1's either.** M1's
  zero is an artifact of host provisioning; this zero is an artifact of the install set. Neither is
  a measurement of httpie's history, and this document supersedes M1's only on the question of
  *which* blocker is in the way.

---

# The post-fix re-mine

**Run date:** 2026-09-01, later the same day · **Assay at:** M2 working tree with ADR-0021 and
ADR-0023 landed · **Range:** the identical 40 commits, from the identical clone HEAD
`5b604c37c6c67e18e7c3e9aee6c88a8c22b98345`.

Two things changed in the build and nothing else changed anywhere:

1. Every image now resolves its dependencies **as of the base commit's committer date** —
   `exclude_newer=history.committed_at(base_sha)`, rendered into the recipe and therefore into the
   content address ([ADR-0021](../adr/0021-resolution-is-pinned-to-the-base-commit-era.md),
   [ADR-0022](../adr/0022-the-resolution-cutoff-has-one-canonical-spelling.md)).
2. Every image is asked what optional extras the project declares, and the allowlisted ones —
   `test`, `tests`, `testing`, `dev` — are installed in a second phase
   ([ADR-0023](../adr/0023-the-image-installs-declared-test-extras.md)).

Together those are **the one widening ADR-0021 fixed in advance**, and the rule that came with it
binds this document: *if the re-mine still yields zero, that is a finding, not a licence for a
second patch.* Nothing below was tuned, and nothing was widened a second time.

## The yield

**40 commits examined → 0 valid tasks.** 2 candidates reached the gate, 1 commit could not be
provisioned, and no candidate was accepted.

| outcome | count | share of examined |
|---|---:|---:|
| `no_test_changes` | 35 | 87.5% |
| `no_source_changes` | 2 | 5.0% |
| `patch_did_not_apply` | 0 | — |
| `already_green` | 0 | — |
| `still_red` | 0 | — |
| `no_tests_executed` | **2** | **5.0%** |
| `unstable_green` | 0 | — |
| `run_timed_out` | 0 | — |
| *unprovisioned* (not a rejection; a commit no environment could be built for) | **1** | **2.5%** |
| **accepted** | **0** | **0.0%** |

Wall clock **76.5 s** for the 40 commits, against 44.2 s pre-fix. The extra time is the second
container every build now runs to ask the image what it declares, plus two extras installs; it is
the expected cost of the widening and it is small.

Against the pre-fix run, commit for commit:

| base commit | cutoff (committer date) | extras declared | extras installed | closure | verdict pre-fix → post-fix |
|---|---|---|---|---:|---|
| `3de7c82077ab` | `2024-03-04T17:12:18Z` | `dev`, `test` | **`test`, `dev`** | 70 lines | `no_tests_executed` → `no_tests_executed` |
| `8ac44b57ce0d` | `2024-03-04T14:57:45Z` | `dev`, `test` | **`test`, `dev`** | 71 lines | `no_tests_executed` → `no_tests_executed` |
| `30a6f73ec806` | `2023-05-24T15:22:56Z` | — (image never built) | — | — | `no_tests_executed` → **`unprovisioned`** |

Both extras fired on both buildable images: httpie declares `dev` and `test`, both are on the
allowlist, and both were installed. The order in the *installed* column is the allowlist's, not the
declaration's, because the selection is hashed into a tag.

## What one image actually holds

`read_installed_closure` asks the built image `uv pip freeze` with no network, and this is the
answer for `3de7c82077ab` — 70 lines, abridged here to the ones that carry the finding, the full
set being in the run's `images.json`:

```
attrs==23.2.0
...
-e file:///workspace
...
jsonschema==4.21.1
jsonschema-specifications==2023.12.1
...
pytest==8.0.2
pytest-cov==4.1.0
pytest-httpbin==2.0.0
pytest-mock==3.12.0
...
werkzeug==2.0.3
```

Three lines answer three separate questions that were open before this run.

**`pytest-httpbin==2.0.0` is installed.** That is layer 1 of ADR-0019 — the missing test
dependency whose absence made `tests/conftest.py` raise `ModuleNotFoundError` — and it is gone.

**`jsonschema-specifications==2023.12.1`, not today's.** That is layer 2 — resolver drift — and the
version is the one March 2024's index served, which is what `--exclude-newer` was for. The
pre-fix run got a 2026 release here and died inside it.

**`pytest==8.0.2`, not `9.1.1`.** The era is visible in the runner itself, which matters for the
junit question below.

The closure is recorded rather than merely observed because it is the only thing that makes
ADR-0021's remaining limit auditable: `--exclude-newer` cannot restore a release PyPI has stopped
serving, so a rebuild months from now can **fail** — but a line-for-line comparison against this
list is what proves it did not quietly resolve to something else and pass.

## The image that did not build is counted `unprovisioned`

`30a6f73ec806` (May 2023) failed at the first phase. The full BuildKit stderr, obtained by
re-running the identical recipe by hand because `CommandFailedError` quotes only its last 500
characters:

```
× Failed to build `multidict==6.0.4`
  ╰─▶ Call to `setuptools.build_meta:__legacy__.build_wheel` failed
      gcc -fno-strict-overflow -Wsign-compare -DNDEBUG -g -O3 ...
      error: command 'gcc' failed: No such file or directory
  help: `multidict` (v6.0.4) was included because `httpie` (v3.2.2) depends on it
```

`multidict==6.0.4` is what May 2023's index served, and its wheel set predates CPython 3.12, so uv
falls back to the source distribution — into a slim base image that has no C compiler. **This is
the interpreter residue ADR-0021 named, arriving exactly where it said it would.** The commit is
counted `unprovisioned`, which is not one of the eight rejection reasons and is not evidence about
httpie: the gate never spoke about this commit at all
([ADR-0015](../adr/0015-a-rejection-reason-must-be-reachable.md)). The walk logged it and carried
on, which is the behaviour a 743-commit run depends on.

Installing `gcc` into the base image would fix this commit. **It is not done, and the reason is the
stop rule**: the one widening is spent, and a second one chosen after seeing which commit failed is
tuning, not engineering.

## junit was produced and parsed

`src/assay/host/junit.py`'s shapes were calibrated against **pytest 9.1.1**, and every image in this
run holds **pytest 8.0.2** — a major version apart. That is a mismatch to check rather than assume,
so it was checked, and it is **not** a defect:

- Running httpie's whole suite inside `3de7c82077ab`'s image: **1028 tests collected, 998 passed,
  2 failed, 24 skipped, 4 xfailed, 53.6 s**, and pytest 8.0.2 wrote a 138 KB junit report whose
  root element is `<testsuites><testsuite name="pytest" errors="0" failures="2" skipped="28"
  tests="1028" ...>` — the shape `build_test_report` parses, unchanged from 9.1.1's.
- Running the candidate's own selection: pytest exits 5, prints `no tests ran in 0.01s`, and still
  writes a junit report — a 212-byte one with an empty `<testsuite>`. No statuses, no
  `uncollectable`, exit code in `_NOTHING_RAN`: the `no_tests_executed` shape exactly, arrived at
  through a parsed report rather than through a missing one.

So junit was produced and parsed for both candidates, and the era gap between the calibration and
the runtime did not move a shape. Recorded as a measurement, not as a licence: a *third* era might
differ, and the next mismatch is still a finding to record rather than a patch to apply.

The two failures in the whole-suite run (`test_config_file_inaccessible`, one
`test_naked_invocation` parametrisation) are the container running as root and a terminal-width
assumption. They are noted for completeness and are not part of any gate decision here.

## Did ADR-0019's reach limit lift? — the post-fix answer

**Yes. The environment blocker is gone. The yield on these 40 commits is still zero, and that is
now a fact about the commits rather than about Assay.**

Both halves of that sentence are load-bearing and they must not be collapsed into either one.

**The limit lifted, and here is the evidence.** ADR-0019 said M1 "cannot mine a repository whose
test dependencies are unpinned, or live in an extra or group that pinning does not cover." Inside
the post-fix image, httpie's test dependencies are installed and its suite runs: 1028 tests
collected and 998 passing, with no network, in an environment resolved as of the commit. Under M1
the same repository could not collect a single test. Both named layers are discharged — layer 1 by
the declared-extras phase, layer 2 by the epoch pin — and the closure above is the receipt.

**And the yield is still 0 of 40.** The two candidates that reached the gate were discarded
`no_tests_executed`, and the reason is now visible in a way it was not before:

| candidate | its test-half changes |
|---|---|
| `10b7d317d03c` "Migrate setup.py to setup.cfg" | `tests/utils/__init__.py` |
| `3524ccf0baa9` "Drop dependency on the abandoned python-lazy-fixture" | `tests/conftest.py`, `tests/fixtures/pytest_lazy_fixture.py` |

Neither commit changed a **test module**. It changed test *machinery* — a helper package, a
conftest, a vendored fixture — and `mine/candidates.py`'s `is_test_path` counts anything under
`tests/` as a test file, so the gate points pytest at files that contain no tests and pytest
correctly reports that nothing ran. These two commits are **not test-anchored fixes**, and
discarding them is right. What changed post-fix is that the discard is now attributable: pre-fix
the same verdict was produced by an environment that could not import a conftest, and the two
causes were indistinguishable from the tally.

That distinction is the whole point of the exercise, so it is worth stating plainly: **the zero did
not move, and what the zero means moved completely.** Pre-fix it meant *Assay could not build an
environment for httpie.* Post-fix it means *these particular 40 commits contain no test-anchored
fix, and one of them is out of reach for a stated reason.*

**What this is not.** It is not a yield figure for httpie. Two candidates and one unprovisioned
commit cannot carry one, and 1650 of httpie's 1690 non-merge commits are still unwalked. It is
not a claim that the residue below is empty. And it is not a claim that a full walk will find
tasks — the full walk is the only thing that can answer that, it was run, and it is reported
below. **It found the residue at scale: 125 of the 127 commits that got past the pre-gate split
could not be built at all.** Read the pilot's answer with that section beside it.

## What this fix cannot do

Five limits are real. None is patched, all five are named, and the reason they are written out in
prose rather than listed as jargon is that a reader has to be able to tell how each one would show
up in a number.

**Yanked and deleted releases.** `--exclude-newer` filters the index by upload date; it cannot
restore a file PyPI no longer serves. The pin is monotone — everything published after the cutoff
is excluded, so the reachable set can only lose members and never gain them — which means a rebuild
months from now can **fail** but cannot silently resolve to something else and pass. That is the
property `read_installed_closure` exists to make checkable: the closure recorded beside a run is
comparable line for line against a rebuild's, so "it reproduced or it refused" is an assertion
somebody can make rather than a hope.

**The interpreter is not epoch-pinned.** Every task image is the same digest-pinned CPython 3.12,
whatever era the commit is from. A commit whose dependency closure predates 3.12's wheels forces a
source build, and a slim base image has no compiler — which is precisely how `30a6f73ec806` was
lost above. The failure is loud and counted `unprovisioned`, never a silent wrong answer, but it is
a genuine narrowing of reach and it will bite hardest on the *oldest* commits, which is to say on
exactly the part of a history a full walk spends most of its time in. Per-era base images are an
M3+ question.

**Undeclared system packages, services and network tests.** A repository whose suite needs
PostgreSQL, a system library apt would install, or a live HTTP endpoint stays red under
`--network none`, and it is discarded for a reason the yield cannot name: it lands in `still_red`
or `no_tests_executed` beside candidates whose fix genuinely failed. Assay cannot distinguish
"this test needed a database" from "this fix did not work" without executing something it has
decided not to execute. httpie's own suite is unusually well behaved here — `pytest-httpbin` runs
the server in-process — which is a fact about httpie and must not be generalised.

**Extras named outside the allowlist.** Four names are installed and everything else is dropped:
`test`, `tests`, `testing`, `dev`. A project that calls its test extra `ci`, or that keeps test
dependencies in a PEP 735 dependency group or a `requirements-dev.txt`, gets the runtime set and
pytest and nothing more — which is the pre-fix failure, re-armed for a different repository. A
fifth name is a decision with an ADR, not a configuration key, and it would be a second widening.

**pytest-era junit calibration.** `host/junit.py`'s shapes were measured against pytest 9.1.1 and
an epoch-pinned image runs whatever pytest the commit's era served. This run confirms the shapes
held at 8.0.2, above. It confirms nothing about 5.x, and a mismatch found there is a finding to
record, not a patch to apply — the same rule that governs everything else on this page.

## The full 743-commit walk

Run immediately after the pilot, over M1's identical range with identical settings:

```
uv run --frozen python wp8_remine.py --repo <clone> --limit 743 \
  --scratch <scratch>/scratch743post --jsonl <scratch>/run743post.jsonl \
  --images-json <scratch>/run743post.images.json > <scratch>/run743post.summary.json
```

It **completed**, in **426.6 seconds** — seven minutes, against the 6–11 hours the pre-fix run was
costed at and the half hour the pilot's revised estimate suggested. It is faster than either
estimate for a reason that is itself the finding.

**743 commits examined → 0 valid tasks.**

| outcome | count | share of examined |
|---|---:|---:|
| `no_test_changes` | 572 | 77.0% |
| `no_source_changes` | 44 | 5.9% |
| `patch_did_not_apply` | 0 | — |
| `already_green` | 0 | — |
| `still_red` | 0 | — |
| `no_tests_executed` | 2 | 0.3% |
| `unstable_green` | 0 | — |
| `run_timed_out` | 0 | — |
| *unprovisioned* (not a rejection; a commit no environment could be built for) | **125** | **16.8%** |
| **accepted** | **0** | **0.0%** |

The pre-gate half reproduces M1's exactly — 572 + 44, leaving **127** commits past the split, which
is the figure the pilot's correction note already established against M1's transposed `171`. Of
those 127, **two reached the gate and 125 did not**.

**The walk attempted 126 distinct base images and 124 of them failed to build.** The two that built
are the pilot's two, and their committer dates are both `2024-03-04`. Every failure is older:

| era of the base commit | images attempted | failed |
|---|---:|---:|
| 2024 | 2 | 0 |
| 2023 | 3 | 3 |
| 2022 | 25 | 25 |
| 2021 | 52 | 52 |
| 2020 | 36 | 36 |
| 2019 | 8 | 8 |

Grouping the 124 failures by the stderr `CommandFailedError` preserved, and reproducing one of each
class by hand for the full message:

- **90 — `ModuleNotFoundError: No module named 'distutils'`.** Reproduced at `2b78d044101e`
  (December 2021): uv's own hint is *"`distutils` was removed from the standard library in Python
  3.12."*
- **31 — `AttributeError: module 'pkgutil' has no attribute 'ImpImporter'`.** Reproduced at
  `a7321d8ac41f` (October 2022): a setuptools older than 67 executing on CPython 3.12.
- **3 — `Failed to build multidict==6.0.4` … `error: command 'gcc' failed: No such file or
  directory`.** Reproduced at `30a6f73ec806` (May 2023), the pilot's third candidate: an era wheel
  set that predates cp312, so uv falls back to a source build in an image with no compiler.

**All three classes are one cause: the interpreter is not epoch-pinned.** The dependency *set* is
now the commit's; the Python it is installed under is 2026's. Every one of these images resolved
correctly and then failed while executing a build backend written for a Python that no longer
behaves that way. That is exactly the residue ADR-0021 named in its Consequences, arriving at the
scale it warned about: it bites hardest on the oldest commits, and a repository's history is mostly
old commits.

It is also why the walk was fast. A build that dies inside `setup.py` dies in about a second, and
125 of the 127 interesting commits never reached a container at all.

### What the full walk changes about the answer

**The reach limit lifted where an image could be built, and a second limit — named in advance,
measured here for the first time — governs everything older than about March 2024 in this
repository.**

For the two 2024 commits, the environment is genuinely fixed: the extras are installed, the closure
is the commit's era, and the suite runs. For the other 125, Assay now fails **earlier, louder and
in the right bucket**. Under M1 and under the pre-fix image those commits produced a *gate verdict*
— `still_red` or `no_tests_executed` — which is a sentence about a repository's tests. They now
produce `unprovisioned`, which is a sentence about Assay, counted separately from the rejection set
because the gate never spoke about them ([ADR-0015](../adr/0015-a-rejection-reason-must-be-reachable.md)).

**That relocation is the most valuable thing in this walk.** 125 commits that used to look like
evidence about httpie are now correctly labelled as evidence about the harness. The zero is the
same zero; it now points at the right thing.

### What must not be concluded from it

- **This is not httpie's yield.** 743 of 1690 non-merge commits were examined and 125 of the 127
  that mattered were never evaluated. The correct sentence is: *Assay cannot currently mine
  httpie's pre-2024 history, and it has not measured whether that history contains tasks.*
- **It is not evidence that epoch-pinning was the wrong fix.** Without it, the two 2024 commits
  would have failed too, on resolver drift, and the 125 would have failed at the gate rather than
  before it — the same zero, less honestly accounted.
- **It is not a licence to install `gcc` and a `setuptools<60` constraint.** Both would raise the
  buildable share, both were visible only after the measurement, and both are the second widening
  the stop rule forbids ([ADR-0025](../adr/0025-the-one-widening-is-spent.md)). Per-era base images
  are the decision this walk motivates, and it belongs to M3 with this run as its evidence.

Artefacts: `run743post.jsonl` (743 records, one per commit), `run743post.images.json` (126 image
records — cutoff, extras declared and installed, closure or build failure per base commit),
`run743post.summary.json`, `run743post.log`.

## Honest-reporting notes for the post-fix run

- **The stop rule held.** ADR-0021 fixed one widening in advance; the epoch pin and the declared
  extras were it. No second widening was made after seeing the result, and two obvious ones were
  deliberately declined and written down instead: installing `gcc` (would have recovered
  `30a6f73ec806`) and adding a fifth extra name.
- **Nothing was tuned.** No gate threshold, selector rule, timeout, resource limit or allowlist was
  changed. The two extras that fired are the two httpie declares, matched against an allowlist
  written before this run.
- **The denominator is 40 and it is stated before the numerator everywhere it appears.** 40 is 2.4%
  of httpie's 1690 non-merge commits. Nothing here supports a claim about the other 1650.
- **The verdicts changed on one commit and it got worse, not better.** `30a6f73ec806` went from a
  countable rejection to `unprovisioned`. A run that reported only the accepted count would have
  hidden that; the partition is what surfaces it.
- **The one diagnostic probe is labelled as one.** Running httpie's whole suite inside a task image,
  and rebuilding `30a6f73ec806`'s recipe by hand for its full stderr, are observations. Neither was
  used to mine, and neither image was fed to the gate.
- **No yield figure for httpie is published from either post-fix run.** The question this
  document answers is about Assay's reach. On 743 commits the reach improved where an image
  could be built and stopped dead where one could not, and 125 of the 127 commits that mattered
  were never evaluated — which is a statement about the harness, not a price for the repository.
- **The full walk's zero is reported with its denominator and was not re-run to improve it.**
  743 commits examined, 0 valid tasks, 125 unprovisioned. It was walked once, and once is what
  is published.
