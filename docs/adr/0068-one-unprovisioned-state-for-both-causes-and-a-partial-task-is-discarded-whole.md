# ADR-0068: One `unprovisioned` state for both causes, and a task that fails partway is discarded whole

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Bogdan Dzekic

## Context

ADR-0067 gave `ResultSet` the two fields that can express "twelve of thirteen, and here is the
one that is missing and why". It closed by saying the decision is inert on its own: nothing
writes `unprovisioned`, and the loop that would is this record and ADR-0069. This is that loop.

`run_run` (`src/assay/cli/main.py:1027`) walks the suite's tasks, builds an image per task, and
runs n trials per task per adapter. Two things inside that walk can fail for reasons that have
nothing to do with the tool being measured:

- **`_task_image` raises.** The task's base commit cannot be built into an image. This is what
  happened on the live `jd/tenacity` run of 2026-09-10: one task of thirteen failed its build
  inside era-pinned `setuptools`, the exception left the loop, and the run ended having written
  nothing — 105 already-scored trials discarded with it.
- **`run_trial` raises `TrialSetupError`** (`src/assay/score/trial.py:62`). The task's own test
  patch does not apply at its recorded base commit. A validated suite guarantees that it does —
  the red→green gate applied that patch to that parent and watched it hold — so a refusal here
  is a broken suite or a broken harness, never the tool.

Both are failures of *provisioning*, and both can strike a task at any point: the build before
any trial has run, the patch at any trial including the last one. That second possibility is
what makes this a decision rather than a `try` block. A task of five trials that refuses on the
fourth has three scored results in hand at the moment it fails, and something has to be decided
about them.

The vocabulary already exists on the mining side. `MiningYield.unprovisioned`
(`src/assay/mine/models.py:233-236`) counts commits whose workspace could not be given an
environment its tests could run in. A run's two failures are the same sentence about a task
rather than about a commit.

## Decision

The task loop wraps each task in `try` / `except (AssayError, OSError)` / `else`, with no
`continue`, no `finally` and no new helper. Trials are appended to a `task_results` list local
to the iteration, and that list is extended into the run's `results` **only in the `else` arm**
(`src/assay/cli/main.py:1139` and `:1182`).

**Both causes are recorded as the same state, and the state is `unprovisioned`.**
`TrialSetupError` is an `AssayError`, so one `except` clause catches the build failure and the
refusing patch alike, and both write `unprovisioned[task.task_id] = str(error)` (`:1175`). The
distinguishing fact a reader needs is not which layer failed — it is *which task* was not
measured and *what sentence* failed it, and both of those are recorded. Naming a third state
would make the report ask a question nobody can answer differently: a task that could not be
given a working environment is unmeasured either way, and the two states would be reported with
one word anyway.

**A task is all-or-nothing.** A task that fails partway keeps none of the trials it scored. Those
trials were real, and discarding them is a deliberate loss of data, because the alternative is
worse: `_summarise_tool` (`src/assay/report/model.py:791`) computes `pass^n` straight off the
trials present for a task, so three surviving trials of a five-trial task would be published as
that task's `pass^n` with n silently equal to 3. CLAUDE.md's rule is that `pass^n` leads every
report; a `pass^n` whose exponent varies per task, invisibly, is the confident number nobody
should trust. `src/assay/score/trial.py:67-70` already states the same principle one layer down:
a mis-set-up trial must never reach the tool's rate.

**The catch stays in `run_run`.** `_task_image` is unchanged and still raises, and
`sandbox_runner_for` still refuses to answer `None` (ADR-0027): a factory that invented an
"unprovisioned" return value would push the decision into a module whose job is to build things.
What changed is only the scope the handler answers for — one task, rather than the run.

**The shortfall is stated twice.** Each failure prints one line as it happens
(`assay run: <task-id> unmeasured: <reason>`), and the tail prints the total with every task
named (`<k> of <n> tasks unmeasured: …`) whenever any task is missing. The stdout summary line
now counts *measured* tasks rather than the suite's, because `13 tasks x 1 adapters x 5 trials =
60 trials recorded` is arithmetic a reader can check and find false.

**Exit code: `EXIT_OK` if anything was measured, `EXIT_FAILED` if nothing was.** Surviving one
bad task must not turn a run that measured nothing into a success.

## Alternatives considered

**Let the exception end the run, as before.** This is the status quo and it is what lost the
2026-09-10 run. One task in thirteen that cannot be provisioned is not a harness defect worth
throwing away twelve tasks of measurement over, and the user's ruling on that run is explicit:
publish twelve of thirteen and name the thirteenth.

**Two states — `unbuildable` and `setup_failed`.** Rejected. The schema ADR-0067 landed carries
one mapping of task id to reason, and the reason string already distinguishes them in the words
the failure itself used. A second state would need a second field, a second column in every
renderer, and a rule about which one wins if a task somehow hits both; it would buy a
distinction no reader acts on differently.

**Keep the trials a failed task scored, and mark the task partial.** Rejected on the measurement
rule. It makes `pass^n`'s exponent a per-task variable that no reader of the file can see, and
the renderer that would have to explain it does not exist. A partial task's trials are honest
data about a task nobody can rank; the file has a place to say that task was not measured, and
that is the place it says it.

**Record the partial trials somewhere else — a second list the report ignores.** Rejected as
scope. It is a new schema field, in a schema this goal has already amended once, for data whose
only use is diagnostic. The per-task stderr line already reports what happened and when.

**Catch inside `_task_image` and return a sentinel instead of raising.** Rejected against
ADR-0027 and ADR-0048. The factory would then answer for a policy question ("is a task that
cannot be built fatal?") that belongs to whoever is running the loop, and the sentinel would have
to be threaded through `_task_adapters` and the trial loop to reach the only place that can act
on it.

**A `finally` block, or a `continue` in the `except` arm.** Rejected in the razor pass on the
plan. `continue` puts the per-task write in two places and makes it possible for a future edit to
add a third path that skips it; `finally` runs after `else`, which reads as though the write were
cleanup rather than the point of the iteration. The `try`/`except`/`else` with one unconditional
write after it has exactly one write site and one place each cause is recorded.

## Consequences

**A run survives a task it cannot provision, and says so in three places:** the per-task stderr
line, the shortfall line at the end, and `unprovisioned` in the file itself — the only one of the
three that outlives the terminal.

**The 2026-09-10 run's failure mode is now covered by a test rather than by a milestone note.**
`tests/cli/test_main.py` drives a whole three-task run with the daemon stubbed out at exactly two
seams — `build_task_image` and `run_trial` — and asserts the unbuildable task, the refusing
patch, the discard of a partial task, and both exit codes.

**Data is deliberately thrown away on a partial task, and that is the cost of this record.** A
task that fails on its last trial loses n-1 real measurements. If that turns out to be common
rather than pathological, the answer is a schema that can say "3 of 5 trials, and here is why",
not a quiet relaxation of the discard — the rule is enforced in code, so changing it requires
changing this decision.

**`unprovisioned` is now written on both sides of the harness**, by the miner and by the run, and
the two still count different things (ADR-0067 says so, and ADR-0066 owes the milestone that
closes the asymmetry between them). Nothing here changes that; it makes the shared word carry a
value in the run's file for the first time.

**The report does not read the new field yet.** `build_report` gains its coverage section in
ADR-0070; until then a result set can say "twelve of thirteen" and the rendered report still
cannot. That ordering is deliberate — this package is revertible on its own.
