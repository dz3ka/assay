"""The task and suite schemas - the shape SPEC §3 mines into and every later stage reads.

Three rules run through all of it. No field has a default, so a document and the model built
from it correspond key for key and re-encode to the bytes they were read from. Paths are
POSIX and repo-relative, because a suite is written on one platform and replayed on another.
And a task list is stored in the one order that hashes to its content address, so a suite
cannot be reordered into a second file that claims the same provenance.

Pure: validation only, no I/O. Reading and writing suite files is :mod:`assay.suite.io`.
"""

from collections.abc import Mapping
from itertools import pairwise
from typing import Literal

from pydantic import Field, field_validator

from assay.core import SchemaModel

# A task id appears in file names, report tables and CLI arguments, so it is restricted to
# what is safe in all three; 128 characters is the same budget as a short branch name.
_TASK_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"

# Full 40-character SHA-1, lowercase: an abbreviated or symbolic ref is not reproducible.
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"


def _repo_relative_posix(path: str) -> str:
    """Return ``path`` unchanged, or refuse it as unusable in a checkout on another host.

    A suite is mined on a developer's machine (Windows, here) and replayed on a Linux runner.
    A backslash is a separator on one and an ordinary filename character on the other, and an
    absolute or ``..``-bearing path names a file the trial has no business touching at all.
    """
    if not path:
        raise ValueError("test file path must not be empty")
    if "\\" in path:
        raise ValueError(f"test file path must use POSIX separators, found a backslash: {path!r}")
    if path.startswith("/"):
        raise ValueError(f"test file path must be repo-relative, found an absolute path: {path!r}")
    if ".." in path.split("/"):
        raise ValueError(f"test file path must not contain a '..' segment: {path!r}")
    return path


class Task(SchemaModel):
    """One mined, ground-truthed task: a repo state, tests that fail there, and the fix.

    ``test_patch`` touches test files only and ``ground_truth_patch`` touches everything but;
    that split is what the red-to-green gate depends on. Enforcing it needs the repository,
    so it is the miner's job (M1), not this boundary's.
    """

    schema_version: Literal[1]
    task_id: str = Field(pattern=_TASK_ID_PATTERN)
    # Never emitted unredacted: the redaction boundary that owns that is in the reporter.
    repo_url: str
    base_commit: str = Field(pattern=_COMMIT_PATTERN)
    test_files: tuple[str, ...] = Field(min_length=1)
    test_patch: str
    ground_truth_patch: str
    # A task with nothing to turn from red to green has no gate and cannot be scored.
    fail_to_pass: tuple[str, ...] = Field(min_length=1)
    pass_to_pass: tuple[str, ...]
    prompt: str
    # str -> str: metadata is provenance a human reads, not a place to smuggle structure that
    # would then have to be canonicalised.
    metadata: Mapping[str, str]

    @field_validator("test_files")
    @classmethod
    def _check_paths(cls, test_files: tuple[str, ...]) -> tuple[str, ...]:
        for path in test_files:
            _repo_relative_posix(path)
        return test_files


class SuiteBody(SchemaModel):
    """The part of a suite file that is hashed: the task set and what it is called."""

    schema_version: Literal[1]
    suite_name: str
    tasks: tuple[Task, ...]

    @field_validator("tasks")
    @classmethod
    def _check_canonical_order(cls, tasks: tuple[Task, ...]) -> tuple[Task, ...]:
        """Require the one order that hashes to the suite's content address.

        Sorting here instead of refusing would let two different files - the same tasks in a
        different order - produce the same digest, so a result could no longer be attributed
        to the exact bytes it was run against.
        """
        task_ids = [task.task_id for task in tasks]
        seen: set[str] = set()
        for task_id in task_ids:
            if task_id in seen:
                raise ValueError(f"duplicate task_id: {task_id!r}")
            seen.add(task_id)
        for earlier, later in pairwise(task_ids):
            if earlier > later:
                raise ValueError(f"tasks must be sorted by task_id: {earlier!r} precedes {later!r}")
        return tasks


class SuiteFile(SchemaModel):
    """A suite on disk: the hashed body, plus provenance that is deliberately not hashed.

    ``schema_version`` is repeated here and in the body on purpose. The one on the envelope
    is what :func:`assay.suite.io.load_suite` probes before parsing anything; the one in the
    body is inside the digest, so a hash always states which schema it was computed under.

    ``generated_at`` and ``generator`` sit outside ``suite_hash``: a digest that covered the
    clock would give two identical task sets two different addresses, which is the whole
    property content addressing exists to provide.
    """

    schema_version: Literal[1]
    suite_hash: str
    generated_at: str
    generator: str
    body: SuiteBody
