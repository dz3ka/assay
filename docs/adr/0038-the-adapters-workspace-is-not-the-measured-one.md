# ADR-0038: The adapter's workspace is never the measured workspace, and the harvest excludes nothing

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
ADR-0037 refuses a diff that names a test path. That rule is worth exactly as much as the diff
it is handed: if the recorded diff is a filtered account of what the tool did, the guard reads
the filter rather than the tool, and a run that rewrote the failing test can still be scored.

Until M3 the question did not arise. Both oracles *return* a diff — `GroundTruthAdapter` copies
the task's recorded one and `NullAdapter` returns the empty string — and neither touches the
workspace at all. M3's agentic adapter is the first that works the other way round: it is given
a checkout, it edits files in place, and the diff has to be harvested from the tree afterwards.

The first design for that harvest excluded test paths with a pathspec, on the reasoning that a
diff which cannot name a test file cannot tamper with one. It is exactly backwards. Excluding
the tool's test edits from the record does not prevent them; it launders them. The edit
disappears from the artefact a human reads, the guard has nothing left to refuse, and the
remaining source changes are then scored on their own — so a tool that got to green by
weakening an assertion is recorded as a tool that fixed a bug. The exclusion actively defeats
ADR-0037, which is why it was cut before it was written up.

Harvesting everything raises the other half of the problem. A tool's workspace after it has
worked is not a clean tree: there are `__pycache__` directories from the test runs the tool
made, editor scratch files, whatever a package manager it invoked installed, and possibly
commits, since nothing stops an agent running `git commit`. Measuring in that tree means the
scoring run sees all of it, and the trial's verdict would then depend on residue nobody
recorded, nobody can reproduce, and no report can show.

There is a third constraint that rules out the obvious tampering detector. The task's test
patch is applied *unstaged* — [`src/assay/host/git.py`](../../src/assay/host/git.py) applies it
with a plain `git apply`, no `--index` — so `git diff --name-only` restricted to the test paths
is non-empty on every trial that ever runs, tampering or not. It cannot distinguish setup from
sabotage, and making it able to would mean staging the patch, which is a widening of the
`History` seam that the miner, its only other caller, has no use for.

## Decision
**`run_trial` prepares the workspace twice. The tool works in the first, the measurement
happens in the second, and the only thing that crosses between them is the diff the attempt
recorded. The harvest excludes nothing.**

Both preparations go through one function,
[`src/assay/score/trial.py`](../../src/assay/score/trial.py)'s `_prepared`: a worktree at the
task's base commit with the task's own test patch applied, and nothing else. Two spellings of
"prepared" could drift into two different states, which would make a diff harvested from the
first fail to apply in the second for a reason no verdict could explain. Because both trees are
that same state by construction, a diff taken from one applies in the other.

The second preparation is entered only when the attempt reports no error. An errored attempt is
never measured (`Outcome.ERRORED`, ADR-0031), so checking out a tree for it would be a git
operation whose result is discarded — and a refusal of the test patch in that second
preparation is the same `TrialSetupError` as in the first, meaning the same thing: the
workspace could not be brought to the state the trial is defined on.

The harvest this makes possible is total and reversal-free: stage everything, record a
baseline tree object, run the tool, stage everything again, and diff the two staged states as
binary. It is robust to a tool that stages or commits its own work, it needs no ignore list,
and it leaves nothing to undo — the tree it ran in is thrown away either way. Any step exiting
nonzero becomes `Attempt.error` and the trial scores `ERRORED`. Writing that harvest is the
agentic adapter's work, not the scorer's; what this record fixes is the contract it must
satisfy, because the guard above depends on it.

A tool that rewrote the failing test now shows that edit **in the recorded diff**, is refused
by ADR-0037, and scores `FAILED` — detected in the artefact rather than excluded by
construction.

## Alternatives considered
- **Harvest with an exclusion pathspec.** Rejected, and this record exists mostly to say why.
  It is one flag instead of one worktree, and it converts a detectable false green into an
  undetectable one.
- **Measure in the tool's own tree, cleaned first — `git reset --hard` plus `git clean -xdf`.**
  Rejected. It restores a tree by trusting the repository state of a directory a tool had
  arbitrary write access to, including its `.git`; a fresh worktree reaches the same state
  without depending on anything the tool could have damaged. It is also a reversal, and the
  reason it would be needed is machinery this milestone added.
- **Detect tampering with `git diff --name-only` over the test paths after the run.** Rejected
  on the measurement above: the unstaged test patch makes it fire on every trial.
- **Snapshot the tree by digest before and after, and diff the snapshots.** Rejected. It needs
  an invented ignore list the first time the tool runs pytest and mints `tests/__pycache__`,
  and that list is a second, quieter exclusion rule with the same failure mode as the first
  alternative.
- **Stage the test patch during setup so the harvest is clean.** Rejected. It widens
  `History.apply_patch` for one caller, and it changes what `mine` — which shares that seam and
  runs the same patch through it — would be doing.
- **One workspace, and trust that a well-behaved tool leaves no residue.** Rejected: the tool
  under evaluation is the one thing in this system whose behaviour Assay may not assume.

## Consequences
Every trial now costs one extra `git worktree add` and one extra patch apply. Against a
container start, an image resolution and two pytest runs, that is noise;
`GitHistory.worktree` already gives every checkout a uuid4 path, so n concurrent trials of one
task were already safe and stay safe.

The trial measures the recorded diff and only the recorded diff. That is the property worth
having — what is scored is exactly what the report shows and exactly what a reproduction would
replay — and it has a cost worth naming: a tool whose fix depends on something the harvest
cannot see is scored as though it had not done it. The harvest is `git add -A`, so the only
such things are paths the repository's own `.gitignore` excludes. A tool that writes its fix
into an ignored path fails, and the recorded diff shows why.

The two-preparation shape is now the thing that keeps ADR-0037 honest, which makes it a
structural fact rather than an implementation detail: a future refactor that folds the trial
back into one workspace to save a git call would re-open the residue question in a place where
no test currently looks. The tests assert the split directly — the adapter's workspace and the
measured workspace are compared and must differ — rather than only asserting the verdicts that
happen to follow from it.
