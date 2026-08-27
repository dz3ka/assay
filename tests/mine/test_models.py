"""The values M1's miner passes around, and the one document it reports.

Two properties are defended here. The in-process values (:class:`TestReport`,
:class:`GateOutcome`, :class:`CommitRef`, :class:`ChangeSplit`) are frozen dataclasses rather
than schema models on purpose - they are never serialised, so pinning them to
``SchemaModel``'s extra="forbid" contract would put schema-stability obligations on internals
M2 has to stay free to change. :class:`MiningYield` is the opposite case: it is the number
CLAUDE.md requires every report to carry ("1,847 commits examined -> 213 valid tasks"), so it
is a document, and it has to survive canonical encoding.

The node-id shape is the third thing here. It is spelled in this package and deliberately not
in the suite schema, where ``fail_to_pass`` is public at v1 and stays wide (ADR-0012 is the
precedent for spelling a convention twice rather than sharing it across a layer).
"""

import dataclasses

import pytest
from pydantic import ValidationError

from assay.core import canonical_json

# TestReport and TestStatus are imported under other names on purpose: pytest tries to collect
# any module-level name starting with "Test", and warns about these two on every run if they
# are bound as they are spelled.
from assay.mine import ChangeSplit, CommitRef, GateOutcome, GateRejection, MiningYield, is_node_id
from assay.mine import TestReport as Report
from assay.mine import TestStatus as Status


def _yield(**overrides: object) -> MiningYield:
    fields: dict[str, object] = {
        "commits_examined": 1847,
        "candidates": 400,
        "accepted": 213,
        "rejected": {GateRejection.ALREADY_GREEN: 100, GateRejection.STILL_RED: 87},
    }
    fields.update(overrides)
    return MiningYield.model_validate(fields)


def test_the_gate_has_exactly_the_eight_rejection_reasons() -> None:
    # The set is closed: yield accounting is a partition of the candidates examined, so a
    # ninth reason added without a place in the accounting would silently lose commits.
    assert {member.value for member in GateRejection} == {
        "merge_commit",
        "no_test_changes",
        "no_source_changes",
        "patch_did_not_apply",
        "already_green",
        "still_red",
        "unstable_green",
        "run_timed_out",
    }


def test_a_test_status_names_the_four_ways_a_selected_test_can_end() -> None:
    # collect_error is not an errored test: it is a test that never ran because its module
    # would not import, which is the ordinary shape of red at the parent commit.
    assert {member.value for member in Status} == {
        "passed",
        "failed",
        "errored",
        "collect_error",
    }


def test_a_mining_value_cannot_be_edited_after_it_is_built() -> None:
    # These four are frozen for the same reason a SchemaModel is: a value read by a later
    # gate step has to still be the value the earlier step produced. The static half of that
    # fence is mypy, which is why each assignment below needs an ignore to compile at all.
    report = Report(statuses={}, uncollectable=(), exit_code=0, timed_out=False)
    outcome = GateOutcome(rejection=None, fail_to_pass=(), pass_to_pass=())
    commit = CommitRef(sha="a" * 40, parent="b" * 40, subject="Fix the parser")
    split = ChangeSplit(test_files=(), source_files=())

    with pytest.raises(dataclasses.FrozenInstanceError):
        report.exit_code = 1  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.rejection = GateRejection.STILL_RED  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        commit.subject = ""  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        split.source_files = ()  # type: ignore[misc]


def test_a_mining_yield_reports_the_denominator_next_to_the_count() -> None:
    # CLAUDE.md: never report the task count alone. The three counts and the per-reason
    # breakdown travel together or the honest form cannot be printed.
    reported = _yield()

    assert reported.commits_examined == 1847
    assert reported.accepted == 213
    assert reported.rejected[GateRejection.ALREADY_GREEN] == 100


def test_a_mining_yield_survives_canonical_encoding() -> None:
    # Every count is an int: core.canonical refuses a float anywhere in a document, so a
    # rate computed here rather than at the renderer would make the yield unhashable.
    encoded = canonical_json(_yield().model_dump(mode="json"))

    assert b'"already_green":100' in encoded
    assert b'"accepted":213' in encoded


def test_a_mining_yield_refuses_a_fractional_count() -> None:
    with pytest.raises(ValidationError, match="rejected"):
        _yield(rejected={GateRejection.STILL_RED: 1.5})


def test_a_mining_yield_refuses_a_field_it_does_not_know() -> None:
    with pytest.raises(ValidationError, match="yield_rate"):
        _yield(yield_rate="0.115")


@pytest.mark.parametrize(
    ("commits_examined", "candidates", "accepted"),
    [(10, 11, 0), (10, 5, 6), (0, 0, 1)],
    ids=["more-candidates-than-commits", "more-accepted-than-candidates", "accepted-from-nothing"],
)
def test_a_mining_yield_refuses_a_count_bigger_than_the_one_it_came_from(
    commits_examined: int, candidates: int, accepted: int
) -> None:
    # A yield line whose numerator exceeds its denominator is the one arithmetic that would
    # overstate the result, and overstating is fatal for a project about measurement.
    with pytest.raises(ValidationError):
        _yield(commits_examined=commits_examined, candidates=candidates, accepted=accepted)


def test_a_mining_yield_refuses_a_negative_count() -> None:
    with pytest.raises(ValidationError, match="accepted"):
        _yield(commits_examined=0, candidates=0, accepted=-1)


@pytest.mark.parametrize(
    "node_id",
    [
        "tests/test_parser.py::test_round_trip",
        "src/pkg/test_api.py::TestClass::test_method",
        "tests/test_parser.py::test_round_trip[case-1]",
        "a.py::t",
    ],
    ids=["plain", "class-nested", "parametrised", "shortest"],
)
def test_a_pytest_node_id_is_a_posix_path_and_a_test_name(node_id: str) -> None:
    assert is_node_id(node_id)


@pytest.mark.parametrize(
    "node_id",
    [
        "",
        "tests/test_parser.py",
        "tests/test_parser.py::",
        "test_round_trip",
        r"tests\test_parser.py::test_round_trip",
        "tests/test parser.py::test_round_trip",
        "tests/test_parser.py::test round trip",
        "tests/fixtures/data.json::test_round_trip",
        "tests/test_parser.py::test_round_trip\n",
    ],
    ids=[
        "empty",
        "no-test-name",
        "empty-test-name",
        "no-path",
        "backslash-separator",
        "space-in-path",
        "space-in-name",
        "not-a-python-file",
        "trailing-newline",
    ],
)
def test_a_node_id_that_would_not_select_anything_is_refused(node_id: str) -> None:
    assert not is_node_id(node_id)
