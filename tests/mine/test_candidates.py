"""Turning one commit into a candidate task: the diff split, the id, and the prompt.

SPEC §3 mines a task by applying a commit's *test* changes without its *source* changes, so
the split those two patches are cut from is the first thing that has to be right - and it has
to be total, because a path in neither half is a change that silently disappears from both
patches.

The id is the second: a mined task's id is minted here and validated by the suite schema, and
the repository directory name it is built from is text nobody in this project chose.
"""

import re

import pytest

from assay.mine import ChangeSplit, build_prompt, is_test_path, mint_task_id, split_changes
from assay.suite.models import _TASK_ID_PATTERN

_SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_parser.py",
        "test/test_parser.py",
        "tests/unit/test_parser.py",
        "src/pkg/test_helpers.py",
        "src/pkg/parser_test.py",
        "conftest.py",
        "tests/conftest.py",
        "tests/fixtures/expected.json",
    ],
    ids=[
        "under-tests",
        "under-test",
        "nested-under-tests",
        "test-prefixed-module",
        "test-suffixed-module",
        "root-conftest",
        "nested-conftest",
        "data-file-under-tests",
    ],
)
def test_a_test_change_is_recognised(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/assay/parser.py",
        "README.md",
        "docs/testing.md",
        "src/pkg/protest.py",
        "src/testing/util.py",
        "latest/thing.py",
        "",
    ],
    ids=[
        "source-module",
        "readme",
        "doc-about-testing",
        "test-inside-a-longer-word",
        "testing-is-not-tests",
        "tests-inside-a-longer-directory",
        "empty",
    ],
)
def test_a_source_change_is_not_mistaken_for_a_test(path: str) -> None:
    assert not is_test_path(path)


def test_the_split_keeps_every_path_exactly_once_and_in_order() -> None:
    # Totality is the property: the test patch and the ground-truth patch are cut from these
    # two tuples, so a path in neither would be a change the mined task loses silently.
    paths = ("src/a.py", "tests/test_a.py", "README.md", "tests/fixtures/x.json", "src/b.py")

    split = split_changes(paths)

    assert split.test_files == ("tests/test_a.py", "tests/fixtures/x.json")
    assert split.source_files == ("src/a.py", "README.md", "src/b.py")
    assert sorted(split.test_files + split.source_files) == sorted(paths)


def test_the_split_of_nothing_is_two_empty_halves() -> None:
    assert split_changes(()) == ChangeSplit(test_files=(), source_files=())


def test_a_minted_id_names_the_repo_and_the_commit() -> None:
    task_id = mint_task_id("fixture-repo", _SHA)

    assert task_id == "fixture-repo-0123456789ab"


@pytest.mark.parametrize(
    "repo_slug",
    [
        "fixture-repo",
        "My Repo!",
        "../../etc/passwd",
        ".hidden",
        "-leading-dash",
        "UPPER_CASE",
        "ünïcødé",
        "x" * 300,
        "",
        "!!!",
    ],
    ids=[
        "already-legal",
        "spaces-and-punctuation",
        "path-traversal",
        "leading-dot",
        "leading-dash",
        "uppercase-and-underscore",
        "non-ascii",
        "very-long",
        "empty",
        "nothing-legal-at-all",
    ],
)
def test_a_minted_id_is_one_the_suite_schema_accepts(repo_slug: str) -> None:
    # Checked against the real pattern, imported from the schema that will reject the task:
    # a copy of it here would agree with itself while drifting from the thing that matters.
    task_id = mint_task_id(repo_slug, _SHA)

    assert re.fullmatch(_TASK_ID_PATTERN, task_id), task_id
    assert task_id.endswith("-0123456789ab")


def test_minting_is_deterministic() -> None:
    assert mint_task_id("My Repo!", _SHA) == mint_task_id("My Repo!", _SHA)


@pytest.mark.parametrize(
    "sha",
    ["", "0123456789a", "0123456789AB0123456789ab0123456789abcdef", "not-hex-at-all"],
    ids=["empty", "too-short", "uppercase-hex", "not-hex"],
)
def test_minting_refuses_a_sha_git_would_not_have_produced(sha: str) -> None:
    # The slug is normalised because it is a directory name; the sha is refused because a
    # wrong one would attribute a task to a commit that cannot be checked out.
    with pytest.raises(ValueError, match="sha"):
        mint_task_id("fixture-repo", sha)


def test_the_prompt_states_the_intent_and_names_the_failing_tests() -> None:
    split = ChangeSplit(test_files=("tests/test_parser.py",), source_files=("src/pkg/parser.py",))

    prompt = build_prompt(
        "Fix off-by-one in the header parser", split, ("tests/test_parser.py::t",)
    )

    assert "Fix off-by-one in the header parser" in prompt
    assert "tests/test_parser.py::t" in prompt
    assert "tests/test_parser.py" in prompt


def test_the_prompt_does_not_name_the_files_the_fix_lives_in() -> None:
    # Naming them would hand over the first half of the answer, uniformly for every tool -
    # which makes the eval easier than the work it claims to measure (SPEC §3).
    split = ChangeSplit(
        test_files=("tests/test_parser.py",),
        source_files=("src/pkg/header.py", "src/pkg/scanner.py"),
    )

    prompt = build_prompt("Fix the parser", split, ("tests/test_parser.py::t",))

    assert "src/pkg/header.py" not in prompt
    assert "src/pkg/scanner.py" not in prompt
    assert "scanner" not in prompt


def test_the_prompt_is_deterministic() -> None:
    # It goes into a content-addressed task, so the same commit must render the same bytes.
    split = ChangeSplit(test_files=("tests/test_parser.py",), source_files=("src/pkg/parser.py",))

    assert build_prompt("Fix it", split, ("a.py::t", "b.py::t")) == build_prompt(
        "Fix it", split, ("a.py::t", "b.py::t")
    )
