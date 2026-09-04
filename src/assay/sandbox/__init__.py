"""Everything that happens inside a container: the task image, and the policy a trial runs under.

Model-generated code never runs on the host (SPEC §5.2), so a trial runs in a container built
from the commit it is scoring. This package owns both halves of that: the image, which is where
dependencies are installed *before* the trial and therefore where "no network during a trial"
becomes affordable, and the run policy, which is where it becomes true.

It sits above :mod:`assay.host` and drives the docker CLI through
:func:`assay.host.run_command`, like every other outside-world call in the tree - there is no
docker SDK, because a second way to start a process is a second thing the ``subprocess`` fence
in ``tests/host/test_process.py`` cannot see.

Import these names from ``assay.sandbox``; which submodule holds which is an implementation
detail.
"""

from assay.sandbox.container import (
    ADAPTER_PHASE_NETWORK,
    OUT_DIR,
    adapter_phase_command,
    run_in_sandbox,
)
from assay.sandbox.errors import SandboxError
from assay.sandbox.image import (
    AGENT_EXECUTABLE,
    TEST_EXTRA_NAMES,
    VENV_PYTHON,
    WORKSPACE_DIR,
    build_agent_image,
    build_task_image,
    image_tag,
    read_declared_extras,
    read_installed_closure,
    render_agent_dockerfile,
    render_base_dockerfile,
    render_extras_dockerfile,
)
from assay.sandbox.models import ContainerLimits
from assay.sandbox.runner import SandboxTestRunner, sandbox_runner_for

__all__ = [
    "ADAPTER_PHASE_NETWORK",
    "AGENT_EXECUTABLE",
    "OUT_DIR",
    "TEST_EXTRA_NAMES",
    "VENV_PYTHON",
    "WORKSPACE_DIR",
    "ContainerLimits",
    "SandboxError",
    "SandboxTestRunner",
    "adapter_phase_command",
    "build_agent_image",
    "build_task_image",
    "image_tag",
    "read_declared_extras",
    "read_installed_closure",
    "render_agent_dockerfile",
    "render_base_dockerfile",
    "render_extras_dockerfile",
    "run_in_sandbox",
    "sandbox_runner_for",
]
