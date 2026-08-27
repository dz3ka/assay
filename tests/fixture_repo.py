"""The purpose-built git repository that proves the red->green gate works (SPEC §9).

SPEC §9 asks for "a small purpose-built git repository ... with a history containing: valid
red->green commits, a flaky test, a commit whose tests pass before the fix (must be rejected),
and a commit whose ground truth does not fix the tests (must be rejected). The miner must
produce exactly the expected yield from it." This module *is* that repository: a builder that
writes the history into a caller-supplied directory, plus the expected yield as an importable
value. CLAUDE.md calls the fixture a first-class deliverable and forbids adjusting the
expected yield to match a changed miner, so the numbers live here, beside the commits that
produce them, rather than inside whichever test happens to assert them.

**Why a builder and not a committed repository.** The obvious alternative - commit a nested
``.git`` directory - was probed and does not work: git records a nested repository as mode
``160000``, a gitlink, and a CI clone of Assay materialises an empty directory where the
fixture should be. A committed ``.bundle`` does work, but a bundle is a binary artefact that
still needs a generator to produce it, which is two sources that can drift. A builder module
is one source, is reviewable as a diff, and is type-checked like everything else.

**Why the object names are pinned.** ``Task.test_files`` is POSIX-only by schema
(``src/assay/suite/models.py:28``), the dev host is Windows and CI is ubuntu-latest, so a
line-ending or file-mode difference between the two would silently build a *different* fixture
repository on each - and a gate proven on one would not be the gate running on the other.
Every invocation below therefore pins identity, both timestamps, line endings and file mode,
and drops the ambient ``GIT_*`` environment together with the user's git config. The resulting
object names are the constants in :data:`FIXTURE_COMMITS`, :func:`build_fixture_repo` refuses
to return a repository that does not match them, and ``tests/mine/test_fixture_repo.py``
asserts them directly. That is the cross-platform canary: it is meant to fail loudly on the
first Linux CI run rather than let a platform difference through unnoticed.

The history, oldest first:

===  ======================  ==========================================  ====================
 #   label                   what the commit does                        expected verdict
===  ======================  ==========================================  ====================
 1   seed                    creates the package and its suite           not walked (root)
 2   mean_of_empty           guards a division by zero, adds its test    ACCEPTED
 3   slug_collapses_spaces   fixes ``slug()``, adds its test             ACCEPTED
 4   documented_total        adds a test that already passes             already_green
 5   broken_field_parse      adds a test its own fix does not repair     still_red
 6   fixed_field_parse       repairs it, touching no test file           no_test_changes
 7   payload_format_two      changes a *binary* fixture under tests/     patch_did_not_apply
 8   flaky_jitter            adds a test that disagrees with itself      unstable_green
 9   slow_lookup             adds a test that cannot finish when red     run_timed_out
10   deterministic_jitter    tidies a test, touching no source file      no_source_changes
11   merge_tidy              merges commit 10 back into main             merge_commit
===  ======================  ==========================================  ====================

Commits 2-10 are what ``History.commits()`` yields, so ``commits_examined`` is **9**: the root
has no parent, the merge has two, and neither is a candidate by construction. Six of the nine
reach :func:`assay.mine.decide_gate` and **2** of those are accepted. :data:`EXPECTED_YIELD`
is that arithmetic as a value and :data:`FIXTURE_COMMITS` is the table it is derived from -
both importable, because M1's end-to-end mining test asserts against them rather than prose.

Two properties of the history are deliberate and easy to undo by accident. Commit 6 repairs
the test commit 5 leaves failing and commit 10 retires the flake commit 8 introduces, so the
fixture's **HEAD is green, fast and deterministic** and an end-to-end test may run its whole
suite. And every one of the eight ``GateRejection`` reasons has a commit that reaches it, so
none of them is speculative - with the one caveat recorded in :data:`EXPECTED_YIELD`.
"""

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from assay.mine import GateRejection, MiningYield

# ----------------------------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------------------------

# Config forced onto every invocation. Line endings and file mode are what make the object
# names identical on Windows and on Linux; a signing key would make them identical on neither.
_CONFIG_FLAGS: Final = (
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
    "-c",
    "core.safecrlf=false",
    "-c",
    "core.fileMode=false",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "gc.auto=0",
)

_AUTHOR_NAME: Final = "Assay Fixture"
_AUTHOR_EMAIL: Final = "fixture@assay.invalid"

# A fixed instant, and one minute per commit: two commits made in the same second tie, and
# `git log`'s newest-first order stops being something the fixture may assert.
_FIRST_COMMIT_EPOCH_S: Final = 1_700_000_000
_COMMIT_INTERVAL_S: Final = 60

# Building the whole history is a dozen plumbing commands on a ten-file tree. This is a
# ceiling on a hang - a git that has not answered in a minute is not going to.
_GIT_TIMEOUT_S: Final = 60

_TRUNK_NAME: Final = "main"
_BRANCH_NAME: Final = "tidy"
_MERGE_SUBJECT: Final = "Merge branch 'tidy'"


@dataclass(frozen=True)
class FixtureCommit:
    """One commit of the fixture history, and what the miner must conclude about it.

    ``walked`` is whether ``History.commits()`` yields the commit at all. It is ``False`` for
    the root (no parent) and for the merge (two parents), which is why ``len(FIXTURE_COMMITS)``
    is not ``commits_examined``.

    ``rejection`` is the verdict, and ``None`` means the gate accepts the commit as a task. It
    is meaningful only where ``walked`` is true, with one documented exception: the merge
    carries ``MERGE_COMMIT`` so that reason has a witness in the history. The root carries
    ``None`` and ``walked=False``, which is *not* an acceptance - anything deriving counts from
    this table filters on ``walked`` first, as :data:`EXPECTED_YIELD` does.
    """

    label: str
    subject: str
    sha: str
    walked: bool
    rejection: GateRejection | None


# ----------------------------------------------------------------------------------------
# The repository's files, in the versions each commit writes
# ----------------------------------------------------------------------------------------

_PYPROJECT = """\
[project]
name = "widget"
version = "0.1.0"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["widget"]
"""

_CONFTEST = '''\
"""Empty on purpose.

pytest's default ``importmode=prepend`` puts a conftest's own directory on ``sys.path``, so
the existence of this file is what lets the suite run against a plain checkout as well as
against an installed wheel. Assay mines repositories it does not get to configure, and this
is the shape most of them have.
"""
'''

_INIT = '''\
"""A tiny library that exists to be mined. Built by Assay's tests/fixture_repo.py."""
'''

_CALC_V1 = '''\
"""Arithmetic over sequences of numbers."""


def total(values: list[float]) -> float:
    """Add ``values`` up."""
    return sum(values)


def mean(values: list[float]) -> float:
    """The arithmetic mean of ``values``."""
    return total(values) / len(values)
'''

_CALC_V2 = '''\
"""Arithmetic over sequences of numbers."""


def total(values: list[float]) -> float:
    """Add ``values`` up."""
    return sum(values)


def mean(values: list[float]) -> float:
    """The arithmetic mean of ``values``, or 0.0 when there are none."""
    if not values:
        return 0.0
    return total(values) / len(values)
'''

# Commit 4's source half: a docstring, and nothing a test could observe.
_CALC_V3 = _CALC_V2.replace(
    '"""Add ``values`` up."""',
    '"""Add ``values`` up. The total of no values at all is 0."""',
)

_TEST_CALC_V1 = """\
from widget.calc import mean, total


def test_total_adds_the_values() -> None:
    assert total([1.0, 2.0, 3.0]) == 6.0


def test_mean_divides_by_the_count() -> None:
    assert mean([2.0, 4.0]) == 3.0
"""

_TEST_CALC_V2 = (
    _TEST_CALC_V1
    + """

def test_mean_of_no_values_is_zero() -> None:
    assert mean([]) == 0.0
"""
)

_TEXT_V1 = '''\
"""Turning free text into url-safe slugs."""


def slug(text: str) -> str:
    """Lowercase ``text`` and join its words with hyphens."""
    return text.lower().replace(" ", "-")
'''

_TEXT_V2 = '''\
"""Turning free text into url-safe slugs."""


def slug(text: str) -> str:
    """Lowercase ``text`` and join its words with hyphens, however they were spaced."""
    return "-".join(text.lower().split())
'''

_TEST_TEXT_V1 = """\
from widget.text import slug


def test_slug_lowercases_and_hyphenates() -> None:
    assert slug("Hello World") == "hello-world"
"""

_TEST_TEXT_V2 = (
    _TEST_TEXT_V1
    + """

def test_slug_collapses_runs_of_whitespace() -> None:
    assert slug("  Hello   World  ") == "hello-world"
"""
)

# Commit 4's test half: already true at the parent, which is the whole point of the commit.
_TEST_REGRESSION = """\
from widget.calc import total


def test_total_of_no_values_is_zero() -> None:
    assert total([]) == 0
"""

_PARSE_V1 = '''\
"""Splitting a delimited record into its fields."""


def fields(record: str) -> list[str]:
    """The comma-separated fields of ``record``."""
    return record.split(",")
'''

_PARSE_V2 = '''\
"""Splitting a delimited record into its fields."""


def fields(record: str) -> list[str]:
    """The comma-separated fields of ``record``, without the padding around them."""
    return [field.strip() for field in record.split(",")]
'''

_TEST_PARSE = """\
from widget.parse import fields


def test_fields_are_stripped_of_padding() -> None:
    assert fields(" a , b ") == ["a", "b"]
"""

_PAYLOAD_V1 = '''\
"""Reading the packed sample payload the suite ships as a binary fixture."""

MAGIC = b"ASSAY"


def version(blob: bytes) -> int:
    """The format version: the byte straight after the magic."""
    return blob[len(MAGIC)]
'''

_PAYLOAD_V2 = '''\
"""Reading the packed sample payload the suite ships as a binary fixture."""

MAGIC = b"ASSAY"


def version(blob: bytes) -> int:
    """The format version: the byte straight after the magic."""
    return blob[len(MAGIC)]


def body(blob: bytes) -> bytes:
    """The payload itself: everything after the header, up to the terminator."""
    return blob[len(MAGIC) + 1 :].rstrip(b"\\x00")
'''

# NUL bytes are what make git call this file binary, and a binary file under ``tests/`` is
# what makes commit 7's test patch unappliable: ``GitHistory.diff`` does not pass ``--binary``,
# so git emits "Binary files ... differ" with an abbreviated index line, and ``git apply``
# refuses it. That is a real limitation of M1's patch splitting, and the fixture pins it
# rather than pretending it away.
_SAMPLE_BIN_V1 = b"ASSAY\x01hello\x00"
_SAMPLE_BIN_V2 = b"ASSAY\x02hello there\x00"

_TEST_PAYLOAD_V1 = """\
from pathlib import Path

from widget.payload import version

BLOB = Path(__file__).parent / "data" / "sample.bin"


def test_version_reads_the_header() -> None:
    assert version(BLOB.read_bytes()) == 1
"""

_TEST_PAYLOAD_V2 = """\
from pathlib import Path

from widget.payload import body, version

BLOB = Path(__file__).parent / "data" / "sample.bin"


def test_version_reads_the_header() -> None:
    assert version(BLOB.read_bytes()) == 2


def test_body_is_everything_after_the_header() -> None:
    assert body(BLOB.read_bytes()) == b"hello there"
"""

_JITTER = '''\
"""Spreading a count of items evenly across a range."""


def spread(count: int) -> list[int]:
    """The positions the items land on."""
    return list(range(count))
'''

# The flaky commit (SPEC §9 requires one). Flakiness driven by ``random`` would make *Assay's
# own* suite flaky, so the disagreement comes from a run counter on disk instead: odd runs
# fail, even runs pass, by construction rather than by chance.
#
# The counting starts at the first confirmation run, not at the red run: ``widget.jitter``
# does not exist at the parent commit, so the red run cannot import this module and never
# touches the counter. The confirmation runs are therefore ordinals 1 and 2 - one failing, one
# passing - whether the gate reuses one worktree for the candidate or takes a fresh one per
# phase. Both readings disagree, which is the verdict this commit is built to produce.
#
# That lands it on ``unstable_green`` and not on a neighbour. ``decide_gate`` checks
# ``run_timed_out`` (no), then ``already_green`` (no - the red run's collect error is a
# failure), then whether the confirmation runs agree, which is where this stops. ``still_red``
# is never reached, and that ordering is the rule this fixture exists to witness.
_TEST_JITTER_FLAKY = '''\
"""Deliberately flaky: consecutive runs of this test disagree with each other.

Assay runs a candidate's ground truth ``GREEN_CONFIRMATION_RUNS`` times and discards it when
the runs disagree (``unstable_green``). Nothing here is random - the disagreement is driven by
an on-disk run counter, so the fixture is flaky in exactly the way the gate is meant to catch
and in no other way.
"""

from pathlib import Path

from widget.jitter import spread

ORDINAL = Path(__file__).with_name(".jitter-run-ordinal")


def _next_ordinal() -> int:
    previous = int(ORDINAL.read_text()) if ORDINAL.exists() else 0
    ORDINAL.write_text(str(previous + 1))
    return previous + 1


def test_spread_is_stable() -> None:
    assert spread(3) == [0, 1, 2]
    # Even runs only. The first confirmation run fails, the second passes.
    assert _next_ordinal() % 2 == 0
'''

# Commit 10 retires the flakiness, so the fixture repository's own HEAD is deterministic and
# an end-to-end test may run the whole suite without inheriting the flake.
_TEST_JITTER_STABLE = """\
from widget.jitter import spread


def test_spread_is_stable() -> None:
    assert spread(3) == [0, 1, 2]
"""

_SLOW = '''\
"""An indexed lookup: the fast path this module exists to provide."""


def lookup(table: dict[str, int], key: str) -> int | None:
    """The value ``key`` maps to, in constant time."""
    return table.get(key)
'''

# The timeout commit. The red run - parent plus test changes only - has no ``widget.slow`` to
# import and falls back to a wait no wall-clock budget outlasts, so ``red.timed_out`` is set
# and ``run_timed_out`` is the first thing ``decide_gate`` checks. The confirmation runs
# import the real module and return at once, so a gate that runs all three anyway still pays
# the budget exactly once.
_TEST_SLOW = '''\
"""The red run of this file cannot finish, on purpose.

At the parent commit ``widget.slow`` does not exist, and the fallback below waits longer than
any budget a miner would set, so the run is killed and the candidate is rejected as
``run_timed_out``. Once the ground truth is applied the import succeeds and the test is
instant, so only the red run costs the timeout.
"""

import time

_LONGER_THAN_ANY_BUDGET_S = 3600

try:
    from widget.slow import lookup
except ImportError:  # the parent commit: the fast path has not been written yet

    def lookup(table: dict[str, int], key: str) -> int | None:
        time.sleep(_LONGER_THAN_ANY_BUDGET_S)
        return None


def test_lookup_finds_the_key() -> None:
    assert lookup({"a": 1}, "a") == 1
'''


def _text(content: str) -> bytes:
    """The exact bytes git will hash for a text file: UTF-8, LF, no BOM."""
    return content.encode("utf-8")


# Each entry is (label, subject, {repo-relative POSIX path: bytes}). A commit rewrites whole
# files rather than describing a diff: computing the diff is git's job, and a whole file is a
# thing a reviewer can read.
_HISTORY: Final[tuple[tuple[str, str, Mapping[str, bytes]], ...]] = (
    (
        "seed",
        "seed the widget package and its suite",
        {
            "pyproject.toml": _text(_PYPROJECT),
            "conftest.py": _text(_CONFTEST),
            "widget/__init__.py": _text(_INIT),
            "widget/calc.py": _text(_CALC_V1),
            "widget/text.py": _text(_TEXT_V1),
            "widget/payload.py": _text(_PAYLOAD_V1),
            "tests/test_calc.py": _text(_TEST_CALC_V1),
            "tests/test_text.py": _text(_TEST_TEXT_V1),
            "tests/test_payload.py": _text(_TEST_PAYLOAD_V1),
            "tests/data/sample.bin": _SAMPLE_BIN_V1,
        },
    ),
    (
        "mean_of_empty",
        "mean of no values is zero, not a division by zero",
        {
            "widget/calc.py": _text(_CALC_V2),
            "tests/test_calc.py": _text(_TEST_CALC_V2),
        },
    ),
    (
        "slug_collapses_spaces",
        "slug: collapse runs of whitespace instead of doubling hyphens",
        {
            "widget/text.py": _text(_TEXT_V2),
            "tests/test_text.py": _text(_TEST_TEXT_V2),
        },
    ),
    (
        "documented_total",
        "document what total() promises for an empty sequence",
        {
            "widget/calc.py": _text(_CALC_V3),
            "tests/test_regression.py": _text(_TEST_REGRESSION),
        },
    ),
    (
        "broken_field_parse",
        "parse: split a record into fields",
        {
            "widget/parse.py": _text(_PARSE_V1),
            "tests/test_parse.py": _text(_TEST_PARSE),
        },
    ),
    (
        "fixed_field_parse",
        "parse: strip the padding around each field",
        {"widget/parse.py": _text(_PARSE_V2)},
    ),
    (
        "payload_format_two",
        "payload: bump the sample fixture to format 2",
        {
            "widget/payload.py": _text(_PAYLOAD_V2),
            "tests/test_payload.py": _text(_TEST_PAYLOAD_V2),
            "tests/data/sample.bin": _SAMPLE_BIN_V2,
        },
    ),
    (
        "flaky_jitter",
        "jitter: spread a count of items across a range",
        {
            "widget/jitter.py": _text(_JITTER),
            "tests/test_jitter.py": _text(_TEST_JITTER_FLAKY),
        },
    ),
    (
        "slow_lookup",
        "slow: add the indexed lookup fast path",
        {
            "widget/slow.py": _text(_SLOW),
            "tests/test_slow.py": _text(_TEST_SLOW),
        },
    ),
    (
        "deterministic_jitter",
        "tests: stop the jitter test disagreeing with itself",
        {"tests/test_jitter.py": _text(_TEST_JITTER_STABLE)},
    ),
)

# The label whose commit is made on a branch, and then merged back. Cutting the branch one
# commit before the end is the cheapest way to put a real merge in the history.
_BRANCH_LABEL: Final = "deterministic_jitter"
_MERGE_LABEL: Final = "merge_tidy"


def build_fixture_repo(root: Path) -> Path:
    """Build the fixture repository under ``root`` and return the path to it.

    ``root`` is a caller-owned directory - pytest's ``tmp_path`` in practice. Nothing outside
    it is written, and nothing in the caller's environment is read: the ambient ``GIT_*``
    variables and the user's global and system config are dropped, because a fixture whose
    object names depend on ``~/.gitconfig`` is not a fixture.

    Raises:
        AssertionError: if the history built to object names other than the pinned ones. See
            :func:`_check_pinned` for why that check lives in the builder and not only in the
            test that also makes it.
    """
    repo = root / "widget-fixture"
    repo.mkdir(parents=True)
    # An explicit empty template, so a developer with `init.templateDir` pointing at real
    # hooks does not get a commit some hook rewrote.
    template = root / "empty-git-template"
    template.mkdir(parents=True, exist_ok=True)
    _git(
        repo,
        "init",
        "--quiet",
        f"--initial-branch={_TRUNK_NAME}",
        "--object-format=sha1",
        f"--template={template}",
        ".",
        ordinal=0,
    )

    built: dict[str, str] = {}
    for ordinal, (label, subject, files) in enumerate(_HISTORY):
        if label == _BRANCH_LABEL:
            _git(repo, "checkout", "--quiet", "-b", _BRANCH_NAME, ordinal=ordinal)
        for path, content in files.items():
            _write(repo, path, content)
        _git(repo, "add", "--all", ordinal=ordinal)
        _git(repo, "commit", "--quiet", "-m", subject, ordinal=ordinal)
        built[label] = _head(repo)

    merge_ordinal = len(_HISTORY)
    _git(repo, "checkout", "--quiet", _TRUNK_NAME, ordinal=merge_ordinal)
    _git(
        repo,
        "merge",
        "--quiet",
        "--no-ff",
        "-m",
        _MERGE_SUBJECT,
        _BRANCH_NAME,
        ordinal=merge_ordinal,
    )
    built[_MERGE_LABEL] = _head(repo)

    _check_pinned(built)
    return repo


def _check_pinned(built: Mapping[str, str]) -> None:
    """Refuse to hand back a repository whose object names are not the pinned ones.

    In the builder rather than only in the tripwire test, because every other caller - the
    end-to-end mining test above all - asserts an exact yield against *these* commits. A
    fixture that had quietly become a different repository would turn that assertion into a
    statement about nothing, and it would say so in whichever test noticed second.
    """
    expected = {commit.label: commit.sha for commit in FIXTURE_COMMITS}
    if built != expected:
        differing = sorted(label for label in expected if built.get(label) != expected[label])
        raise AssertionError(
            "the fixture repository built to object names other than the pinned ones "
            f"({', '.join(differing) or 'labels differ'}). git, the builder, or the "
            f"platform's line endings changed. Built: {dict(built)}"
        )


def _write(repo: Path, path: str, content: bytes) -> None:
    """Write one file's exact bytes, creating the directories above it."""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    # Bytes, never text: a newline translated on the way to disk is a different blob, and a
    # different blob is a different commit on one platform and not on the other.
    target.write_bytes(content)


def _git(repo: Path, *arguments: str, ordinal: int) -> str:
    """Run one git command against the fixture, with identity and both timestamps pinned.

    Driven through ``subprocess`` directly rather than through :func:`assay.host.run_command`,
    matching ``tests/host/test_git.py``: the fixture must not be built by the code it exists
    to test, or a bug the two shared would cancel itself out.
    """
    completed = subprocess.run(
        ("git", *_CONFIG_FLAGS, *arguments),
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=_environment(repo, ordinal),
        timeout=_GIT_TIMEOUT_S,
    )
    return completed.stdout


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD", ordinal=0).strip()


def _environment(repo: Path, ordinal: int) -> dict[str, str]:
    """The complete environment a git child sees, with nothing ambient left in it.

    Every ``GIT_*`` name is dropped before the pins go in, so a developer with ``GIT_DIR`` or
    ``GIT_AUTHOR_DATE`` exported does not build a different repository from CI's. The global
    config is pointed at a path that does not exist and the system config is switched off,
    which is git's own supported way of saying "ignore whoever is running this".
    """
    when = f"{_FIRST_COMMIT_EPOCH_S + ordinal * _COMMIT_INTERVAL_S} +0000"
    inherited = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    return {
        **inherited,
        "GIT_CONFIG_GLOBAL": str(repo.parent / "no-such-gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": _AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": _AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": _AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": _AUTHOR_EMAIL,
        "GIT_AUTHOR_DATE": when,
        "GIT_COMMITTER_DATE": when,
    }


# ----------------------------------------------------------------------------------------
# The expected yield: exactly what the miner must produce from the history above
# ----------------------------------------------------------------------------------------

FIXTURE_COMMITS: Final[tuple[FixtureCommit, ...]] = (
    FixtureCommit(
        label="seed",
        subject="seed the widget package and its suite",
        sha="89c5b2060bf6736daa8d0098a8e1f9097096d99f",
        walked=False,
        rejection=None,
    ),
    FixtureCommit(
        label="mean_of_empty",
        subject="mean of no values is zero, not a division by zero",
        sha="522ebe0b013a5500f18809be4a09d3950a347d4b",
        walked=True,
        rejection=None,
    ),
    FixtureCommit(
        label="slug_collapses_spaces",
        subject="slug: collapse runs of whitespace instead of doubling hyphens",
        sha="b209fc7be9b5bf13531cb6ecda20e76d333e8425",
        walked=True,
        rejection=None,
    ),
    FixtureCommit(
        label="documented_total",
        subject="document what total() promises for an empty sequence",
        sha="1ff998652cb572dfc2b802d72417283cf27abaf7",
        walked=True,
        rejection=GateRejection.ALREADY_GREEN,
    ),
    FixtureCommit(
        label="broken_field_parse",
        subject="parse: split a record into fields",
        sha="7095e24d73b8beb652acb6632ed8cfefead8d1b2",
        walked=True,
        rejection=GateRejection.STILL_RED,
    ),
    FixtureCommit(
        label="fixed_field_parse",
        subject="parse: strip the padding around each field",
        sha="2af47e0d07d8e99fcd93f1d20ce62fbe45636be0",
        walked=True,
        rejection=GateRejection.NO_TEST_CHANGES,
    ),
    FixtureCommit(
        label="payload_format_two",
        subject="payload: bump the sample fixture to format 2",
        sha="ef9d5e090661c4a6e6ca96915bd4f3edcef4bdd5",
        walked=True,
        rejection=GateRejection.PATCH_DID_NOT_APPLY,
    ),
    FixtureCommit(
        label="flaky_jitter",
        subject="jitter: spread a count of items across a range",
        sha="af31dc81cb120e4f8d292944153768d71d6749b2",
        walked=True,
        rejection=GateRejection.UNSTABLE_GREEN,
    ),
    FixtureCommit(
        label="slow_lookup",
        subject="slow: add the indexed lookup fast path",
        sha="4d2dd6b6133cb5d0ea83957d5c2b163899ea2cd6",
        walked=True,
        rejection=GateRejection.RUN_TIMED_OUT,
    ),
    FixtureCommit(
        label="deterministic_jitter",
        subject="tests: stop the jitter test disagreeing with itself",
        sha="10daef0c2c303a1103bac366dd2524b5581f6dc9",
        walked=True,
        rejection=GateRejection.NO_SOURCE_CHANGES,
    ),
    FixtureCommit(
        label="merge_tidy",
        subject=_MERGE_SUBJECT,
        sha="f4e2610fed21c5a1c9026f133932d22c76852dfc",
        walked=False,
        rejection=GateRejection.MERGE_COMMIT,
    ),
)

# The three reasons decided on the diff alone, before any test is run. A commit rejected for
# one of these never reaches `decide_gate`, so it is examined but is not a candidate.
_DECIDED_BEFORE_THE_GATE: Final = frozenset(
    {
        GateRejection.MERGE_COMMIT,
        GateRejection.NO_TEST_CHANGES,
        GateRejection.NO_SOURCE_CHANGES,
        GateRejection.PATCH_DID_NOT_APPLY,
    }
)

_WALKED: Final = tuple(commit for commit in FIXTURE_COMMITS if commit.walked)

EXPECTED_YIELD: Final = MiningYield(
    commits_examined=len(_WALKED),
    candidates=sum(1 for commit in _WALKED if commit.rejection not in _DECIDED_BEFORE_THE_GATE),
    accepted=sum(1 for commit in _WALKED if commit.rejection is None),
    rejected=MappingProxyType(
        {
            reason: sum(1 for commit in _WALKED if commit.rejection is reason)
            for reason in GateRejection
        }
    ),
)
"""What ``assay mine`` must report for this repository: 9 examined, 6 candidates, 2 accepted.

Derived from :data:`FIXTURE_COMMITS` rather than typed out, so the table and the number cannot
disagree; ``tests/mine/test_fixture_repo.py`` pins the derivation's result all the same, since
a table edited without meaning to move the yield is the mistake CLAUDE.md forbids.

The one caveat. ``GitHistory.commits`` asks git for ``--no-merges``, so commit 11 is never
yielded and ``rejected[MERGE_COMMIT]`` is **0** here: under M1's walk that reason is
unreachable, and the merge sits in the history as a witness for the day something walks with
merges, not as a count. Every other reason has a walked commit that produces it.
"""
