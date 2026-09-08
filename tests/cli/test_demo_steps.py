"""What the one-command demo runs, asserted without running any of it.

`scripts/demo.py` is the shortest path from a clone to a rendered report, and the thing that
can rot about it is not the pipeline - `tests/cli/test_main.py` and
`tests/score/test_end_to_end.py` already drive that - but the command line it types. A flag
renamed in `src/assay/cli/main.py` leaves the demo composing an argv argparse will refuse, and
nothing in the suite would notice until somebody ran the demo. So these tests read the argvs
back out of :func:`scripts.demo.demo_steps`, which is pure for exactly this reason, and put
each of them through the parser that will actually receive it.

They live in `tests/cli/` and not in a package of their own because every assertion below is an
assertion about a flag declared next door in `main.py`: a rename should break a test sitting
beside the parser.

Nothing here starts a process, builds a fixture or needs Docker. What the demo *does* with
these argvs is the demo's own to prove, by being run.
"""

from pathlib import Path

import pytest
from scripts.demo import demo_steps

from assay.cli.main import ADAPTER_NAMES, DEFAULT_TRIALS, ORACLE_ADAPTERS, build_parser

REPO = Path("/tmp/fixture/widget-fixture")
SUITE = Path("/tmp/fixture/suite.json")
RESULTS = Path("/tmp/fixture/results.json")

STEPS = demo_steps(repo=REPO, suite=SUITE, results=RESULTS)

# What each step's argv reads as after `<interpreter> -m assay.cli.main`: the subcommand, then
# the flags. SPEC §6's order is the pipeline's order, and `report` is run twice because the
# demo's artefact is the page in both prose formats.
EXPECTED_COMMANDS = ("mine", "validate", "run", "report", "report")


def command_of(argv: tuple[str, ...]) -> str:
    """The subcommand one step invokes, dropping the `-m assay.cli.main` prefix."""
    return argv[3]


def flags_of(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Every `--flag` in one step's argv, values dropped."""
    return tuple(word for word in argv if word.startswith("--"))


def value_after(argv: tuple[str, ...], flag: str) -> str:
    """The single value the given flag carries in one step's argv."""
    return argv[argv.index(flag) + 1]


def values_after(argv: tuple[str, ...], flag: str) -> set[str]:
    """Every value a repeatable flag carries in one step's argv."""
    return {argv[index + 1] for index, word in enumerate(argv) if word == flag}


def test_the_demo_runs_specs_four_commands_in_specs_order() -> None:
    assert tuple(command_of(argv) for argv in STEPS) == EXPECTED_COMMANDS


def test_every_step_is_an_invocation_of_the_cli_module_under_this_interpreter() -> None:
    # `-m assay.cli.main` rather than the `assay` console script: the demo has to work from a
    # `python scripts/demo.py` that never went through an entry point.
    assert {argv[1:3] for argv in STEPS} == {("-m", "assay.cli.main")}


@pytest.mark.parametrize("argv", STEPS, ids=EXPECTED_COMMANDS)
def test_every_step_is_a_command_line_the_parser_accepts(argv: tuple[str, ...]) -> None:
    # The whole point of the module. A flag renamed in `main.py` fails here rather than in
    # somebody's terminal, and argparse - not a list of strings in this file - is the judge.
    assert build_parser().parse_args(argv[3:]).command == command_of(argv)


def test_the_suite_mine_writes_is_the_suite_validate_and_run_read() -> None:
    mine, validate, run, *_ = STEPS

    assert value_after(mine, "--out") == value_after(validate, "--suite")
    assert value_after(run, "--suite") == value_after(validate, "--suite")


def test_the_results_run_writes_are_the_results_both_reports_read() -> None:
    _, _, run, text, html = STEPS

    assert value_after(text, "--results") == value_after(run, "--out")
    assert value_after(html, "--results") == value_after(run, "--out")


def test_the_two_reports_differ_only_in_the_format_they_ask_for() -> None:
    _, _, _, text, html = STEPS

    assert "--format" not in text, "the text report takes the default format, as a reader would"
    assert value_after(html, "--format") == "html"


def test_the_trials_count_tracks_the_house_default_rather_than_a_literal() -> None:
    # pass^n is read against this number, and the caption in every report says which n it was.
    # A demo that typed `5` would keep printing 5 after the default moved.
    run = STEPS[2]

    assert value_after(run, "--trials") == str(DEFAULT_TRIALS)


def test_the_demo_names_no_adapter_that_would_call_a_model() -> None:
    # The property that makes this runnable by anybody: both adapters answer from the task
    # itself, so the demo needs no key, reaches no network and spends nothing.
    tools = set(ADAPTER_NAMES) - ORACLE_ADAPTERS
    named = values_after(STEPS[2], "--adapter")

    assert len(named) == 2, "both oracles are named, because they bracket every result"
    assert named & tools == set()


def test_no_step_asks_for_a_model_or_a_price() -> None:
    # `--model` is only read by the two adapters the demo does not name, and `--price` needs
    # `--prices-source`, which is the reader's own words about a run that cost nothing.
    for argv in STEPS:
        assert "--model" not in flags_of(argv)
        assert "--price" not in flags_of(argv)
        assert "--prices-source" not in flags_of(argv)
