"""The four commands SPEC §6 publishes, and the one of them M0 can actually run.

The surface is declared whole from M0 even though three quarters of it is unbuilt. A command
that does not exist yet is reachable, names the milestone that builds it and exits non-zero,
so a script driving Assay fails loudly rather than reading silence as a result - which is the
milestone discipline in CLAUDE.md expressed in exit codes.

This module is where Assay owns two output streams, and it is the only one. Everything below
it returns strings and lets its caller decide where they go: :func:`~assay.report.render_json`
in particular must not print the placeholder admission, because prose inside the canonical
document would freeze one wording as a compatibility promise (the flag
``intervals_are_placeholders`` is the machine-readable half, and it stays in the schema). So
the obligation lands here: the notice goes to stderr, the document goes to stdout, and
``assay report --format json > out.json`` leaves a file that parses *and* a human who was
still told the intervals were invented.

Thin by design: parse arguments, call the pipeline, choose a stream and an exit code. No
scoring, no statistics and no rule of its own - a command that computed anything would put
logic somewhere no test in ``tests/report``, ``tests/results`` or ``tests/mine`` can see it.
``mine`` and ``validate`` do reach the outside world, because somebody has to: this module is
the only place allowed to know both :mod:`assay.mine` (which must never learn that uv and
pytest exist) and :mod:`assay.host` (which implements them), so the closure that bridges the
two is written here and nowhere else.

That bridge is also why this module carries a warning banner. Provisioning a workspace runs
``uv pip install -e .`` inside a checkout of the repository being mined, which executes that
repository's own build hooks as the invoking user, and its tests then run the same way. The
exposure is deliberate and bounded - :mod:`assay.host` starts every process without a shell,
without the ambient environment and under a timeout, and SPEC §5.2's container lands in M2 -
but until now nothing in the surface *said* so, and a security posture a user can only find by
reading the source is not one they were told.
"""

import argparse
import sys
import tempfile
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path

from assay.core import AssayError, NotImplementedInMilestone
from assay.host import (
    EnvironmentSetupError,
    GitHistory,
    PytestHostRunner,
    provision_venv,
)
from assay.mine import (
    GateOutcome,
    GateRejection,
    MinedCommit,
    MiningYield,
    TestRunner,
    mine_suite,
    revalidate_suite,
    revalidates,
    tally_yield,
)
from assay.report import (
    STUB_INTERVAL_NOTICE,
    RedactionPolicy,
    Report,
    build_report,
    redact,
    render_html,
    render_json,
    render_text,
    summarise,
)
from assay.results import read_result_set
from assay.suite import SuiteBody, Task, load_suite, save_suite

# The milestone this build is. Quoted in every "not implemented" message, so one edit moves
# the whole surface forward when M1 lands.
MILESTONE = "M1"

# Where each unbuilt command is scheduled (SPEC §7). Only `run` is left: it needs adapters and
# n-trial execution, which is M3 - not M2, which builds the sandbox and scoring underneath it
# but no end-to-end run.
PLANNED: dict[str, str] = {
    "run": "M3",
}

# One line of help per unbuilt command: what it will do, so `assay --help` reads as a map of
# the tool rather than a list of errors.
_UNBUILT_HELP: dict[str, str] = {
    "run": "Run a suite against one or more adapters, n trials per task.",
}

type Renderer = Callable[[Report], str]

RENDERERS: dict[str, Renderer] = {
    "json": render_json,
    "text": render_text,
    "html": render_html,
}

# The default is the human format, because the person who typed no flag is at a terminal;
# a machine consumer names `--format json` and gets the canonical document, unmixed with the
# admission that stderr carries for the human. Defaulting to JSON would optimise for the
# caller that is already explicit at the expense of the one who is not.
DEFAULT_FORMAT = "text"

# Success.
EXIT_OK = 0
# The command ran and could not finish - an unreadable result set, most of them.
EXIT_FAILED = 1
# argparse's own code for a malformed command line. Named here only so the three do not
# collide; argparse exits with it directly and this module never returns it.
EXIT_USAGE = 2
# The command exists in the surface but not in this milestone. Distinct from EXIT_FAILED so a
# script can tell "Assay cannot do this yet" from "Assay tried and failed".
EXIT_NOT_IMPLEMENTED = 3

# The ceiling on **one** test run, and what `--test-timeout-s` defaults to. Three runs happen
# per candidate, so it is not a budget for the whole gate; it is the point at which a hanging
# test is killed and the candidate discarded as `run_timed_out`. Five minutes because a run is
# a *selection* - the test files one commit touched, never the repository's whole suite - and a
# selection that has not finished in five minutes is hung rather than slow. A repository with a
# genuinely slower suite says so with the flag; guessing higher would make every hanging
# candidate cost that guess three times over.
DEFAULT_TEST_TIMEOUT_S = 300

# Wall clock for `uv venv` plus the editable install of one workspace. Not a flag: provisioning
# is seconds with a warm uv cache and can be a minute cold (`assay.host.venv` measures both),
# and neither number is a property of the commit being mined - so this is a ceiling on a hang,
# and a knob for it would be a knob nobody could set from evidence.
PROVISION_TIMEOUT_S = 600

# The one sentence of the warning below that also appears in the README, so the two say the
# same thing in the same words. A warning worded twice is a warning a reader cannot match to
# what they were told.
HOST_EXECUTION_SENTENCE = (
    "mining a repository runs that repository's build and tests on your machine"
)

# Printed to stderr before anything belonging to the target repository is executed, by both
# commands that execute any. A statement, not a gate: there is deliberately no `--yes` flag and
# no prompt, because a confirmation nobody can answer would break the scripted use this surface
# exists for, and because the decision to run on the host in M1 is settled rather than the
# user's to make (SPEC §5.2 - the container is M2's).
HOST_EXECUTION_NOTICE = (
    "assay: this command runs the target repository's own build and test suite on this "
    "machine, outside a sandbox - provisioning a workspace executes that repository's "
    "packaging hooks as you, and its tests then run the same way. Point it only at a "
    "repository you would already run locally. Sandboxed execution lands in M2 (SPEC 5.2)."
)

# What a suite file records as its maker, read from the installed distribution rather than
# retyped - a version bump must not leave a suite claiming it was made by the previous build.
GENERATOR = f"assay/{version('assay')}"


def _walk_limit(raw: str) -> int:
    """Parse ``--limit``, refusing the values git reads as *no limit at all*.

    ``git log --max-count -1`` is neither an error nor a walk of one commit: it walks the
    entire history. So a mistyped ``assay mine --limit -1`` would silently turn the smallest
    run a user can ask for into the largest one, and every commit of it provisions an
    environment and runs the target repository's own build hooks and tests on this machine
    (ADR-0013). Zero is the same mistake from the other side: a walk of nothing, reported as a
    repository holding no red->green commit.

    A bare ``type=int`` cannot say this, so the refusal is spelled here and raised as
    :class:`argparse.ArgumentTypeError` rather than returned - that keeps it argparse's own
    error, printed to stderr above the usage line and exited with :data:`EXIT_USAGE`, like
    every other malformed command line. The non-integer case is caught only to keep the
    message about commits rather than about the name of this function.
    """
    try:
        limit = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a whole number of commits, got {raw!r}"
        ) from None
    if limit < 1:
        raise argparse.ArgumentTypeError(
            f"must be at least 1, got {limit}: git reads a limit below one as no limit at all, "
            "and would walk the whole history"
        )
    return limit


def _test_timeout_seconds(raw: str) -> int:
    """Parse ``--test-timeout-s``, refusing a ceiling no run can actually be held to.

    A budget below one second is not a shorter run, because nothing downstream can honour it:
    :func:`assay.host.pytest_runner._remaining` floors every pytest invocation at one second,
    so ``--test-timeout-s 0`` and ``--test-timeout-s -1`` both arrive at the process layer as
    one. The flag would then quietly mean something other than what it says, and what it came
    to mean would be *nothing a caller could predict* - with a one-second ceiling, whether a
    candidate comes back accepted or ``run_timed_out`` turns on how fast this machine is rather
    than on the commit, and the same command line on two machines mines two different suites.
    That is the one thing a content-addressed suite may not be (SPEC §5.5), and it is worse
    than an outright zero yield would have been, because the run that produced it looks fine.

    Sibling to :func:`_walk_limit` rather than a shared core it parameterises: the two agree on
    ``< 1`` and on nothing else, and the whole of each is its reason - git's unlimited walk
    there, an unhonourable ceiling here. A function taking the message as an argument would
    keep six lines of parsing and move the part worth reading to the call site.

    Raised as :class:`argparse.ArgumentTypeError` for the same reason as ``--limit``: the
    refusal stays argparse's own, on stderr above the usage line, at :data:`EXIT_USAGE`, and it
    lands before either command has executed anything belonging to the target repository.
    """
    try:
        seconds = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a whole number of seconds, got {raw!r}"
        ) from None
    if seconds < 1:
        raise argparse.ArgumentTypeError(
            f"must be at least 1, got {seconds}: a test run is floored at one second, so a "
            "lower ceiling is not honoured - it would make the yield a property of this "
            "machine's speed rather than of the history"
        )
    return seconds


def build_parser() -> argparse.ArgumentParser:
    """Build the whole command surface, the unbuilt command included.

    `run` is registered as a real subcommand rather than omitted: `assay --help` showing the
    four commands is M0's stated exit criterion (SPEC §7) and it should show what Assay is
    going to be, and a user who types `assay run` deserves a schedule instead of "invalid
    choice". The subcommands are registered in SPEC §6's order rather than alphabetically,
    because that order is the pipeline: mine, validate, run, report.
    """
    parser = argparse.ArgumentParser(
        prog="assay",
        description=(
            "Evaluate AI coding tools against a suite mined from a repository's own history."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command", required=True)

    mine = subparsers.add_parser(
        "mine",
        help="Mine an evaluation suite from a repository's own git history.",
        description="Mine an evaluation suite from a repository's own git history. Every "
        f"candidate is put through the red->green gate, and {HOST_EXECUTION_SENTENCE}.",
    )
    mine.add_argument(
        "--repo",
        type=Path,
        required=True,
        metavar="PATH",
        help="An existing local clone to mine. Assay never clones and never fetches: the "
        "repository under evaluation does not leave the machine, and it is never written to.",
    )
    mine.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="PATH",
        help="Where to write the suite file. Required: a suite left somewhere nobody named "
        "would be a guess.",
    )
    mine.add_argument(
        "--name",
        default=None,
        metavar="NAME",
        help="What to call the suite, and what its task ids are prefixed with "
        "(default: the repository directory's name).",
    )
    mine.add_argument(
        "--limit",
        type=_walk_limit,
        default=None,
        metavar="N",
        help="Ask the walk for only the newest N commits (default: all of them). Merges are "
        "not counted against it, and a walk that reaches the root commit examines one fewer "
        "than it asked for: neither has a parent to be read against.",
    )
    mine.add_argument(
        "--test-timeout-s",
        type=_test_timeout_seconds,
        default=DEFAULT_TEST_TIMEOUT_S,
        metavar="SECONDS",
        help=f"Ceiling on one test run, of the three each candidate needs "
        f"(default: {DEFAULT_TEST_TIMEOUT_S}). A run that hits it is discarded as "
        "run_timed_out and counted.",
    )

    validate = subparsers.add_parser(
        "validate",
        help="Re-check a suite against the red-green gate and report what still holds.",
        description="Put every task in a suite back through the byte-identical gate that "
        "minted it. Exits non-zero if any task no longer reproduces the sets it records.",
    )
    validate.add_argument(
        "--suite",
        type=Path,
        required=True,
        metavar="PATH",
        help="The suite file to re-check.",
    )
    validate.add_argument(
        "--repo",
        type=Path,
        required=True,
        metavar="PATH",
        help="The local clone the suite's base commits live in.",
    )
    validate.add_argument(
        "--test-timeout-s",
        type=_test_timeout_seconds,
        default=DEFAULT_TEST_TIMEOUT_S,
        metavar="SECONDS",
        help=f"Ceiling on one test run (default: {DEFAULT_TEST_TIMEOUT_S}).",
    )

    for command in _UNBUILT_HELP:
        subparsers.add_parser(
            command,
            help=f"{_UNBUILT_HELP[command]} Not implemented in {MILESTONE}; "
            f"planned for {PLANNED[command]}.",
            description=_UNBUILT_HELP[command],
        )

    report = subparsers.add_parser(
        "report",
        help="Render a report from a recorded result set.",
        description="Render a redacted report from a recorded result set.",
    )
    report.add_argument(
        "--results",
        type=Path,
        required=True,
        metavar="PATH",
        help="Result-set file to report on. Required: reporting on a file nobody named "
        "would be a guess.",
    )
    report.add_argument(
        "--format",
        choices=sorted(RENDERERS),
        default=DEFAULT_FORMAT,
        help=f"Output format (default: {DEFAULT_FORMAT}).",
    )
    return parser


def _report_document(results: Path, fmt: str) -> tuple[Report, str]:
    """Read a result set and return the report and its rendering, redacted.

    Redaction is applied here with a policy drawn fresh per invocation, so two runs over one
    file produce different tokens and neither can be joined to the other (SPEC §5.4). There is
    no flag to skip it: an opt-out would make redaction something a caller remembers rather
    than a property the pipeline has.
    """
    result_set = read_result_set(results)
    report = build_report(result_set, summarise(result_set))
    redacted = redact(report, RedactionPolicy.from_random())
    return redacted, RENDERERS[fmt](redacted)


def _use_lf(stream: object) -> None:
    """Pin ``stream`` to LF line endings, where the runtime allows it.

    Only a real :class:`io.TextIOWrapper` can be reconfigured. A stream a caller has replaced
    with an in-memory buffer - which is what pytest's capture does - cannot be, and does not
    need to be: it never reaches an OS newline translation layer in the first place.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(newline="\n")


def run_report(results: Path, fmt: str) -> int:
    """Print the report for ``results``, admission on stderr and document on stdout.

    The notice goes out first and flushed, so a reader watching one terminal sees the caveat
    above the numbers even when stderr is redirected somewhere block-buffered. It is written
    whenever the report says its intervals are placeholders, in every format - the text and
    HTML renderers also carry it inside their documents, and the duplication is deliberate:
    stdout may be a file the human never opens, and no renderer can know that.

    Exactly one trailing newline, whichever format: `render_json` returns the document without
    one by contract and the two prose formats end with one already.
    """
    try:
        report, document = _report_document(results, fmt)
    except (AssayError, OSError, ValueError, RecursionError) as error:
        # ValueError covers both halves of "the file is not a result set": json's decode error
        # and pydantic's ValidationError, which subclasses it. RecursionError is neither, but
        # deeply nested JSON raises it out of the decoder, and unreadable input owes the caller
        # one sentence and EXIT_FAILED whatever shape the refusal arrives in. The path is
        # repeated in our own words because not every one of these errors names it.
        print(f"assay report: cannot read {results}: {error}", file=sys.stderr)
        return EXIT_FAILED

    # LF on every platform, not the host's. RULING 4 owes stderr the notice byte-for-byte,
    # and a report rendered on Windows must be the same bytes as one rendered on the ubuntu
    # runner - the same reason every file write in this repo pins ``newline="\n"``. In-process
    # test capture never crosses a translation layer, so only this guards the real streams.
    _use_lf(sys.stderr)
    _use_lf(sys.stdout)

    if report.intervals_are_placeholders:
        print(STUB_INTERVAL_NOTICE, file=sys.stderr, flush=True)

    sys.stdout.write(document if document.endswith("\n") else document + "\n")
    return EXIT_OK


def host_runner_for(workspace: Path) -> TestRunner | None:
    """Give ``workspace`` an environment its tests can run in, or admit that nothing can.

    The whole of what :mod:`assay.mine` is not allowed to know, and the reason
    :data:`assay.mine.RunnerFactory` is a callable rather than a runner: a workspace is a
    worktree the gate has only just made, so its environment cannot be provisioned any earlier
    than here.

    ``None`` rather than a raised ``EnvironmentSetupError``, and this is the seam that decides
    it. Provisioning happens per commit, so a repository mined back past the commit that
    introduced its packaging has commits that simply cannot be installed; a walk that died on
    the first of them would report no yield at all. Catching it here is also what keeps
    ``assay.mine`` from importing ``assay.host`` - the miner counts the commit as
    ``unprovisioned`` and keeps walking, and never learns that uv exists.
    """
    try:
        python = provision_venv(workspace, timeout_s=PROVISION_TIMEOUT_S)
    except EnvironmentSetupError:
        return None
    return PytestHostRunner(python)


def run_mine(*, repo: Path, out: Path, name: str | None, limit: int | None, timeout_s: int) -> int:
    """Mine ``repo`` into a suite at ``out``, progress on stderr and the yield on stdout.

    A yield of zero is still a suite and still exits 0: a repository whose history holds no
    red->green commit is a finding about that repository, honestly reported (decision D9,
    spelled out in :mod:`assay.mine`'s module docstring). Only git, uv or the filesystem
    refusing is a failure of the tool.

    The mined commits are materialised because they are read twice - once for the tasks, once
    for the tally - but they are *printed* as they arrive: mining a real repository is minutes
    of work, and a command that says nothing for minutes is indistinguishable from a hung one.
    """
    _use_lf(sys.stderr)
    _use_lf(sys.stdout)
    print(HOST_EXECUTION_NOTICE, file=sys.stderr, flush=True)

    slug = name if name is not None else repo.resolve().name
    mined: list[MinedCommit] = []
    try:
        # The worktrees live outside both the clone and the output directory, and go with the
        # run: a checkout of the repository under evaluation is the largest thing this command
        # creates, and leaking one per interrupted run fills a disk quietly.
        with tempfile.TemporaryDirectory(prefix="assay-mine-") as scratch:
            history = GitHistory(repo, worktree_root=Path(scratch))
            for found in mine_suite(
                history=history,
                runner_for=host_runner_for,
                repo_slug=slug,
                limit=limit,
                timeout_s=timeout_s,
            ):
                mined.append(found)
                print(_examined_line(len(mined), found), file=sys.stderr, flush=True)
        body = SuiteBody(schema_version=1, suite_name=slug, tasks=_mined_tasks(mined))
        save_suite(out, body, generator=GENERATOR)
    except (AssayError, OSError) as error:
        # OSError as well as Assay's own: a repository path that is not there fails inside
        # ``subprocess`` before git is ever asked anything, and "no such repository" owes the
        # caller one sentence rather than a traceback.
        print(f"assay mine: cannot mine {repo}: {error}", file=sys.stderr)
        return EXIT_FAILED

    print(f"assay mine: wrote {len(body.tasks)} tasks to {out}", file=sys.stderr)
    for line in _yield_lines(tally_yield(found.outcome for found in mined)):
        print(line)
    return EXIT_OK


def run_validate(*, suite_path: Path, repo: Path, timeout_s: int) -> int:
    """Re-prove every task in ``suite_path`` against ``repo``; exit 0 only if all of them hold.

    The other half of decision D9's asymmetry. A suite is a claim that these commits went red
    to green, and a claim that has stopped being true - an environment that drifted, a
    dependency that moved - is exactly what this project exists to catch before a tool is
    scored against it, so one task that no longer revalidates fails the command.

    Validity is :func:`assay.mine.revalidates` and nothing weaker. This function formats the
    difference between a task the gate rejected, a task no environment could be built for and
    a task whose recorded sets drifted; it does not decide which of them counts.
    """
    _use_lf(sys.stderr)
    _use_lf(sys.stdout)
    print(HOST_EXECUTION_NOTICE, file=sys.stderr, flush=True)

    try:
        suite = load_suite(suite_path)
    except (AssayError, OSError, ValueError, RecursionError) as error:
        # The same four ``run_report`` catches, for the same reason: an unreadable document
        # arrives as json's decode error, pydantic's ValidationError (a ValueError), a
        # RecursionError out of deeply nested input, or one of Assay's own refusals.
        print(f"assay validate: cannot read {suite_path}: {error}", file=sys.stderr)
        return EXIT_FAILED

    checked: list[bool] = []
    try:
        with tempfile.TemporaryDirectory(prefix="assay-validate-") as scratch:
            history = GitHistory(repo, worktree_root=Path(scratch))
            for task, outcome in revalidate_suite(
                suite=suite.body,
                history=history,
                runner_for=host_runner_for,
                timeout_s=timeout_s,
            ):
                valid = revalidates(task, outcome)
                checked.append(valid)
                print(_revalidated_line(task, outcome, valid), file=sys.stderr, flush=True)
    except (AssayError, OSError) as error:
        print(f"assay validate: cannot validate against {repo}: {error}", file=sys.stderr)
        return EXIT_FAILED

    held = sum(checked)
    print(f"{held} of {len(checked)} tasks revalidate")
    return EXIT_OK if held == len(checked) else EXIT_FAILED


def _mined_tasks(mined: Sequence[MinedCommit]) -> tuple[Task, ...]:
    """The accepted commits' tasks, in the one order a suite may be written in.

    Sorted by task id because :class:`assay.suite.SuiteBody` refuses any other - the digest
    addresses the bytes, so two orderings of one task set would be two addresses for it - and
    the walk's order is newest-first, which is not it.
    """
    return tuple(
        sorted(
            (found.task for found in mined if found.task is not None),
            key=lambda task: task.task_id,
        )
    )


def _yield_lines(tallied: MiningYield) -> tuple[str, ...]:
    """Render the yield, which CLAUDE.md forbids reporting as a bare count of accepted tasks.

    Rendering lives here and not on :class:`assay.mine.MiningYield`, because a value that knows
    how to print itself has an opinion about a stream, and this module is the only one in Assay
    allowed one.

    The arrow is ASCII, where SPEC writes it as an arrow character: nothing in ``src/`` is
    non-ASCII, this line goes to a Windows console whose code page is routinely not UTF-8, and
    the repository already spells the gate ``red->green`` in prose.

    Three lines rather than one, because the yield is three claims. What was walked and what
    survived it; the two populations that are not rejections - the commits no environment could
    be built for, and the merges and the root commit the walk never yielded at all (ADR-0015);
    and a count for every rejection reason, zeros included, since "never fired" and "not looked
    for" must not read as the same document.
    """
    reasons = ", ".join(f"{reason.value} {tallied.rejected[reason]}" for reason in GateRejection)
    return (
        f"{tallied.commits_examined} single-parent commits examined -> "
        f"{tallied.accepted} valid tasks",
        f"{tallied.candidates} candidates reached the gate, "
        f"{tallied.unprovisioned} unprovisioned; "
        "merges and the root commit are not examined at all",
        f"rejected: {reasons}",
    )


def _examined_line(index: int, found: MinedCommit) -> str:
    """One examined commit, as it is decided. Subject last: it is the only ragged field."""
    verdict = _verdict(found.outcome)
    return f"[{index:>4}] {found.commit.sha[:12]} {verdict}: {found.commit.subject}"


def _revalidated_line(task: Task, outcome: GateOutcome | None, valid: bool) -> str:
    """One re-checked task, and - when it did not hold - which of the three ways it did not.

    An accepting outcome that crossed a different set of tests than the task records is the
    interesting failure and the one a bare verdict would hide, so it is named in words.
    """
    if valid:
        return f"{task.task_id} revalidates"
    drifted = outcome is not None and outcome.rejection is None
    reason = "the gate accepted a different set of tests" if drifted else _verdict(outcome)
    return f"{task.task_id} DOES NOT REVALIDATE: {reason}"


def _verdict(outcome: GateOutcome | None) -> str:
    """What the gate said about one commit, including its never having been asked."""
    if outcome is None:
        return "unprovisioned"
    return "accepted" if outcome.rejection is None else outcome.rejection.value


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``assay`` console script; returns the process exit code.

    ``argv`` defaults to the real command line and is a parameter so tests can drive the whole
    surface in-process, without a shell and without depending on the script being installed.

    ``NotImplementedInMilestone`` is raised by the unbuilt commands and caught here rather
    than avoided: raising is what an in-process caller should see, and turning it into a line
    on stderr plus an exit code is exactly this module's job.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    command: str = args.command

    try:
        if command == "mine":
            return run_mine(
                repo=args.repo,
                out=args.out,
                name=args.name,
                limit=args.limit,
                timeout_s=args.test_timeout_s,
            )
        if command == "validate":
            return run_validate(
                suite_path=args.suite, repo=args.repo, timeout_s=args.test_timeout_s
            )
        if command == "report":
            results: Path = args.results
            fmt: str = args.format
            return run_report(results, fmt)
        raise NotImplementedInMilestone(command, MILESTONE, PLANNED[command])
    except NotImplementedInMilestone as error:
        print(error, file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
