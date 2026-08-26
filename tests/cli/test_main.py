"""What the four-command surface promises while three of the four commands do not exist yet.

Two properties carry this module.

The first is that an unbuilt command is *honest* rather than broken: ``mine``, ``validate`` and
``run`` are reachable, say which milestone builds them, and exit non-zero, so a script that
runs one fails instead of reading an empty report as an empty result (CLAUDE.md's milestone
discipline). The tests assert that a schedule is named, not the exact sentence - the wording
belongs to ``NotImplementedInMilestone``.

The second is RULING 4's stream split, which exists nowhere else in Assay: the placeholder
admission goes to stderr and the document goes to stdout, so ``assay report --format json >
out.json`` leaves a file a consumer can parse *and* a human who still saw the admission. The
JSON case is asserted both ways round - the notice is on stderr byte-for-byte, and the stdout
bytes validate as a :class:`~assay.report.Report` - because either half alone would pass while
the split was broken.

Redaction is asserted structurally and never by token value: the salt is fresh per run
(SPEC §5.4), so a test that pinned a token would pin the one thing that must not be stable.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from assay.cli import main
from assay.report import STUB_INTERVAL_NOTICE, Report

FIXTURES = Path(__file__).parent.parent / "fixtures"
RESULTS = FIXTURES / "results_overlapping.json"

# The three formats the command offers, and the three commands M0 does not implement.
FORMATS = ["json", "text", "html"]
UNBUILT = ["mine", "validate", "run"]


def invoke(capsys: pytest.CaptureFixture[str], argv: Sequence[str]) -> tuple[int, str, str]:
    """Run the CLI in-process and return ``(exit code, stdout, stderr)``.

    In-process rather than through a subprocess: the point of ``main(argv)`` returning an int
    is that the surface is testable without a shell, and a subprocess would make these tests
    depend on the console script being installed and on Windows and Linux quoting alike.
    """
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def raw_task_ids() -> set[str]:
    """The unredacted task identifiers in the fixture - the text that must not reach stdout."""
    document: dict[str, Any] = json.loads(RESULTS.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = document["results"]
    return {str(result["task_id"]) for result in results}


def test_help_lists_every_command_the_surface_declares(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `assay --help` working is M0's stated exit criterion (SPEC §7), and the four commands are
    # the published surface (SPEC §6) whether or not they are built.
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0

    out = capsys.readouterr().out
    for command in ["mine", "validate", "run", "report"]:
        assert command in out


def test_no_command_at_all_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    # Bare `assay` has nothing to do. It must not exit 0 and leave a caller believing it did.
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0
    assert capsys.readouterr().err != ""


@pytest.mark.parametrize("command", UNBUILT)
def test_an_unbuilt_command_fails_and_names_its_milestone(
    capsys: pytest.CaptureFixture[str], command: str
) -> None:
    code, out, err = invoke(capsys, [command])

    assert code != 0
    # Nothing on stdout: a caller piping the command gets an empty document, never a
    # diagnostic it might parse as one.
    assert out == ""
    assert f"assay {command}" in err
    assert "M0" in err
    # The schedule, not the wording: the user should read when the work lands.
    assert "planned:" in err


def test_report_writes_a_document_stdout_can_be_parsed_from(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The acceptance property of RULING 4: the admission is a *field* of the schema, not an
    # envelope key and not a banner glued to the front of the document.
    code, out, err = invoke(capsys, ["report", "--results", str(RESULTS), "--format", "json"])

    assert code == 0
    report = Report.model_validate(json.loads(out))
    assert report.intervals_are_placeholders is True
    assert STUB_INTERVAL_NOTICE not in out
    assert STUB_INTERVAL_NOTICE in err


@pytest.mark.parametrize("fmt", FORMATS)
def test_stderr_carries_the_placeholder_notice_once_and_verbatim(
    capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    # Equality, not a substring: verbatim (never re-wrapped or paraphrased) and exactly once,
    # both in one assertion. The trailing newline is the CLI's, since the constant has none.
    _, _, err = invoke(capsys, ["report", "--results", str(RESULTS), "--format", fmt])

    assert err == STUB_INTERVAL_NOTICE + "\n"


def test_the_json_document_gets_the_one_newline_render_json_withholds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # render_json returns the document with no trailing newline by contract; a terminal wants
    # one, and a second would be a byte the consumer did not ask for.
    _, out, _ = invoke(capsys, ["report", "--results", str(RESULTS), "--format", "json"])

    assert out.endswith("\n")
    assert not out.endswith("\n\n")


@pytest.mark.parametrize(
    ("fmt", "opening"),
    [("json", "{"), ("text", STUB_INTERVAL_NOTICE), ("html", "<!DOCTYPE html>")],
)
def test_the_format_flag_selects_the_renderer(
    capsys: pytest.CaptureFixture[str], fmt: str, opening: str
) -> None:
    _, out, _ = invoke(capsys, ["report", "--results", str(RESULTS), "--format", fmt])

    assert out.startswith(opening)


@pytest.mark.parametrize("fmt", FORMATS)
def test_no_format_prints_a_task_id_the_fixture_recorded(
    capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    # Redaction is on by default and has no opt-out (SPEC §5.4). The CLI is the caller that
    # would be tempted to add one.
    _, out, _ = invoke(capsys, ["report", "--results", str(RESULTS), "--format", fmt])

    for task_id in raw_task_ids():
        assert task_id not in out


def test_two_runs_of_one_file_differ_in_tokens_and_agree_in_structure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # A fresh salt per run is what stops two reports of the same repository being joined on a
    # shared token. Everything a reader is meant to compare survives; the tokens do not.
    argv = ["report", "--results", str(RESULTS), "--format", "json"]
    _, first_out, _ = invoke(capsys, argv)
    _, second_out, _ = invoke(capsys, argv)

    first = Report.model_validate(json.loads(first_out))
    second = Report.model_validate(json.loads(second_out))

    assert first.suite_hash == second.suite_hash
    assert first.tools == second.tools
    assert first.comparisons == second.comparisons
    assert len(first.tasks) == len(second.tasks)
    assert [line.outcome for line in first.tasks] == [line.outcome for line in second.tasks]
    assert {line.task_id for line in first.tasks} != {line.task_id for line in second.tasks}


def test_report_without_results_is_a_usage_error() -> None:
    # --results has no default. Reporting on a file the user did not name would be a guess.
    with pytest.raises(SystemExit) as excinfo:
        main(["report"])
    assert excinfo.value.code != 0


def test_a_missing_results_file_fails_with_a_message_not_a_traceback(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    absent = tmp_path / "absent.json"
    code, out, err = invoke(capsys, ["report", "--results", str(absent)])

    assert code != 0
    assert out == ""
    assert "Traceback" not in err
    assert str(absent) in err


def test_an_unreadable_results_document_fails_with_a_message(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # A document declaring no schema version is the version probe's own case; the CLI's job is
    # to report it as a refusal rather than as a crash.
    path = tmp_path / "versionless.json"
    path.write_text("{}", encoding="utf-8", newline="\n")

    code, out, err = invoke(capsys, ["report", "--results", str(path)])

    assert code != 0
    assert out == ""
    assert "Traceback" not in err
    assert err != ""
