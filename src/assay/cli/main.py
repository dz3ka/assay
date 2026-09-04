"""The four commands SPEC §6 publishes, all four of them now built.

The surface was declared whole from M0 and filled in a milestone at a time: until a command
existed it was still reachable, named the milestone that would build it and exited non-zero,
so a script driving Assay failed loudly rather than reading silence as a result. M3 built the
last of them, ``run``, and the machinery for scheduling an unbuilt one is left in place
(:data:`PLANNED`, :data:`_UNBUILT_HELP`) rather than deleted - not because a fifth command is
coming, since SPEC §6 publishes four and §7's M5 adds none, but because deleting it would
retire :data:`EXIT_NOT_IMPLEMENTED` from a surface that has published it since M0. That is a
compatibility decision, and it is taken at M5's release freeze rather than here (ADR-0047).

What the surface says about itself is ``--version``, on the top-level parser alone: the build
is a fact about the installation, not about a command, and the line it prints leads with the
same token every suite records as its ``generator``.

This module is where Assay owns two output streams, and it is the only one. Everything below
it returns strings and lets its caller decide where they go: a renderer never writes, and this
module never computes. The division is what keeps ``assay report --format json > out.json``
honest - the canonical document goes to stdout and carries no prose, because a sentence inside
it would freeze one wording as a compatibility promise, and anything a human is owed alongside
the numbers is a caption in the two formats written for one.

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
import os
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from importlib.metadata import version
from pathlib import Path

from pydantic import ValidationError

from assay.adapters import (
    Adapter,
    AgenticCliAdapter,
    GroundTruthAdapter,
    NaiveBaselineAdapter,
    NullAdapter,
    ProcessOutput,
    ToolProcess,
)
from assay.core import AssayError, NotImplementedInMilestone
from assay.host import (
    CommandTimeoutError,
    EnvironmentSetupError,
    GitHistory,
    HttpModelTransport,
    PytestHostRunner,
    minimal_env,
    provision_venv,
    run_command,
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
    PriceTable,
    RedactionPolicy,
    Report,
    ToolPrice,
    build_report,
    redact,
    render_html,
    render_json,
    render_text,
    summarise,
)
from assay.results import Budget, Result, ResultSet, read_result_set, write_result_set
from assay.sandbox import (
    AGENT_EXECUTABLE,
    ContainerLimits,
    adapter_phase_command,
    build_agent_image,
    build_task_image,
    sandbox_runner_for,
)
from assay.score import run_trial
from assay.suite import SuiteBody, Task, load_suite, save_suite

# The milestone this build is, and the only thing in the tree that can say so. The package
# version has read 0.1.0 since M0 and will keep reading it until something is released, so it
# cannot tell M0's four-command skeleton apart from this harness - which is why `--version`
# prints both (ADR-0047). Also quoted in every "not implemented" message, so one edit moves the
# whole surface forward.
MILESTONE = "M4"

# Where each unbuilt command is scheduled (SPEC §7). Empty since M3 built `run`, which was the
# last of the four, and empty for good: SPEC §6 publishes exactly four commands and §7's M5
# adds none. Kept rather than deleted because deleting it retires exit code 3 from a published
# surface - a compatibility decision, deferred to M5's release freeze (ADR-0047).
PLANNED: dict[str, str] = {}

# One line of help per unbuilt command: what it would do, so `assay --help` reads as a map of
# the tool rather than a list of errors.
_UNBUILT_HELP: dict[str, str] = {}

type Renderer = Callable[[Report], str]

RENDERERS: dict[str, Renderer] = {
    "json": render_json,
    "text": render_text,
    "html": render_html,
}

# The default is the human format, because the person who typed no flag is at a terminal; a
# machine consumer names `--format json` and gets the canonical document, without the captions
# the two prose formats carry for a reader. Defaulting to JSON would optimise for the caller
# that is already explicit at the expense of the one who is not.
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

# The ceiling put on one model call's completion, and the only cap that costs money if it is
# wrong in the generous direction. A task's answer is a unified diff over the files one commit
# touched, which is hundreds of lines at the outside, so this is roomy rather than tight - a
# diff truncated mid-hunk is a trial spent for nothing, while a cap nobody reaches costs
# nothing at all. A module constant and not a flag: it is a property of what an answer looks
# like, not of the run, and a flag with no second reader would be dead wiring (SPEC §6's
# surface is fixed and does not carry one).
DEFAULT_MAX_OUTPUT_TOKENS = 8192

# What a tool killed at its wall-clock budget reports as an exit code. A killed process never
# chose one; the value is negative so it cannot be mistaken for a status the tool set itself,
# and `ProcessOutput.timed_out` is the field that is read first. The same convention, and the
# same number, as `assay.host.pytest_runner`'s.
TOOL_KILLED_EXIT_CODE = -1

# How many trials of one task one adapter gets, and the n that pass^n is read against. Five
# because CLAUDE.md fixes it: a single trial of a nondeterministic tool is an anecdote, and
# pass^n over one trial is pass@1 wearing a stricter name.
DEFAULT_TRIALS = 5

# Wall clock for one trial: the ceiling the tool is killed at, and the ceiling on the test runs
# that measure what it left. Fifteen minutes because an agentic tool works in turns - it reads
# files, runs commands and thinks between them - and a budget that kills the median attempt
# measures the budget instead of the tool. A run that needs longer says so with the flag.
DEFAULT_TRIAL_TIMEOUT_S = 900

# Which model both real adapters ask for when the caller names none. It is a flag rather than a
# constant alone because the model *is* half of what a report measures - it is written into
# every adapter's version string - so a run that compared two of them has to be able to say so.
# An alias rather than a dated snapshot, and current rather than the generation it was written
# on: an unflagged run is what a reader reproducing this repo gets, so the default is the
# recommendation (ADR-0041).
DEFAULT_MODEL = "claude-sonnet-5"

# Where the naive baseline's one call goes (ruling 6). Not a flag: the host is allowlisted in
# `assay.host.model_api` and a second endpoint is a decision with an ADR behind it, not a
# command line the prompt - which carries the repository under evaluation - can be redirected
# with.
MODEL_ENDPOINT = "https://api.anthropic.com/v1/messages"

# The two names one API key travels under, and the rename happens here and nowhere else. Assay
# reads its own name so that a machine holding a key for something else does not silently spend
# it; the agentic tool reads the vendor's, because that is what the CLI being measured looks
# for. Neither the adapter nor `assay.sandbox` learns either name - the adapter is handed an
# environment and the sandbox is handed a name to pass through - so this line is the whole of
# the mapping (plan §7a).
MODEL_API_KEY_ENV = "ASSAY_MODEL_API_KEY"
TOOL_API_KEY_ENV = "ANTHROPIC_API_KEY"

# What a trial's containers may consume - both phases, the tool's and the measurement's.
# `assay.sandbox.ContainerLimits` deliberately carries no defaults, so the shipped numbers live
# here, at the call site that starts containers. Two gibibytes and two CPUs because the
# measurement phase runs a repository's own test selection and the adapter phase runs a node
# toolchain over it; the process ceiling is what a fork bomb in a mined test runs into.
TRIAL_LIMITS = ContainerLimits(memory_mb=2048, cpus="2", pids=512)

# Wall clock for building one task image, and for the agent image layered over it. Half an hour
# because a cold build pulls a base image, resolves the repository's whole dependency tree as of
# the commit's own date, and - for a run naming the agentic adapter - installs a node toolchain
# on top. Warm, both are re-tags of layers BuildKit already holds.
IMAGE_BUILD_TIMEOUT_S = 1800

# The version of the agentic CLI pinned into the agent image, or ``None`` for whatever the
# registry serves today. ``None`` is honest rather than convenient: it says the image address
# does not capture which build of the tool is inside. Pin it to the version M3's live run
# observes as soon as there is one (:func:`assay.sandbox.render_agent_dockerfile`).
AGENT_TOOL_VERSION: str | None = None

# Every adapter `--adapter` accepts, in the order a report reads best: the two oracles that
# bracket the scale, then the baseline, then the tool. The names are the adapters' own, so a
# result set cannot name a tool the CLI would not run.
ADAPTER_NAMES: tuple[str, ...] = (
    GroundTruthAdapter.name,
    NullAdapter.name,
    NaiveBaselineAdapter.name,
    AgenticCliAdapter.name,
)

# The two adapters that are not tools. They answer from the task itself - the recorded fix, and
# nothing at all - so a run of the pair measures the harness rather than anything a baseline
# could be compared against, which is why they alone are exempt from the rule below.
ORACLE_ADAPTERS = frozenset({GroundTruthAdapter.name, NullAdapter.name})

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
    "repository you would already run locally. Sandboxed execution covers evaluation "
    "trials, not mining (SPEC 5.2)."
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


def _trial_count(raw: str) -> int:
    """Parse ``--trials``, refusing a run that would measure nothing and report it anyway.

    Zero trials is not a cheaper run: it writes a result set in which every tool was named and
    none was measured, and a report over it prints a tool that scored nothing - which reads
    exactly like a tool that failed everything. The third sibling of :func:`_walk_limit` and
    :func:`_test_timeout_seconds`, refused for its own reason and raised as argparse's own
    error, so it lands on stderr above the usage line at :data:`EXIT_USAGE`.
    """
    try:
        trials = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a whole number of trials, got {raw!r}"
        ) from None
    if trials < 1:
        raise argparse.ArgumentTypeError(
            f"must be at least 1, got {trials}: a run of no trials still reports every tool it "
            "names, and a tool that was never measured must not read as one that scored zero"
        )
    return trials


def _price_entry(raw: str) -> ToolPrice:
    """Parse one ``--price TOOL=INPUT/OUTPUT``, the only way a price ever reaches a report.

    Assay knows no prices and stores none: a rate baked into this repository would be a public
    price list nobody is maintaining, and a rate written into a result set would outlive the
    quote it came from (ADR-0046). So the numbers arrive here, on the command line, once per
    tool - repeatable because every report has at least two tools in it (CLAUDE.md's naive
    baseline is always one of them) and they are rarely billed alike.

    Two rates rather than one, per *million* tokens rather than per token. Input and output
    tokens are not billed at the same rate anywhere on the market, so a single number would
    price one of them wrong; and a per-token rate cannot be spelled at the six decimal places
    money is written to (ADR-0010) - everything under a dollar per million tokens would price
    at exactly zero.

    The fourth sibling of :func:`_walk_limit`, :func:`_test_timeout_seconds` and
    :func:`_trial_count`, refused for its own reasons and raised as
    :class:`argparse.ArgumentTypeError` rather than returned - that keeps it argparse's own
    error, on stderr above the usage line at :data:`EXIT_USAGE`. The arithmetic rules are not
    restated here: :class:`~assay.report.ToolPrice` owns what a rate may be, and this catches
    its refusal so the sentence a user reads is about a command line rather than about a model.
    """
    tool, assigned, rates = raw.partition("=")
    if not assigned or not tool:
        raise argparse.ArgumentTypeError(
            f"expected TOOL=INPUT/OUTPUT naming the tool the rates are for, got {raw!r}"
        )
    input_rate, divided, output_rate = rates.partition("/")
    if not divided:
        raise argparse.ArgumentTypeError(
            f"expected two rates as INPUT/OUTPUT for {tool!r}, got {rates!r}: input and output "
            "tokens are not billed alike, so one number cannot stand for both"
        )
    try:
        return ToolPrice(
            tool=tool,
            input_usd_per_mtok=Decimal(input_rate),
            output_usd_per_mtok=Decimal(output_rate),
        )
    except (InvalidOperation, ValidationError):
        raise argparse.ArgumentTypeError(
            f"expected TOOL=INPUT/OUTPUT with two rates in dollars per million tokens, each at "
            f"or above zero and no finer than a millionth of a dollar, got {raw!r}"
        ) from None


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
    # Built from GENERATOR rather than from a second read of the distribution's version: that
    # constant is what every suite file records as its maker, so a reader holding a suite can
    # match its `generator` against this line byte for byte. The milestone is what the package
    # version cannot say (ADR-0047). Registered before `add_subparsers` and on this parser
    # only - `action="version"` fires while options are consumed, so `assay --version` answers
    # without a subcommand, and `assay report --version` stays the usage error it should be.
    parser.add_argument(
        "--version",
        action="version",
        version=f"{GENERATOR} (milestone {MILESTONE})",
        help="Print the package version and the milestone this build implements.",
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

    run = subparsers.add_parser(
        "run",
        help="Run a suite against one or more adapters, n trials per task.",
        description="Score every task in a suite against every named adapter, n trials each, "
        "and write the trials to a result set. Each trial builds nothing on this machine that "
        "the tool can reach: the tool works in a container and the tests are run in a second "
        "one with no network at all.",
    )
    run.add_argument(
        "--suite",
        type=Path,
        required=True,
        metavar="PATH",
        help="The suite file to run. Its digest is recorded in the result set, because results "
        "are only comparable to other results from the same task set.",
    )
    run.add_argument(
        "--repo",
        type=Path,
        required=True,
        metavar="PATH",
        help="The local clone the suite's base commits live in. Read only, and never fetched.",
    )
    run.add_argument(
        "--out",
        type=Path,
        required=True,
        metavar="PATH",
        help="Where to write the result set. Required: results left somewhere nobody named "
        "would be a guess.",
    )
    run.add_argument(
        "--adapter",
        action="append",
        dest="adapters",
        required=True,
        choices=ADAPTER_NAMES,
        metavar="NAME",
        help=f"An adapter to measure; repeat the flag for each. One of: "
        f"{', '.join(ADAPTER_NAMES)}. A run naming a tool must also name "
        f"{NaiveBaselineAdapter.name}, because a tool that cannot beat one raw model call is "
        "the finding.",
    )
    run.add_argument(
        "--trials",
        type=_trial_count,
        default=DEFAULT_TRIALS,
        metavar="N",
        help=f"How many trials of each task each adapter gets (default: {DEFAULT_TRIALS}). "
        "pass^n is read against this number, so lowering it makes the headline weaker.",
    )
    run.add_argument(
        "--trial-timeout-s",
        type=_test_timeout_seconds,
        default=DEFAULT_TRIAL_TIMEOUT_S,
        metavar="SECONDS",
        help=f"Ceiling on one trial (default: {DEFAULT_TRIAL_TIMEOUT_S}) - the tool is killed "
        "at it, and the test runs that measure its work are held to it.",
    )
    run.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        metavar="NAME",
        help=f"The model the baseline and the agentic tool ask for (default: {DEFAULT_MODEL}). "
        "It is written into every adapter's recorded version: a report that could not say "
        "which model answered could not say what it measured.",
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
    report.add_argument(
        "--price",
        action="append",
        type=_price_entry,
        dest="price",
        metavar="TOOL=IN/OUT",
        help="Price one tool's tokens, in dollars per million: input rate, then output rate. "
        "Repeat it once per tool. Assay stores no prices, so a report without this flag "
        "reports tokens and says no price was supplied. Requires --prices-source.",
    )
    report.add_argument(
        "--prices-source",
        metavar="TEXT",
        help="Where the prices came from, in your own words, printed with them. Required "
        "whenever --price is given: a dollar figure nobody can attribute is not a "
        "measurement.",
    )
    return parser


def _report_document(results: Path, fmt: str, prices: PriceTable | None) -> str:
    """Read a result set and return the rendering of the redacted report it produces.

    The report itself does not come back out. Nothing above this line may read a field off it
    and print a second thing beside the document: what a reader is owed is inside the
    rendering, decided by the renderer that laid it out.

    Redaction is applied here with a policy drawn fresh per invocation, so two runs over one
    file produce different tokens and neither can be joined to the other (SPEC §5.4). There is
    no flag to skip it: an opt-out would make redaction something a caller remembers rather
    than a property the pipeline has.

    ``prices`` is ``None`` when nobody supplied any, which is a costs section saying so on
    every row rather than a report without one (ADR-0046). It is a parameter and not a default
    for the same reason ``--results`` is required: what a run was priced at is the caller's to
    state, and this module has no rate of its own to fall back on.
    """
    result_set = read_result_set(results)
    report = build_report(result_set, summarise(result_set), prices)
    redacted = redact(report, RedactionPolicy.from_random())
    return RENDERERS[fmt](redacted)


def _use_lf(stream: object) -> None:
    """Pin ``stream`` to LF line endings, where the runtime allows it.

    Only a real :class:`io.TextIOWrapper` can be reconfigured. A stream a caller has replaced
    with an in-memory buffer - which is what pytest's capture does - cannot be, and does not
    need to be: it never reaches an OS newline translation layer in the first place.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(newline="\n")


def run_report(results: Path, fmt: str, prices: PriceTable | None) -> int:
    """Print the report for ``results`` on stdout, and nothing anywhere else.

    Every caveat a reader is owed travels inside the document now that the intervals are
    measured: pass@1's missing band is captioned by the two prose renderers, and the canonical
    JSON states the same absence structurally. The costs section is there whether or not
    ``prices`` holds anything, for the same reason - an absent section is a statement nobody
    wrote (ADR-0035, ADR-0046). Nothing is printed to stderr on the way, so a successful
    ``assay report`` is silent apart from the document itself.

    Exactly one trailing newline, whichever format: `render_json` returns the document without
    one by contract and the two prose formats end with one already.
    """
    try:
        document = _report_document(results, fmt, prices)
    except (AssayError, OSError, ValueError, RecursionError) as error:
        # ValueError covers both halves of "the file is not a result set": json's decode error
        # and pydantic's ValidationError, which subclasses it. RecursionError is neither, but
        # deeply nested JSON raises it out of the decoder.
        #
        # The frame names the file and claims nothing else about it. This ``try`` spans reading
        # *and* summarising *and* rendering, so "cannot read" would be a guess - and it is
        # wrong for the case that made it visible, a rate too large to cost out against a file
        # that parsed perfectly (ADR-0048). The path is repeated in our own words because not
        # every one of these errors names it; the cause is the error's own sentence, which is
        # why ``report`` raises ``CostOutOfRangeError`` rather than letting decimal's signal
        # out.
        print(f"assay report: cannot produce a report from {results}: {error}", file=sys.stderr)
        return EXIT_FAILED

    # LF on every platform, not the host's: a report rendered on Windows must be the same bytes
    # as one rendered on the ubuntu runner - the same reason every file write in this repo pins
    # ``newline="\n"``. In-process test capture never crosses a translation layer, so only this
    # guards the real stream.
    _use_lf(sys.stdout)

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


def host_tool_process(
    argv: Sequence[str], *, cwd: Path, timeout_s: int, env: Mapping[str, str]
) -> ProcessOutput:
    """Run an agentic tool's command line on the host, per :class:`assay.adapters.ToolProcess`.

    The second bridge this module writes, and it exists for the reason ``host_runner_for``
    does: an adapter must be drivable on a fake in CI, so it takes a callable and never learns
    that :mod:`assay.host` - the only package allowed to start a process - is on the other end
    of it.

    A kill at the budget is a value here rather than an exception, because it is an outcome of
    the measurement: a tool that ran out of wall clock produced whatever it had produced by
    then, and the trial scores on the workspace it left behind. Every other failure is the
    tool's own exit code, handed back as data.

    ``env`` is passed through exactly as given. This function adds nothing: what a tool under
    evaluation may see - :func:`assay.host.minimal_env` plus, for a model-backed tool, the one
    key name - is the caller's decision, made where the tool is configured.
    """
    try:
        result = run_command(argv, cwd=cwd, timeout_s=timeout_s, env=env)
    except CommandTimeoutError:
        return ProcessOutput(exit_code=TOOL_KILLED_EXIT_CODE, stdout="", stderr="", timed_out=True)
    return ProcessOutput(
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=False,
    )


def adapter_phase_process(
    *,
    image_tag: str,
    api_key: str,
    executable: str = AGENT_EXECUTABLE,
    limits: ContainerLimits = TRIAL_LIMITS,
    process: ToolProcess = host_tool_process,
) -> ToolProcess:
    """Route the agentic adapter's one seam to the two places its two kinds of argv belong.

    :class:`assay.adapters.AgenticCliAdapter` has a single :class:`assay.adapters.ToolProcess`
    and puts both the tool and the `git` calls that harvest its work through it - deliberately,
    because *where* each runs is a question about the binding rather than about the harvest
    (ADR-0038). This is that binding, and the two destinations are not the same:

    * **The harvest runs on this host.** The adapter's workspace is a linked worktree, so its
      ``.git`` is a *file* holding an absolute path into the clone; inside a container that path
      names nothing, and a bind mount of the worktree alone cannot be read as a repository at
      all. Mounting the clone as well would put the repository under evaluation inside the same
      container as the tool, which is the one place SPEC §5.1 says it may not go.
    * **The tool runs inside the container** (ADR-0039, ruling 7). What runs on the host is the
      docker client, which is a remote control rather than the tool: the model-generated work
      still happens on the far side of the wall.

    The discriminator is ``argv[0]``: the adapter builds exactly one command line out of
    ``executable`` and every other call it makes is `git`. That is a narrow contract between two
    modules, and it is narrow on purpose - the alternative is a second seam on the adapter,
    which would put "there is a container" into a class whose whole property is not knowing.

    ``api_key`` is renamed here and only here: Assay reads :data:`MODEL_API_KEY_ENV` and the tool
    reads :data:`TOOL_API_KEY_ENV`. The value goes into the *client's* environment and the
    container gets the name alone, because an argv is readable by every process on this machine
    (plan §7a). An empty key is passed on rather than refused: the run that reaches here has
    already been refused one at :class:`assay.host.HttpModelTransport`, which the mandatory
    baseline builds first, and a tool that cannot authenticate reports a non-zero exit that the
    adapter records as an errored trial - a measured outcome rather than a crash.

    Args:
        image_tag: The agent image for this task, from
            :func:`assay.sandbox.build_agent_image`.
        api_key: The model API key, as read from the environment. Never logged, never in an
            argv, never in an attempt.
        executable: The path the tool has inside the image. The one argv that is containerised.
        limits: The ceiling the adapter phase runs under.
        process: How a command line is actually started. The default is the host bridge; tests
            hand in a fake, which is what makes the routing above assertable without a daemon.

    Returns:
        A :class:`assay.adapters.ToolProcess` to hand :class:`assay.adapters.AgenticCliAdapter`.
    """

    def start(
        argv: Sequence[str], *, cwd: Path, timeout_s: int, env: Mapping[str, str]
    ) -> ProcessOutput:
        if not argv or argv[0] != executable:
            return process(argv, cwd=cwd, timeout_s=timeout_s, env=env)
        return process(
            adapter_phase_command(
                image_tag=image_tag,
                workspace=cwd,
                argv=argv,
                limits=limits,
                env_names=(TOOL_API_KEY_ENV,),
            ),
            cwd=cwd,
            timeout_s=timeout_s,
            env={**env, TOOL_API_KEY_ENV: api_key},
        )

    return start


def _adapters_needing_no_image(
    names: Sequence[str], *, model: str, api_key: str
) -> tuple[Adapter, ...]:
    """Every named adapter except the agentic one, made once for the whole run.

    The three that are left answer from the task, from nothing, or from one model call, so none
    of them needs to know which image a task was built into and all three can be made before the
    first build. The agentic adapter is the exception and is made per task
    (:func:`_agentic_adapter`), because the container it drives holds that task's environment.

    The naive baseline's transport is built here, which is where a missing or malformed key is
    refused - before a single image is built, rather than an hour into a run.
    """
    made: list[Adapter] = []
    for name in names:
        if name == GroundTruthAdapter.name:
            made.append(GroundTruthAdapter())
        elif name == NullAdapter.name:
            made.append(NullAdapter())
        elif name == NaiveBaselineAdapter.name:
            made.append(
                NaiveBaselineAdapter(
                    transport=HttpModelTransport(endpoint=MODEL_ENDPOINT, api_key=api_key),
                    model=model,
                )
            )
    return tuple(made)


def _agentic_adapter(*, image_tag: str, model: str, api_key: str) -> Adapter:
    """The agentic adapter, bound to one task's agent image.

    ``minimal_env()`` and nothing else: what the tool under evaluation may see is decided here,
    and the model key is not in it - it is added to the *docker client's* environment by
    :func:`adapter_phase_process` and passed into the container by name.
    """
    return AgenticCliAdapter(
        process=adapter_phase_process(image_tag=image_tag, api_key=api_key),
        executable=AGENT_EXECUTABLE,
        model=model,
        env=minimal_env(),
    )


def _adapter_refusal(names: Sequence[str]) -> str | None:
    """The reason this set of adapters may not be run together, or ``None`` if it may.

    Two rules, and the first is CLAUDE.md's: **the naive baseline is in every report.** One raw
    model call with no agent loop is what an agentic tool has to beat to have earned its
    complexity, and a report without it can only say a tool scored *something*. It is refused
    rather than added for the caller, because adding it would spend money nobody asked to
    spend. The two oracles are exempt: they answer from the task itself, so a run of the pair
    measures this harness and has nothing to compare a baseline against.

    The second is that one adapter named twice would be measured twice under one name, and the
    two runs of it would land in the result set as duplicate trials of one task - which pass^n
    counts as two tasks. Refused here rather than deduplicated, because a caller who typed it
    meant something this milestone does not do (repeated runs of one tool are M4's).
    """
    named = set(names)
    if len(named) != len(names):
        return (
            f"assay run: an adapter is named more than once ({', '.join(names)}); each one is "
            "measured once per trial, and a repeated name would report one tool as two"
        )
    if named - ORACLE_ADAPTERS and NaiveBaselineAdapter.name not in named:
        return (
            f"assay run: a run measuring a tool must also name --adapter "
            f"{NaiveBaselineAdapter.name}; the naive baseline is one raw model call with no "
            "agent loop, and a tool that cannot beat it is the finding"
        )
    return None


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
        # RecursionError out of deeply nested input, or one of Assay's own refusals. The frame
        # is the stronger claim here, and it is true: this ``try`` wraps ``load_suite`` alone,
        # so reading is the only thing that can have failed inside it.
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


def run_run(
    *,
    suite_path: Path,
    repo: Path,
    out: Path,
    adapter_names: Sequence[str],
    trials: int,
    timeout_s: int,
    model: str,
) -> int:
    """Score every task in a suite against every named adapter, n trials each.

    The command M0 declared and M3 builds, and it is a loop rather than an orchestrator: the
    pieces underneath it are the ones ``tests/score/test_end_to_end.py`` already drives - a
    task image per task, :func:`assay.sandbox.sandbox_runner_for`, and
    :func:`assay.score.run_trial` per task per adapter per trial. What this function adds is the
    order they happen in, a line of progress each, and a result set at the end.

    Everything is accumulated in memory and written once. There is no append and no resume: a
    partially written result set is a report that would silently omit trials, and a run that has
    to be repeated is honest about it. The largest measured yield to date is two tasks.

    Nothing here computes a number a report will show. The trials go out exactly as they were
    scored, and ``assay report`` is where pass@1, pass^n and their intervals are decided - which
    is what keeps the statistics in one module with tests around it.

    A trial that ``ERRORED`` is data, not a failure of the command: an unfunded key, a tool that
    exited non-zero, a model that answered with prose are all outcomes the report has to be able
    to state. Only the harness failing - git, docker, the filesystem, an unreadable suite -
    ends the run non-zero.
    """
    _use_lf(sys.stderr)
    _use_lf(sys.stdout)

    refusal = _adapter_refusal(adapter_names)
    if refusal is not None:
        # Before the suite is read and long before an image is built: a run that must not be
        # reported should cost nothing at all.
        print(refusal, file=sys.stderr)
        return EXIT_FAILED

    try:
        suite = load_suite(suite_path)
    except (AssayError, OSError, ValueError, RecursionError) as error:
        # The same four ``run_validate`` catches, for the reasons it gives - including the
        # narrow frame, which this ``try`` earns the same way: it wraps ``load_suite`` and
        # nothing else.
        print(f"assay run: cannot read {suite_path}: {error}", file=sys.stderr)
        return EXIT_FAILED

    tasks = suite.body.tasks
    planned = len(tasks) * len(adapter_names) * trials
    # Every cap the tool is held to. `max_usd` is null and stays null in M3: cost accounting is
    # M4's row in SPEC §7, so this milestone records tokens and says so rather than reporting a
    # number it did not measure.
    budget = Budget(
        max_wall_clock_s=timeout_s,
        max_input_tokens=None,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        max_tool_calls=None,
        max_usd=None,
    )
    api_key = os.environ.get(MODEL_API_KEY_ENV, "")
    results: list[Result] = []
    try:
        # Built before anything else, so a run configured without a key fails in a second
        # rather than after the first image.
        adapters = _adapters_needing_no_image(adapter_names, model=model, api_key=api_key)
        # Outside both the clone and the output, and gone when the run ends: worktrees and the
        # directories trials write their junit reports into are the largest things this command
        # makes, and one leaked per interrupted run fills a disk quietly.
        with tempfile.TemporaryDirectory(prefix="assay-run-") as scratch:
            worktrees = Path(scratch) / "worktrees"
            out_root = Path(scratch) / "out"
            worktrees.mkdir()
            out_root.mkdir()
            history = GitHistory(repo, worktree_root=worktrees)
            for task in tasks:
                image = _task_image(history, task)
                for adapter in _task_adapters(
                    adapters,
                    names=adapter_names,
                    task=task,
                    image=image,
                    model=model,
                    api_key=api_key,
                ):
                    for trial_index in range(trials):
                        result = run_trial(
                            task=task,
                            adapter=adapter,
                            budget=budget,
                            history=history,
                            runner_for=sandbox_runner_for(
                                image, limits=TRIAL_LIMITS, out_root=out_root
                            ),
                            timeout_s=timeout_s,
                            trial_index=trial_index,
                        )
                        results.append(result)
                        print(
                            _trial_line(len(results), planned, result, trials),
                            file=sys.stderr,
                            flush=True,
                        )
        write_result_set(
            out,
            ResultSet(schema_version=1, suite_hash=suite.suite_hash, results=tuple(results)),
        )
    except (AssayError, OSError) as error:
        # OSError as well as Assay's own: a repository path that is not there fails inside
        # ``subprocess`` before git is asked anything, and a docker client that is not installed
        # fails the same way. Both owe the caller one sentence rather than a traceback.
        print(f"assay run: cannot run {suite_path} against {repo}: {error}", file=sys.stderr)
        return EXIT_FAILED

    print(f"assay run: wrote {len(results)} trials to {out}", file=sys.stderr)
    print(f"read them with: assay report --results {out}", file=sys.stderr)
    print(
        f"{len(tasks)} tasks x {len(adapter_names)} adapters x {trials} trials "
        f"= {len(results)} trials recorded"
    )
    return EXIT_OK


def _task_adapters(
    adapters: Sequence[Adapter],
    *,
    names: Sequence[str],
    task: Task,
    image: str,
    model: str,
    api_key: str,
) -> tuple[Adapter, ...]:
    """The adapters this task is measured with - the run's own, plus the tool if one was named.

    The agentic adapter is the only one made per task, and building the image it drives is why:
    the tool is installed *over* the task image (ADR-0039), so its container is that task's
    environment with a tool in it. Cheap on repeat, like every build in
    :mod:`assay.sandbox.image` - the tag is a content address.
    """
    if AgenticCliAdapter.name not in names:
        return tuple(adapters)
    agent_image = build_agent_image(
        base_tag=image,
        base_commit=task.base_commit,
        tool_version=AGENT_TOOL_VERSION,
        timeout_s=IMAGE_BUILD_TIMEOUT_S,
    )
    return (*adapters, _agentic_adapter(image_tag=agent_image, model=model, api_key=api_key))


def _task_image(history: GitHistory, task: Task) -> str:
    """Build the image ``task``'s trials run in, from a checkout of its base commit.

    Neither the test patch nor any fix is applied first: the image holds the state a tool is
    handed. What a trial actually runs is the workspace it mounts rather than this tree, so an
    image per base commit is an environment per task and not a copy of the answer.

    The dependency cutoff is the commit's own committer date (ADR-0021), which is the whole
    reason this is done here rather than inside :mod:`assay.sandbox`: reading it needs the
    clone, and the sandbox package holds no git history.
    """
    with history.worktree(task.base_commit) as checkout:
        return build_task_image(
            context=checkout,
            base_commit=task.base_commit,
            exclude_newer=history.committed_at(task.base_commit),
            timeout_s=IMAGE_BUILD_TIMEOUT_S,
        )


def _trial_line(index: int, planned: int, result: Result, trials: int) -> str:
    """One scored trial, as it is recorded. Never the prompt, the diff or the tool's output.

    A trial is minutes of container work, so a run that said nothing until it finished would be
    indistinguishable from a hung one - the reason ``run_mine`` prints as it goes. What is
    printed is the four fields that identify the trial and the verdict it earned (plan §7g):
    anything the model wrote is untrusted text on its way to a terminal, and it is in the result
    set for a reader who asks rather than on the way past.
    """
    return (
        f"[{index:>4}/{planned}] {result.task_id} {result.adapter_name} "
        f"trial {result.trial_index + 1}/{trials}: {result.outcome.value}"
    )


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
        if command == "run":
            return run_run(
                suite_path=args.suite,
                repo=args.repo,
                out=args.out,
                adapter_names=args.adapters,
                trials=args.trials,
                timeout_s=args.trial_timeout_s,
                model=args.model,
            )
        if command == "report":
            results: Path = args.results
            fmt: str = args.format
            entries: list[ToolPrice] = args.price or []
            source: str | None = args.prices_source
            # Symmetric, and refused here because this is where ``parser`` is: a price with no
            # stated source prints dollars nobody can attribute (SPEC §5.5), and a source with
            # no price names the provenance of a table the report does not carry. Neither is a
            # report worth rendering, and both are a command line, so both exit EXIT_USAGE
            # through argparse's own error rather than as a failure of the run.
            if bool(entries) != (source is not None):
                parser.error(
                    "--price and --prices-source go together: dollars with no stated source "
                    "cannot be attributed, and a source that priced nothing describes a table "
                    "this report does not carry"
                )
            try:
                prices = (
                    None if source is None else PriceTable(source=source, prices=tuple(entries))
                )
            except ValidationError as error:
                # The table's own refusals - two rates for one tool, a source that would print
                # as two lines. The schema owns them, so its sentence is the one shown.
                parser.error(f"these prices cannot be used: {error}")
            return run_report(results, fmt, prices)
        raise NotImplementedInMilestone(command, MILESTONE, PLANNED[command])
    except NotImplementedInMilestone as error:
        print(error, file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    raise SystemExit(main())
