"""The container an agentic tool works in, asserted about the argv rather than about a daemon.

Unlike its siblings in this directory these tests need no Docker (ADR-0024 is about the
*negatives* a running trial proves, and there is no skip path here to hide one):
:func:`assay.sandbox.adapter_phase_command` is pure, and every property below is a property of
the command line it composes. That is the point of it being pure - a claim about what a
container may do should not be checkable only on a host that has one.

Three of these matter more than the rest. The workspace is **writable** here and read-only in
the measurement phase, which is the difference between the phase a tool edits in and the phase a
verdict is read from (ADR-0038). The API key travels as a **name**, never as ``NAME=value``,
because an argv is readable by every process on the host (plan section 7a). And the network is
what :data:`assay.sandbox.ADAPTER_PHASE_NETWORK` says it is - the last test in this file exists
to state, in a place a reader will find, that it is not a hostname allowlist.
"""

from pathlib import Path

import pytest

from assay.sandbox import (
    ADAPTER_PHASE_NETWORK,
    WORKSPACE_DIR,
    ContainerLimits,
    SandboxError,
    adapter_phase_command,
    image_tag,
    render_agent_dockerfile,
)

_IMAGE = "assay-task:cafe"
_AGENT_ARGV = ("/usr/local/bin/claude", "-p", "fix the failing test", "--model", "some-model")
_LIMITS = ContainerLimits(memory_mb=512, cpus="1", pids=256)
_KEY_NAME = "ANTHROPIC_API_KEY"
_COMMIT = "0" * 40


def _command(
    workspace: Path,
    *,
    argv: tuple[str, ...] = _AGENT_ARGV,
    env_names: tuple[str, ...] = (_KEY_NAME,),
) -> tuple[str, ...]:
    return adapter_phase_command(
        image_tag=_IMAGE,
        workspace=workspace,
        argv=argv,
        limits=_LIMITS,
        env_names=env_names,
    )


def _flag(command: tuple[str, ...], name: str) -> str:
    """The value docker would read for ``name``, so a test names a flag rather than an index."""
    return command[command.index(name) + 1]


def test_the_tools_own_argv_is_the_tail_of_the_command(tmp_path: Path) -> None:
    # After the image tag, which is what makes it the container's command rather than more
    # flags for the client.
    command = _command(tmp_path)

    assert command[:2] == ("docker", "run")
    assert command[-len(_AGENT_ARGV) :] == _AGENT_ARGV
    assert command[-len(_AGENT_ARGV) - 1] == _IMAGE


def test_the_workspace_is_mounted_writable_and_is_the_working_directory(tmp_path: Path) -> None:
    # Writable, unlike the measurement phase: the tool's whole output is the tree it leaves,
    # and nothing is measured in this checkout (ADR-0038).
    command = _command(tmp_path)

    assert _flag(command, "--volume") == f"{tmp_path.as_posix()}:{WORKSPACE_DIR}"
    assert not _flag(command, "--volume").endswith(":ro")
    assert _flag(command, "--workdir") == WORKSPACE_DIR


def test_the_image_itself_stays_read_only_with_a_scratch_tmpfs(tmp_path: Path) -> None:
    command = _command(tmp_path)

    assert "--read-only" in command
    assert _flag(command, "--tmpfs") == "/tmp"
    assert "HOME=/tmp" in command


def test_the_tool_runs_with_no_capabilities_and_cannot_regain_any(tmp_path: Path) -> None:
    # The two flags that matter because the container runs as uid 0, for the reasons
    # `assay.sandbox.container`'s header measures.
    command = _command(tmp_path)

    assert _flag(command, "--cap-drop") == "ALL"
    assert _flag(command, "--security-opt") == "no-new-privileges"


def test_a_missing_image_is_refused_here_rather_than_fetched(tmp_path: Path) -> None:
    # The task image *is* the repository under evaluation, so a registry round trip is the one
    # thing SPEC section 5.1 does not allow - true of this phase as much as of the trial's.
    assert _flag(_command(tmp_path), "--pull") == "never"


def test_the_caller_s_resource_ceiling_is_what_the_container_gets(tmp_path: Path) -> None:
    command = _command(tmp_path)

    assert _flag(command, "--memory") == "512m"
    assert _flag(command, "--memory-swap") == "512m"
    assert _flag(command, "--cpus") == "1"
    assert _flag(command, "--pids-limit") == "256"


def test_the_container_is_removed_when_it_stops(tmp_path: Path) -> None:
    assert "--rm" in _command(tmp_path)


def test_an_api_key_travels_as_a_name_and_never_as_a_value(tmp_path: Path) -> None:
    # The load-bearing one. `--env NAME` takes the value from the client's environment; an
    # argv holding `NAME=sk-ant-...` is readable by every process on the host (plan section 7a).
    command = _command(tmp_path)
    passed = [command[index + 1] for index, part in enumerate(command) if part == "--env"]

    assert _KEY_NAME in passed
    assert all("=" not in name for name in passed if name != "HOME=/tmp")


@pytest.mark.parametrize("name", ["", "KEY=value", "not a name", "--privileged", "KEY;rm"])
def test_a_name_that_is_not_an_environment_variable_name_is_refused(
    tmp_path: Path, name: str
) -> None:
    # Refused where it arrives rather than escaped, the posture this package takes towards
    # every value that reaches a command line.
    with pytest.raises(SandboxError):
        _command(tmp_path, env_names=(name,))


def test_a_phase_with_no_command_to_run_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SandboxError):
        _command(tmp_path, argv=())


def test_the_adapter_phase_network_is_the_named_posture_and_not_an_allowlist(
    tmp_path: Path,
) -> None:
    """The gap, asserted so that closing it has to change a test rather than only a comment.

    ADR-0039 says the adapter phase should reach ``api.anthropic.com`` and nothing else. Docker
    has no native hostname allowlist, and what this phase actually gets is an ordinary bridge
    with unrestricted egress. That is stated in :data:`assay.sandbox.ADAPTER_PHASE_NETWORK`, in
    the ADR and in M3's milestone record rather than papered over - and it is asserted here,
    negatively, so that a future change which really does allowlist a host arrives with this
    test failing and a reader asking why.
    """
    command = _command(tmp_path)

    assert _flag(command, "--network") == ADAPTER_PHASE_NETWORK
    # Not the measurement phase's posture: a tool that cannot reach a model is not a tool.
    assert _flag(command, "--network") != "none"
    assert not any("anthropic" in part for part in command)


def test_the_agent_recipe_installs_the_tool_over_the_task_image() -> None:
    recipe = render_agent_dockerfile(base_tag=_IMAGE, tool_version=None)

    assert recipe.startswith(f"FROM {_IMAGE}\n")
    assert "@anthropic-ai/claude-code" in recipe


def test_a_pinned_tool_version_is_a_different_image_than_an_unpinned_one() -> None:
    # The address is keyed on the recipe, so pinning is visible in the tag - which is the whole
    # reason `tool_version` exists: an unpinned install means the address does not capture what
    # is inside, and two runs months apart can measure two different tools.
    unpinned = render_agent_dockerfile(base_tag=_IMAGE, tool_version=None)
    pinned = render_agent_dockerfile(base_tag=_IMAGE, tool_version="2.0.1")

    assert "@2.0.1" in pinned
    assert image_tag(base_image=_IMAGE, dockerfile=unpinned, base_commit=_COMMIT) != image_tag(
        base_image=_IMAGE, dockerfile=pinned, base_commit=_COMMIT
    )


@pytest.mark.parametrize("version", ["latest", "^2.0.1", "2.0", "2.0.1 && rm -rf /", ""])
def test_a_version_npm_would_read_as_a_range_or_a_tag_is_refused(version: str) -> None:
    with pytest.raises(SandboxError):
        render_agent_dockerfile(base_tag=_IMAGE, tool_version=version)
