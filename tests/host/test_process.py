"""Every subprocess Assay ever runs goes through ``run_command``; this is that seam's fence.

The repository under evaluation is hostile (SPEC §5.2): its ``conftest.py`` and its tests run
as the invoking user. So the three properties pinned here are not conveniences - no shell can
be reached from an argv, no name the caller did not put in ``env`` reaches the child, and a
command that outlives its budget takes its whole process group with it. A pytest run spawns
children, so killing only the child would leave the interesting half alive.
"""

import ast
import os
import sys
import time
from pathlib import Path

import pytest

from assay.host import (
    CommandFailedError,
    CommandResult,
    CommandTimeoutError,
    minimal_env,
    run_command,
)

# A heartbeat rather than a sleep-and-check: the grandchild rewrites this file ten times a
# second, so "the counter stopped moving across a two-second window" is twenty missed beats,
# not a race with the scheduler.
_HEARTBEAT_PERIOD_S = 0.1
_HEARTBEAT_WINDOW_S = 2.0


def _python(*code: str) -> list[str]:
    """An argv running this interpreter, which is the one process every host here has."""
    return [sys.executable, "-c", *code]


def _run(argv: list[str], cwd: Path, *, timeout_s: int = 30, check: bool = False) -> CommandResult:
    return run_command(argv, cwd=cwd, timeout_s=timeout_s, env=minimal_env(), check=check)


def _spawner(beat: Path) -> str:
    """Code for a child that spawns a longer-lived grandchild and then waits on nothing.

    This is the shape of a test run: the process ``run_command`` starts is not the process
    that holds the resources, so a timeout that only reaches the child is not a timeout.
    """
    grandchild = (
        "import pathlib, time\n"
        f"p = pathlib.Path({str(beat)!r})\n"
        "for i in range(600):\n"
        "    p.write_text(str(i))\n"
        f"    time.sleep({_HEARTBEAT_PERIOD_S})\n"
    )
    return (
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
        "time.sleep(600)\n"
    )


def _wait_for_first_beat(beat: Path) -> None:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if beat.exists():
            return
        time.sleep(_HEARTBEAT_PERIOD_S)
    raise AssertionError("the grandchild never started beating")


def _imports_subprocess(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import) and any(
            alias.name.split(".")[0] == "subprocess" for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "subprocess":
            return True
    return False


def test_a_command_that_succeeds_reports_its_argv_and_both_streams(tmp_path: Path) -> None:
    argv = _python("import sys; print('out'); print('err', file=sys.stderr)")

    result = _run(argv, tmp_path)

    assert result.argv == tuple(argv)
    assert result.exit_code == 0
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


def test_a_nonzero_exit_is_data_until_the_caller_asks_for_check(tmp_path: Path) -> None:
    # `git apply --check` refusing a patch is an answer, not an incident, so the default has
    # to hand the exit code back rather than raise.
    argv = _python("import sys; sys.exit(3)")

    assert _run(argv, tmp_path).exit_code == 3

    with pytest.raises(CommandFailedError) as caught:
        _run(argv, tmp_path, check=True)
    assert caught.value.result.exit_code == 3
    assert "3" in str(caught.value)


def test_the_command_runs_in_the_directory_it_was_given(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = _run(_python("import pathlib; print(pathlib.Path.cwd())"), workspace)

    assert Path(result.stdout.strip()).resolve() == workspace.resolve()


def test_a_command_string_is_refused_because_only_a_shell_could_run_it(tmp_path: Path) -> None:
    # `str` satisfies `Sequence[str]`, so mypy will not catch this one; the check has to be
    # at runtime or "assay mines a repo" becomes "assay runs whatever the repo wrote".
    with pytest.raises(TypeError):
        run_command("echo hi", cwd=tmp_path, timeout_s=5, env=minimal_env())


def test_an_empty_argv_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        run_command([], cwd=tmp_path, timeout_s=5, env=minimal_env())


@pytest.mark.parametrize(
    "hostile",
    ["a & echo pwned", "a; echo pwned", "a | echo pwned", "$(echo pwned)", "a\nb"],
    ids=["ampersand", "semicolon", "pipe", "substitution", "newline"],
)
def test_shell_metacharacters_in_an_argument_stay_one_literal_argument(
    tmp_path: Path, hostile: str
) -> None:
    argv = [*_python("import sys; print(repr(sys.argv[1]))"), hostile]

    result = _run(argv, tmp_path)

    assert result.stdout.strip() == repr(hostile)


def test_the_child_sees_exactly_the_environment_it_was_handed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The developer's shell holds model API keys. Third-party test code from a mined repo
    # runs under this call, so inheriting the ambient environment would hand them over.
    monkeypatch.setenv("ASSAY_TEST_FAKE_API_KEY", "sk-not-a-real-key")
    argv = _python("import os; print('\\n'.join(sorted(os.environ)))")

    names = _run(argv, tmp_path).stdout.split()

    assert "ASSAY_TEST_FAKE_API_KEY" not in names
    assert "PATH" in names


def test_the_minimal_environment_carries_no_name_the_module_did_not_choose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-not-a-real-key")

    env = minimal_env()

    assert "OPENAI_API_KEY" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert env["PATH"] == os.environ["PATH"]


def test_a_timeout_kills_the_whole_process_group_not_just_the_child(tmp_path: Path) -> None:
    beat = tmp_path / "beat.txt"

    with pytest.raises(CommandTimeoutError):
        _run(_python(_spawner(beat)), tmp_path, timeout_s=1)

    _wait_for_first_beat(beat)
    before = beat.read_text(encoding="utf-8")
    time.sleep(_HEARTBEAT_WINDOW_S)
    assert beat.read_text(encoding="utf-8") == before, "the grandchild outlived the timeout"


def test_a_timeout_names_the_command_and_the_budget_it_blew(tmp_path: Path) -> None:
    argv = _python("import time; time.sleep(600)")

    with pytest.raises(CommandTimeoutError) as caught:
        _run(argv, tmp_path, timeout_s=1)

    assert caught.value.argv == tuple(argv)
    assert caught.value.timeout_s == 1
    assert "1" in str(caught.value)


def test_output_is_decoded_without_translating_line_endings(tmp_path: Path) -> None:
    # A diff carries the bytes of the file it describes: turning a CRLF in a mined repo into
    # an LF here would produce a patch that does not apply on the host it was mined from.
    argv = _python("import sys; sys.stdout.buffer.write(b'a\\r\\nb\\n')")

    assert _run(argv, tmp_path).stdout == "a\r\nb\n"


def test_undecodable_output_is_replaced_rather_than_raising(tmp_path: Path) -> None:
    # A mined repo may hold a filename that is not UTF-8. Refusing to decode it would turn a
    # skippable commit into a crashed mining run.
    argv = _python("import sys; sys.stdout.buffer.write(b'\\xff\\xfe')")

    result = _run(argv, tmp_path)

    assert result.exit_code == 0
    assert "�" in result.stdout


def test_the_result_is_frozen(tmp_path: Path) -> None:
    result = _run(_python("pass"), tmp_path)

    with pytest.raises(AttributeError):
        result.exit_code = 1  # type: ignore[misc]


def test_no_module_outside_the_host_package_imports_subprocess() -> None:
    """The invariant this package exists to hold (SPEC §5.2).

    Read from the import statements rather than from the file's text: a module that explains
    the rule in its docstring is obeying it, not breaking it.
    """
    source_root = Path(__file__).parent.parent.parent / "src" / "assay"

    offenders = [
        path.relative_to(source_root).as_posix()
        for path in sorted(source_root.rglob("*.py"))
        if path.parent.name != "host" and _imports_subprocess(path)
    ]

    assert offenders == []
