"""The three ways a report is written out: canonical JSON, a console report, a single page.

A renderer is a pure function from a :class:`~assay.report.Report` to a string. It formats;
it does not decide. In particular it never compares two point estimates: the winner - or the
refusal to name one - arrives in a :class:`~assay.report.Verdict` and is printed through
:func:`~assay.report.format_verdict`, so all three formats state one measurement one way
(SPEC §4, KICKOFF item 6). Nor does any of them manufacture an interval: bands arrive inside a
:class:`~assay.report.ToolSummary` already, and ``stub_interval`` is deliberately not exported.

Every M0 interval is invented, so every rendered report says so. The renderers read
``Report.intervals_are_placeholders`` and print :data:`~assay.report.STUB_INTERVAL_NOTICE`
verbatim when it is true - never re-wrapped, truncated or paraphrased, and never as a key in
the JSON document, where prose would become a compatibility promise. When M4 flips the flag the
notice disappears from all three formats without a renderer changing. A harness that produced a
confident number nobody should trust would be worse than no harness (CLAUDE.md), and this
paragraph of text is the difference.

``tasks`` is a trial log, not a task list: :func:`~assay.report.build_report` emits one line per
recorded *result*, so a task appears once per tool per trial. All three formats present it that
way, and each says so next to the count - collapsing the repeats would be the M4 aggregation
decision (SPEC §7) taken silently, in the presentation layer, by whoever laid out a table.

Dependency direction (KICKOFF item 7): this is the last link. Renderers depend on the report
schema and on nothing further up - not on ``assay.results``, not on ``assay.suite``. Whatever a
report does not carry, a renderer cannot show.

Pure: string building only. No I/O, no clock, no network - a renderer returns the document and
its caller decides where it goes.
"""

import html
import json

from assay.report.model import (
    STUB_INTERVAL_NOTICE,
    Comparison,
    Interval,
    Report,
    TaskLine,
    ToolSummary,
    format_verdict,
)

# Indentation for the canonical document. Pretty-printed rather than compact: a report is read
# and diffed by people, and it is explicitly not content-addressed (ADR-0008), so no hash
# depends on its byte layout.
JSON_INDENT = 2

# Decimal places on a printed proportion. Three keeps 1/3 of 12 trials distinguishable from 1/4
# without implying a precision the trial counts in M0 cannot support.
_PROPORTION_DIGITS = 3

# Said next to every trial count, in all three formats. The report is a log of trials and a
# reader who assumed it was a list of tasks would divide every count by the trial depth.
_TRIAL_LOG_CAPTION = "one line per trial, so a task appears once per tool per trial"


def _proportion(value: float) -> str:
    """Format a proportion the same way in every format, so two reports can be compared."""
    return f"{value:.{_PROPORTION_DIGITS}f}"


def _interval(interval: Interval) -> str:
    """Format a closed interval as its two endpoints - the band, never a +/- half-width."""
    return f"[{_proportion(interval.low)}, {_proportion(interval.high)}]"


def render_json(report: Report) -> str:
    """Render the canonical document: the report, serialised, and nothing else (SPEC §6).

    The string round-trips - ``Report.model_validate(json.loads(out))`` returns an equal
    report - because this format is API from M0 (CLAUDE.md) and a consumer must be able to read
    back what Assay wrote.

    The placeholder admission travels as ``"intervals_are_placeholders": true``. The prose is
    not here and must not be added: :data:`~assay.report.STUB_INTERVAL_NOTICE` is worded for a
    human, and a key holding it would freeze one wording as a compatibility promise. A caller
    printing this document for a person is the one that shows the notice alongside it.

    No trailing newline: this is the document exactly, and whoever writes it to a file or a
    terminal adds the separator that medium wants.
    """
    return json.dumps(report.model_dump(mode="json"), indent=JSON_INDENT)


def _text_tool_line(summary: ToolSummary, tool_width: int) -> str:
    """One tool's row: the two scores, the interval that qualifies pass^n, and the sample."""
    return (
        f"  {summary.tool:<{tool_width}}  trials={summary.trials}"
        f"  pass@1={_proportion(summary.pass_at_1)}"
        f"  pass^n={_proportion(summary.pass_caret_n)}"
        f"  pass^n interval={_interval(summary.pass_caret_n_interval)}"
    )


def _text_comparison_line(comparison: Comparison) -> str:
    """One pairing and the verdict's own sentence - this module never writes another."""
    return f"  {comparison.tool_a} vs {comparison.tool_b}: {format_verdict(comparison.verdict)}"


def _text_trial_line(line: TaskLine, task_width: int) -> str:
    """One recorded trial. Provenance is appended only when the report actually carries it.

    An absent ``repo_path`` is absent information rather than a redacted one, and printing a
    placeholder for it would read as "we are not showing you this" (a M0 result set records no
    provenance at all; M1's miner supplies it).
    """
    parts = [f"  {line.task_id:<{task_width}}  {line.outcome.value}"]
    if line.repo_path is not None:
        parts.append(f"  repo={line.repo_path}")
    if line.commit_subject is not None:
        parts.append(f"  subject={line.commit_subject}")
    return "".join(parts)


def render_text(report: Report) -> str:
    """Render the console report: the notice, then the numbers, then the trial log.

    The notice comes first, as one unwrapped paragraph, before a single number - a reader who
    stops after the first paragraph has still been told the intervals were invented. Wrapping
    it here would put a line width between the text and the constant the tests pin.
    """
    tool_width = max((len(s.tool) for s in report.tools), default=0)
    task_width = max((len(t.task_id) for t in report.tasks), default=0)

    tools = [_text_tool_line(s, tool_width) for s in report.tools] or ["  (no tools recorded)"]
    comparisons = [_text_comparison_line(c) for c in report.comparisons] or [
        "  (none - a comparison needs two tools)"
    ]
    trials = [_text_trial_line(t, task_width) for t in report.tasks] or ["  (no trials recorded)"]

    sections = [
        f"Assay report\nSuite: {report.suite_hash}",
        "\n".join(["Tools", *tools]),
        "\n".join(["Comparisons", *comparisons]),
        "\n".join([f"Trials ({len(report.tasks)} recorded; {_TRIAL_LOG_CAPTION})", *trials]),
    ]
    body = "\n\n".join(sections) + "\n"
    if report.intervals_are_placeholders:
        return f"{STUB_INTERVAL_NOTICE}\n\n{body}"
    return body


# Everything the page needs to be legible, inline. An external stylesheet would make opening a
# report a network request, and a report is read on machines that must not make one.
_HTML_STYLE = """\
body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 60rem; }
table { border-collapse: collapse; margin-bottom: 1.5rem; }
th, td { border: 1px solid #999; padding: 0.25rem 0.75rem; text-align: left; }
caption { text-align: left; font-style: italic; padding-bottom: 0.25rem; }
.placeholder-notice { border: 2px solid #a00; color: #a00; padding: 0.75rem; font-weight: bold; }
.absent { color: #777; }"""

# Refuses every remote fetch the document could otherwise be made to perform, so the page keeps
# its offline promise even after someone edits it. Inline styles are the one exception, because
# the stylesheet above has to travel inside the file.
_HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'"


def _escape(text: str) -> str:
    """Escape one string for HTML. Every piece of text on the page goes through here.

    Including the placeholder notice: a constant that skipped escaping would be the seam where
    a later reworded notice broke the markup, and there is no text this page trusts.
    """
    return html.escape(text, quote=True)


def _html_cell(value: str | None) -> str:
    """One table cell, with an absent value shown as absent rather than as empty."""
    if value is None:
        return '<td class="absent">-</td>'
    return f"<td>{_escape(value)}</td>"


def _html_tools_table(report: Report) -> list[str]:
    """The per-tool scores. Each pass^n is printed next to the band that qualifies it."""
    if not report.tools:
        return ["<p>No tools were recorded.</p>"]
    rows = [
        "<tr>"
        f"<td>{_escape(s.tool)}</td>"
        f"<td>{s.trials}</td>"
        f"<td>{_proportion(s.pass_at_1)}</td>"
        f"<td>{_proportion(s.pass_caret_n)}</td>"
        f"<td>{_escape(_interval(s.pass_caret_n_interval))}</td>"
        "</tr>"
        for s in report.tools
    ]
    return [
        "<table>",
        "<thead><tr><th>Tool</th><th>Trials</th><th>pass@1</th>"
        "<th>pass^n</th><th>pass^n interval</th></tr></thead>",
        "<tbody>",
        *rows,
        "</tbody>",
        "</table>",
    ]


def _html_comparisons(report: Report) -> list[str]:
    """One paragraph per pairing, each carrying the verdict's own sentence and nothing more."""
    if not report.comparisons:
        return ["<p>No comparison was possible: a comparison needs two tools.</p>"]
    return [
        f'<p class="comparison">{_escape(c.tool_a)} vs {_escape(c.tool_b)}: '
        f"{_escape(format_verdict(c.verdict))}</p>"
        for c in report.comparisons
    ]


def _html_trials_table(report: Report) -> list[str]:
    """The trial log: one row per recorded result, captioned so the count cannot mislead."""
    if not report.tasks:
        return ["<p>No trials were recorded.</p>"]
    rows = [
        '<tr class="trial">'
        f"<td>{_escape(line.task_id)}</td>"
        f"<td>{_escape(line.outcome.value)}</td>"
        f"{_html_cell(line.repo_path)}"
        f"{_html_cell(line.commit_subject)}"
        "</tr>"
        for line in report.tasks
    ]
    return [
        "<table>",
        f"<caption>{len(report.tasks)} recorded; {_TRIAL_LOG_CAPTION}</caption>",
        "<thead><tr><th>Task</th><th>Outcome</th><th>Repo path</th>"
        "<th>Commit subject</th></tr></thead>",
        "<tbody>",
        *rows,
        "</tbody>",
        "</table>",
    ]


def render_html(report: Report) -> str:
    """Render the single-page report: self-contained, offline, and honest above the fold.

    The page fetches nothing. No stylesheet, no font, no image, and a Content-Security-Policy
    that refuses the attempt: a report describes a private repository, and opening one must not
    tell anybody that it was opened.

    The placeholder notice is the first element in the body, ahead of every number and table,
    for the same reason it opens the text report.
    """
    notice = (
        [f'<p class="placeholder-notice">{_escape(STUB_INTERVAL_NOTICE)}</p>']
        if report.intervals_are_placeholders
        else []
    )
    lines = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f'<meta http-equiv="Content-Security-Policy" content="{_HTML_CSP}">',
        "<title>Assay report</title>",
        "<style>",
        _HTML_STYLE,
        "</style>",
        "</head>",
        "<body>",
        *notice,
        "<h1>Assay report</h1>",
        f"<p>Suite: <code>{_escape(report.suite_hash)}</code></p>",
        "<h2>Tools</h2>",
        *_html_tools_table(report),
        "<h2>Comparisons</h2>",
        *_html_comparisons(report),
        "<h2>Trials</h2>",
        *_html_trials_table(report),
        "</body>",
        "</html>",
    ]
    return "\n".join(lines) + "\n"
