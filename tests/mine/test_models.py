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
from types import MappingProxyType
from typing import Final

import pytest
from pydantic import ValidationError

from assay.core import canonical_json

# TestReport and TestStatus are imported under other names on purpose: pytest tries to collect
# any module-level name starting with "Test", and warns about these two on every run if they
# are bound as they are spelled.
from assay.mine import ChangeSplit, CommitRef, GateOutcome, GateRejection, MiningYield, is_node_id
from assay.mine import TestReport as Report
from assay.mine import TestStatus as Status

# A yield that partitions: 213 accepted + 1447 rejected before the gate + 187 rejected by it
# = 1847 examined, and 213 + 187 = 400 candidates. Spelled out rather than computed, so a test
# that breaks the arithmetic breaks it visibly.
_REJECTED: Final = MappingProxyType(
    {
        GateRejection.NO_TEST_CHANGES: 1200,
        GateRejection.NO_SOURCE_CHANGES: 200,
        GateRejection.PATCH_DID_NOT_APPLY: 47,
        GateRejection.ALREADY_GREEN: 100,
        GateRejection.STILL_RED: 87,
        GateRejection.UNSTABLE_GREEN: 0,
        GateRejection.RUN_TIMED_OUT: 0,
    }
)


def _yield(**overrides: object) -> MiningYield:
    fields: dict[str, object] = {
        "commits_examined": 1847,
        "candidates": 400,
        "accepted": 213,
        "rejected": dict(_REJECTED),
    }
    fields.update(overrides)
    return MiningYield.model_validate(fields)


def test_the_gate_has_exactly_the_seven_rejection_reasons() -> None:
    # The set is closed: yield accounting is a partition of the commits examined, so an
    # eighth reason added without a place in the accounting would silently lose commits -
    # and a reason the walk can never reach (ADR-0015) would silently overstate coverage.
    assert {member.value for member in GateRejection} == {
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


def _counts(**counts: int) -> dict[GateRejection, int]:
    """A dense per-reason mapping, zero everywhere the caller did not name a count."""
    return {reason: counts.get(reason.name.lower(), 0) for reason in GateRejection}


@pytest.mark.parametrize(
    ("commits_examined", "candidates", "accepted", "rejected"),
    [
        (10, 11, 0, _counts(no_test_changes=10)),
        (10, 5, 6, _counts(still_red=4)),
        (0, 0, 1, _counts()),
    ],
    ids=["more-candidates-than-commits", "more-accepted-than-candidates", "accepted-from-nothing"],
)
def test_a_mining_yield_refuses_a_count_bigger_than_the_one_it_came_from(
    commits_examined: int, candidates: int, accepted: int, rejected: dict[GateRejection, int]
) -> None:
    # A yield line whose numerator exceeds its denominator is the one arithmetic that would
    # overstate the result, and overstating is fatal for a project about measurement. Each case
    # keeps the rest of the arithmetic sound, so the refusal is the overstatement it names.
    with pytest.raises(ValidationError):
        _yield(
            commits_examined=commits_examined,
            candidates=candidates,
            accepted=accepted,
            rejected=rejected,
        )


def test_a_mining_yield_refuses_a_negative_count() -> None:
    with pytest.raises(ValidationError, match="accepted"):
        _yield(commits_examined=0, candidates=0, accepted=-1, rejected=_counts())


def test_a_mining_yield_refuses_counts_that_do_not_partition_what_was_examined() -> None:
    # Nine commits cannot hold nine of every reason and six acceptances as well. Only the two
    # nesting inequalities used to be checked, so this document was accepted - and it overstates
    # both numerators at once.
    with pytest.raises(ValidationError, match="partition commits examined"):
        _yield(
            commits_examined=9,
            candidates=6,
            accepted=6,
            rejected=dict.fromkeys(GateRejection, 9),
        )


def test_a_mining_yield_refuses_a_rejected_mapping_that_omits_a_reason() -> None:
    # A reason missing and a reason that fired zero times must not be the same document
    # (ADR-0015). The rule was enforced only where the miner counted; a yield read back from a
    # file has to be refusable on the same terms (ADR-0011).
    with pytest.raises(ValidationError, match="every reason"):
        _yield(
            commits_examined=9,
            candidates=2,
            accepted=2,
            rejected={GateRejection.STILL_RED: 1},
        )


def test_a_mining_yield_refuses_a_negative_rejection_count() -> None:
    # ``Field(ge=0)`` reaches the scalars only, and a negative count here is exactly what would
    # balance both partition sums while overstating ``accepted``. It is why the two nesting
    # inequalities could be dropped as implied and this clause could not.
    with pytest.raises(ValidationError, match="negative"):
        _yield(
            commits_examined=9,
            candidates=8,
            accepted=8,
            rejected=_counts(still_red=1, unstable_green=-1),
        )


def test_a_mining_yield_counts_a_commit_with_no_environment_outside_the_seven_reasons() -> None:
    # A commit whose workspace could not be provisioned was examined, was never a candidate,
    # and belongs under no rejection reason - the gate never spoke about it.
    reported = _yield(
        commits_examined=10, candidates=2, accepted=2, rejected=_counts(), unprovisioned=8
    )

    assert reported.unprovisioned == 8
    assert reported.candidates == 2


def test_a_mining_yield_written_without_the_unprovisioned_count_still_partitions() -> None:
    # The field defaults to zero so a yield that predates it, and the fixture oracle that
    # constructs one without it, still describe the same partition.
    assert _yield().unprovisioned == 0


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
