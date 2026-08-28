"""The one-way dependency this package's whole testability rests on: ``mine`` never sees ``host``.

Four docstrings assert it - ``assay.mine`` itself, ``assay.mine.protocols``,
``assay.mine.pipeline`` and ``assay.cli.main`` - and until this file existed, nothing held it.
The rule is what lets every decision in ``mine`` be exercised on values alone (CLAUDE.md: mining
is a pure function over explicit inputs, and git, uv and pytest live behind adapters), and the
way it goes is not a rewrite but a shortcut: ``pipeline`` needs a :class:`TestRunner` and
``assay.host`` has one, so ``from assay.host import provision_venv`` looks like deleting an
indirection rather than like inverting a layer. It type-checks, it lints, and every other test
in this suite still passes - which is precisely why the boundary has to be a grep rather than a
habit. The bridge is a closure the CLI writes and nothing else may (``assay.cli.main``'s
``host_runner_for``), because the CLI is the only module allowed to know both packages.

Read from the import statements rather than from the file's text, for the reason
``tests/host/test_process.py`` gives about its own fence: a module that explains the rule in its
docstring is obeying it, not breaking it. The forms recognised are the absolute ones, which is
every import in ``src/assay/mine`` today; the package spells its own siblings ``assay.mine.gate``
rather than ``.gate``, so a relative import here would be a new convention rather than a way the
rule quietly lapses.
"""

import ast
from pathlib import Path

MINE_ROOT = Path(__file__).parent.parent.parent / "src" / "assay" / "mine"

# The package that must stay unreachable from here, and the prefix every module in it shares.
_HOST_PACKAGE = "assay.host"
_HOST_PARENT, _HOST_NAME = _HOST_PACKAGE.rsplit(".", 1)


def _reaches_host(module: str) -> bool:
    """Whether a dotted module name is ``assay.host`` or something inside it."""
    return module == _HOST_PACKAGE or module.startswith(f"{_HOST_PACKAGE}.")


def _imports_host(path: Path) -> bool:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        # `import assay.host` and `import assay.host.venv`, under any alias.
        if isinstance(node, ast.Import) and any(_reaches_host(alias.name) for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            # `from assay.host import provision_venv` and `from assay.host.venv import ...`.
            if _reaches_host(node.module or ""):
                return True
            # `from assay import host`, which binds the same module by a different route.
            if node.module == _HOST_PARENT and any(
                alias.name == _HOST_NAME for alias in node.names
            ):
                return True
    return False


def test_no_module_in_the_mine_package_imports_the_host_package() -> None:
    offenders = [
        path.relative_to(MINE_ROOT).as_posix()
        for path in sorted(MINE_ROOT.rglob("*.py"))
        if _imports_host(path)
    ]

    assert offenders == []
