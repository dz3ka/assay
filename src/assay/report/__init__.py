"""The report schema, the winner rule, and the prose the renderers print for it.

Import these names from ``assay.report`` rather than from the submodules; the split between
``model`` (schema and the comparison rule), ``redact`` (the boundary) and ``render`` (the three
output formats) is an implementation detail, this surface is not.

A report is redacted by default (SPEC §5.4): :func:`redact` is total and has no opt-out, so
nothing a renderer receives carries a path, an identifier or a commit subject from the
repository under evaluation.

:func:`decide_verdict` is the only place in Assay that names a winner. When two pass^n
intervals overlap it names none, and no renderer may re-derive one from the point estimates
(SPEC §4, KICKOFF item 6).
"""

from assay.report.model import (
    STUB_INTERVAL_NOTICE,
    Comparison,
    Interval,
    Redacted,
    Report,
    TaskLine,
    ToolSummary,
    Verdict,
    VerdictReason,
    build_report,
    decide_verdict,
    format_verdict,
    overlaps,
    summarise,
)
from assay.report.redact import RedactionPolicy, hash_token, redact
from assay.report.render import render_html, render_json, render_text

__all__ = [
    "STUB_INTERVAL_NOTICE",
    "Comparison",
    "Interval",
    "Redacted",
    "RedactionPolicy",
    "Report",
    "TaskLine",
    "ToolSummary",
    "Verdict",
    "VerdictReason",
    "build_report",
    "decide_verdict",
    "format_verdict",
    "hash_token",
    "overlaps",
    "redact",
    "render_html",
    "render_json",
    "render_text",
    "summarise",
]
