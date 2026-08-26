"""The schema is the project's API (CLAUDE.md): what it accepts is what a suite may contain.

Every rejection below is a document that would otherwise be hashed and later replayed as if
it were trustworthy - a Windows path that cannot be checked out on the CI runner, a task set
whose order makes its own content hash ambiguous, a field this build does not understand.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.core import JsonValue, canonical_json, content_hash
from assay.suite import SuiteBody, Task

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _minimal_task_payload() -> dict[str, JsonValue]:
    """The hand-written fixture, freshly decoded so a test can mutate its copy."""
    payload: dict[str, JsonValue] = json.loads(
        (FIXTURES / "task_minimal.json").read_text(encoding="utf-8")
    )
    return payload


def _task(**overrides: JsonValue) -> Task:
    return Task.model_validate(_minimal_task_payload() | overrides)


def test_a_hand_written_task_round_trips_to_byte_identical_canonical_bytes() -> None:
    """M0's exit criterion (SPEC §7): the file, the model and the hash agree exactly."""
    raw = _minimal_task_payload()

    dumped: JsonValue = Task.model_validate(raw).model_dump(mode="json")

    assert canonical_json(dumped) == canonical_json(raw)
    assert content_hash(dumped) == content_hash(raw)


def test_a_task_document_may_not_omit_a_field() -> None:
    # No field has a default: a default would let a document omit a key and still round-trip
    # to different bytes than it was written with, which is the one thing §7 forbids.
    incomplete = _minimal_task_payload()
    del incomplete["prompt"]

    with pytest.raises(ValidationError, match="prompt"):
        Task.model_validate(incomplete)


def test_an_unknown_field_is_rejected_rather_than_dropped() -> None:
    # SPEC §8.7: a suite written by a future Assay must fail loudly here, because a silently
    # dropped field would re-hash to a different digest and break attribution.
    with pytest.raises(ValidationError, match="difficulty"):
        _task(difficulty="hard")


def test_a_task_cannot_be_mutated_after_validation() -> None:
    task = _task()

    with pytest.raises(ValidationError):
        task.task_id = "other"


@pytest.mark.parametrize(
    "task_id",
    ["fixture-repo.0001", "a", "0", "a1._-", "x" * 128],
    ids=["fixture", "single-letter", "digit", "all-legal-punctuation", "max-length"],
)
def test_a_legal_task_id_is_accepted(task_id: str) -> None:
    assert _task(task_id=task_id).task_id == task_id


@pytest.mark.parametrize(
    "task_id",
    ["", "Fixture", "-leading", ".leading", "has space", "has/slash", "x" * 129, "trailing\n"],
    ids=[
        "empty",
        "uppercase",
        "leading-hyphen",
        "leading-dot",
        "space",
        "slash",
        "too-long",
        "trailing-newline",
    ],
)
def test_an_illegal_task_id_is_rejected(task_id: str) -> None:
    with pytest.raises(ValidationError, match="task_id"):
        _task(task_id=task_id)


@pytest.mark.parametrize(
    "base_commit",
    [
        "0123456789abcdef0123456789abcdef0123456",
        "0123456789ABCDEF0123456789abcdef01234567",
        "",
        "HEAD",
    ],
    ids=["39-chars", "uppercase-hex", "empty", "symbolic-ref"],
)
def test_base_commit_must_be_a_full_lowercase_sha1(base_commit: str) -> None:
    with pytest.raises(ValidationError, match="base_commit"):
        _task(base_commit=base_commit)


@pytest.mark.parametrize(
    "path",
    [r"tests\test_parser.py", r"tests/sub\test.py"],
    ids=["backslash-separator", "backslash-inside-path"],
)
def test_a_test_file_path_containing_a_backslash_is_rejected(path: str) -> None:
    # The suite is written on Windows and replayed on an Ubuntu runner; a backslash there is
    # a legal filename character, not a separator, so it must never reach a checkout.
    with pytest.raises(ValidationError, match="backslash"):
        _task(test_files=[path])


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "/tests/test_parser.py"],
    ids=["outside-repo", "root-anchored"],
)
def test_an_absolute_test_file_path_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError, match="repo-relative"):
        _task(test_files=[path])


@pytest.mark.parametrize(
    "path",
    ["../secrets.py", "tests/../../escape.py"],
    ids=["leading", "embedded"],
)
def test_a_test_file_path_escaping_the_repo_is_rejected(path: str) -> None:
    with pytest.raises(ValidationError, match=r"\.\."):
        _task(test_files=[path])


def test_an_empty_test_file_path_is_rejected() -> None:
    with pytest.raises(ValidationError, match="empty"):
        _task(test_files=[""])


def test_a_task_must_name_at_least_one_test_file() -> None:
    with pytest.raises(ValidationError, match="test_files"):
        _task(test_files=[])


def test_a_task_must_name_at_least_one_failing_test() -> None:
    # A task with nothing to turn from red to green has no gate (SPEC §3) and cannot be scored.
    with pytest.raises(ValidationError, match="fail_to_pass"):
        _task(fail_to_pass=[])


def test_a_task_may_have_no_pre_existing_passing_tests() -> None:
    assert _task(pass_to_pass=[]).pass_to_pass == ()


def test_metadata_values_are_strings_and_are_not_coerced() -> None:
    with pytest.raises(ValidationError, match="metadata"):
        _task(metadata={"attempts": 3})


def test_metadata_may_be_empty() -> None:
    assert dict(_task(metadata={}).metadata) == {}


def _body(*task_ids: str) -> SuiteBody:
    tasks: list[JsonValue] = [
        _minimal_task_payload() | {"task_id": task_id} for task_id in task_ids
    ]
    return SuiteBody.model_validate(
        {"schema_version": 1, "suite_name": "fixture-repo", "tasks": tasks}
    )


def test_tasks_in_task_id_order_are_accepted() -> None:
    body = _body("a", "b", "c")

    assert [task.task_id for task in body.tasks] == ["a", "b", "c"]


def test_a_suite_may_contain_no_tasks() -> None:
    # A mining run with zero surviving candidates is a legitimate, reportable outcome.
    assert _body().tasks == ()


def test_tasks_out_of_task_id_order_are_rejected_rather_than_sorted() -> None:
    # Silently sorting would let two different files claim the same provenance: the bytes
    # that get hashed are exactly these, in exactly this order.
    with pytest.raises(ValidationError, match="sorted by task_id"):
        _body("b", "a")


def test_a_duplicate_task_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate task_id: 'a'"):
        _body("a", "a")
