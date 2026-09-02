"""The other end of the one-way rule: ``score`` never sees ``host``, and never sees ``sandbox``.

The scorer runs the tool under evaluation and measures what it left behind, so it is the module
with the most reason to reach for a runner - and the least right to. ``assay.score``'s own
docstring claims it drives the ``History``, ``Adapter`` and ``RunnerFactory`` seams "never
learning what implements them", :mod:`assay.score.trial` says the same in longer form, and until
this file existed nothing held either. What the rule buys is that a trial can be exercised on
fakes: every branch of ``run_trial`` - the adapter that errors, the patch that will not apply,
the diff that changes nothing - is reachable without git, docker or a subprocess, which is the
only way the harness's own verdict is testable at all (CLAUDE.md: scoring is a pure function
over explicit inputs, and containers live behind adapters).

Two forbidden packages rather than the miner's one, because a trial has two implementations to
be tempted by and the temptation reads differently in each. ``assay.host`` is the shortcut a
test would take - ``PytestHostRunner`` is right there, and importing it looks like deleting an
indirection rather than like inverting a layer. ``assay.sandbox`` is the shortcut M2 makes
plausible, because a trial *is* meant to run inside a container: ``from assay.sandbox import
sandbox_runner_for`` inside :mod:`assay.score.trial` would type-check, lint and pass every other
test in this suite, and would quietly make the scorer untestable without a docker daemon. Both
bridges are closures the CLI writes and nothing else may (``assay.cli.main``'s
``host_runner_for``, passed to ``run_trial`` as ``runner_for``), because the CLI is the only
module allowed to know both sides.

Read from the import statements rather than from the file's text, for the reason
``tests/host/test_process.py`` gives about its own fence: a module that explains the rule in its
docstring is obeying it, not breaking it. The forms recognised are the absolute ones, which is
every import in ``src/assay/score`` today; the package spells its own sibling
``assay.score.executable`` rather than ``.executable``, so a relative import here would be a new
convention rather than a way the rule quietly lapses.
"""

import ast
from pathlib import Path

SCORE_ROOT = Path(__file__).parent.parent.parent / "src" / "assay" / "score"

# The packages that must stay unreachable from here. Both are named rather than one being
# derived from the other: they are two separate claims about this package, and a failure has to
# say which of them broke.
_FORBIDDEN_PACKAGES = ("assay.host", "assay.sandbox")


def _reaches(module: str, package: str) -> bool:
    """Whether a dotted module name is ``package`` itself or something inside it."""
    return module == package or module.startswith(f"{package}.")


def _forbidden_imports(path: Path) -> list[str]:
    """Every forbidden package this module imports, by whichever route it reaches it."""
    reached: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        for package in _FORBIDDEN_PACKAGES:
            parent, name = package.rsplit(".", 1)
            # `import assay.sandbox` and `import assay.sandbox.runner`, under any alias.
            if isinstance(node, ast.Import) and any(
                _reaches(alias.name, package) for alias in node.names
            ):
                reached.add(package)
            if isinstance(node, ast.ImportFrom):
                # `from assay.host import PytestHostRunner` and `from assay.host.venv import ...`.
                if _reaches(node.module or "", package):
                    reached.add(package)
                # `from assay import sandbox`, which binds the same module by a different route.
                if node.module == parent and any(alias.name == name for alias in node.names):
                    reached.add(package)
    return sorted(reached)


def test_no_module_in_the_score_package_imports_the_host_or_sandbox_packages() -> None:
    offenders = [
        f"{path.relative_to(SCORE_ROOT).as_posix()} imports {package}"
        for path in sorted(SCORE_ROOT.rglob("*.py"))
        for package in _forbidden_imports(path)
    ]

    assert offenders == []
