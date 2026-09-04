"""What the agent phase is entitled to assume about the image it will run the tool in.

The third phase (ADR-0039), and until now the only build in this package with no test at all.
Its recipe was covered - ``tests/sandbox/test_adapter_phase.py`` pins what
:func:`assay.sandbox.render_agent_dockerfile` renders - but the recipe is a string, and a string
that installs nothing is still a string that renders. What was never asserted is that the
recipe *builds*, and that what it builds holds the tool.

That gap had a name in the source: :func:`assay.sandbox.build_agent_image` carried an
*Unverified* caveat saying every line of the recipe was written from documentation rather than
from a build on this host, because the daemon was down when it was written. A throwaway probe
retired that by hand once. A probe that is not committed is not a property, so these tests are
the committed form of it.

The property worth the most here is the last one: the recipe hardcodes where npm puts the
binary and :func:`assay.sandbox.adapter_phase_command` hardcodes the path it invokes, and
nothing in the repository connected those two strings. A build that installed the tool
somewhere else would leave both halves passing their own tests and every agentic trial failing
for a reason no test could name.

These tests really build images with a real daemon, for the reason ``tests/sandbox/support.py``
gives: the assumption being retired is docker's behaviour and npm's, and a mock of either
retires nothing. The images are deliberately left behind - they are content-addressed, so the
next run re-tags layers rather than reinstalling a node toolchain.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from assay.core import AssayError
from assay.host import CommandFailedError, minimal_env, run_command
from assay.sandbox import (
    SandboxError,
    build_agent_image,
    build_task_image,
    image_tag,
    render_agent_dockerfile,
)
from tests.sandbox.support import BUILD_BUDGET_S, fixture_worktree, image_created_at

# The path `assay.sandbox.adapter_phase_command` invokes, spelled out here rather than imported
# from the module that builds the argv. An oracle that reads its answer out of the code under
# test cannot notice that code drifting, and the whole point of the last test in this file is
# that these two hardcoded paths are the same path.
_AGENT_BINARY = "/usr/local/bin/claude"

# Longer than `BUILD_BUDGET_S`, because a cold agent build is an apt transaction and a global
# npm install on top of a task image that may itself be cold. Still a ceiling rather than a
# hang: a wedged daemon is a failure here, not a test that runs until someone kills it.
_AGENT_BUILD_BUDGET_S = 1200

# A commit that is not the fixture's, used only where a *second* content address is needed. It
# never has to exist: `build_agent_image` takes the commit as an ingredient of the tag, not as
# something to check out - the checkout was already done by the phase underneath.
_OTHER_COMMIT = "89abcdef0123456789abcdef0123456789abcdef"


@pytest.fixture(scope="module")
def task_image(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, str]]:
    """A task image built from the fixture repository, and the commit it holds.

    Module-scoped for the reason :func:`tests.sandbox.support.fixture_image` gives about
    holding an image open rather than rebuilding per test: the build is cheap on the second
    call and afterwards, but it is not free, and everything in this file layers over the same
    one.

    Yields:
        The task image's tag and the commit it was built from - the two arguments the agent
        phase layers over.
    """
    root = tmp_path_factory.mktemp("agent-image")
    with fixture_worktree(root) as (checkout, commit):
        yield (
            build_task_image(
                context=checkout,
                base_commit=commit,
                exclude_newer=None,
                timeout_s=BUILD_BUDGET_S,
            ),
            commit,
        )


def _tool_version_inside(tag: str) -> str:
    """What the tool inside ``tag`` says when asked for its version.

    Asked of the image rather than of the build log, for the reason
    :func:`tests.sandbox.support.installed_version` gives: the log is a rendering, the installed
    image is the fact. ``--network none`` because a version string that needed a registry to
    answer would be describing something other than what is in the image.
    """
    found = run_command(
        ("docker", "run", "--rm", "--network", "none", tag, _AGENT_BINARY, "--version"),
        cwd=Path.cwd(),
        timeout_s=120,
        env=minimal_env(),
        check=True,
    )
    return found.stdout.strip()


def test_the_recipe_written_from_documentation_really_builds(
    task_image: tuple[str, str],
) -> None:
    """The *Unverified* caveat, retired: these lines produce an image the daemon holds."""
    base_tag, commit = task_image

    built = build_agent_image(
        base_tag=base_tag,
        base_commit=commit,
        tool_version=None,
        timeout_s=_AGENT_BUILD_BUDGET_S,
    )

    assert built.startswith("assay-task:")
    # `image_created_at` fails loudly if the daemon does not hold the tag, which is the half of
    # "it built" that a returned string on its own does not prove.
    assert image_created_at(built)


def test_the_tool_the_adapter_will_invoke_is_at_the_path_it_invokes(
    task_image: tuple[str, str],
) -> None:
    """The two hardcoded paths agree - the failure nothing else in the repo could catch.

    `render_agent_dockerfile` decides where npm installs the tool; `adapter_phase_command`
    decides what path the trial executes. Both are covered by tests that would keep passing if
    the two disagreed, and every agentic trial would then fail on a missing binary.
    """
    base_tag, commit = task_image

    built = build_agent_image(
        base_tag=base_tag,
        base_commit=commit,
        tool_version=None,
        timeout_s=_AGENT_BUILD_BUDGET_S,
    )

    # `check=True` inside the helper: a tool that is not at this path is a failed run, and the
    # failure is the assertion. The string it prints is the tool naming itself, which is how we
    # know npm installed the package we asked for rather than some other `claude` on the PATH.
    assert "Claude Code" in _tool_version_inside(built)


def test_building_the_same_agent_image_twice_costs_one_build(
    task_image: tuple[str, str],
) -> None:
    """The docstring's "cheap to call twice", asserted the way the task-image test asserts it.

    Timestamps rather than image IDs: a fully cached rebuild still exports a fresh manifest, so
    the ID moves even when nothing was built. The creation timestamp lives in the image config,
    which is part of what gets cached, so it moves if and only if a layer was actually built.
    """
    base_tag, commit = task_image

    first = build_agent_image(
        base_tag=base_tag,
        base_commit=commit,
        tool_version=None,
        timeout_s=_AGENT_BUILD_BUDGET_S,
    )
    built_at = image_created_at(first)
    second = build_agent_image(
        base_tag=base_tag,
        base_commit=commit,
        tool_version=None,
        timeout_s=_AGENT_BUILD_BUDGET_S,
    )

    assert second == first
    assert image_created_at(second) == built_at


def test_the_measurement_image_is_untouched_by_the_phase_layered_over_it(
    task_image: tuple[str, str],
) -> None:
    """ADR-0039's central claim: the image M2 measured in does not move when the tool arrives.

    The reason the agent phase is a layer rather than a line in the base recipe. If installing a
    node toolchain re-addressed or rebuilt the task image, every trial M2 measured would have
    been measured in an environment that no longer exists.
    """
    base_tag, commit = task_image
    before = image_created_at(base_tag)

    build_agent_image(
        base_tag=base_tag,
        base_commit=commit,
        tool_version=None,
        timeout_s=_AGENT_BUILD_BUDGET_S,
    )

    assert image_created_at(base_tag) == before


def test_two_base_commits_are_two_agent_images_under_one_recipe(
    task_image: tuple[str, str],
) -> None:
    """The commit is an ingredient of the address, not just of the image underneath.

    Two commits are two environments even when the tool installed on top is identical, and a
    tag that ignored the commit would let a trial be scored against the wrong one.
    """
    base_tag, commit = task_image
    recipe = render_agent_dockerfile(base_tag=base_tag, tool_version=None)

    built = build_agent_image(
        base_tag=base_tag,
        base_commit=commit,
        tool_version=None,
        timeout_s=_AGENT_BUILD_BUDGET_S,
    )

    assert built != image_tag(base_image=base_tag, dockerfile=recipe, base_commit=_OTHER_COMMIT)


@pytest.mark.parametrize("version", ["latest", "^2.0.1", "2.0", "2.0.1 && rm -rf /", ""])
def test_a_version_that_is_not_a_release_is_refused_before_anything_is_built(
    version: str,
) -> None:
    """The refusal beats the build to it, proved without a daemon and without a mock.

    The base tag names an image nothing holds, so a build that started would fail with
    `CommandFailedError`. Getting `SandboxError` instead is the ordering: the version reaches a
    `RUN` line and a content address, so it is refused where it arrives.
    """
    with pytest.raises(SandboxError) as refusal:
        build_agent_image(
            base_tag="assay-task:0000000000000000000000000000000000000000000000000000000000000000",
            base_commit=_OTHER_COMMIT,
            tool_version=version,
            timeout_s=_AGENT_BUILD_BUDGET_S,
        )

    assert not isinstance(refusal.value, CommandFailedError)
    # Catchable as this package's own error, the way every other refusal here is.
    assert isinstance(refusal.value, AssayError)
