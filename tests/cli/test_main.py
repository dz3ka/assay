"""What the four-command surface promises, and what its three built commands do.

Three properties carry this module.

The first is that ``run`` refuses a run nobody should trust the report of *before* it spends
anything: a tool named without the naive baseline is refused with one sentence and exit 1
(CLAUDE.md - the baseline is in every report), and the refusal lands before the suite is even
read. The seam that decides where each of the agentic adapter's argvs runs - `git` on this
host, the tool inside the container - is asserted on a fake process rather than a daemon, for
the reason ``tests/sandbox/test_adapter_phase.py`` gives about the argv it composes. What
cannot be asserted here is the run itself: that is ``tests/score/test_end_to_end.py``'s
bracket, which needs images and containers.

The second is that a successful ``report`` writes the document and nothing else: stdout carries
bytes that validate as a :class:`~assay.report.Report`, and stderr carries nothing at all. M0
split the streams because the intervals were invented and the canonical document could not
carry the prose admitting it (RULING 4); the intervals are measured now, so every caveat a
reader is owed is a caption inside the two prose formats and stderr means only that something
went wrong.

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
import re
import sys
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from assay.adapters import ProcessOutput
from assay.cli import main
from assay.cli.main import (
    DEFAULT_MODEL,
    DEFAULT_TRIAL_TIMEOUT_S,
    DEFAULT_TRIALS,
    EXIT_FAILED,
    EXIT_USAGE,
    GENERATOR,
    HOST_EXECUTION_NOTICE,
    HOST_EXECUTION_SENTENCE,
    TOOL_API_KEY_ENV,
    TOOL_KILLED_EXIT_CODE,
    adapter_phase_process,
    build_parser,
    host_tool_process,
)
from assay.host import minimal_env
from assay.report import Report
from assay.sandbox import AGENT_EXECUTABLE
from assay.suite import load_suite
from tests.fixture_repo import EXPECTED_YIELD, build_fixture_repo

FIXTURES = Path(__file__).parent.parent / "fixtures"
RESULTS = FIXTURES / "results_overlapping.json"

# The three formats the `report` command offers.
FORMATS = ["json", "text", "html"]

# Stands in for the value of ASSAY_MODEL_API_KEY. Never a real one, and never read from the
# environment either: what these tests are about is where a key travels, not what it is.
_KEY = "sk-not-a-real-key"

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


def test_version_names_the_milestone_beside_the_package_version_and_needs_no_subcommand(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The package version has read 0.1.0 since M0 and cannot tell that skeleton apart from this
    # harness, so the line carries the milestone too (ADR-0047). The bare argv is half the
    # claim: `--version` is consumed while options are read, before argparse enforces the
    # required subcommand, so a user asking what they have installed does not have to name a
    # command they are not running.
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert re.fullmatch(r"assay/\d+\.\d+(\.\d+)? \(milestone M\d\)\n", captured.out)
    # A version is not a warning: nothing about it belongs on the stream that means something
    # went wrong.
    assert captured.err == ""


def test_the_version_line_leads_with_the_token_a_suite_records_as_its_generator(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # One string, two surfaces. Every suite Assay writes records GENERATOR in its `generator`
    # field, so the version line is built from that constant rather than from a second read of
    # the distribution's version - a reader holding a suite can match the token in it against
    # the token this prints, and two spellings of it could drift apart.
    with pytest.raises(SystemExit):
        main(["--version"])

    assert capsys.readouterr().out.split(" ")[0] == GENERATOR


def test_no_command_at_all_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    # Bare `assay` has nothing to do. It must not exit 0 and leave a caller believing it did.
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0
    assert capsys.readouterr().err != ""


def test_report_writes_a_document_stdout_can_be_parsed_from(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Nothing but the document reaches stdout, and it parses back into the schema it was
    # rendered from - the canonical format is API (CLAUDE.md).
    code, out, err = invoke(capsys, ["report", "--results", str(RESULTS), "--format", "json"])

    assert code == 0
    report = Report.model_validate(json.loads(out))
    assert len(report.tools) == 2
    assert err == ""


@pytest.mark.parametrize("fmt", FORMATS)
def test_a_successful_report_says_nothing_on_stderr(
    capsys: pytest.CaptureFixture[str], fmt: str
) -> None:
    # M0 printed the placeholder admission here, because the intervals were invented and the
    # JSON document could not carry the prose saying so. The intervals are measured now, every
    # caveat a reader is owed is a caption inside the two prose formats, and stderr is back to
    # meaning "something went wrong" in every format.
    _, _, err = invoke(capsys, ["report", "--results", str(RESULTS), "--format", fmt])

    assert err == ""


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
    [("json", "{"), ("text", "Assay report"), ("html", "<!DOCTYPE html>")],
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


def _tool(*code: str) -> list[str]:
    """A stand-in for an agentic tool: this interpreter, which every host here has."""
    return [sys.executable, "-c", *code]


def test_the_tool_process_bridge_reports_the_exit_code_and_both_streams(tmp_path: Path) -> None:
    # The second seam this module binds (`assay.adapters.ToolProcess`). A tool's non-zero exit
    # is data an adapter records, exactly as a non-zero `git apply --check` is: the tool
    # answered, and the answer was no.
    argv = _tool("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)")

    output = host_tool_process(argv, cwd=tmp_path, timeout_s=30, env=minimal_env())

    assert output.exit_code == 3
    assert output.stdout.strip() == "out"
    assert output.stderr.strip() == "err"
    assert output.timed_out is False


def test_a_tool_killed_at_its_budget_is_a_value_rather_than_an_exception(tmp_path: Path) -> None:
    # A tool that ran out of wall clock is a countable outcome of the trial, not an incident:
    # the adapter records it and the workspace is scored on whatever the tool left behind.
    argv = _tool("import time; time.sleep(600)")

    output = host_tool_process(argv, cwd=tmp_path, timeout_s=1, env=minimal_env())

    assert output.timed_out is True
    assert output.exit_code == TOOL_KILLED_EXIT_CODE
    # Negative, so it cannot be mistaken for a status the tool chose for itself.
    assert output.exit_code < 0


def test_the_tool_sees_the_directory_and_the_environment_it_was_handed_and_no_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bridge adds nothing to `env`. The model key is the name this matters most for: a tool
    # under evaluation gets it only when the caller put it there deliberately (plan section 7).
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ASSAY_MODEL_API_KEY", "sk-not-a-real-key")
    argv = _tool(
        "import os, pathlib; print(pathlib.Path.cwd()); print('ASSAY_MODEL_API_KEY' in os.environ)"
    )

    output = host_tool_process(argv, cwd=workspace, timeout_s=30, env=minimal_env())

    reported_cwd, saw_the_key = output.stdout.splitlines()
    assert Path(reported_cwd).resolve() == workspace.resolve()
    assert saw_the_key == "False"


# --- `assay run`: the surface, the baseline rule, and where each argv actually runs ----------

# A suite path that does not exist. Every refusal below has to arrive *before* anything is read,
# so the tests can prove the order by pointing the command at a file nobody wrote.
_NO_SUITE = "suite-that-was-never-written.json"

# The flags SPEC section 6 fixes for the command, and the ones `run_run` is driven by.
RUN_FLAGS = ["--suite", "--repo", "--out", "--adapter", "--trials", "--trial-timeout-s", "--model"]


def run_argv(tmp_path: Path, *adapters: str) -> list[str]:
    """An `assay run` command line naming ``adapters``, against paths that do not exist yet."""
    argv = [
        "run",
        "--suite",
        str(tmp_path / _NO_SUITE),
        "--repo",
        str(tmp_path),
        "--out",
        str(tmp_path / "results.json"),
    ]
    for adapter in adapters:
        argv += ["--adapter", adapter]
    return argv


@dataclass(frozen=True)
class Started:
    """One call the tool seam was asked to make, recorded rather than run."""

    argv: tuple[str, ...]
    cwd: Path
    timeout_s: int
    env: dict[str, str]


class FakeProcess:
    """A :class:`assay.adapters.ToolProcess` that starts nothing and remembers everything.

    The routing binding decides where an argv goes, and *that* is what these tests are about:
    a real docker client would prove the same thing far more slowly and only on a host with a
    daemon up (``tests/sandbox/test_adapter_phase.py`` takes the same position about the argv
    it composes).
    """

    def __init__(self) -> None:
        self.calls: list[Started] = []

    def __call__(
        self, argv: Sequence[str], *, cwd: Path, timeout_s: int, env: Mapping[str, str]
    ) -> ProcessOutput:
        self.calls.append(Started(argv=tuple(argv), cwd=cwd, timeout_s=timeout_s, env=dict(env)))
        return ProcessOutput(exit_code=0, stdout="", stderr="", timed_out=False)


def test_the_run_help_no_longer_says_the_command_is_unbuilt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The command is built, so the surface must stop scheduling it: a user who reads "not
    # implemented" about a command that runs has been told something false about the tool.
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--help"])
    assert excinfo.value.code == 0

    shown = " ".join(capsys.readouterr().out.split())
    assert "not implemented" not in shown.lower()
    for flag in RUN_FLAGS:
        assert flag in shown


def test_a_run_naming_a_tool_without_the_naive_baseline_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # CLAUDE.md: the naive baseline is in every report. Refused rather than added silently -
    # adding it would spend money the caller did not ask to spend - and refused before the
    # suite is read, which is what pointing at a file that does not exist proves.
    code, out, err = invoke(capsys, run_argv(tmp_path, "agentic"))

    assert code == 1
    assert out == ""
    assert len(err.strip().splitlines()) == 1
    assert "naive" in err


def test_naming_the_baseline_alongside_the_tool_gets_past_the_refusal(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # The same run, with the baseline in it, fails on the suite it was pointed at instead -
    # so the refusal is about the missing baseline and not about naming a tool at all.
    code, out, err = invoke(capsys, run_argv(tmp_path, "agentic", "naive"))

    assert code == 1
    assert out == ""
    assert _NO_SUITE in err


def test_the_two_oracles_are_not_asked_for_a_baseline_they_would_only_bracket(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    # An oracle is not a tool: the pair exists to bracket a report at 1.0 and 0.0, and a run of
    # the two of them measures the harness rather than anything the baseline could be compared
    # with. This is also the smallest run there is, and the one the bracket test drives.
    code, _out, err = invoke(capsys, run_argv(tmp_path, "ground-truth", "null"))

    assert code == 1
    assert _NO_SUITE in err


@pytest.mark.parametrize(
    "argv",
    [
        ["run"],
        ["run", "--suite", "s.json"],
        ["run", "--suite", "s.json", "--repo", ".", "--out", "r.json"],
    ],
    ids=["nothing", "suite-only", "no-adapter"],
)
def test_a_run_missing_a_required_argument_is_a_usage_error(argv: list[str]) -> None:
    # No defaults for the three paths or for the adapter list: which tools were measured is the
    # whole claim a result set makes, and a default would make it a guess.
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == EXIT_USAGE


@pytest.mark.parametrize("trials", ["0", "-1", "not-a-number"], ids=["zero", "negative", "words"])
def test_a_trial_count_below_one_is_refused(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, trials: str
) -> None:
    # A run of no trials writes an empty result set, which reports as a tool that was measured
    # and scored nothing rather than as a tool nobody ran.
    with pytest.raises(SystemExit) as excinfo:
        main([*run_argv(tmp_path, "null"), "--trials", trials])
    assert excinfo.value.code == EXIT_USAGE
    assert "--trials" in capsys.readouterr().err


def test_the_defaults_are_five_trials_and_the_model_the_adapters_name() -> None:
    # Five is CLAUDE.md's default n, and it is the number pass^n is read against.
    parsed = build_parser().parse_args(run_argv(Path(), "null"))

    assert parsed.trials == DEFAULT_TRIALS
    assert parsed.trial_timeout_s == DEFAULT_TRIAL_TIMEOUT_S
    assert parsed.model == DEFAULT_MODEL


def test_the_harvest_runs_git_on_the_host_exactly_as_the_adapter_asked(tmp_path: Path) -> None:
    # The agentic adapter has one seam and puts both its harvest and its tool through it, and
    # the two cannot go to the same place: `git` must run on the host, because the worktree the
    # harvest reads has a `.git` *file* holding a host absolute path, which means nothing on
    # the far side of a bind mount. So a `git` argv is handed on untouched.
    fake = FakeProcess()
    seam = adapter_phase_process(image_tag="assay-task:abc", api_key=_KEY, process=fake)

    seam(("git", "add", "-A"), cwd=tmp_path, timeout_s=120, env={"PATH": "/usr/bin"})

    started = fake.calls[0]
    assert started.argv == ("git", "add", "-A")
    assert started.cwd == tmp_path
    assert started.timeout_s == 120
    # Untouched: the harvest is Assay's own machinery and has no business holding a model key.
    assert started.env == {"PATH": "/usr/bin"}


def test_the_tool_itself_is_wrapped_into_the_adapter_phase_container(tmp_path: Path) -> None:
    # ADR-0039, ruling 7: the tool runs inside the container. What runs on the host is the
    # docker client, and the argv it is given is the one `assay.sandbox` composes - this
    # binding writes no container flag of its own.
    fake = FakeProcess()
    seam = adapter_phase_process(image_tag="assay-task:abc", api_key=_KEY, process=fake)
    tool = (AGENT_EXECUTABLE, "-p", "fix the tests")

    seam(tool, cwd=tmp_path, timeout_s=900, env=minimal_env())

    started = fake.calls[0]
    assert started.argv[:2] == ("docker", "run")
    assert "assay-task:abc" in started.argv
    # The tool's own command line, last and unchanged: the container is around it, not in it.
    assert started.argv[-len(tool) :] == tool
    assert started.timeout_s == 900


def test_the_model_key_reaches_the_container_by_name_and_never_through_an_argv(
    tmp_path: Path,
) -> None:
    # The rename happens here, at the binding: Assay reads ASSAY_MODEL_API_KEY and the tool
    # reads ANTHROPIC_API_KEY, and neither the adapter nor the sandbox learns either name. The
    # value travels in the client's environment because an argv is readable by every process
    # on this machine (plan section 7a).
    fake = FakeProcess()
    seam = adapter_phase_process(image_tag="assay-task:abc", api_key=_KEY, process=fake)

    seam((AGENT_EXECUTABLE, "-p", "fix the tests"), cwd=tmp_path, timeout_s=900, env={})

    started = fake.calls[0]
    assert "--env" in started.argv
    assert TOOL_API_KEY_ENV in started.argv
    assert _KEY not in started.argv
    assert started.env[TOOL_API_KEY_ENV] == _KEY


# Prices reach a report only through the command line, and the ones below are plainly nobody's:
# no rate that could be mistaken for a figure this repository maintains is written into a file
# here (ADR-0046). $100 per million input tokens and $200 per million output tokens divide by
# hand against the disjoint fixture's recorded 10240 and 960.
PRICES_SOURCE = "an invented rate card, priced against nothing"
PRICED_RESULTS = FIXTURES / "results_disjoint.json"


def price_argv(*flags: str) -> list[str]:
    """A `report` command line over the disjoint fixture, plus whatever pricing flags."""
    return ["report", "--results", str(PRICED_RESULTS), "--format", "json", *flags]


def test_a_report_prices_the_tools_named_and_says_whose_prices_they_are(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The whole flag, end to end. ground-truth recorded 10240 input and 960 output tokens, so
    # (10240 * 100 + 960 * 200) / 1e6 = $1.216000, over the five tasks it solved: $0.243200
    # each. null recorded no tokens at all and is reported as unmeasured rather than free.
    code, out, err = invoke(
        capsys,
        price_argv(
            "--price",
            "ground-truth=100/200",
            "--price",
            "null=100/200",
            "--prices-source",
            PRICES_SOURCE,
        ),
    )

    assert code == 0
    assert err == ""
    document = json.loads(out)
    null, ground_truth = document["costs"]
    assert ground_truth["total_usd"] == "1.216000"
    assert ground_truth["usd_per_solved_task"] == "0.243200"
    assert null["basis"] == "no_tokens_recorded"
    assert document["prices_source"] == PRICES_SOURCE


def test_a_report_without_any_price_still_carries_a_costs_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The default, and every report rendered before this flag existed. The section is there and
    # every row says why it has no dollars in it: a section that appeared only when it had
    # money in it would make its own absence a statement (ADR-0035, ADR-0046).
    _, out, _ = invoke(capsys, price_argv())

    document = json.loads(out)

    assert document["prices_source"] is None
    assert [cost["basis"] for cost in document["costs"]] == [
        "no_price_supplied",
        "no_price_supplied",
    ]


@pytest.mark.parametrize("fmt", FORMATS)
def test_every_format_shows_the_costs_section(capsys: pytest.CaptureFixture[str], fmt: str) -> None:
    _, out, _ = invoke(
        capsys,
        [
            "report",
            "--results",
            str(PRICED_RESULTS),
            "--format",
            fmt,
            "--price",
            "ground-truth=100/200",
            "--prices-source",
            PRICES_SOURCE,
        ],
    )

    assert "1.216000" in out


@pytest.mark.parametrize(
    "flags",
    [
        ["--price", "ground-truth=100/200"],
        ["--prices-source", PRICES_SOURCE],
    ],
    ids=["price-without-source", "source-without-price"],
)
def test_either_pricing_flag_without_its_partner_is_a_usage_error(
    capsys: pytest.CaptureFixture[str], flags: list[str]
) -> None:
    # Symmetric. Dollars with no stated source cannot be attributed (SPEC 5.5), and a source
    # that priced nothing describes a table the report does not carry. Both are a command line,
    # so both land on stderr above the usage line at EXIT_USAGE rather than as a failed run.
    with pytest.raises(SystemExit) as excinfo:
        main(price_argv(*flags))

    assert excinfo.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--price" in captured.err


@pytest.mark.parametrize(
    "entry",
    [
        "ground-truth",
        "=100/200",
        "ground-truth=100",
        "ground-truth=one/two",
        "ground-truth=-100/200",
        "ground-truth=100/0.0000001",
    ],
    ids=["no-equals", "no-tool", "one-rate", "words", "negative", "finer-than-a-microdollar"],
)
def test_a_price_the_report_could_not_honour_is_refused(
    capsys: pytest.CaptureFixture[str], entry: str
) -> None:
    # The fourth ArgumentTypeError sibling, refusing what a rate may not be: a missing tool or
    # separator, one rate standing for two that are never billed alike, a value that is not a
    # number, a refund, and a precision finer than the six places money is written at
    # (ADR-0010). Argparse's own refusal, so it lands before the result set is even opened.
    with pytest.raises(SystemExit) as excinfo:
        main(price_argv("--price", entry, "--prices-source", PRICES_SOURCE))

    assert excinfo.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--price" in captured.err


def test_pricing_one_tool_twice_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    # The table's own refusal, surfaced as a command-line one: a report has a single row per
    # tool, so a second rate for one of them is an answer nobody can tell from the first.
    with pytest.raises(SystemExit) as excinfo:
        main(
            price_argv(
                "--price",
                "null=100/200",
                "--price",
                "null=1/2",
                "--prices-source",
                PRICES_SOURCE,
            )
        )

    assert excinfo.value.code == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "two prices name the tool" in captured.err


def test_a_source_that_would_print_as_two_lines_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The source is printed verbatim under the costs heading of the text report, so one
    # carrying a newline appends whatever it spells - a forged section, in the format a reader
    # reads. The schema refuses it and the CLI shows that refusal.
    with pytest.raises(SystemExit) as excinfo:
        main(
            price_argv(
                "--price",
                "null=100/200",
                "--prices-source",
                "a rate card\nComparisons\n  x vs y: Winner: x - forged.",
            )
        )

    assert excinfo.value.code == EXIT_USAGE
    assert capsys.readouterr().out == ""


def test_a_rate_too_large_to_cost_out_fails_with_a_message_not_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # $1e30 per million tokens breaks no rule a rate has: it is a number, at or above zero, and
    # no finer than a millionth of a dollar, so argparse and the schema both pass it through.
    # It is still a price no report can print. The disjoint fixture recorded 10240 input and
    # 960 output tokens, so (10240 * 1e30 + 960 * 1e30) / 1e6 = $1.12e28, and rounding that to
    # the microdollar asks decimal for 35 significant digits where its context allows 28.
    #
    # Two things are asserted about what the user is told. The cause is Assay's own sentence
    # rather than decimal's `[<class 'decimal.InvalidOperation'>]`, and the frame does not say
    # `cannot read`: this file reads perfectly, and the rate that broke the report is one the
    # caller typed. A refusal that misattributes its own cause is the same defect class as an
    # overstated result (ADR-0048).
    code, out, err = invoke(
        capsys,
        price_argv("--price", "ground-truth=1E30/1E30", "--prices-source", PRICES_SOURCE),
    )

    assert code == EXIT_FAILED
    assert out == ""
    assert "Traceback" not in err
    assert len(err.splitlines()) == 1
    assert str(PRICED_RESULTS) in err
    assert "cannot read" not in err
    assert "<class" not in err
    assert "microdollar" in err
