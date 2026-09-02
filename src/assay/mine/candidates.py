"""Turning one commit into a candidate task: the diff split, the id, and the prompt (SPEC §3).

The split is the load-bearing part. A mined task exists because a commit's *test* changes can
be applied without its *source* changes; if a path is classified wrongly the gate is measuring
something other than what it claims, and if a path is classified as neither it vanishes from
both patches. So the split here is total by construction: every changed path is a test change
or it is part of the ground truth.

Pure: string work over paths the caller already read from git.
"""

from collections.abc import Sequence

from assay.mine.models import ChangeSplit, NodeId

# A path segment equal to one of these makes everything under it a test change - including
# data files, which a test patch has to carry or the tests it applies cannot run.
_TEST_DIRECTORIES = frozenset({"test", "tests"})

# pytest's own default discovery shape, plus conftest: a module named this way is a test even
# when it lives beside the code it exercises.
_TEST_PREFIX = "test_"
_TEST_SUFFIX = "_test.py"
_CONFTEST = "conftest.py"

# What a task id may contain (suite/models.py:22 pins the whole shape). Anything else in a
# repository directory name is replaced rather than dropped, so two different names cannot
# collapse into one id by having their illegal characters deleted.
_ID_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")
_ID_SEPARATOR = "-"
_ID_FALLBACK = "repo"

# 128 characters total (suite/models.py:22), minus the separator and the abbreviated sha.
_SHA_CHARS = 12
_MAX_SLUG = 128 - 1 - _SHA_CHARS

_HEX = frozenset("0123456789abcdef")


def is_test_path(path: str) -> bool:
    """Return whether ``path`` is part of a commit's test change.

    ``path`` is repo-relative POSIX, as git reports it. The rule is pytest's discovery
    convention plus the directory convention every repository that has one uses, and it is
    deliberately conservative in one direction only: a source file misread as a test would be
    applied before the gate's red run and could make a genuinely red commit look already
    green, whereas a test file misread as source is discarded as ``no_test_changes``. Losing
    a candidate is a smaller error than minting a wrong one.
    """
    if not path:
        return False
    *directories, name = path.split("/")
    if any(directory in _TEST_DIRECTORIES for directory in directories):
        return True
    if name == _CONFTEST:
        return True
    return name.endswith(_TEST_SUFFIX) or (name.startswith(_TEST_PREFIX) and name.endswith(".py"))


def pytest_selectors(test_files: Sequence[str]) -> tuple[str, ...]:
    """The members of ``test_files`` a test runner can actually be pointed at.

    A commit's test half is whatever :func:`is_test_path` claimed, which includes the data
    files a suite ships - the fixture repository's own ``tests/data/sample.bin`` is one. Handing
    those to pytest as a selection would either collect nothing or refuse the whole run, and
    handing it *no* selection at all is worse: pytest would run the entire suite and the gate
    would be measuring a different thing than it says it is.

    A path that would reach the runner's argv as a *command-line option* is not one of them
    either. Both runners refuse a selector beginning with a dash rather than let it change the
    command they build (``assay.host.SelectorError``, ``assay.sandbox.SandboxError``), so
    passing one on would end a whole mining walk where one candidate should simply have been
    discarded. The shape cannot arrive from git - ``assay.host.git`` refuses such a path when it
    reads it - but it can arrive from a suite on disk, whose recorded ``test_files`` are taken as
    written, and the answer is the same either way: it is not a path a runner can be pointed at,
    so it is not selected. Deciding it here, on the task's own data, is what keeps every caller
    from having to catch a refusal (ADR-0029). The empty string needs no separate test: it does
    not end in ``.py``.

    Spelled here rather than in the caller because both halves of M1 need the same answer - the
    pipeline decides ``no_test_changes`` on it, and the gate builds its argv from it - and two
    spellings of "runnable" would let those two disagree about what was measured.
    """
    return tuple(path for path in test_files if path.endswith(".py") and not path.startswith("-"))


def split_changes(paths: Sequence[str]) -> ChangeSplit:
    """Divide ``paths`` into the test half and the ground-truth half, keeping git's order.

    Total: a path that is not a test change is part of the ground truth, including files that
    are neither code nor tests. A commit's ground-truth patch is "the commit minus its test
    changes", and anything else would apply a different diff than the one that was reviewed.
    """
    test_files = tuple(path for path in paths if is_test_path(path))
    source_files = tuple(path for path in paths if not is_test_path(path))
    return ChangeSplit(test_files=test_files, source_files=source_files)


def mint_task_id(repo_slug: str, sha: str) -> str:
    """Mint the task id for ``sha`` in the repository called ``repo_slug``.

    The id is ``<normalised slug>-<first 12 sha characters>`` and must satisfy the pattern
    ``suite/models.py:22`` pins, or the task the miner just proved cannot be written down.
    ``repo_slug`` is a directory name - text nobody in this project chose - so it is
    allowlisted down to the legal alphabet rather than trusted; the sha is refused instead of
    normalised, because a mangled one would attribute a task to a commit that cannot be
    checked out.

    Raises:
        ValueError: if ``sha`` is not at least 12 lowercase hex characters.
    """
    if len(sha) < _SHA_CHARS or any(character not in _HEX for character in sha):
        raise ValueError(f"sha must be at least {_SHA_CHARS} lowercase hex characters: {sha!r}")
    return f"{_normalise_slug(repo_slug)}{_ID_SEPARATOR}{sha[:_SHA_CHARS]}"


def build_prompt(subject: str, split: ChangeSplit, fail_to_pass: Sequence[NodeId]) -> str:
    """Write the task statement the tool under evaluation sees alongside the workspace.

    It states the intent (the commit's own subject, which is the closest thing a mined task
    has to an issue), names the tests that must go from red to green, and names the test files
    as off-limits - they are the specification, and a tool that edits them has not fixed
    anything.

    ``split.source_files`` is deliberately **not** rendered. Those are the files the fix lives
    in, and naming them hands over the first half of the answer: it would make every tool
    score higher on a task easier than the work the task claims to measure. The parameter is
    the whole split because that is the value the caller holds, not because both halves are
    used.

    The result goes into a content-addressed ``Task``, so it is a pure function of its
    arguments - same commit, same bytes.
    """
    targets = "\n".join(f"- {node_id}" for node_id in fail_to_pass)
    off_limits = "\n".join(f"- {path}" for path in split.test_files)
    return (
        f"{subject.strip()}\n"
        "\n"
        "The tests below fail in this workspace. Make them pass:\n"
        f"{targets}\n"
        "\n"
        "The tests are the specification: do not modify these files.\n"
        f"{off_limits}\n"
        "\n"
        "The rest of the suite must keep passing.\n"
    )


def _normalise_slug(repo_slug: str) -> str:
    """Reduce a repository directory name to something a task id may legally contain.

    Illegal characters become the separator rather than disappearing, so two different names
    stay two different ids; runs of separators collapse and the ends are trimmed, because the
    pattern requires the first character to be alphanumeric and a trailing separator reads as
    a truncation. A name with nothing legal in it at all still has to produce a usable id, so
    it falls back to a fixed word - the sha half keeps it unique.
    """
    lowered = repo_slug.lower()
    allowed = "".join(
        character if character in _ID_ALLOWED else _ID_SEPARATOR for character in lowered
    )
    collapsed = _ID_SEPARATOR.join(part for part in allowed.split(_ID_SEPARATOR) if part)
    trimmed = collapsed[:_MAX_SLUG].strip("._-")
    # Stripping ``._-`` from the front leaves an alphanumeric first character or nothing at
    # all, which is exactly what the pattern asks for.
    return trimmed or _ID_FALLBACK
