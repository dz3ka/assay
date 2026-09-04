"""The report schema, the winner rule, and the prose the renderers print for it.

Import these names from ``assay.report`` rather than from the submodules; the split between
``model`` (schema and the comparison rule), ``redact`` (the boundary) and ``render`` (the three
output formats) is an implementation detail, this surface is not.

A report is redacted by default (SPEC §5.4): :func:`redact` is total and has no opt-out, so
nothing a renderer receives carries a path, an identifier or a commit subject from the
repository under evaluation.

:func:`decide_verdict` is the only place in Assay that names a winner. When two pass^n
intervals overlap it names none, and no renderer may re-derive one from the point estimates
(SPEC §4, KICKOFF item 6). A comparison also carries a :class:`PairedTest` - the exact McNemar
p over the tasks two tools were both given - and that p never moves the ranking either: it is
printed beside the verdict by :func:`format_paired`, with the sentence that says so
(ADR-0044). Neither does cost: a report carries one :class:`ToolCost` per tool, priced against
whatever :class:`PriceTable` the reader supplied at report time, and the cheaper tool has won
nothing by being cheaper (ADR-0046).
"""

from assay.report.model import (
    Comparison,
    CostBasis,
    CostOutOfRangeError,
    Interval,
    PairedTest,
    PriceTable,
    Redacted,
    Report,
    TaskLine,
    ToolCost,
    ToolPrice,
    ToolSummary,
    Verdict,
    VerdictReason,
    build_report,
    decide_verdict,
    format_basis,
    format_paired,
    format_verdict,
    overlaps,
    summarise,
)
from assay.report.redact import RedactionPolicy, hash_token, redact
from assay.report.render import render_html, render_json, render_text

__all__ = [
    "Comparison",
    "CostBasis",
    "CostOutOfRangeError",
    "Interval",
    "PairedTest",
    "PriceTable",
    "Redacted",
    "RedactionPolicy",
    "Report",
    "TaskLine",
    "ToolCost",
    "ToolPrice",
    "ToolSummary",
    "Verdict",
    "VerdictReason",
    "build_report",
    "decide_verdict",
    "format_basis",
    "format_paired",
    "format_verdict",
    "hash_token",
    "overlaps",
    "redact",
    "render_html",
    "render_json",
    "render_text",
    "summarise",
]
