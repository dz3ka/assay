"""Shared scaffolding for the sandbox tests: a real worktree, and one question about an image.

These tests talk to a real Docker daemon. There is no marker guarding them and no skip path: a
sandbox test that quietly does not run is a network-off proof that quietly does not happen, and
that is the exact failure this project exists to catch. If the daemon is not up, the suite is
red, and that is the intended report.

The checkout under test is the SPEC §9 fixture repository, taken through
:class:`assay.host.GitHistory` rather than copied into place, because a git worktree is what
production hands :func:`assay.sandbox.build_task_image` - a tree whose ``.git`` is a *file*
pointing back at the clone, which is one of the two things the build's dockerignore excludes.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

from assay.host import GitHistory, minimal_env, run_command
from assay.sandbox import VENV_PYTHON, ContainerLimits, build_task_image
from tests.fixture_repo import FIXTURE_COMMITS, build_fixture_repo

# Long enough for a cold build - a base-image pull plus an editable install of the project and
# pytest - and short enough that a wedged daemon is still a failure rather than a hang.
BUILD_BUDGET_S = 600

# Generous enough that nothing here is killed by accident, because the tests that are *about*
# being killed pass their own far smaller ceiling. Production numbers do not live in this repo
# yet: `assay.sandbox.ContainerLimits` deliberately has no defaults, so until `assay run` exists
# the only call sites that start a container are these tests, and this is theirs.
TRIAL_LIMITS = ContainerLimits(memory_mb=512, cpus="1", pids=256)

# How long a killed container is given to leave `docker ps`, and how often that is asked.
# `docker kill` returns once the daemon has signalled the process, not once the container has
# been reaped, so "it is gone" is a question with an answer that arrives shortly afterwards.
_SETTLE_INTERVAL_S = 0.2

# The fixture's merge commit: its tree is one of the green, fast, deterministic trees the fixture
# module maintains on purpose, so an image built from it holds a suite that can actually be run.
# Named rather than "the tip": commits appended after the merge must not silently change what
# these tests build an image from.
_HEAD_LABEL = "merge_tidy"


@contextmanager
def fixture_worktree(root: Path) -> Iterator[tuple[Path, str]]:
    """Build the fixture repository under ``root`` and check its HEAD out, yielding both.

    Args:
        root: A caller-owned directory, pytest's ``tmp_path`` in practice. The clone and the
            worktree both live under it and neither outlives the block.

    Yields:
        The worktree path and the commit sha it holds - the two arguments a task image is built
        from.
    """
    repo = build_fixture_repo(root / "repo")
    commit = next(entry.sha for entry in FIXTURE_COMMITS if entry.label == _HEAD_LABEL)
    history = GitHistory(repo, worktree_root=root / "worktrees")
    with history.worktree(commit) as checkout:
        yield checkout, commit


def image_created_at(tag: str) -> str:
    """The creation timestamp docker records for ``tag``.

    The one honest way to ask "was that second build a cache hit?". A fully cached rebuild of
    the same tag still exports a fresh manifest list, so the image *ID* changes even when
    nothing was rebuilt (measured; see :mod:`assay.sandbox.image`). The timestamp comes out of
    the image config, which is part of what gets cached, so it moves if and only if a layer was
    actually built.
    """
    found = run_command(
        ("docker", "image", "inspect", "--format", "{{.Created}}", tag),
        cwd=Path.cwd(),
        timeout_s=60,
        env=minimal_env(),
        check=True,
    )
    return found.stdout.strip()


@contextmanager
def fixture_image(root: Path) -> Iterator[tuple[Path, str]]:
    """The fixture worktree, with a task image already built from it, ready to run.

    The two arguments every trial needs and the one setup step none of the run-policy tests are
    about. Building is cheap on the second call and afterwards - the tag is a content address
    over a fixture whose commits are pinned, so the daemon already holds the layers from the
    last run of ``tests/sandbox`` - but it is not free, so callers hold this open for a module
    rather than per test.

    Yields:
        The workspace to mount and the tag to run.
    """
    with fixture_worktree(root) as (checkout, commit):
        yield (
            checkout,
            build_task_image(
                context=checkout,
                base_commit=commit,
                exclude_newer=None,
                timeout_s=BUILD_BUDGET_S,
            ),
        )


def installed_version(tag: str, distribution: str) -> tuple[int, ...]:
    """The version of ``distribution`` inside ``tag``'s virtual environment, as a tuple.

    Asked of the image rather than of a build log, because the log is a rendering and the
    installed metadata is the fact. A tuple rather than a string so that a caller can compare
    it: ``"10.0"`` sorts before ``"9.0"`` as text and the era test would then pass for the
    wrong reason.

    Only the numeric release segment is returned - a pre-release or local suffix is not
    something these tests are about, and parsing one here would need a packaging dependency
    inside a helper whose whole job is one question.
    """
    found = run_command(
        (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            tag,
            VENV_PYTHON,
            "-c",
            f"from importlib.metadata import version; print(version({distribution!r}))",
        ),
        cwd=Path.cwd(),
        timeout_s=120,
        env=minimal_env(),
        check=True,
    )
    release = found.stdout.strip().split("+")[0].split("-")[0]
    return tuple(int(part) for part in release.split(".") if part.isdigit())


def imports_cleanly(tag: str, module: str) -> bool:
    """Whether ``module`` imports inside ``tag``'s virtual environment.

    The question an extras phase is judged on, and asked of the image for the reason
    :func:`installed_version` gives: a build log is a rendering, the installed environment is
    the fact. ``check=False`` because a module that is absent is an *answer* here rather than a
    failure - the negative half of the assertion is the half that matters.
    """
    found = run_command(
        (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            tag,
            VENV_PYTHON,
            "-c",
            f"import {module}",
        ),
        cwd=Path.cwd(),
        timeout_s=120,
        env=minimal_env(),
        check=False,
    )
    return found.exit_code == 0


def running_containers_from(tag: str, *, settle_s: float) -> tuple[str, ...]:
    """The containers still running from ``tag``, once they have had ``settle_s`` to stop.

    Polls rather than sleeps a fixed span: the answer is wanted as soon as it is empty, and a
    test that waits the whole budget every time to prove a container went away would charge the
    suite for a race that almost never happens. It returns what is *left* rather than a bool so
    that a failure names the containers it found.

    Only sound while the sandbox tests run one container at a time, which pytest does here: a
    parallel sibling running from the same image would answer this question for it.
    """
    deadline = monotonic() + settle_s
    while True:
        found = run_command(
            ("docker", "ps", "--quiet", "--filter", f"ancestor={tag}"),
            cwd=Path.cwd(),
            timeout_s=60,
            env=minimal_env(),
            check=True,
        )
        running = tuple(found.stdout.split())
        if not running or monotonic() >= deadline:
            return running
        sleep(_SETTLE_INTERVAL_S)
