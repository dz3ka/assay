"""The three ways a report is written out: canonical JSON, a console report, a single page.

A renderer is a pure function from a :class:`~assay.report.Report` to a string. It formats;
it does not decide. In particular it never compares two point estimates: the winner - or the
refusal to name one - arrives in a :class:`~assay.report.Verdict` and is printed through
:func:`~assay.report.format_verdict`, so all three formats state one measurement one way
(SPEC §4, KICKOFF item 6). Nor does any of them manufacture an interval: bands arrive inside a
:class:`~assay.report.ToolSummary` already, computed by :mod:`assay.stats`.

Every report carries two bands, and both prose formats say which instrument produced each.
pass^n gets a Wilson interval and pass@1 a percentile bootstrap, because they are different
shapes of number (ADR-0035, ADR-0043) - and two bands printed side by side read as one
procedure applied twice unless the report says otherwise. The wording is
:data:`_INTERVAL_METHODS`; it names both methods and the bootstrap's resample count and seed,
and it stays out of the JSON document, where prose would become a compatibility promise.

The paired test is printed the same way and for the same reason. :func:`format_paired` supplies
one sentence to both prose formats; it reports the p and says in as many words that the p does
not rank the two tools, because a number published without its reading acquires the reader's
(ADR-0044). A harness that produced a confident number nobody should trust would be worse than
no harness (CLAUDE.md), and those two sentences are the difference.

Money is printed the same way and never leads. Every report carries a costs section, whether
or not anybody supplied a price, because a section that appeared only when it had dollars in it
would make its own absence a statement (ADR-0035). Each row states its :class:`CostBasis` in
prose through :func:`~assay.report.format_basis`, so a blank total says which of the four
things it means, and the rates the row priced with are printed beside it - a dollar figure a
reader cannot re-derive from the document is a claim rather than a measurement (SPEC 5.5).
Cost ranks nothing here either.

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
from decimal import Decimal

from assay.report.model import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    Comparison,
    Interval,
    Report,
    TaskLine,
    ToolCost,
    ToolSummary,
    format_basis,
    format_paired,
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

# Said next to the scores, in both prose formats. The two bands are produced by two different
# procedures on two different shapes of number, and a reader who assumed one procedure produced
# both would read the narrower band as the better-measured tool (ADR-0035, ADR-0043). The
# bootstrap's resample count and seed are named because a band nobody can reproduce is a claim
# rather than a measurement (SPEC §5.5), and they are interpolated from the constants that
# actually produced it, so the caption cannot drift from the arithmetic. Render-local: it is a
# caption about how a table is laid out, and a sentence inside the schema would freeze one
# wording as a compatibility promise.
_INTERVAL_METHODS = (
    "two bands by two methods, both 95%: pass^n is a Wilson score interval over tasks; pass@1 "
    "is a mean of per-task rates rather than a proportion, so its band is a seeded percentile "
    f"bootstrap over tasks ({BOOTSTRAP_RESAMPLES} resamples, seed {BOOTSTRAP_SEED})"
)


# Said next to the money, in both prose formats. Three things a reader would otherwise supply
# themselves: that Assay knows no prices and is quoting theirs back, that an errored trial's
# tokens are in the total, and that being cheaper is not a way of winning (CLAUDE.md ranks on
# executable signal alone). Render-local for the same reason as the caption above it.
_COST_METHOD = (
    "dollars are the prices supplied with this report, per million tokens, and Assay knows no "
    "others; a total covers every recorded trial, errored ones included; cost ranks nothing - "
    "the pass^n intervals decide that alone"
)

# What the costs section says instead of naming a source when no price was given. Stated rather
# than left blank: every row already carries its own reason, and the heading has to agree.
_NO_PRICES = "no prices were supplied"


def _price_provenance(report: Report) -> str:
    """Where a report's money came from, in the reader's own words or not at all."""
    if report.prices_source is None:
        return _NO_PRICES
    return f"prices as supplied: {report.prices_source}"


def _usd(amount: Decimal | None) -> str:
    """Format money the one way every format prints it, or show it absent.

    Six decimal places always, the scale the schema pins (ADR-0010): a total that dropped its
    trailing zeroes would print two spellings of one amount across two rows of one table.
    """
    if amount is None:
        return "-"
    return f"${amount:.6f}"


def _rates(cost: ToolCost) -> str:
    """The two rates a cost line priced with, so its dollars can be re-derived from the report.

    Both or neither: the schema keeps them that way, and the pair is printed as one field so a
    reader reads a price rather than two unrelated numbers.
    """
    if cost.input_usd_per_mtok is None or cost.output_usd_per_mtok is None:
        return "-"
    return f"{_usd(cost.input_usd_per_mtok)} in / {_usd(cost.output_usd_per_mtok)} out per MTok"


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

    No prose: both bands arrive here as numbers, without the caption naming the two methods
    (:data:`_INTERVAL_METHODS`) and without the paired test's sentence, because a key holding
    either would freeze one wording as a compatibility promise. A consumer reads which band is
    which off the schema, and the two formats written for a person carry the explanation.

    No trailing newline: this is the document exactly, and whoever writes it to a file or a
    terminal adds the separator that medium wants.
    """
    return json.dumps(report.model_dump(mode="json"), indent=JSON_INDENT)


def _text_tool_line(summary: ToolSummary, tool_width: int) -> str:
    """One tool's row: each score printed next to the band that qualifies it, and the sample."""
    return (
        f"  {summary.tool:<{tool_width}}  trials={summary.trials}"
        f"  pass@1={_proportion(summary.pass_at_1)}"
        f"  pass@1 interval={_interval(summary.pass_at_1_interval)}"
        f"  pass^n={_proportion(summary.pass_caret_n)}"
        f"  pass^n interval={_interval(summary.pass_caret_n_interval)}"
    )


def _text_comparison_lines(comparison: Comparison) -> list[str]:
    """One pairing: the verdict's own sentence, then the paired test's own sentence.

    Two lines rather than one, and in that order. The verdict is the ranking and the paired test
    is not, so the p is indented under the claim it does not make (ADR-0044). This module writes
    neither sentence itself.
    """
    return [
        f"  {comparison.tool_a} vs {comparison.tool_b}: {format_verdict(comparison.verdict)}",
        f"    {format_paired(comparison)}",
    ]


def _text_cost_lines(cost: ToolCost, tool_width: int) -> list[str]:
    """One tool's spend: the counts and the money, then the sentence for whatever is absent.

    Two lines, as a comparison gets two and for the same reason: the reason a number is not
    there is prose, and parenthesising it into a row a reader skims for figures is how it goes
    unread.
    """
    return [
        f"  {cost.tool:<{tool_width}}  input={cost.input_tokens}"
        f"  output={cost.output_tokens}  solved={cost.solved_tasks}"
        f"  rates={_rates(cost)}"
        f"  total={_usd(cost.total_usd)}"
        f"  per solved task={_usd(cost.usd_per_solved_task)}",
        f"    {format_basis(cost)}",
    ]


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
    """Render the console report: the numbers, then the trial log.

    Each section heading carries the caveat its table needs - what pass@1's missing band means
    under Tools, what a trial line counts under Trials - unwrapped, because wrapping would put
    a line width between the text and the constants the tests pin.
    """
    tool_width = max((len(s.tool) for s in report.tools), default=0)
    task_width = max((len(t.task_id) for t in report.tasks), default=0)

    tools = [_text_tool_line(s, tool_width) for s in report.tools] or ["  (no tools recorded)"]
    comparisons = [line for c in report.comparisons for line in _text_comparison_lines(c)] or [
        "  (none - a comparison needs two tools)"
    ]
    trials = [_text_trial_line(t, task_width) for t in report.tasks] or ["  (no trials recorded)"]
    costs = [line for c in report.costs for line in _text_cost_lines(c, tool_width)] or [
        "  (no tools recorded)"
    ]

    sections = [
        f"Assay report\nSuite: {report.suite_hash}",
        "\n".join([f"Tools ({_INTERVAL_METHODS})", *tools]),
        "\n".join(["Comparisons", *comparisons]),
        "\n".join([f"Costs ({_price_provenance(report)}; {_COST_METHOD})", *costs]),
        "\n".join([f"Trials ({len(report.tasks)} recorded; {_TRIAL_LOG_CAPTION})", *trials]),
    ]
    return "\n\n".join(sections) + "\n"


# Everything the page needs to be legible, inline. An external stylesheet would make opening a
# report a network request, and a report is read on machines that must not make one.
_HTML_STYLE = """\
body { font-family: system-ui, sans-serif; margin: 2rem; max-width: 60rem; }
table { border-collapse: collapse; margin-bottom: 1.5rem; }
th, td { border: 1px solid #999; padding: 0.25rem 0.75rem; text-align: left; }
caption { text-align: left; font-style: italic; padding-bottom: 0.25rem; }
.absent { color: #777; }"""

# Refuses every remote fetch the document could otherwise be made to perform, so the page keeps
# its offline promise even after someone edits it. Inline styles are the one exception, because
# the stylesheet above has to travel inside the file.
_HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'"


def _escape(text: str) -> str:
    """Escape one string for HTML. Every piece of text on the page goes through here.

    Including the captions: a constant that skipped escaping would be the seam where a later
    rewording broke the markup, and there is no text this page trusts.
    """
    return html.escape(text, quote=True)


def _html_cell(value: str | None) -> str:
    """One table cell, with an absent value shown as absent rather than as empty."""
    if value is None:
        return '<td class="absent">-</td>'
    return f"<td>{_escape(value)}</td>"


def _html_tools_table(report: Report) -> list[str]:
    """The per-tool scores. Each score is printed next to the band that qualifies it."""
    if not report.tools:
        return ["<p>No tools were recorded.</p>"]
    rows = [
        "<tr>"
        f"<td>{_escape(s.tool)}</td>"
        f"<td>{s.trials}</td>"
        f"<td>{_proportion(s.pass_at_1)}</td>"
        f"<td>{_escape(_interval(s.pass_at_1_interval))}</td>"
        f"<td>{_proportion(s.pass_caret_n)}</td>"
        f"<td>{_escape(_interval(s.pass_caret_n_interval))}</td>"
        "</tr>"
        for s in report.tools
    ]
    return [
        "<table>",
        f"<caption>{_escape(_INTERVAL_METHODS)}</caption>",
        "<thead><tr><th>Tool</th><th>Trials</th><th>pass@1</th><th>pass@1 interval</th>"
        "<th>pass^n</th><th>pass^n interval</th></tr></thead>",
        "<tbody>",
        *rows,
        "</tbody>",
        "</table>",
    ]


def _html_comparisons(report: Report) -> list[str]:
    """Two paragraphs per pairing: the verdict, then the paired test that does not rank it.

    Separate elements rather than one sentence joined by a comma, so a reader skimming the
    ranking cannot pick the p up as part of it.
    """
    if not report.comparisons:
        return ["<p>No comparison was possible: a comparison needs two tools.</p>"]
    return [
        paragraph
        for c in report.comparisons
        for paragraph in (
            f'<p class="comparison">{_escape(c.tool_a)} vs {_escape(c.tool_b)}: '
            f"{_escape(format_verdict(c.verdict))}</p>",
            f'<p class="paired">{_escape(format_paired(c))}</p>',
        )
    ]


def _html_costs_table(report: Report) -> list[str]:
    """The per-tool spend, captioned with where the prices came from and what a total covers.

    The basis travels as its sentence rather than as the enum member: the member is a machine
    reason and belongs in the JSON, and a page that printed ``no_tokens_recorded`` at a reader
    would be publishing a key name instead of an explanation.
    """
    if not report.costs:
        return ["<p>No costs were computed: no tool was recorded.</p>"]
    rows = [
        '<tr class="cost">'
        f"<td>{_escape(cost.tool)}</td>"
        f"<td>{cost.input_tokens}</td>"
        f"<td>{cost.output_tokens}</td>"
        f"<td>{cost.solved_tasks}</td>"
        f"<td>{_escape(_rates(cost))}</td>"
        f"<td>{_escape(_usd(cost.total_usd))}</td>"
        f"<td>{_escape(_usd(cost.usd_per_solved_task))}</td>"
        f"<td>{_escape(format_basis(cost))}</td>"
        "</tr>"
        for cost in report.costs
    ]
    return [
        "<table>",
        f"<caption>{_escape(_price_provenance(report))}; {_escape(_COST_METHOD)}</caption>",
        "<thead><tr><th>Tool</th><th>Input tokens</th><th>Output tokens</th>"
        "<th>Solved tasks</th><th>Rates</th><th>Total</th><th>Per solved task</th>"
        "<th>Basis</th></tr></thead>",
        "<tbody>",
        *rows,
        "</tbody>",
        "</table>",
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

    Every caveat is a caption on the table it qualifies, escaped like every other string on
    the page: there is no text here the document trusts.
    """
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
        "<h1>Assay report</h1>",
        f"<p>Suite: <code>{_escape(report.suite_hash)}</code></p>",
        "<h2>Tools</h2>",
        *_html_tools_table(report),
        "<h2>Comparisons</h2>",
        *_html_comparisons(report),
        "<h2>Costs</h2>",
        *_html_costs_table(report),
        "<h2>Trials</h2>",
        *_html_trials_table(report),
        "</body>",
        "</html>",
    ]
    return "\n".join(lines) + "\n"
