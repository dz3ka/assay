"""Version probing has one job: fail with an actionable error before a parser fails with a dump."""

import pytest

from assay.core import SUPPORTED, AssayError, UnsupportedSchemaVersionError
from assay.core.versioning import require_supported_version


def test_every_schema_kind_starts_at_version_one() -> None:
    assert dict(SUPPORTED) == {"task": 1, "suite": 1, "result_set": 1}


def test_supported_versions_cannot_be_mutated_by_a_caller() -> None:
    with pytest.raises(TypeError):
        SUPPORTED["task"] = 2  # type: ignore[index]


def test_a_supported_version_is_returned_to_the_caller() -> None:
    assert require_supported_version("task", {"schema_version": 1, "task_id": "t1"}) == 1


def test_an_unsupported_version_names_kind_found_and_supported() -> None:
    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        require_supported_version("task", {"schema_version": 2})

    message = str(caught.value)
    assert "task" in message
    assert "2" in message
    assert "supported: 1" in message
    assert caught.value.kind == "task"
    assert caught.value.found == 2
    assert caught.value.supported == (1,)


def test_an_absent_version_key_reads_as_absent_rather_than_as_none() -> None:
    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        require_supported_version("result_set", {"results": []})

    message = str(caught.value)
    assert caught.value.found is None
    assert "None" not in message
    assert "absent" in message
    assert "result_set" in message
    assert "supported: 1" in message


def test_a_non_integer_version_is_rejected_rather_than_coerced() -> None:
    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        require_supported_version("suite", {"schema_version": "1"})

    assert caught.value.found == "1"
    assert "'1'" in str(caught.value)


def test_a_boolean_is_not_accepted_as_version_one() -> None:
    with pytest.raises(UnsupportedSchemaVersionError):
        require_supported_version("suite", {"schema_version": True})


def test_unsupported_schema_version_is_an_assay_error() -> None:
    assert issubclass(UnsupportedSchemaVersionError, AssayError)
