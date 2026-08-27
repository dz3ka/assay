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
scoring, no statistics and no I/O beyond reading the file the user named - a command that
computed anything would put logic somewhere no test in ``tests/report`` or ``tests/results``
can see it.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from assay.core import AssayError, NotImplementedInMilestone
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

# The milestone this build is. Quoted in every "not implemented" message, so one edit moves
# the whole surface forward when M1 lands.
MILESTONE = "M0"

# Where each unbuilt command is scheduled (SPEC §7). `mine` and `validate` are M1's whole
# scope; `run` needs adapters and n-trial execution, which is M3 - not M2, which builds the
# sandbox and scoring underneath it but no end-to-end run.
PLANNED: dict[str, str] = {
    "mine": "M1",
    "validate": "M1",
    "run": "M3",
}

# One line of help per unbuilt command: what it will do, so `assay --help` reads as a map of
# the tool rather than a list of three errors.
_UNBUILT_HELP: dict[str, str] = {
    "mine": "Mine an evaluation suite from a repository's own git history.",
    "validate": "Re-check a suite against the red-green gate and report its yield.",
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


def build_parser() -> argparse.ArgumentParser:
    """Build the whole command surface, unbuilt commands included.

    The unbuilt three are registered as real subcommands rather than omitted: `assay --help`
    is M0's stated exit criterion (SPEC §7) and it should show what Assay is going to be, and
    a user who types `assay mine` deserves a schedule instead of "invalid choice".
    """
    parser = argparse.ArgumentParser(
        prog="assay",
        description=(
            "Evaluate AI coding tools against a suite mined from a repository's own history."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command", required=True)

    for command in ("mine", "validate", "run"):
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
