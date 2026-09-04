"""The agentic CLI adapter: a tool somebody else wrote, run once, and read off the tree.

The naive baseline asks a model for a diff and records the answer. An agentic tool does not
answer at all - it is given a checkout, it edits files in place over however many turns it
takes, and it exits. So the two adapters differ in the one place that matters: this one has to
*harvest* the diff from the tree afterwards, and the harvest is the whole of what it records.

The harvest is ADR-0038's, verbatim and in this order: stage everything, record the tree that
results, run the tool, stage everything again, and diff the second staged state against the
first. Five steps, and each of them matters.

* Staging *before* the tool runs is what folds the task's own test patch - applied unstaged by
  :meth:`assay.host.GitHistory.apply_patch` - into the baseline, so it is setup rather than
  something the tool appears to have done.
* Staging *after* is what makes the record robust to a tool that ran ``git add`` or ``git
  commit`` of its own: whatever it staged or committed is in the index either way.
* Diffing against a tree object rather than against ``HEAD`` is what makes a tool's commits
  invisible to the harvest - the baseline is a tree, and a commit does not move it.
* **There is no pathspec, no exclusion and no reversal.** A tool that rewrote the failing test
  shows that edit in the recorded diff, is refused by ADR-0037 and scores ``FAILED``. Excluding
  test paths here does not prevent the tampering; it launders it, and the trial then mints a
  confident false ``PASSED`` - which is the failure this whole project exists to catch.

Nothing here knows that a container exists. The tool is invoked through an injected
:class:`assay.adapters.process.ToolProcess` and the harvest goes through the same seam, so
every branch below - the tool that exits non-zero, the tool killed at its budget, the tool that
changed nothing - is reachable on a fake in CI with no docker, no network and no `claude`
installed. Where the tool's argv actually runs is the seam's business, and in production it is
inside the task image with only the model endpoint reachable (ADR-0039).

Two things it deliberately does not record. It does not read the tool's own output: an agentic
CLI prints the model's reasoning, and that text is neither the measurement nor something a
redacted-by-default report should carry by accident (plan section 7g), so a failure is recorded
as the step and the status that produced it and nothing else. And it does not report tokens,
because the only way to learn them is to parse the CLI's output format, which is not a stable
contract - a zero that is stated is better than a number that is guessed.
"""

import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns
from typing import Final

from assay.adapters.process import ProcessOutput, ToolProcess
from assay.results import Attempt, Budget
from assay.suite import Task

_NS_PER_MS = 1_000_000

# The twin of the constants in the other adapters, copied rather than shared for the reason
# :mod:`assay.adapters.null` gives: no adapter owns another's internals.
_NO_COST = Decimal("0.000000")
_NO_DIFF = ""

# The harness's own version, because the code in this file is half of what is being measured.
_HARNESS_VERSION = "0.1.0"

# What ``git write-tree`` prints, and the one value in this module that arrives from outside it
# and then goes back out in a command line. Checked where it arrives rather than where it would
# detonate, the posture ``host/git.py``'s ``_checked_revision`` takes towards an object name:
# forty hex characters today, sixty-four under SHA-256, and nothing else - a `git` that answered
# with an option-shaped string would otherwise be handing this module an argument to run.
_TREE_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")

# The harvest's own wall clock, per step. Not the trial's budget: that belongs to the tool,
# which is the thing being measured, and a `git add` that has not answered in two minutes is a
# broken checkout rather than a slow one. It is a constant rather than a fraction of the budget
# because a trial run with a small budget still needs its work read back.
_HARVEST_TIMEOUT_S: Final = 120

# The most of a failed step's own stderr that is quoted into ``Attempt.error``. `git` failing is
# Assay's machinery failing and its message is the only useful thing a reader gets, but an
# attempt is written into a result set, so the quote is bounded. The tool's output is never
# quoted at all, at any length - see the module docstring.
_MAX_QUOTED_STDERR = 500

# The flags the tool is driven with, and the one place they are spelled. ``-p`` is what makes
# `claude` non-interactive (ruling 4); permissions are skipped because the tool is running in a
# container whose filesystem is the throwaway workspace and whose network reaches one endpoint,
# so a prompt nobody can answer would simply be the trial timing out.
#
# *Unverified:* these are the flags the CLI is documented to take, and M3's live run (WP8) is
# the first thing that exercises them. If they are wrong, this tuple is what changes; the
# harvest around it is a contract (ADR-0038) and does not.
_PRINT_FLAG: Final = "-p"
_MODEL_FLAG: Final = "--model"
_TOOL_FLAGS: Final[tuple[str, ...]] = ("--dangerously-skip-permissions",)

# What the tool is told beyond the task's own prompt. It is told about the test-path rule
# (ADR-0037) rather than silently refused by it, exactly as the naive baseline is: a harness
# that scores a tool ``FAILED`` for breaking a rule it never stated is measuring the harness's
# own reticence. The other two sentences describe how the work is read, not how it must be
# done - a tool free to commit is still measured correctly (the baseline is a tree), and saying
# so is cheaper than a trial spent discovering it.
_INSTRUCTIONS: Final = (
    "Fix the failing tests by editing the source files in this checkout, in place. Change "
    "source files only - a diff that touches a test file is refused, because the tests are the "
    "measurement. Your work is read out of the tree when you exit, so nothing needs to be "
    "committed and anything you leave behind is part of what is recorded. The environment is "
    "already the one the tests are run in; do not install anything."
)


class AgenticCliAdapter:
    """Drives one command-line tool over a workspace, and records the tree it left behind."""

    name: str = "agentic"
    # The model *is* half of this tool. A report that could not say which one answered could
    # not say what it measured, so it is written into the version beside the version of the
    # harness code that framed the call. What is *not* in it is the CLI's own version: the
    # adapter never runs the tool twice, and asking it would be a second failure branch for a
    # string. The pinning that matters is the image's (:mod:`assay.sandbox.image`).
    version: str

    def __init__(
        self,
        *,
        process: ToolProcess,
        executable: str,
        model: str,
        env: Mapping[str, str],
    ) -> None:
        self._process = process
        self._executable = executable
        self._model = model
        # Complete and never merged with the ambient one: what a tool under evaluation may see
        # - :func:`assay.host.minimal_env` plus, for a model-backed tool, the one key name - is
        # decided where the tool is configured, and this adapter adds nothing to it and reads
        # nothing out of it (plan section 7a).
        self._env = dict(env)
        self.version = f"{_HARNESS_VERSION}+{model}"

    def run(self, task: Task, workspace: Path, budget: Budget, *, trial_index: int) -> Attempt:
        """Workspace is a repo checked out at the task's base state, tests already
        failing. Return the diff produced, plus token and latency accounting.

        ``workspace`` is the tool's to write: it is a throwaway checkout that no measurement
        happens in (ADR-0038), so whatever the tool leaves there dies with it and only the
        harvested diff crosses over. ``budget`` supplies the tool's wall clock, which is the
        ceiling it is killed at.

        A tool killed at that ceiling is **not** an error. It produced whatever it had produced
        by then, and the harvest reads it - the same reading ADR-0028 gives a cgroup kill, and
        read in the same order, before the exit code a killed process never got to choose.

        Every other failure lands in ``error``: the tool exiting non-zero, any harvest step
        exiting non-zero, or `git` answering with something that is not a tree object. All of
        them are a trial that ``ERRORED`` rather than a tool that failed, and
        :func:`assay.score.run_trial` starts no container for one. Nothing else is caught, and
        nothing raises past here.
        """
        started_ns = monotonic_ns()

        staged = self._git(workspace, "add", "-A")
        if staged.exit_code != 0:
            return self._errored(task, trial_index, started_ns, _refusal("git add -A", staged))

        recorded = self._git(workspace, "write-tree")
        if recorded.exit_code != 0:
            return self._errored(
                task, trial_index, started_ns, _refusal("git write-tree", recorded)
            )
        baseline = recorded.stdout.strip()
        if not _TREE_PATTERN.match(baseline):
            return self._errored(
                task,
                trial_index,
                started_ns,
                "the harvest's baseline is not a tree object, so there is nothing to diff against",
            )

        worked = self._process(
            self._argv(task),
            cwd=workspace,
            timeout_s=budget.max_wall_clock_s,
            env=self._env,
        )
        # Timed out first, then the exit code: a process killed at its ceiling never chose one.
        if not worked.timed_out and worked.exit_code != 0:
            return self._errored(
                task,
                trial_index,
                started_ns,
                f"the tool exited {worked.exit_code}. Its output is not recorded, because it "
                "is model text rather than measurement",
            )

        restaged = self._git(workspace, "add", "-A")
        if restaged.exit_code != 0:
            return self._errored(task, trial_index, started_ns, _refusal("git add -A", restaged))

        # No pathspec, and none may ever be added here (ADR-0038).
        harvested = self._git(workspace, "diff", "--binary", "--cached", baseline)
        if harvested.exit_code != 0:
            return self._errored(
                task, trial_index, started_ns, _refusal("git diff --binary --cached", harvested)
            )
        return self._attempt(
            task,
            trial_index=trial_index,
            started_ns=started_ns,
            diff=harvested.stdout,
            error=None,
        )

    def _argv(self, task: Task) -> tuple[str, ...]:
        """The tool's command line: the task, the model, and nothing the shell could read.

        Already split, because :class:`assay.adapters.process.ToolProcess` never takes a
        command string. The API key is not here and never will be - it reaches the tool through
        the environment alone, because an argv is readable by every process on the host that
        runs it (plan section 7a).
        """
        return (
            self._executable,
            _PRINT_FLAG,
            f"{task.prompt}\n\n{_INSTRUCTIONS}",
            _MODEL_FLAG,
            self._model,
            *_TOOL_FLAGS,
        )

    def _git(self, workspace: Path, *args: str) -> ProcessOutput:
        """One harvest step, through the same seam the tool goes through.

        The adapter has one seam and uses it for both, which is what keeps this module free of
        every process and every socket: whether `git` and the tool run in the same place is a
        question about the binding, not about the harvest.
        """
        return self._process(
            ("git", *args),
            cwd=workspace,
            timeout_s=_HARVEST_TIMEOUT_S,
            env=self._env,
        )

    def _errored(self, task: Task, trial_index: int, started_ns: int, error: str) -> Attempt:
        """A trial that produced nothing usable, with no diff to show for it."""
        return self._attempt(
            task,
            trial_index=trial_index,
            started_ns=started_ns,
            diff=_NO_DIFF,
            error=error,
        )

    def _attempt(
        self,
        task: Task,
        *,
        trial_index: int,
        started_ns: int,
        diff: str,
        error: str | None,
    ) -> Attempt:
        """The one place this adapter builds an attempt, so every exit records the same fields."""
        return Attempt(
            schema_version=1,
            adapter_name=self.name,
            adapter_version=self.version,
            task_id=task.task_id,
            trial_index=trial_index,
            diff=diff,
            # Stated zeros, not measured ones. The tool's token accounting is only available by
            # parsing its output format, which is not a stable contract, and a harness that
            # invented the number would be reporting an estimate as a measurement. M3's token
            # column is the naive baseline's; SPEC section 7 puts cost accounting in M4, which
            # is where this is answered properly.
            input_tokens=0,
            output_tokens=0,
            # Measured around the whole trial, harvest included: that is what the tool cost the
            # harness. Floor division: sub-millisecond work reports the 0 ms it took.
            wall_clock_ms=(monotonic_ns() - started_ns) // _NS_PER_MS,
            # Same reason as the tokens: an agent loop's turns are in its output, not in its
            # exit status, and counting them would mean parsing that output.
            tool_calls=0,
            # One invocation, no retry: n trials per task is how this harness measures variance
            # (SPEC section 4), and a hidden retry inside one of them would flatter the tool.
            retries=0,
            # M3 records tokens and not money; ADR-0010's trigger for cost work has not fired.
            cost_usd=_NO_COST,
            error=error,
        )


def _refusal(step: str, output: ProcessOutput) -> str:
    """How a failed harvest step is written down: what ran, what it answered, and why it stopped.

    `git`'s own stderr is quoted, bounded, because a harvest step failing is Assay's machinery
    failing and the message is the only thing a reader could act on. The tool's output is never
    quoted anywhere - it is model text, and this function is deliberately not reachable with it.
    """
    quoted = _quoted(output.stderr)
    if output.timed_out:
        return f"the harvest step `{step}` was killed before it answered"
    return f"the harvest step `{step}` exited {output.exit_code}{quoted}"


def _quoted(stderr: str) -> str:
    """A bounded tail of a step's own error output, or nothing when it said nothing."""
    trimmed = stderr.strip()
    if not trimmed:
        return ""
    return f": {trimmed[-_MAX_QUOTED_STDERR:]}"
