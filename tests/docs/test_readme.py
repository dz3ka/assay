"""The README and the CLI make one promise about the host in one wording, or the test fails.

`assay.cli.main.HOST_EXECUTION_SENTENCE` is spelled once and printed in `assay mine --help`; the
README carries the same sentence, because a warning worded two ways is a warning a reader cannot
match to the thing they were told. That makes it a string spelled in two documents with nothing
holding them together - the situation ADR-0012 answers with a drift test rather than with a
promise, and ADR-0013 is the decision the sentence states.

`tests/cli/test_main.py` pins the constant's own wording and its presence in the help output. The
other half of the pair - the README - is a document, so it is asserted here beside the decision
record's shape rather than in the CLI's tests.

The fixture repository's yield is the second pair, and the more dangerous one. The README quotes
it as prose - "9 single-parent commits examined -> 2 valid tasks" - which is the harness's
headline number in a project whose whole subject is measurement honesty, and CLAUDE.md forbids
adjusting that number without an ADR behind it. So the assertion below *composes* the sentence
from :data:`tests.fixture_repo.EXPECTED_YIELD` rather than repeating the digits: a yield that
moves fails here, and the README cannot be left quietly misstating it.
"""

from pathlib import Path

from assay.cli.main import HOST_EXECUTION_SENTENCE
from tests.fixture_repo import EXPECTED_YIELD

README = Path(__file__).parent.parent.parent / "README.md"


def test_the_readme_carries_the_host_execution_sentence_verbatim() -> None:
    # Verbatim and unwrapped: the README is hand-wrapped prose, so a sentence broken across two
    # lines is the way this drifts, and reflowing it must fail here rather than pass quietly.
    assert HOST_EXECUTION_SENTENCE in README.read_text(encoding="utf-8")


def test_the_readme_quotes_the_fixture_yield_the_miner_actually_reports() -> None:
    # Composed from the constant, never typed out: the README, `tests/mine/test_pipeline.py` and
    # the CLI's own output would otherwise be three places holding the same numbers with nothing
    # between them, which is the situation ADR-0012 answers with a drift test.
    #
    # Verbatim and unwrapped, as with the sentence above: the README is hand-wrapped prose, so a
    # phrase reflowed across two lines is a way this silently stops being checked. Both phrases
    # therefore have to sit on one line each, and a reflow that splits either must fail here.
    readme = README.read_text(encoding="utf-8")

    assert (
        f"{EXPECTED_YIELD.commits_examined} single-parent commits examined -> "
        f"{EXPECTED_YIELD.accepted} valid tasks"
    ) in readme
    assert (
        f"{EXPECTED_YIELD.candidates} candidates reached the gate, "
        f"{EXPECTED_YIELD.unprovisioned} unprovisioned"
    ) in readme
