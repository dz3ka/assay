"""The task image: one container image per mined commit, built here and never pushed anywhere.

A trial has to run the repository's tests against dependencies that were installed *before* the
trial started (SPEC §5.3, ADR-0006) - otherwise a tool can ``pip install`` its way to a passing
test, and one will. So the environment is baked into an image at mining time and the trial gets
no network at all. The image is built from the worktree of the commit it belongs to, which makes
it as pinned as ADR-0017 and ADR-0019 need it to be: the environment a trial runs in is the
environment the red->green gate validated, not whatever the index happened to serve that day.

The image is **built locally on demand and never pushed or pulled**. An image containing the
repository *is* the repository, so a registry round-trip would break SPEC §5.1 outright.

Four shapes of the design are worth naming before the measurements below, because each looks
arbitrary otherwise:

* **Dependency *resolution* is pinned to the base commit's era, not only its install**
  (ADR-0021). ``uv --exclude-newer`` is handed the commit's committer date, so a 2020 commit
  resolves against the index as it stood in 2020 rather than against today's. Without it the
  tree is the commit's and the environment around it is dated today, which is the measured
  cause of M2's zero-yield httpie re-mine. ``exclude_newer=None`` keeps the old behaviour -
  today's index - and renders the recipe every tag built before ADR-0021 was addressed by.
* **The virtual environment lives at ``/opt/venv``, not at ``/workspace/.venv``.** At run time
  ``/workspace`` is replaced by a bind mount of the trial's own checkout, so anything the build
  left inside ``/workspace`` is simply gone. The project is nonetheless installed *editable*
  against ``/workspace``, so the code the tests import is the mounted code rather than a copy
  frozen at build time. That is the load-bearing assumption, and it is measured below.
* **The Dockerfile is written outside the build context** and passed with ``-f``, together with
  a sibling ``Dockerfile.dockerignore``. The context is a checkout Assay is about to score with
  ``git diff``; a file Assay added to it would show up as the tool's work.
* **The build has two phases, and the second one is skipped by most repositories** (ADR-0023).
  A repository keeps its test dependencies in an optional extra or nowhere; which of the two is
  a fact only the built project's own metadata knows, so the first phase installs the runtime
  set and pytest, the image is asked what extras it declares
  (:func:`read_declared_extras`), and a second phase installs the allowlisted ones on top. A
  project declaring none - the fixture repository is one - gets the first phase's tag
  unchanged, byte for byte, so nothing already built churns.

**Measured, 2026-08-28** (Docker Desktop, server 29.7.2, OSType linux, driver overlayfs, cgroup
v2 with the cgroupfs driver, Windows 11 host over WSL2). Every line below is an observation from
this host, not a reading of the documentation - the M2 plan required these five to be retired by
a probe before anything depended on them:

* **Base image.** ``ghcr.io/astral-sh/uv:python3.12-bookworm-slim`` resolves to manifest-list
  digest ``sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58`` and carries
  **uv 0.9.30** and **CPython 3.12.12** at ``/usr/local/bin/python3``. :data:`_BASE_IMAGE` pins
  that digest: a tag that silently moves would make a content-addressed tag a lie. ghcr.io rather
  than Docker Hub because CI pulls anonymously and Hub rate-limits that.
* **An editable install at ``/workspace`` survives ``/workspace`` being replaced by a bind
  mount.** ``uv pip install -e /workspace`` leaves ``_editable_impl_widget.pth`` in the venv's
  ``site-packages`` holding the single line ``/workspace``, so resolution happens through
  ``sys.path`` at import time rather than through a copy. Probed by building the image from a
  flat-layout hatchling project, then running it with ``-v <host dir>:/workspace:ro`` over a
  *modified* copy of that project: ``import widget.calc`` reported ``/workspace/widget/calc.py``,
  a module added to the host copy **after** the image was built imported fine, and
  ``python -m pytest -q -p no:cacheprovider`` printed ``3 passed`` where the built image had only
  ever seen one test. The whole image design rests on this and it holds.
* **A Windows ``%TEMP%`` path bind-mounts.** The probe above mounted
  ``C:/Users/<user>/AppData/Local/Temp/...`` directly, forward slashes, with no ``/mnt/c``
  rewriting and no Docker Desktop file-sharing prompt. That is where pytest's ``tmp_path`` lives,
  so the sandbox tests can mount what they build.
* **``--memory-swap`` equal to ``--memory`` produces exit 137.** ``docker run --memory 64m
  --memory-swap 64m ... python3 -c "<allocate 400 MiB>"`` exited **137** - the OOM kill, not a
  slow swap. Worth recording honestly: the same allocation under ``--memory 64m`` *alone* (whose
  default ``--memory-swap`` is twice the limit) also exited 137 on this host, because WSL2's VM
  had no swap to give. So the flag is not what saves us here; it is what stops a host that *does*
  have swap from turning the resource-limit assertion into a slow test that never fails.
* **A broken root ``conftest.py`` exits 4 and writes no junit report at all.** Measured on real
  httpie (shallow clone, root ``conftest.py`` replaced by an import of a module that does not
  exist), running ``pytest -p no:cacheprovider --junit-xml=/tmp/j.xml -q tests/test_uploads.py``:
  exit **4**, ``ImportError while loading conftest``, and ``/tmp/j.xml`` was never created. That
  is the "nothing ran" shape M2's eighth ``GateRejection`` member is defined by - no statuses
  *and* an empty ``uncollectable``, because :func:`assay.host.junit.build_test_report` is handed
  no report to parse rather than a report full of collection errors.

**Measured too, and load-bearing for the cache-hit test:** BuildKit prints ``CACHED`` per reused
step to **stderr**, and a fully cached rebuild of the same tag yields a *different* image ID -
the manifest list is re-exported each time - while ``{{.Created}}`` from ``docker image inspect``
is unchanged. So "the second build was a cache hit" is asserted on the creation timestamp, never
on the ID. ``minimal_env()`` on its own is enough to run ``docker build``: no ``DOCKER_HOST``, no
``DOCKER_BUILDKIT``, nothing beyond the names that allowlist already carries.
"""

import re
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from time import monotonic
from typing import Final

from assay.core import HASH_PREFIX, content_hash
from assay.host import CheckoutState, GitError, checkout_state, minimal_env, run_command
from assay.sandbox.errors import SandboxError

# Where the repository under evaluation lives inside the image, and the interpreter its tests are
# run with. Exported because the container policy and the sandbox runner have to name the same
# two paths this module creates, and a second spelling of either is a silent misconfiguration.
WORKSPACE_DIR: Final = "/workspace"
VENV_PYTHON: Final = "/opt/venv/bin/python"

# The local repository name every task image is tagged under. Never pushed, so it needs no
# registry host - and would be wrong to give one, since a registry is exactly what SPEC §5.1
# forbids here. Lowercase because docker requires it of a repository name.
_REPOSITORY: Final = "assay-task"

# Pinned by digest, not by tag: the tag is what the *content address* means, and a base image
# that moved under a stable tag would leave two different environments sharing one address. The
# digest is the manifest list's, so it resolves on any architecture.
_BASE_IMAGE: Final = (
    "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"
    "@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58"
)

# A cutoff on its way into the ``RUN`` line, which is a shell line. Exactly one spelling gets
# through - UTC, second precision, literal ``Z`` - because this is the boundary where the value
# enters a *content address* (ADR-0022). Two spellings of one instant, or a bare ``YYYY-MM-DD``
# whose meaning uv resolves in the container's own time zone, would each let one commit carry
# two addresses. Producing the canonical form is ``host/git.py``'s job, not this module's; here
# anything else is refused where it arrives rather than where it detonates, the same rule
# ``host/git.py``'s ``_checked_revision`` applies to an object name.
_CUTOFF_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Excluded from the context. ``.git`` in a worktree is a *file* pointing back at the clone, and
# ``.venv`` is what an M1 host provisioning run leaves behind; neither is part of the commit, and
# both would make the image content depend on the host's scratch state while the tag - computed
# from the commit - did not move. Top level only, because that is what a dockerignore pattern
# without ``**/`` means: a ``widget/__pycache__`` *does* reach the image and is therefore not
# something :func:`_context_divergence` may wave through.
_CONTEXT_EXCLUSIONS: Final[tuple[str, ...]] = (".git", ".venv", "__pycache__")

# The same list as a dockerignore, derived rather than spelled a second time (ADR-0027). What a
# build copies and what the precondition forgives have to be one list: two lists drift, and the
# drift is silent in both directions - an image that quietly holds the host's scratch state, or a
# refusal of a context that was fine. Written beside the Dockerfile rather than inside the
# context, which BuildKit honours as ``<dockerfile>.dockerignore``; measured, not assumed. The
# trailing slashes the literal used to carry are dropped rather than rendered, and the meaning is
# unchanged: **measured 2026-09-01** with exactly this file over a context holding a ``.git``
# *file*, a ``.venv/``, a ``__pycache__/`` and a ``widget/__pycache__/``, the image held
# ``keep.txt`` and ``widget/__pycache__/b.pyc`` and nothing else - so a bare name excludes a
# directory and a file alike, and a pattern without ``**/`` reaches the top level only.
_DOCKERIGNORE: Final = "".join(f"{name}\n" for name in _CONTEXT_EXCLUSIONS)

# Where the path starts in a ``git status --porcelain`` entry: two status characters and a
# space. A rename's ``ORIG -> PATH`` form is deliberately not taken apart - git tracks nothing
# under :data:`_CONTEXT_EXCLUSIONS`, so a rename can never be excluded, and the whole two-path
# string simply fails to match an exclusion the way it should.
_PORCELAIN_PATH_START: Final = 3

_DOCKERFILE_NAME: Final = "Dockerfile"

# The agentic tool M3 measures, and where npm's global prefix puts its entry point on Debian.
# Both are named here rather than in the adapter, which never learns what it is driving
# (ADR-0039): the adapter is handed an executable and an argv, and this module is what puts a
# binary at that path. Both are verified against a real daemon: a built image runs the binary
# at this exact path - see ``test_the_tool_the_adapter_will_invoke_is_at_the_path_it_invokes``.
_AGENT_PACKAGE: Final = "@anthropic-ai/claude-code"
AGENT_EXECUTABLE: Final = "/usr/local/bin/claude"

# A plain release version on its way into a ``RUN`` line and a content address: digits and dots,
# nothing that npm would read as a range or a shell would read as anything at all.
_TOOL_VERSION_PATTERN: Final = re.compile(r"^\d+\.\d+\.\d+$")

# The optional extras a repository is allowed to have its test dependencies installed from, in
# the order they are rendered (ADR-0023). An allowlist rather than "every declared extra": a
# ``docs`` or ``lint`` extra has nothing to do with running tests and everything to do with
# widening the resolver surface, which is the failure ADR-0018 measured. Four names because
# these four are what the ecosystem actually uses; a fifth is a decision, not a config key.
TEST_EXTRA_NAMES: Final[tuple[str, ...]] = ("test", "tests", "testing", "dev")

# PEP 610 records where a distribution was installed from, and for the editable install the
# first phase performs that is the workspace. Matched on rather than on a project name because
# Assay does not know what the repository under evaluation calls itself - and must not have to
# guess, since the guess would be read off packaging the miner is forbidden to execute on the
# host (ADR-0023). Measured: uv 0.9.30 writes ``{"url":"file:///workspace",...}``.
_WORKSPACE_URL: Final = f"file://{WORKSPACE_DIR}"

# Asked of the image, not of the host, and with no network: the extras a project declares are
# known only once its build backend has run, and running that backend on the host is exactly
# what M2 moved into the sandbox. Prints one extra per line, and exits non-zero if the editable
# install the first phase performed is not there to be found - that is a broken image rather
# than a project without extras, and the two must not arrive as the same answer.
_DECLARED_EXTRAS_PROBE: Final = f"""\
import json
import sys
from importlib.metadata import distributions

for dist in distributions():
    recorded = dist.read_text("direct_url.json")
    if recorded is None or json.loads(recorded)["url"] != "{_WORKSPACE_URL}":
        continue
    for extra in dist.metadata.get_all("Provides-Extra") or ():
        print(extra)
    break
else:
    sys.exit("no distribution in this image was installed from {WORKSPACE_DIR}")
"""


def render_base_dockerfile(*, exclude_newer: str | None) -> str:
    """The whole recipe, verbatim - and, through :func:`image_tag`, an input to every tag.

    Changing a line here changes every address, so no trial can be scored against an image
    built from the previous recipe. That is also how ``exclude_newer`` becomes part of the
    content address without any special case: the cutoff lands in the text, and the text is
    already what the tag is keyed on.

    ``UV_LINK_MODE=copy``: uv hardlinks out of its cache by default and warns on every install
    when the cache and the target sit on different filesystems, which inside a build they do.
    ``pytest`` is installed alongside the project for the reason ``host/venv.py`` gives: a
    repository declares pytest as a development dependency or not at all, and a run that cannot
    start is evidence of nothing.

    Args:
        exclude_newer: The instant to resolve dependencies as of - the base commit's committer
            date (:meth:`assay.host.GitHistory.committed_at`) in production, and in the one
            canonical RFC3339 spelling that method produces: ``YYYY-MM-DDTHH:MM:SSZ``, nothing
            else. ``None`` means **today's index**, which is the M1 behaviour and the
            behaviour every in-repo caller still wants; the rendering is then byte-identical to
            the recipe every existing tag was computed from, so nothing already built churns.

    Returns:
        The complete Dockerfile text.

    Raises:
        SandboxError: if ``exclude_newer`` is not a canonical UTC instant. It reaches a ``RUN``
            line, so this is refused rather than escaped - the same posture
            :func:`assay.sandbox.runner._checked_selector` takes towards an argv.
    """
    # One resolution policy for the one install, appended rather than templated as an empty
    # line: an unconditional `--exclude-newer` with some sentinel value would make "today"
    # a date, and a rebuild months later would then no longer mean today.
    cutoff = "" if exclude_newer is None else f" --exclude-newer {_checked_cutoff(exclude_newer)}"
    return f"""\
FROM {_BASE_IMAGE}
ENV UV_LINK_MODE=copy
WORKDIR {WORKSPACE_DIR}
COPY . {WORKSPACE_DIR}
RUN uv venv /opt/venv \\
 && uv pip install --python {VENV_PYTHON}{cutoff} -e {WORKSPACE_DIR} pytest
"""


def render_extras_dockerfile(
    *, base_tag: str, extras: Sequence[str], exclude_newer: str | None
) -> str:
    """The second phase: the repository's declared test extras, installed over ``base_tag``.

    Nothing is copied, because the workspace is already in ``base_tag`` from the first phase;
    the install is re-run with an extras clause so that uv resolves the test set as well as the
    runtime one. Rendered as text and hashed like the first phase, so an image with extras can
    never carry the address of the image without them.

    Args:
        base_tag: The first phase's tag, which is this recipe's ``FROM``.
        extras: What :func:`_select_extras` chose - allowlisted, deduplicated, and in
            :data:`TEST_EXTRA_NAMES` order. Never empty: a phase with nothing to install would
            give one environment two addresses.
        exclude_newer: The same cutoff the first phase resolved under, or ``None`` for today's
            index. Passing a different one here would pin the runtime set to the commit's era
            and date the test set today, which is ADR-0021's defect reintroduced halfway.

    Returns:
        The complete Dockerfile text for the second phase.

    Raises:
        SandboxError: if ``extras`` is empty or holds anything outside :data:`TEST_EXTRA_NAMES`,
            or if ``exclude_newer`` is not a canonical UTC instant. Both reach a ``RUN`` line
            and a content address, so both are refused where they arrive.
    """
    cutoff = "" if exclude_newer is None else f" --exclude-newer {_checked_cutoff(exclude_newer)}"
    # Quoted: `[test]` is a shell glob pattern, and one that happens to match nothing today is
    # not a property to depend on inside a line that installs a test environment.
    clause = f"'{WORKSPACE_DIR}[{_checked_extras(extras)}]'"
    return f"""\
FROM {base_tag}
RUN uv pip install --python {VENV_PYTHON}{cutoff} -e {clause}
"""


def render_agent_dockerfile(*, base_tag: str, tool_version: str | None) -> str:
    """The agent phase: the agentic CLI, installed over a task image (ADR-0039).

    A third phase over the task image rather than a line in
    :func:`render_base_dockerfile`, and the reason is the content address. Every task image ever
    built is addressed by that recipe's text, so adding a node toolchain to it would re-address
    the environment every M2 trial was measured in - for a tool that no measurement phase ever
    runs. Layered instead, the measurement image stays byte for byte what it was and the agent
    image is a strictly larger thing with an address of its own.

    Nothing is copied: ``/workspace`` is already inside ``base_tag`` from the first phase, and
    at run time it is replaced by a bind mount of the trial's own checkout anyway.

    Written from documentation and since verified against a real daemon: the recipe builds,
    and the tool answers at :data:`AGENT_EXECUTABLE` inside the built image - see
    ``tests/sandbox/test_agent_image.py``, which exists to retire exactly this note. The
    harvest around it is a contract either way (ADR-0038).

    Args:
        base_tag: The task image this installs over, from :func:`build_task_image`.
        tool_version: The npm version to pin, or ``None`` for whatever the registry serves
            today. ``None`` is honest rather than convenient, and it is spelled the way
            ``exclude_newer=None`` is: an unpinned install means the address does **not** capture
            which version of the tool is inside, so two runs months apart can measure two
            different tools under one tag. Pass the version M3's live run observed as soon as
            there is one, and the address starts meaning what it says.

    Returns:
        The complete Dockerfile text.

    Raises:
        SandboxError: if ``tool_version`` is not a plain release version. It reaches a ``RUN``
            line and a content address, so it is refused where it arrives.
    """
    pinned = "" if tool_version is None else f"@{_checked_tool_version(tool_version)}"
    # `--no-install-recommends` because the recommended set of a node toolchain is most of a
    # desktop; the apt lists are removed in the same layer so they are not carried in the image.
    return f"""\
FROM {base_tag}
RUN apt-get update \\
 && apt-get install -y --no-install-recommends nodejs npm \\
 && rm -rf /var/lib/apt/lists/* \\
 && npm install -g {_AGENT_PACKAGE}{pinned}
"""


def build_agent_image(
    *, base_tag: str, base_commit: str, tool_version: str | None, timeout_s: int
) -> str:
    """Build the agent image over ``base_tag`` and return its tag.

    The image the adapter phase runs in (:func:`assay.sandbox.adapter_phase_command`), and the
    only image in this package that is built with a network reachable at build time on purpose:
    the tool comes from a registry, and SPEC §5.3's rule is that dependencies are installed when
    the image is built rather than during a trial. The measurement image is untouched.

    Cheap to call twice for the same base and the same version, like every other build here: the
    tag is a content address, so a second call re-tags layers BuildKit already holds.

    Args:
        base_tag: The task image to layer over.
        base_commit: The commit that image holds, which goes into this tag as well - two
            commits are two environments even when the tool installed on top is the same.
        tool_version: The version to pin, or ``None`` for today's registry.
        timeout_s: Wall-clock budget for the build. A cold one installs a node toolchain, so
            this is minutes rather than seconds.

    Returns:
        The tag the agent image now carries.

    Raises:
        SandboxError: if ``tool_version`` is not a plain release version.
        CommandFailedError: if ``docker build`` exited non-zero. Not wrapped, for the reason
            :func:`build_task_image` gives: the message already quotes the tail of the command's
            stderr, which is the only thing a caller could usefully print.
        CommandTimeoutError: if the budget expired.
    """
    recipe = render_agent_dockerfile(base_tag=base_tag, tool_version=tool_version)
    tag = image_tag(base_image=base_tag, dockerfile=recipe, base_commit=base_commit)
    # An empty context, because this phase copies nothing - the same reason the extras phase
    # sends one: the repository is already inside `base_tag`.
    with tempfile.TemporaryDirectory(prefix="assay-agent-") as nothing:
        _docker_build(dockerfile=recipe, tag=tag, context=Path(nothing), timeout_s=timeout_s)
    return tag


def image_tag(*, base_image: str, dockerfile: str, base_commit: str) -> str:
    """Address a task image by everything that decides what ends up inside it.

    Keyed on the recipe as well as on the commit. A tag keyed on ``base_commit`` alone would go
    on matching after the Dockerfile template or the pinned base image changed, and the run would
    quietly score a trial against an environment other than the one the gate validated - the
    failure this project exists to catch, committed inside its own harness.

    Args:
        base_image: The ``FROM`` reference, digest included if it is pinned by one.
        dockerfile: The complete Dockerfile text.
        base_commit: The commit the image is built from. That the context handed to the build
            *is* that commit is not something this function can see - it is checked before any
            build starts, by :func:`_checked_context` (ADR-0027).

    Returns:
        ``assay-task:<64 lowercase hex>`` - the digest half of
        :func:`assay.core.content_hash`, because a docker tag may not contain a colon.
    """
    address = content_hash(
        {"base_image": base_image, "dockerfile": dockerfile, "base_commit": base_commit}
    )
    return f"{_REPOSITORY}:{address.removeprefix(HASH_PREFIX)}"


def read_declared_extras(image_tag: str, *, timeout_s: int) -> tuple[str, ...]:
    """Every optional extra the repository inside ``image_tag`` declares, in the image's order.

    The question the second phase turns on, and it is put to the *built image* rather than to
    the checkout. A repository declares its extras in ``pyproject.toml``, in ``setup.cfg``, or
    in ``setup.py``, and the last of those is only answerable by running the repository's own
    packaging code - which SPEC §5.2 does not allow on the host and which M2 moved into the
    sandbox precisely so it would not have to be (ADR-0023). Once the first phase has installed
    the project, the answer is already sitting in the image as installed metadata.

    Args:
        image_tag: A first-phase task image, whose venv holds the workspace's editable install.
        timeout_s: Wall-clock budget. Seconds of work: one container, one interpreter start.

    Returns:
        The extras as the image reports them, unfiltered and unsorted - :func:`_select_extras`
        is what decides which of them mean anything and in what order. Empty when the project
        declares none, which is the common case.

    Raises:
        CommandFailedError: if the container could not be run, or if no distribution in the
            image was installed from the workspace. The second is a broken image rather than a
            project without extras, and answering ``()`` to it would install the wrong
            environment quietly. Deliberately the same error the build raises, so the composing
            caller has one failure to catch and counts the commit unprovisioned either way.
        CommandTimeoutError: if the budget expired.
    """
    found = run_command(
        # `--network none` because nothing here needs an index, and a probe that could reach one
        # is a probe that could change the environment it is describing.
        (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            image_tag,
            VENV_PYTHON,
            "-c",
            _DECLARED_EXTRAS_PROBE,
        ),
        # The docker client writes nothing into its working directory, and unlike the build
        # there is no context here that must stay untouched.
        cwd=Path.cwd(),
        timeout_s=timeout_s,
        env=minimal_env(),
        check=True,
    )
    # An extra name cannot contain whitespace (PEP 685), so splitting on it recovers the lines
    # the probe printed without caring how the metadata was folded.
    return tuple(found.stdout.split())


def read_installed_closure(image_tag: str, *, timeout_s: int) -> tuple[str, ...]:
    """Every distribution installed in ``image_tag``'s virtual environment, as uv reports it.

    The image's own account of what ended up inside it, and the one thing that makes
    ADR-0021's remaining limit *checkable*. ``--exclude-newer`` filters the index by upload
    date; it cannot restore a release PyPI no longer serves. That drift is monotone - the
    reachable set only ever loses members - so a rebuild can **fail** but cannot quietly
    resolve to something else and pass. "Cannot quietly" is a claim, and this is how it is
    audited: the closure recorded beside a run is comparable, line for line, with the closure
    of a rebuild months later.

    Asked of the built image rather than read off the build log, for the reason
    :func:`read_declared_extras` is asked of the image: a log is a rendering of what was
    requested, and the installed metadata is what arrived.

    Measured 2026-09-01 (uv 0.9.30, inside a task image): ``uv pip freeze --python`` prints one
    requirement per line, sorted, and spells the first phase's editable install as a
    ``-e file:///workspace`` line - a line with a space in it, which is why this splits on
    newlines rather than on whitespace the way :func:`read_declared_extras` can afford to.

    Args:
        image_tag: Any task image, first phase or widened.
        timeout_s: Wall-clock budget. Seconds of work: one container, one uv invocation.

    Returns:
        The requirement lines in uv's own order, trimmed and with blanks dropped. **Not parsed
        into names and versions.** This module refuses rather than repairs, and there is
        nothing to repair towards: ``-e file:///workspace`` carries no version, so any mapping
        would need a special case whose only purpose is to make the answer look uniform. Each
        line is trimmed because :func:`assay.host.run_command` decodes bytes without
        universal-newline translation, so a carriage return off a Windows pipe would
        otherwise poison a comparison between two closures that are in fact identical.

    Raises:
        CommandFailedError: if the container could not be run - a tag the daemon does not hold
            included. An image that cannot be asked must not answer "nothing is installed",
            which is exactly what an empty tuple would say.
        CommandTimeoutError: if the budget expired.
    """
    found = run_command(
        # `--network none` for the reason the extras probe has it: a probe that could reach an
        # index is a probe that could change the environment it is describing.
        (
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            image_tag,
            "uv",
            "pip",
            "freeze",
            # The venv is at `/opt/venv` and nothing activates it, so uv is told which
            # environment the question is about rather than left to discover one.
            "--python",
            VENV_PYTHON,
        ),
        cwd=Path.cwd(),
        timeout_s=timeout_s,
        env=minimal_env(),
        check=True,
    )
    trimmed = (line.strip() for line in found.stdout.splitlines())
    return tuple(line for line in trimmed if line)


def build_task_image(
    *, context: Path, base_commit: str, exclude_newer: str | None, timeout_s: int
) -> str:
    """Build the task image for ``base_commit`` out of ``context``, and return its tag.

    Two phases (ADR-0023). The first installs the project's runtime set and pytest; the image is
    then asked which extras the project declares, and if any of them is allowlisted a second
    phase installs those over the first. **A project declaring none gets the first phase's tag,
    byte for byte** - which is every image this repository's own suite builds, so nothing
    already in the daemon's cache changes meaning.

    Cheap to call twice: both tags are content addresses, so a second call for the same commit
    and the same recipes re-tags the layers BuildKit already holds instead of installing
    anything again.

    Args:
        context: A checkout of ``base_commit`` - a :meth:`assay.host.GitHistory.worktree` in
            practice - and **proved to be one before anything is built** (ADR-0027), because the
            tag says so and nothing downstream can check. **Read only.** Nothing is written into
            it, because the trial that follows is scored by diffing this tree and a file Assay
            left behind would score as the tool's work.
        base_commit: The commit ``context`` holds, which goes into both tags.
        exclude_newer: The canonical UTC instant to resolve this commit's dependencies as of
            (``YYYY-MM-DDTHH:MM:SSZ``), or ``None``
            for today's index. Passed rather than derived here because the one git question
            ``assay.sandbox`` asks is the precondition above - what commit a directory holds -
            and not what a commit's history says: deriving the cutoff needs a
            :class:`assay.host.GitHistory` bound to the clone, which the caller has and this
            module does not, so the caller reads
            :meth:`~assay.host.GitHistory.committed_at` off it (ADR-0021).
        timeout_s: Wall-clock budget for **the whole build**, both phases and the question
            between them, not for each in turn. A cold build pulls a base image and installs the
            repository's whole dependency tree, so this is minutes rather than seconds.

    Returns:
        The tag the image now carries. Two cutoffs give two tags, and so do two extras sets,
        because both are in a recipe and every recipe is in an address.

    Raises:
        SandboxError: if ``context`` is not a clean checkout of ``base_commit``, or if
            ``exclude_newer`` is not a canonical UTC instant. Both are refused before any image
            is built.
        CommandFailedError: if ``docker build`` exited non-zero, or if the built image could not
            be asked what it declares. Deliberately not wrapped: the message already quotes the
            tail of the command's stderr, which is the only thing a caller could usefully print,
            and nothing in M2 branches on which phase failed.
        CommandTimeoutError: if the budget expired.
    """
    deadline = monotonic() + timeout_s
    _checked_context(context, base_commit, timeout_s=_remaining(deadline))
    base = render_base_dockerfile(exclude_newer=exclude_newer)
    tag = image_tag(base_image=_BASE_IMAGE, dockerfile=base, base_commit=base_commit)
    _docker_build(dockerfile=base, tag=tag, context=context, timeout_s=_remaining(deadline))

    extras = _select_extras(read_declared_extras(tag, timeout_s=_remaining(deadline)))
    if not extras:
        return tag

    recipe = render_extras_dockerfile(base_tag=tag, extras=extras, exclude_newer=exclude_newer)
    widened = image_tag(base_image=tag, dockerfile=recipe, base_commit=base_commit)
    # An empty context, because the second phase copies nothing: `/workspace` is already inside
    # `tag`. Sending the repository again would upload a tree the recipe cannot read.
    with tempfile.TemporaryDirectory(prefix="assay-extras-") as nothing:
        _docker_build(
            dockerfile=recipe,
            tag=widened,
            context=Path(nothing),
            timeout_s=_remaining(deadline),
        )
    return widened


def _checked_context(context: Path, base_commit: str, *, timeout_s: int) -> None:
    """Refuse a context the address would then misdescribe (ADR-0027).

    The one question this package asks git, and it asks it through the host seam rather than by
    running git itself. It is here because :func:`image_tag` puts ``base_commit`` into a tag and
    nothing after this point can tell whether the tree it was computed over was that commit: a
    caller who patched the workspace and then built would get an image whose address claims one
    thing and whose content is another, and every later step would read the address.

    Refusal rather than repair, the posture :func:`_checked_cutoff` takes towards a value on its
    way into an address. There is nothing to repair towards - Assay does not own this tree, and
    a harness that reset somebody's checkout to make an address true would be corrupting the
    measurement rather than taking it.

    Raises:
        SandboxError: if ``context`` is not a clean checkout of ``base_commit``, or if git could
            not answer at all - a directory that is not a checkout included, with the
            :class:`assay.host.GitError` chained. A tree git has never heard of has no head for
            the tag to name, so it is the same refusal rather than a different one.
    """
    try:
        state = checkout_state(context, timeout_s=timeout_s)
    except GitError as unanswerable:
        raise SandboxError(
            f"cannot confirm {str(context)!r} is a checkout of {base_commit}: {unanswerable}"
        ) from unanswerable

    divergence = _context_divergence(state, base_commit)
    if divergence:
        raise SandboxError(
            f"{str(context)!r} is not a clean checkout of {base_commit}, so an image tagged "
            f"for that commit would not hold it: {divergence!r}"
        )


def _context_divergence(state: CheckoutState, base_commit: str) -> tuple[str, ...]:
    """Pure. The reasons ``state`` is not a clean checkout of ``base_commit``; empty means it is.

    Porcelain lines whose path is excluded from the build context are not divergence. That is
    the half of this function that has to stay bound to :data:`_DOCKERIGNORE`, which is why both
    read :data:`_CONTEXT_EXCLUSIONS`: a ``.venv`` an M1 provisioning run left behind never
    reaches the image, so refusing to build over it would be a false refusal, and a harness that
    cannot mine the trees it is pointed at is no better than one that mines them wrongly.

    The head is compared verbatim rather than case-folded or abbreviated, because the string
    compared is the string :func:`image_tag` hashes: two spellings of one commit are already two
    addresses, and accepting a second spelling here would only decide which of them lies.

    The reasons are returned rather than a bool so the refusal can name the diverging path. They
    are the porcelain entries as git wrote them - diagnostic text, never a path this module then
    resolves, which is what makes :func:`assay.host.checkout_state`'s newline splitting safe
    enough to keep (ADR-0027 records the residual).
    """
    reasons = [] if state.head == base_commit else [f"HEAD is {state.head}, not {base_commit}"]
    reasons.extend(
        entry
        for entry in state.changed
        if entry[_PORCELAIN_PATH_START:].partition("/")[0] not in _CONTEXT_EXCLUSIONS
    )
    return tuple(reasons)


def _docker_build(*, dockerfile: str, tag: str, context: Path, timeout_s: int) -> None:
    """One ``docker build``, with its recipe written outside the context it is handed."""
    with tempfile.TemporaryDirectory(prefix="assay-image-") as scratch:
        recipe = Path(scratch) / _DOCKERFILE_NAME
        recipe.write_text(dockerfile, encoding="utf-8", newline="\n")
        recipe.with_suffix(".dockerignore").write_text(
            _DOCKERIGNORE, encoding="utf-8", newline="\n"
        )
        run_command(
            ("docker", "build", "--tag", tag, "--file", str(recipe), str(context)),
            # The scratch directory, not the context: the docker client writes nothing into its
            # working directory, but the one tree that must stay untouched is not the place to
            # find that out.
            cwd=Path(scratch),
            timeout_s=timeout_s,
            env=minimal_env(),
            check=True,
        )


def _select_extras(declared: Iterable[str]) -> tuple[str, ...]:
    """Which of the extras a project declares are the ones its tests are installed from.

    Pure, and the whole of ADR-0023's policy: a name in :data:`TEST_EXTRA_NAMES` is installed
    and anything else is dropped, silently and by design - a repository's ``docs`` extra is not
    a signal about its tests, and installing it would widen the resolver surface that ADR-0018
    measured going wrong.

    The result is always in :data:`TEST_EXTRA_NAMES` order rather than in the order the extras
    arrived, because it is rendered into a recipe that is hashed. Measured 2026-09-01: a project
    declaring ``test`` before ``docs`` in ``pyproject.toml`` has them the other way round in the
    installed ``METADATA``, so the arrival order belongs to a packaging backend and not to the
    commit. Names are compared case-folded for the same reason PEP 685 normalises them, and the
    match - never the declaration - is what gets rendered, so the recipe can only ever hold one
    of four known strings.
    """
    lowered = {name.lower() for name in declared}
    return tuple(name for name in TEST_EXTRA_NAMES if name in lowered)


def _checked_extras(extras: Sequence[str]) -> str:
    """The extras clause for a ``RUN`` line, or a refusal - never a repair.

    :func:`_checked_cutoff`'s posture applied to the other value that reaches this module's
    shell line and its content address. Two things are refused and they fail differently:

    An extra outside :data:`TEST_EXTRA_NAMES` is refused because the clause is interpolated into
    a shell line, and because a policy enforced only by the one caller that happens to call
    :func:`_select_extras` first is a convention rather than a constraint.

    An *empty* clause is refused because ``-e '/workspace[]'`` installs precisely what the first
    phase already installed, under a different address. One environment with two addresses is
    the failure the content address exists to prevent, so a second phase with nothing to install
    is not rendered at all.
    """
    unknown = tuple(extra for extra in extras if extra not in TEST_EXTRA_NAMES)
    if unknown:
        raise SandboxError(f"not allowlisted test extras: {unknown!r}")
    if not extras:
        raise SandboxError("no extras to install: the second phase exists only to install some")
    return ",".join(extras)


def _remaining(deadline: float) -> int:
    """Seconds left before ``deadline``, never below one - a zero budget kills on the spot.

    A second copy of :func:`assay.sandbox.runner._remaining` rather than a shared helper, for
    the reason ``_checked_selector`` is one: three lines that read the same clock, and the
    module they sit in imports this one, so sharing them would close a cycle.
    """
    return max(1, int(deadline - monotonic()))


def _checked_cutoff(value: str) -> str:
    """Refuse a cutoff that is not *the* canonical instant, before it becomes a build argument.

    In the spirit of ``host/git.py``'s ``_checked_revision``: the value arrives from outside
    this module, it is interpolated into a shell line inside the image build, and a cutoff that
    is anything other than an instant is either an injection or a caller error. Both are loud
    here.

    A validator, never a canonicaliser (ADR-0022). The producer is
    :meth:`assay.host.GitHistory.committed_at`, which is where an instant git spelled two ways
    becomes one string; narrowing the check here is what makes the second spelling
    *unconstructible* at the boundary that computes the address, rather than merely absent from
    what the in-repo caller happens to pass.

    Rejection is total rather than sanitising. A cutoff Assay silently repaired would resolve
    the dependency set of some *other* era, and an image addressed by a recipe nobody chose is
    exactly the failure the content address exists to prevent.
    """
    if not _CUTOFF_PATTERN.match(value):
        raise SandboxError(f"not a canonical RFC3339 UTC instant: {value!r}")
    return value


def _checked_tool_version(value: str) -> str:
    """Refuse a tool version that is not one, before it becomes an install argument.

    :func:`_checked_cutoff`'s posture applied to the other value that reaches a ``RUN`` line
    from outside this module. npm's version syntax includes ranges and tags - ``^2``,
    ``latest``, ``next`` - and every one of them would put an address on an image whose contents
    the address cannot describe, which is the failure a content address exists to prevent. A
    version is a version or it is refused; ``None`` is how "today's registry" is said, and it is
    said in the recipe rather than smuggled through this check.
    """
    if not _TOOL_VERSION_PATTERN.match(value):
        raise SandboxError(f"not a plain release version: {value!r}")
    return value
