"""What Assay is entitled to assume about the image a trial will run in.

Three properties, and they are the three the rest of M2 leans on. The tag is a *content
address*, so an image built from a different recipe cannot be mistaken for one built from this
recipe - that is what stops a trial being scored against an environment the red->green gate
never saw. Building twice costs one build, because a suite has many tasks over few base commits
and a run that reinstalled a dependency tree per trial would price the harness out of use. And
the image installs the repository's *declared* test extras and nothing else, so a suite that
cannot import its own conftest is a fact about the repository rather than about Assay.

These tests really build images with a real daemon, for the reason ``tests/host/test_venv.py``
gives about really running ``uv``: the assumption being retired is docker's behaviour, and a
mock of it retires nothing. There is no skip path (see ``tests/sandbox/support.py``).

The images they build are deliberately **left behind**. They are content-addressed, so they are
reused rather than re-created on the next run, which is the same property production depends on;
removing them at teardown would make every run pay for a cold install and would delete the very
thing the second test is about.
"""

import os
import subprocess
from pathlib import Path

import pytest

from assay.core import AssayError
from assay.host import CheckoutState, CommandFailedError, GitError
from assay.sandbox import (
    TEST_EXTRA_NAMES,
    SandboxError,
    build_task_image,
    image_tag,
    read_declared_extras,
    read_installed_closure,
    render_base_dockerfile,
    render_extras_dockerfile,
)
from assay.sandbox.image import _context_divergence, _select_extras
from tests.sandbox.support import (
    BUILD_BUDGET_S,
    fixture_worktree,
    image_created_at,
    imports_cleanly,
    installed_version,
)

_RECIPE = "FROM scratch\n"
_OTHER_RECIPE = "FROM scratch\nENV CHANGED=1\n"
_COMMIT = "0123456789abcdef0123456789abcdef01234567"
_OTHER_COMMIT = "89abcdef0123456789abcdef0123456789abcdef"

# The recipe every image built before ADR-0021 was addressed by, spelled out here rather than
# imported: an oracle that reads its answer out of the module under test cannot notice the
# module drifting. `exclude_newer=None` has to keep rendering exactly this, or every tag in the
# daemon's cache changes meaning and the suite pays for a cold rebuild of images that are
# byte-for-byte the ones it already holds.
_RECIPE_WITHOUT_A_CUTOFF = (
    "FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
    "@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58\n"
    "ENV UV_LINK_MODE=copy\n"
    "WORKDIR /workspace\n"
    "COPY . /workspace\n"
    "RUN uv venv /opt/venv \\\n"
    " && uv pip install --python /opt/venv/bin/python -e /workspace pytest\n"
)

# The instant `tests/fixture_repo.py` dates its root commit at, in the one spelling a cutoff is
# allowed to have (ADR-0022): UTC, second precision, `Z`. A bare `2023-11-14` is refused now,
# because uv resolves a bare date in the *container's* time zone and a content address whose
# meaning depends on `TZ` is the defect the canonical spelling exists to close. Midnight UTC is
# still November 2023, when pytest was at 7.4.3 - which is what makes the era visible in a build.
_FIXTURE_ERA = "2023-11-14T00:00:00Z"

# How long one question put to a built image may take. Seconds of work, so a budget this size
# only ever expires on a daemon that has stopped answering.
_PROBE_BUDGET_S = 120

# The pinned base image, spelled a second time here for the same reason the recipe above is: the
# phase-1 address has to be computable in the test without asking the module under test what its
# base image is. `test_a_project_that_declares_no_test_extra...` asserts the two spellings agree,
# which is the drift licence ADR-0012 sets out.
_PINNED_BASE_IMAGE = (
    "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
    "@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
)

# A tag the renderer is handed rather than one it computes: these tests are about the text of the
# second phase, and a real address would only make the expected string harder to read.
_BASE_TAG = "assay-task:cafe"

# Two real distributions, chosen by measurement rather than by name. The base image's closure is
# `iniconfig`, `packaging`, `pluggy`, `pygments` and `pytest` (measured 2026-09-01, `uv pip
# freeze` inside a built image), so neither of these can arrive as a dependency of pytest. Naming
# one that pytest already pulls in - `iniconfig` is the obvious trap - would make the positive
# half of the extras assertion pass with the whole second phase deleted.
# The line `uv pip freeze` prints for the editable install the first phase performs, spelled
# here rather than composed from `WORKSPACE_DIR`: this is uv's rendering of an install, not a
# path Assay chose, and an oracle that builds it out of the module's own constant would follow
# uv's format silently if it ever changed. Measured 2026-09-01, uv 0.9.30.
_EDITABLE_WORKSPACE_LINE = "-e file:///workspace"

# What November 2023's index served for pytest. A fact about that month, so it can never move -
# unlike the version today's index serves, which is why only this half is pinned to a string.
_ERA_PYTEST = "pytest==7.4.3"

_TEST_EXTRA_DEPENDENCY = "sniffio"
_DOCS_EXTRA_DEPENDENCY = "wcwidth"

# Deliberately declares one allowlisted extra and one that is not, because the claim under test
# has two halves and the second is what stops "install every extra" from passing it.
_DECLARES_EXTRAS_PYPROJECT = f"""\
[project]
name = "widget"
version = "0.1.0"
requires-python = ">=3.12"

[project.optional-dependencies]
test = ["{_TEST_EXTRA_DEPENDENCY}"]
docs = ["{_DOCS_EXTRA_DEPENDENCY}"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["widget"]
"""

_EXTRAS_RECIPE = (
    f"FROM {_BASE_TAG}\n"
    "RUN uv pip install --python /opt/venv/bin/python -e '/workspace[test,dev]'\n"
)

_EXTRAS_RECIPE_UNDER_A_CUTOFF = (
    f"FROM {_BASE_TAG}\n"
    "RUN uv pip install --python /opt/venv/bin/python"
    f" --exclude-newer {_FIXTURE_ERA} -e '/workspace[test]'\n"
)


# Everything that decides the object name of the commit below, forced onto every invocation:
# identity, no signature, and the line endings and file mode that make a Windows dev host and a
# Linux CI hash the same blob. `tests/fixture_repo.py` pins the same set for the same reason.
_PINNED_GIT = (
    "-c",
    "user.name=Assay Test",
    "-c",
    "user.email=assay@example.invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
    "-c",
    "core.fileMode=false",
)

# A fixed instant for both timestamps, with every ambient `GIT_*` name dropped first: a
# developer with `GIT_AUTHOR_DATE` or `GIT_DIR` exported must not build a different commit -
# and so a different image address - from the one CI builds.
_GIT_ENVIRONMENT = {
    **{name: value for name, value in os.environ.items() if not name.startswith("GIT_")},
    "GIT_AUTHOR_DATE": "1700000000 +0000",
    "GIT_COMMITTER_DATE": "1700000000 +0000",
}

# One commit on a three-file tree. A ceiling on a hang, not a budget.
_GIT_TIMEOUT_S = 60


def _write_project_declaring_extras(root: Path) -> tuple[Path, str]:
    """A one-commit repository holding an installable project that declares two extras.

    Written here rather than mined from the fixture repository, which declares no optional
    dependencies at all and must go on declaring none: every sha in ``tests/fixture_repo.py`` is
    pinned, and moving them to prove something about packaging would cost the yield assertion
    those shas exist to hold still.

    A checkout rather than a plain directory, and it hands its commit back with it.
    :func:`assay.sandbox.build_task_image` now proves the context is the commit its tag claims
    (ADR-0027), so a build context is a git checkout here for the same reason it is one in
    production: a directory git has never heard of has no head for an address to name.

    Everything about the commit is pinned the way ``tests/fixture_repo.py`` pins its history -
    identity, both timestamps, line endings, file mode, and no ambient ``GIT_*`` left in the
    environment. Not tidiness: the object name goes into a content address, so a sha that moved
    with the host's clock would charge every run for a cold build of an image already cached.
    """
    project = root / "declares-extras"
    (project / "widget").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        _DECLARES_EXTRAS_PYPROJECT, encoding="utf-8", newline="\n"
    )
    (project / "widget" / "__init__.py").write_text(
        '"""A project that exists to declare extras."""\n', encoding="utf-8", newline="\n"
    )
    _git(project, "init", "--quiet", "--initial-branch=main")
    _git(project, "add", "--all")
    _git(project, "commit", "--quiet", "-m", "the project that declares extras")
    return project, _git(project, "rev-parse", "HEAD").strip()


def _git(repo: Path, *arguments: str) -> str:
    """Drive git directly, so a fixture is not built by the seam these tests build over.

    ``tests/host/test_git.py``'s idiom, minus the parts that module needs for a walk: this
    repository has one commit, so nothing here depends on ordering, and what has to hold still
    is the object name.
    """
    completed = subprocess.run(
        ("git", *_PINNED_GIT, *arguments),
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=_GIT_ENVIRONMENT,
        timeout=_GIT_TIMEOUT_S,
    )
    return completed.stdout


def test_the_tag_is_a_content_address_over_the_recipe_as_well_as_the_commit() -> None:
    address = image_tag(base_image="python:3.12", dockerfile=_RECIPE, base_commit=_COMMIT)
    again = image_tag(base_image="python:3.12", dockerfile=_RECIPE, base_commit=_COMMIT)
    moved_base = image_tag(base_image="python:3.13", dockerfile=_RECIPE, base_commit=_COMMIT)
    new_recipe = image_tag(base_image="python:3.12", dockerfile=_OTHER_RECIPE, base_commit=_COMMIT)
    other_commit = image_tag(
        base_image="python:3.12", dockerfile=_RECIPE, base_commit=_OTHER_COMMIT
    )

    assert again == address
    assert moved_base != address, "a moved base image must not keep the old address"
    assert new_recipe != address, "a changed recipe must not keep the old address"
    assert other_commit != address, "a different commit must not keep the old address"


def test_the_tag_is_something_docker_will_accept_as_a_tag() -> None:
    repository, _, reference = image_tag(
        base_image="python:3.12", dockerfile=_RECIPE, base_commit=_COMMIT
    ).partition(":")

    assert repository == "assay-task"
    # The digest half of `content_hash`, with its `sha256:` prefix removed: a docker tag may not
    # contain a colon, so the prefix cannot simply be carried through.
    assert len(reference) == 64
    assert set(reference) <= set("0123456789abcdef")


def test_building_the_same_worktree_twice_costs_one_build_and_one_tag(tmp_path: Path) -> None:
    with fixture_worktree(tmp_path) as (checkout, commit):
        first = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )
        built_at = image_created_at(first)

        second = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

    assert second == first
    # Unchanged means every layer came from the cache. The image ID is *not* the thing to assert
    # on: a cached rebuild re-exports the manifest list and so reports a new one.
    assert image_created_at(second) == built_at


def test_the_build_leaves_no_trace_in_the_worktree_it_is_about_to_score(tmp_path: Path) -> None:
    with fixture_worktree(tmp_path) as (checkout, commit):
        before = sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*"))

        build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

        # The Dockerfile and its dockerignore live outside the context on purpose. This tree is
        # what the trial's `git diff` is measured against, so a file Assay added to it would be
        # scored as the tool's work.
        assert (
            sorted(path.relative_to(checkout).as_posix() for path in checkout.rglob("*")) == before
        )


def test_no_cutoff_renders_the_recipe_every_existing_tag_was_addressed_by() -> None:
    assert render_base_dockerfile(exclude_newer=None) == _RECIPE_WITHOUT_A_CUTOFF


def test_a_cutoff_enters_the_content_address_rather_than_sitting_beside_it() -> None:
    # Not asserted on the tag directly, because `image_tag` is already keyed on the recipe: the
    # point is that the cutoff reaches the recipe at all, so two eras cannot share an address.
    # A pin that did not fall out this way would be the failure this project exists to catch.
    era = render_base_dockerfile(exclude_newer=_FIXTURE_ERA)
    later = render_base_dockerfile(exclude_newer="2024-06-01T00:00:00Z")

    assert era != later
    assert image_tag(base_image="python:3.12", dockerfile=era, base_commit=_COMMIT) != image_tag(
        base_image="python:3.12", dockerfile=later, base_commit=_COMMIT
    )


@pytest.mark.parametrize(
    "hostile",
    [
        "2023-11-14 && curl http://example.invalid",
        "2023-11-14; rm -rf /",
        "$(date)",
        "--offline",
        "yesterday",
        "",
        "2023-11-14T22:13:20+00:00",
        "2023-11-14",
    ],
    ids=[
        "shell-and",
        "shell-semicolon",
        "substitution",
        "option",
        "human-date",
        "empty",
        "second-spelling",
        "bare-date",
    ],
)
def test_a_cutoff_that_is_not_the_canonical_instant_is_refused_before_it_reaches_the_recipe(
    hostile: str,
) -> None:
    # The cutoff is interpolated into a `RUN` line, which is a shell line, so anything that is
    # not an instant is refused where it arrives rather than where it detonates.
    #
    # The last two are not injections; they are the regression ADR-0022 is about, and each was
    # measured rather than imagined. `+00:00` is what git before 2.55 prints for the same
    # instant `Z` names, so accepting both would let two hosts compute two tags for one task.
    # A bare `2023-11-14` is resolved by uv in the container's configured time zone, so its
    # meaning is not fixed by the address that carries it. Neither may be constructible at the
    # boundary that computes the address, however harmless each looks on its own.
    with pytest.raises(SandboxError, match="RFC3339"):
        render_base_dockerfile(exclude_newer=hostile)


def test_a_cutoff_resolves_the_commits_era_rather_than_todays_index(tmp_path: Path) -> None:
    """The whole point of ADR-0021, asserted against a real index rather than a mock of one.

    The fixture's tree is dated November 2023, when pytest was 7.4.3. Built without a cutoff it
    gets whatever the index serves today; built with one it gets what the commit could have had.
    A resolution that ignored the cutoff would show up here as two identical versions.
    """
    with fixture_worktree(tmp_path) as (checkout, commit):
        era = build_task_image(
            context=checkout,
            base_commit=commit,
            exclude_newer=_FIXTURE_ERA,
            timeout_s=BUILD_BUDGET_S,
        )
        today = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

    assert era != today, "two cutoffs must not share one content address"
    # Measured 2026-09-01: 7.4.3 under the cutoff, 9.1.1 without it. Asserted as the major
    # version boundary either side, because the first is a fact about November 2023 and can
    # never move, while the second is a fact about the index on the day the suite runs.
    assert installed_version(era, "pytest") < (8, 0)
    assert installed_version(today, "pytest") >= (9, 0)


@pytest.mark.parametrize(
    ("declared", "selected"),
    [
        ((), ()),
        (("test",), ("test",)),
        (("dev", "test"), ("test", "dev")),
        (("Test", "TESTS", "tests"), ("test", "tests")),
        (("docs", "lint", "test"), ("test",)),
        (("docs", "lint"), ()),
        (("dev", "testing", "tests", "test"), TEST_EXTRA_NAMES),
    ],
    ids=[
        "declares-nothing",
        "one-allowlisted",
        "declaration-order-does-not-decide",
        "case-folded-and-deduplicated",
        "unknown-dropped",
        "only-unknown",
        "all-four",
    ],
)
def test_only_allowlisted_extras_are_selected_and_always_in_the_allowlists_order(
    declared: tuple[str, ...], selected: tuple[str, ...]
) -> None:
    # The order is the allowlist's, never the metadata's, and that is measured rather than
    # tidy: a project whose `pyproject.toml` declares `test` before `docs` has them the other
    # way round in the installed `METADATA` (measured 2026-09-01). The selection reaches a
    # content address, so an order decided by a packaging backend would let one project's one
    # commit carry two tags depending on which backend built it.
    assert _select_extras(declared) == selected


def test_the_second_phase_installs_the_selected_extras_over_the_first_phases_tag() -> None:
    # Byte-exact, for the reason `_RECIPE_WITHOUT_A_CUTOFF` is: this text is hashed into the
    # widened tag, so "close enough" is a second address for one environment.
    assert (
        render_extras_dockerfile(base_tag=_BASE_TAG, extras=("test", "dev"), exclude_newer=None)
        == _EXTRAS_RECIPE
    )


def test_the_second_phase_resolves_under_the_same_cutoff_as_the_first() -> None:
    # An extras install resolved against today's index would reintroduce ADR-0021's defect
    # halfway: the runtime set pinned to the commit's era and the test set dated today.
    assert (
        render_extras_dockerfile(base_tag=_BASE_TAG, extras=("test",), exclude_newer=_FIXTURE_ERA)
        == _EXTRAS_RECIPE_UNDER_A_CUTOFF
    )


@pytest.mark.parametrize(
    "extras",
    [
        ("docs",),
        ("test", "docs"),
        ("test; rm -rf /",),
        ("--offline",),
        ("",),
        ("TEST",),
    ],
    ids=[
        "unknown",
        "one-unknown-among-allowlisted",
        "shell-semicolon",
        "option",
        "empty-name",
        "unselected-spelling",
    ],
)
def test_an_extra_outside_the_allowlist_is_refused_before_it_reaches_the_recipe(
    extras: tuple[str, ...],
) -> None:
    # The clause is interpolated into a `RUN` line and into a content address, so the same
    # posture `_checked_cutoff` takes applies: what `_select_extras` did not choose cannot be
    # rendered, however harmless it looks. `TEST` is here because case-folding is the selector's
    # job and doing it twice would put a second spelling into the address.
    with pytest.raises(SandboxError, match="allowlisted"):
        render_extras_dockerfile(base_tag=_BASE_TAG, extras=extras, exclude_newer=None)


def test_a_refusal_from_this_package_is_catchable_as_an_assay_error() -> None:
    """The base class is the point, not the name: a walk catches ``AssayError`` to *record* it.

    ``assay.host.git`` and ``assay.host.venv`` both turn a failure into a per-commit outcome by
    catching that base, and the miner counts what they return. A refusal that escaped this
    package as a bare ``ValueError`` would pass straight through those handlers, so one
    malformed value would cost a whole walk its measurement instead of costing it one row.
    """
    with pytest.raises(AssayError, match="RFC3339"):
        render_base_dockerfile(exclude_newer="2023-11-14")


def test_a_second_phase_with_nothing_to_install_is_refused_rather_than_rendered_empty() -> None:
    # `-e '/workspace[]'` installs exactly what the first phase already installed, under a
    # different address. Two addresses for one environment is the failure the content address
    # exists to prevent, so the empty clause is refused rather than allowed to render.
    with pytest.raises(SandboxError, match="no extras"):
        render_extras_dockerfile(base_tag=_BASE_TAG, extras=(), exclude_newer=None)


def test_the_second_phase_refuses_a_cutoff_that_is_not_the_canonical_instant() -> None:
    with pytest.raises(SandboxError, match="RFC3339"):
        render_extras_dockerfile(base_tag=_BASE_TAG, extras=("test",), exclude_newer="2023-11-14")


def test_a_project_declaring_a_test_extra_gets_that_extra_and_no_other(tmp_path: Path) -> None:
    """The claim ADR-0023 makes, asserted in both directions against a real build.

    The positive half alone would pass for an image that installed *every* declared extra, which
    is the option ADR-0018 rejected and this decision does not reopen. So the `docs` extra is
    declared too, and its dependency has to be absent.
    """
    project, commit = _write_project_declaring_extras(tmp_path)

    widened = build_task_image(
        context=project, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
    )

    # Sorted, not asserted in order: what the image reports is the packaging backend's order,
    # and fixing an order is `_select_extras`'s job rather than this function's.
    assert sorted(read_declared_extras(widened, timeout_s=_PROBE_BUDGET_S)) == ["docs", "test"]
    assert widened != image_tag(
        base_image=_PINNED_BASE_IMAGE, dockerfile=_RECIPE_WITHOUT_A_CUTOFF, base_commit=commit
    ), "an image with extras installed must not carry the address of the one without them"
    assert imports_cleanly(widened, _TEST_EXTRA_DEPENDENCY)
    assert not imports_cleanly(widened, _DOCS_EXTRA_DEPENDENCY), (
        "the second phase installs the allowlisted extras, not every extra declared"
    )


def test_a_project_declaring_no_test_extra_keeps_the_tag_the_first_phase_built(
    tmp_path: Path,
) -> None:
    # The fixture repository declares no optional dependencies, so nothing is widened and the
    # address is the one every image in the daemon's cache already carries. A second phase that
    # ran anyway would re-tag every task in the suite and charge the next run for a cold build
    # of images it already holds.
    with fixture_worktree(tmp_path) as (checkout, commit):
        assert _RECIPE_WITHOUT_A_CUTOFF.startswith(f"FROM {_PINNED_BASE_IMAGE}\n")

        built = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

        assert read_declared_extras(built, timeout_s=_PROBE_BUDGET_S) == ()
        assert built == image_tag(
            base_image=_PINNED_BASE_IMAGE,
            dockerfile=_RECIPE_WITHOUT_A_CUTOFF,
            base_commit=commit,
        )


def test_the_installed_closure_is_the_images_own_account_of_what_arrived(tmp_path: Path) -> None:
    """What the image holds, read off the image, because a build log is only what was asked for.

    The editable install is the load-bearing line: it is the one entry that proves the closure
    describes *this* project's environment rather than some venv uv happened to find.
    """
    with fixture_worktree(tmp_path) as (checkout, commit):
        built = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

    closure = read_installed_closure(built, timeout_s=_PROBE_BUDGET_S)

    assert _EDITABLE_WORKSPACE_LINE in closure
    assert any(line.startswith("pytest==") for line in closure)
    # No blank and no padded lines: a closure is compared line for line against a rebuild's, so
    # a stray carriage return off a Windows pipe would report drift that did not happen.
    assert all(line == line.strip() and line for line in closure)


def test_two_eras_of_one_commit_do_not_share_one_closure(tmp_path: Path) -> None:
    """The audit ADR-0021's stated limit needs, asserted rather than assumed.

    `--exclude-newer` cannot restore a release PyPI has stopped serving, so a rebuild months
    from now may fail. What it may *not* do is resolve to something else and pass quietly, and
    that claim is only checkable if the closure a run recorded is comparable with a rebuild's.
    Two eras of one commit is the cheapest case where the two must differ.
    """
    with fixture_worktree(tmp_path) as (checkout, commit):
        era = build_task_image(
            context=checkout,
            base_commit=commit,
            exclude_newer=_FIXTURE_ERA,
            timeout_s=BUILD_BUDGET_S,
        )
        today = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

    era_closure = read_installed_closure(era, timeout_s=_PROBE_BUDGET_S)
    todays_closure = read_installed_closure(today, timeout_s=_PROBE_BUDGET_S)

    assert _ERA_PYTEST in era_closure
    assert _ERA_PYTEST not in todays_closure
    # Both are the same commit's editable install, so the difference is the resolution and
    # nothing else - which is what makes a line-for-line comparison mean anything.
    assert _EDITABLE_WORKSPACE_LINE in era_closure
    assert _EDITABLE_WORKSPACE_LINE in todays_closure


def test_an_image_the_daemon_does_not_hold_is_a_refusal_not_an_empty_closure() -> None:
    # An empty tuple reads as "nothing is installed", which is a sentence about an environment
    # rather than about a missing image. A report that quoted one for the other would be this
    # project's own subject matter failing inside it, so the failure is raised, not returned.
    with pytest.raises(CommandFailedError):
        read_installed_closure("assay-task:0000000000000000", timeout_s=_PROBE_BUDGET_S)


def test_a_context_patched_after_the_checkout_is_refused_before_anything_is_built(
    tmp_path: Path,
) -> None:
    """The whole point: a tag claims a commit, so a context that is not that commit is refused.

    A caller who patches the worktree and then builds gets an image whose *address* names the
    base commit and whose *content* is the patch. Nothing downstream can notice - the tag is
    what every later step reads - so the trial would be scored against an environment nobody
    chose, which is this project's own subject matter failing inside it.
    """
    with fixture_worktree(tmp_path) as (checkout, commit):
        (checkout / "widget" / "calc.py").write_text(
            "def total(values):\n    return 0\n", encoding="utf-8", newline="\n"
        )

        with pytest.raises(SandboxError) as refusal:
            build_task_image(
                context=checkout,
                base_commit=commit,
                exclude_newer=None,
                timeout_s=BUILD_BUDGET_S,
            )

    # The diverging path is named. "This context is dirty" would leave the caller to go and
    # find out which file of the thousand in a real repository it meant.
    assert "widget/calc.py" in str(refusal.value)


def test_a_context_dirty_only_where_the_build_ignores_it_is_still_built(tmp_path: Path) -> None:
    """The false-refusal half, and what binds the precondition's filter to the dockerignore.

    A host provisioning run leaves `.venv` behind and an interpreter leaves `__pycache__`.
    Neither is part of the commit and neither reaches the image, because both are excluded from
    the build context - so neither is a reason to refuse. If the two lists ever drift apart, the
    build starts refusing trees it should mine, which is a harness that measures nothing at all.
    """
    with fixture_worktree(tmp_path) as (checkout, commit):
        (checkout / ".venv").mkdir()
        (checkout / ".venv" / "pyvenv.cfg").write_text(
            "home = /nowhere\n", encoding="utf-8", newline="\n"
        )
        (checkout / "__pycache__").mkdir()
        (checkout / "__pycache__" / "widget.cpython-312.pyc").write_bytes(b"\x00")

        built = build_task_image(
            context=checkout, base_commit=commit, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

    # The address the clean tree builds to, unchanged: scratch state the build never copies must
    # not decide whether an image exists, and must not decide what it is called either.
    assert built == image_tag(
        base_image=_PINNED_BASE_IMAGE, dockerfile=_RECIPE_WITHOUT_A_CUTOFF, base_commit=commit
    )


def test_a_context_git_has_never_heard_of_is_refused_rather_than_built(tmp_path: Path) -> None:
    # "There is no commit here" is not a tree an address can name, so it is the same refusal a
    # patched checkout gets. The `GitError` is chained rather than swallowed: what git said is
    # the only thing that tells a caller whether the path was wrong or git was missing.
    plain = tmp_path / "not-a-checkout"
    plain.mkdir()

    with pytest.raises(SandboxError) as refusal:
        build_task_image(
            context=plain, base_commit=_COMMIT, exclude_newer=None, timeout_s=BUILD_BUDGET_S
        )

    assert isinstance(refusal.value.__cause__, GitError)


@pytest.mark.parametrize(
    ("changed", "diverging"),
    [
        ((), ()),
        ((" M widget/calc.py",), (" M widget/calc.py",)),
        (("?? scratch.txt",), ("?? scratch.txt",)),
        (("A  widget/added.py", "?? .venv/"), ("A  widget/added.py",)),
        (("?? .venv/", "?? __pycache__/", "?? .git"), ()),
        (("?? widget/__pycache__/",), ("?? widget/__pycache__/",)),
        (("?? .venv-of-somebody-elses/",), ("?? .venv-of-somebody-elses/",)),
        (
            ("R  widget/calc.py -> widget/total.py",),
            ("R  widget/calc.py -> widget/total.py",),
        ),
    ],
    ids=[
        "clean",
        "tracked-file-modified",
        "untracked-file",
        "one-of-each",
        "only-what-the-build-excludes",
        "an-exclusion-below-the-top-level-still-reaches-the-image",
        "a-name-the-exclusion-is-only-a-prefix-of",
        "rename",
    ],
)
def test_only_a_change_the_image_would_carry_counts_as_divergence(
    changed: tuple[str, ...], diverging: tuple[str, ...]
) -> None:
    # Pure, so it is asserted directly rather than through a build: the entries below are the
    # shapes `git status --porcelain` actually emits, and the question is which of them describe
    # a tree the tag would misdescribe. `widget/__pycache__/` is one of them - a dockerignore
    # pattern without `**/` is top level only, so that directory does reach the image.
    state = CheckoutState(head=_COMMIT, changed=changed)

    assert _context_divergence(state, _COMMIT) == diverging


def test_a_spotless_checkout_of_another_commit_is_still_the_wrong_commit() -> None:
    divergence = _context_divergence(CheckoutState(head=_OTHER_COMMIT, changed=()), _COMMIT)

    # Named both ways round, because the interesting failure is a caller passing the commit it
    # meant to check out rather than the one it did.
    assert len(divergence) == 1
    assert _COMMIT in divergence[0]
    assert _OTHER_COMMIT in divergence[0]
