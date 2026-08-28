"""What the four-command surface promises, and what its three built commands do.

Three properties carry this module.

The first is that an unbuilt command is *honest* rather than broken: ``run`` is reachable, says
which milestone builds it, and exits non-zero, so a script that runs it fails instead of
reading an empty report as an empty result (CLAUDE.md's milestone discipline). The tests assert
that a schedule is named, not the exact sentence - the wording belongs to
``NotImplementedInMilestone``.

The second is RULING 4's stream split, which exists nowhere else in Assay: the placeholder
admission goes to stderr and the document goes to stdout, so ``assay report --format json >
out.json`` leaves a file a consumer can parse *and* a human who still saw the admission. The
JSON case is asserted both ways round - the notice is on stderr byte-for-byte, and the stdout
bytes validate as a :class:`~assay.report.Report` - because either half alone would pass while
the split was broken.

Redaction is asserted structurally and never by token value: the salt is fresh per run
(SPEC §5.4), so a test that pinned a token would pin the one thing that must not be stable.

The third is M1's: ``mine`` and ``validate`` are driven against SPEC §9's fixture repository -
real worktrees, a real uv environment per candidate, real pytest processes - because the only
claim worth making about this seam is that the whole thing runs. Those tests share **one**
mining run through a module-scoped fixture, for the reason ``tests/mine/test_pipeline.py``
gives: a run is an environment and three pytest processes per candidate, and paying that once
per assertion would buy nothing but minutes. Sharing it costs the house style of one property
per test and pytest's function-scoped ``capsys``, so :func:`drive` captures the two streams
itself.
"""

import io
import json
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from assay.cli import main
from assay.cli.main import EXIT_USAGE, HOST_EXECUTION_NOTICE, HOST_EXECUTION_SENTENCE
from assay.report import STUB_INTERVAL_NOTICE, Report
from assay.suite import load_suite
from tests.fixture_repo import EXPECTED_YIELD, build_fixture_repo

FIXTURES = Path(__file__).parent.parent / "fixtures"
RESULTS = FIXTURES / "results_overlapping.json"

# The three formats the command offers, and the one command M1 does not implement.
FORMATS = ["json", "text", "html"]
UNBUILT = ["run"]

# The ceiling on one test run, passed to every fixture-repo invocation below. Ten seconds, as
# in `tests/mine/test_pipeline.py`: only `slow_lookup`'s red run is slow, and it is slow by an
# hour, so the CLI's own 300s default would buy nothing but a longer wait for the same verdict.
RUN_TIMEOUT_S = "10"


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
    assert "M1" in err
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


@dataclass(frozen=True)
class Invocation:
    """One CLI run: its exit code and both of its streams, captured verbatim."""

    code: int
    out: str
    err: str


@dataclass(frozen=True)
class MinedFixture:
    """The shared mining run: what was mined, where the suite went, and what it printed."""

    repo: Path
    suite: Path
    run: Invocation


def drive(argv: Sequence[str]) -> Invocation:
    """Run the CLI in-process with its streams captured, without pytest's ``capsys``.

    ``capsys`` is function-scoped and the mining run below is module-scoped, so the capture has
    to be one this module owns. Redirection rather than a subprocess for the same reason
    :func:`invoke` is in-process: the point of ``main(argv)`` returning an int is that the whole
    surface is testable without a shell.
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return Invocation(code, out.getvalue(), err.getvalue())


@pytest.fixture(scope="module")
def mined(tmp_path_factory: pytest.TempPathFactory) -> MinedFixture:
    """Mine SPEC §9's fixture repository once, for every assertion about a real run."""
    root = tmp_path_factory.mktemp("mine")
    repo = build_fixture_repo(root / "build")
    suite = root / "suite.json"
    return MinedFixture(
        repo=repo,
        suite=suite,
        run=drive(
            [
                "mine",
                "--repo",
                str(repo),
                "--out",
                str(suite),
                "--test-timeout-s",
                RUN_TIMEOUT_S,
            ]
        ),
    )


def test_mining_the_fixture_repository_writes_the_suite_it_proved(mined: MinedFixture) -> None:
    # M1's exit criterion end to end: a real git history in, a loadable suite out. The task
    # count is the fixture's expected yield, which CLAUDE.md forbids adjusting to match a
    # changed miner - `tests/mine/test_fixture_repo.py` owns the number, this owns the file.
    assert mined.run.code == 0

    written = load_suite(mined.suite)

    assert len(written.body.tasks) == EXPECTED_YIELD.accepted
    assert [task.task_id for task in written.body.tasks] == sorted(
        task.task_id for task in written.body.tasks
    )


def test_the_yield_line_names_the_denominator_and_every_discard(mined: MinedFixture) -> None:
    # CLAUDE.md's "report yield, not just totals", asserted as the document a caller reads:
    # the population walked, what survived it, the commits no environment could be built for,
    # and a count per rejection reason - never the accepted count on its own.
    document = mined.run.out

    assert (
        f"{EXPECTED_YIELD.commits_examined} single-parent commits examined -> "
        f"{EXPECTED_YIELD.accepted} valid tasks" in document
    )
    assert f"{EXPECTED_YIELD.unprovisioned} unprovisioned" in document
    for reason, count in EXPECTED_YIELD.rejected.items():
        assert f"{reason.value} {count}" in document


def test_the_host_execution_banner_is_on_stderr_and_never_in_the_document(
    mined: MinedFixture,
) -> None:
    # The same stream split RULING 4 gives `report`: stdout is the yield a script parses,
    # stderr is what the human is owed - here that mining executed the target repository's own
    # build and tests on this machine (SPEC §5.2).
    assert HOST_EXECUTION_NOTICE in mined.run.err
    assert HOST_EXECUTION_NOTICE not in mined.run.out


def test_a_suite_the_walk_just_wrote_revalidates_against_the_same_repository(
    mined: MinedFixture,
) -> None:
    # `assay validate` is the claim that the suite is still true. A suite mined minutes ago
    # against the repository it was mined from is the one case where the answer is knowable in
    # advance, which is what makes it worth asserting.
    validated = drive(
        [
            "validate",
            "--suite",
            str(mined.suite),
            "--repo",
            str(mined.repo),
            "--test-timeout-s",
            RUN_TIMEOUT_S,
        ]
    )

    assert validated.code == 0
    assert f"{EXPECTED_YIELD.accepted} of {EXPECTED_YIELD.accepted}" in validated.out
    assert HOST_EXECUTION_NOTICE in validated.err


def test_a_yield_of_zero_still_writes_a_suite_and_still_exits_zero(tmp_path: Path) -> None:
    # A repository whose history holds no red->green commit is a finding about that repository,
    # not a failure of the tool (`assay.mine`'s module docstring, decision D9). `--limit 1`
    # walks only the newest single-parent commit, which the fixture builds to touch no source
    # file at all - so nothing is provisioned and nothing is run, and the empty suite is still
    # a document with a yield attached.
    out = tmp_path / "empty-suite.json"

    built = build_fixture_repo(tmp_path / "build")
    zero = drive(["mine", "--repo", str(built), "--out", str(out), "--limit", "1"])

    assert zero.code == 0
    assert "1 single-parent commits examined -> 0 valid tasks" in zero.out
    assert load_suite(out).body.tasks == ()


def test_mining_a_repository_that_is_not_there_fails_with_a_message(tmp_path: Path) -> None:
    # Exit 1, not 0 with an empty suite: "there is no such repository" and "this repository
    # yielded nothing" are the two answers a caller must never see as the same one.
    absent = tmp_path / "absent"

    failed = drive(["mine", "--repo", str(absent), "--out", str(tmp_path / "suite.json")])

    assert failed.code == 1
    assert failed.out == ""
    assert "Traceback" not in failed.err
    assert not (tmp_path / "suite.json").exists()


def test_validating_a_suite_that_cannot_be_read_fails(tmp_path: Path) -> None:
    # The other half of decision D9's asymmetry: a suite that cannot be re-proved has not been
    # re-proved, so `validate` exits 1 where `mine` exits 0.
    absent = tmp_path / "absent-suite.json"

    failed = drive(["validate", "--suite", str(absent), "--repo", str(tmp_path)])

    assert failed.code == 1
    assert failed.out == ""
    assert "Traceback" not in failed.err
    assert str(absent) in failed.err


def test_the_mine_help_says_the_target_repository_runs_on_this_machine(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # One sentence, verbatim, because the README carries the identical one: a warning worded
    # two ways is a warning a reader cannot match to the thing they were told.
    assert HOST_EXECUTION_SENTENCE == (
        "mining a repository runs that repository's build and tests on your machine"
    )
    with pytest.raises(SystemExit) as excinfo:
        main(["mine", "--help"])
    assert excinfo.value.code == 0

    # Whitespace-normalised: argparse rewraps help text to the terminal width, so the sentence
    # arrives split across lines and only its words survive the journey.
    assert HOST_EXECUTION_SENTENCE in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize(
    "argv",
    [["mine"], ["mine", "--repo", "."], ["validate"], ["validate", "--suite", "s.json"]],
    ids=["mine-nothing", "mine-without-out", "validate-nothing", "validate-without-repo"],
)
def test_a_command_missing_a_required_path_is_a_usage_error(argv: list[str]) -> None:
    # No defaults for either path. Mining whatever directory the user happens to be in, or
    # writing a suite somewhere nobody named, would both be guesses.
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code != 0


@pytest.mark.parametrize("limit", ["-1", "0", "not-a-number"], ids=["negative", "zero", "words"])
def test_a_limit_git_would_read_as_unlimited_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, limit: str
) -> None:
    # `git log --max-count -1` walks the whole history rather than one commit or none, so a
    # mistyped limit would turn the smallest run a caller can ask for into the largest - hours
    # of the target repository's build hooks and tests running on this machine (ADR-0013). The
    # refusal is argparse's own, which is what keeps it at EXIT_USAGE and on stderr, and it
    # lands before `--repo` is even looked at: nothing is provisioned and nothing is run.
    with pytest.raises(SystemExit) as excinfo:
        main(["mine", "--repo", str(tmp_path), "--out", str(tmp_path / "s.json"), "--limit", limit])

    assert excinfo.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    # Same invariant as every other refusal in this file: nothing on stdout, so a caller
    # piping the suite out gets an empty document rather than a diagnostic.
    assert captured.out == ""
    assert "--limit" in captured.err


@pytest.mark.parametrize("timeout", ["-1", "0", "not-a-number"], ids=["negative", "zero", "words"])
@pytest.mark.parametrize("command", ["mine", "validate"], ids=["mine", "validate"])
def test_a_test_timeout_below_one_second_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, command: str, timeout: str
) -> None:
    # A ceiling below one second is not a shorter run, it is a run the host layer floors back up
    # to one second (`assay.host.pytest_runner._remaining`) - so the flag would quietly mean
    # something other than what it says, and which candidates came back `run_timed_out` would be
    # a property of how fast this machine is rather than of the history. Both commands, because
    # the same value lies in both directions: a yield of zero `mine` still exits 0 on, and a
    # suite `validate` reports as no longer holding.
    argv = (
        ["mine", "--repo", str(tmp_path), "--out", str(tmp_path / "s.json")]
        if command == "mine"
        else ["validate", "--repo", str(tmp_path), "--suite", str(tmp_path / "s.json")]
    )
    with pytest.raises(SystemExit) as excinfo:
        main([*argv, "--test-timeout-s", timeout])

    assert excinfo.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    # Same invariant as every other refusal in this file: nothing on stdout, so a caller reading
    # the yield off the pipe gets silence rather than a diagnostic.
    assert captured.out == ""
    assert "--test-timeout-s" in captured.err
    # And it lands before either command reaches the outside world: the host-execution notice is
    # the first thing both of them print, and it was never printed.
    assert HOST_EXECUTION_NOTICE not in captured.err
