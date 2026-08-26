"""The command surface: ``mine``, ``validate``, ``run``, ``report`` (SPEC §6).

Import these names from ``assay.cli`` rather than from the submodule; ``main`` is the console
script's entry point (``assay = "assay.cli.main:main"``), and that path is a packaging detail
of one file rather than the surface other code should reach for.

Only ``report`` is built in M0. The other three exist so the surface is honest about its own
schedule - see :mod:`assay.cli.main`.
"""

from assay.cli.main import build_parser, main, run_report

__all__ = [
    "build_parser",
    "main",
    "run_report",
]
