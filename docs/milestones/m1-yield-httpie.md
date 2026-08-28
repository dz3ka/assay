# M1 by-hand mining run: httpie/httpie

**Run date:** 2026-08-28 · **Assay at:** `48a3298` (M1, working tree) · **Milestone:** M1 exit criterion 4

## What was run

```
uv run --frozen assay mine --test-timeout-s 300 --name httpie <clone> --out httpie-full.json
```

| | |
|---|---|
| Target | `https://github.com/httpie/httpie.git`, cloned fresh, never modified |
| Clone HEAD | `5b604c37c6c67e18e7c3e9aee6c88a8c22b98345` |
| History size | 1797 commits (1690 non-merge — the walk asks git for `--no-merges`, ADR-0015) |
| Range examined | newest-first from `5b604c37c6c6` down to `9bd8b4e8f75e` (2019-08-29) |
| Commits examined | **743 of 1797** — the walk was **interrupted**, not completed (see *Why the walk was not finished*) |

## The yield

**743 commits examined → 0 valid tasks.**

Because the walk was interrupted, the command printed no closing yield block; the distribution
below is recomputed from its per-commit progress lines, one per examined commit.

| outcome | count | share of examined |
|---|---:|---:|
| `no_test_changes` | 572 | 77.0% |
| `still_red` | 127 | 17.1% |
| `no_source_changes` | 44 | 5.9% |
| `patch_did_not_apply` | 0 | — |
| `already_green` | 0 | — |
| `unstable_green` | 0 | — |
| `run_timed_out` | 0 | — |
| *unprovisioned* (not a rejection; a commit no environment could be built for) | 0 | — |
| **accepted** | **0** | **0.0%** |

171 commits (23.0%) reached the gate as candidates. **Not one was accepted.**

## What the zero means — read this before quoting the number

**This zero is not a property of httpie's history. It is a property of Assay's M1
host-execution model, and it should not be reported as httpie's yield.**

Every one of the 127 `still_red` verdicts was investigated rather than assumed. The
investigation replayed the gate on a spread sample of candidates and inspected the underlying
test reports at *both* gate states. The failure is uniform, and it has two layers.

**Layer 1 — the provisioned environment has no test dependencies.** `provision_venv`
(`src/assay/host/venv.py:66`) installs `-e .` plus a pytest requirement. That is the project's
*runtime* dependency set; httpie declares its test dependencies in a `test` extra, which is
never installed. So `tests/conftest.py` raises `ModuleNotFoundError: No module named
'pytest_httpbin'`, pytest exits **4** (usage error) having collected nothing, and the report
carries zero statuses and zero uncollectable files — at the parent commit *and* at the fixed
commit alike.

That shape is red by `_shows_failure` (`mine/gate.py:144` — "a selection that ran nothing at
all" counts as a failure) and is not green by `_is_green` (which requires exit code 0). The gate
therefore returns `still_red`, correctly and conservatively, for a candidate on which **no test
ever ran**. The gate is not wrong; it is being fed evidence gathered in an environment the
commit's tests cannot run in.

**Layer 2 — pinning is missing, not just the extra.** Re-provisioning one candidate by hand with
`-e .[test]` clears the conftest import and moves pytest from exit 4 to exit 1 — but the tests
still do not run. uv resolves httpie's unpinned transitive dependencies to *today's* releases
against a years-old commit, and collection dies inside a modern `jsonschema_specifications`
whose data files the pinned-era code does not expect (`FileNotFoundError` on a
`schemas/draft202012/vocabularies/` resource). Installing the test extra is therefore **not** the
fix; it exchanges one environment artifact for another.

Both layers are the same root cause: **provisioning a historical commit against the present-day
package index, on the host, under the host's interpreter.** A commit's dependency closure as it
stood on the day it was written is not recoverable this way.

### The finding

> **httpie/httpie cannot be honestly mined under M1's host-execution model.** The measured yield
> is 0 valid tasks from 743 commits examined, and that 0 is an artifact of provisioning, not a
> statement about httpie's history. No number from this run should be published as httpie's
> yield, and no task from it should be scored against.

This is a genuine result about the harness's reach rather than a failure to produce one, and it
is the concrete motivation for M2: sandboxed execution with **pinned per-task images**, built once
per task from the commit's own declared dependencies (SPEC §5.2, ADR-0013). A per-task image is
what makes the layer-2 problem solvable at all; the layer-1 problem is a narrower question of
which dependency groups provisioning should install, and is worth deciding explicitly rather than
inheriting.

A repository whose test dependencies are fully pinned and installable from its own packaging,
with no test extra, would mine correctly today. httpie is not that repository, and finding that
out is what this run was for.

## Why the walk was not finished

The walk was left running in the background across a session boundary and was killed at commit
743. It was not restarted, deliberately: the diagnosis above shows that every candidate is
discarded for one proven environment reason, so extending the walk from 743 to 1797 commits would
grow the denominator of a number that is already known not to measure httpie. The 743-commit
sample — 171 candidates, uniform failure mode, root cause identified and reproduced — establishes
the finding. Completing the walk is worth doing only *after* M2's pinned images make the result
mean something.

## Reproducing the diagnosis

1. Clone httpie at `5b604c37c6c6`.
2. Take any candidate the walk marked `still_red` whose selectors include a real `test_*.py`
   module — e.g. `011402152c69`, `f3b500119c78`, `a66af2497a7e`, `69e1067a2c84`, `9bd8b4e8f75e`.
3. Check out its parent into a worktree, apply the test half of the diff, provision with
   `provision_venv`, and run the selectors. Observe pytest exit 4 and the `pytest_httpbin`
   conftest ImportError.
4. Apply the source half and run again. Observe the identical shape — which is what makes the
   verdict `still_red`.
5. Repeat step 3 installing `-e .[test]` instead, to observe layer 2.

## Honest-reporting notes

- Reported as yield, never as a bare task count, per CLAUDE.md's measurement rules.
- The zero was **not** tuned away. No gate threshold, selector rule or timeout was changed to
  manufacture a task, and none should be: a low or zero yield is a legitimate result (decision
  D9).
- The distinction this document turns on — that "the fix did not work" and "no test ran" must not
  be reported as the same thing — is currently invisible in the tally, because both land in
  `still_red`. That is a known limitation of this run's accounting and is flagged for the M1 wrap.
