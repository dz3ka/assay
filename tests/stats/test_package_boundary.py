"""The leaf rule, held by a grep instead of by three docstrings and a habit.

``assay.stats`` imports nothing from Assay - not ``core``, not ``report``, not ``results``. The
package docstring says so, :mod:`assay.stats.wilson`, :mod:`assay.stats.bootstrap` and
:mod:`assay.stats.mcnemar` each repeat it about themselves, and until this file existed all four
were statements of intent. The rule is what keeps a statistic from encoding a policy: a function
that could reach a :class:`ResultSet` would eventually be handed one and left to decide what its
own numerator was, and deciding what counts as a success is ``assay.report.summarise``'s job,
which is the only caller that knows.

The way it goes is not a rewrite. It is one plausible-looking line. ``mcnemar_exact_p`` takes two
task counts and ``summarise`` has the tasks, so ``from assay.report.model import TaskLine`` -
to take the lines directly and count the discordant ones here - reads like deleting an
indirection rather than like inverting a layer. It would type-check, lint, and pass every other
test in this suite, and ``stats`` would have acquired an opinion about what a task is. The same
shortcut is available to the bootstrap, whose one argument is a sequence of per-task rates
somebody has to build.

Two things narrow what this file has to recognise. Imports *within* ``assay.stats`` are not
escapes - ``__init__.py`` re-exports the three submodules that way, and that is the package
being a package - so the check is for a name under ``assay`` that is not under ``assay.stats``.
And only the absolute forms are read, because ``pyproject.toml`` bans relative imports repo-wide
(``ban-relative-imports = "all"``), so a relative import that reached out of the package could
not land in the first place. Naming the root package alone counts as an escape too: ``from assay
import core`` and ``import assay`` both bind ``assay/__init__.py``, by a different route.

Read from the import statements rather than from the file's text, for the reason
``tests/host/test_process.py`` gives about its own fence: a module that explains the rule in its
docstring is obeying it, not breaking it.
"""

import ast
from pathlib import Path

STATS_ROOT = Path(__file__).parent.parent.parent / "src" / "assay" / "stats"

# The package everything here is allowed to reach, and the one it is not allowed to leave.
_LEAF_PACKAGE = "assay.stats"
_ROOT_PACKAGE = "assay"


def _escapes_the_leaf(module: str) -> bool:
    """Whether a dotted module name is part of Assay but outside :mod:`assay.stats`."""
    if module != _ROOT_PACKAGE and not module.startswith(f"{_ROOT_PACKAGE}."):
        return False
    return module != _LEAF_PACKAGE and not module.startswith(f"{_LEAF_PACKAGE}.")


def _assay_imports_outside_stats(path: Path) -> list[str]:
    """Every name outside ``assay.stats`` this module imports from Assay."""
    reached: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        # `import assay.report` and `import assay.report.model`, under any alias.
        if isinstance(node, ast.Import):
            reached.update(alias.name for alias in node.names if _escapes_the_leaf(alias.name))
        # `from assay.report.model import TaskLine`, and `from assay import report`, which
        # names the root package and so escapes whatever it goes on to bind.
        if isinstance(node, ast.ImportFrom) and _escapes_the_leaf(node.module or ""):
            reached.add(node.module or "")
    return sorted(reached)


def test_no_module_in_the_stats_package_imports_the_rest_of_assay() -> None:
    offenders = [
        f"{path.relative_to(STATS_ROOT).as_posix()} imports {module}"
        for path in sorted(STATS_ROOT.rglob("*.py"))
        for module in _assay_imports_outside_stats(path)
    ]

    assert offenders == []
