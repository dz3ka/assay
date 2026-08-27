"""What Assay is entitled to assume about an environment it built for someone else's code.

The provisioning step is the one place a mined repository's *dependencies* are decided, and
the property worth defending is narrow: the interpreter handed back is real, it can import the
project that was installed into it, and it can import pytest even though the throwaway project
here never asks for one - a repository that declares pytest only as a development dependency
is the common case, and a run that cannot start measures nothing (SPEC §3).

These tests really run ``uv``. That is deliberate: the assumption being retired is uv's
behaviour, and a mock of it would retire nothing. They need uv's cache warm or a network -
see the measurements in :mod:`assay.host.venv`.
"""

import sys
from pathlib import Path

import pytest

from assay.host import EnvironmentSetupError, minimal_env, provision_venv, run_command

# Long enough that a cold uv cache downloading a build backend does not fail the suite, short
# enough that a hung install is still caught. Provisioning measured at 2-4 s with a warm cache.
_BUDGET_S = 300

_PYPROJECT = """\
[project]
name = "tiny"
version = "0.1.0"
requires-python = ">=3.12"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


def _project(root: Path) -> Path:
    """A one-module installable package, as small as a thing with a build backend gets."""
    (root / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8", newline="\n")
    package = root / "src" / "tiny"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 7\n", encoding="utf-8", newline="\n")
    return root


def test_the_interpreter_returned_can_import_the_project_and_pytest(tmp_path: Path) -> None:
    python = provision_venv(_project(tmp_path), timeout_s=_BUDGET_S)

    assert python.exists()
    assert python.is_relative_to(tmp_path / ".venv")
    proof = run_command(
        [str(python), "-c", "import tiny, pytest; print(tiny.VALUE)"],
        cwd=tmp_path,
        timeout_s=60,
        env=minimal_env(),
    )
    assert proof.exit_code == 0, proof.stderr
    assert proof.stdout.strip() == "7"


def test_the_environment_is_the_workspaces_own_and_not_the_one_assay_runs_in(
    tmp_path: Path,
) -> None:
    # The whole point of provisioning: a mined repository's tests must not be measured against
    # Assay's own dependency set (SPEC §5.2).
    python = provision_venv(_project(tmp_path), timeout_s=_BUDGET_S)

    assert python != Path(sys.executable)


def test_a_workspace_with_nothing_to_install_is_a_loud_failure(tmp_path: Path) -> None:
    # No pyproject.toml, so `uv pip install -e .` has no project to install. This is not a
    # countable rejection - it is a repository Assay cannot mine at all - so it raises.
    with pytest.raises(EnvironmentSetupError, match="command exited"):
        provision_venv(tmp_path, timeout_s=_BUDGET_S)
