"""The stub-command error is user-facing copy: its exact shape is the contract."""

import pytest

from assay.core import AssayError, CanonicalizationError, NotImplementedInMilestone


def test_the_stub_message_names_the_command_the_milestone_and_the_plan() -> None:
    error = NotImplementedInMilestone("run", "M0", "M3")

    assert str(error) == "assay run is not implemented in M0 (planned: M3, SPEC section 7)"


@pytest.mark.parametrize(
    ("command", "planned"),
    [("mine", "M1"), ("validate", "M1"), ("run", "M3")],
)
def test_every_m0_stub_command_renders_its_own_planned_milestone(
    command: str, planned: str
) -> None:
    error = NotImplementedInMilestone(command, "M0", planned)

    expected = f"assay {command} is not implemented in M0 (planned: {planned}, SPEC section 7)"
    assert str(error) == expected
    assert error.command == command
    assert error.milestone == "M0"
    assert error.planned == planned


def test_stub_error_is_catchable_as_an_assay_error() -> None:
    with pytest.raises(AssayError):
        raise NotImplementedInMilestone("run", "M0", "M3")


def test_canonicalization_error_is_an_assay_error() -> None:
    assert issubclass(CanonicalizationError, AssayError)
