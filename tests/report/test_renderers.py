"""What the three renderers are allowed to say about the measurement they are handed.

Four properties are load-bearing here and each is asserted for all three formats, because a
report that is honest in JSON and confident in HTML is not an honest report.

The first is that the two bands are two instruments. pass^n carries a Wilson interval over
tasks and pass@1 carries a percentile bootstrap over the same tasks, so both prose formats
have to name both methods (ADR-0035, ADR-0043) - the caption is asserted verbatim, the whole
constant, because a substring match would let a rewording that dropped one method's name keep
passing, and two bands printed as though one procedure produced them is the misreading the
sentence exists to prevent. The formats also have to be clear of the M0 placeholder caption,
which M3 deleted along with the invented band it described (ADR-0034).

The second is SPEC §4: the renderers inherit the overlap rule rather than re-deriving one. The
3x2 parametrisation over ``{json, text, html}`` x ``{overlapping, disjoint}`` is the milestone's
evidence that suppression holds at the presentation layer, where a table of point estimates is
most tempting to rank.

The third is the redaction boundary (SPEC §5.4). The sentinel test seeds a report with a path,
an identifier and a commit subject that would be unmistakable in any output, renders it once
unredacted to prove the renderers really do print those fields, and once through :func:`redact`
to prove no byte of them survives.

The fourth is that the two prose formats *say* they are redacted, in the wording
:data:`~assay.report.render._REDACTION_STATEMENT` and nowhere else. A page of HMAC tokens that
never names them is a page a reader has to guess about, so the statement is asserted verbatim
above the numbers, asserted absent from the JSON where prose would become a compatibility
promise, and - because a sentence is a claim like any other here - checked against the property
it asserts: one report rendered twice shares the sentence and no token. The sentence says "here",
so both prose formats take a :data:`~assay.report.RedactedReport` and a static negative below
pins that they still reject a report nobody redacted (ADR-0058) - which is why the helpers in
this file, which build unredacted reports on purpose, have to say so at every call.
"""

import html
import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from assay.report import (
    CostBasis,
    Interval,
    PriceTable,
    Redacted,
    RedactedReport,
    RedactionPolicy,
    Report,
    TaskLine,
    ToolCost,
    ToolPrice,
    ToolSummary,
    build_report,
    format_basis,
    format_paired,
    format_verdict,
    redact,
    render_html,
    render_json,
    render_text,
    summarise,
)
from assay.report.render import (
    _COST_METHOD,
    _INTERVAL_METHODS,
    _NO_PRICES,
    _REDACTION_STATEMENT,
)
from assay.results import Outcome, read_result_set

FIXTURES = Path(__file__).parent.parent / "fixtures"

SUITE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

type Renderer = Callable[[RedactedReport], str]

# Every format, so that a claim proved of one is proved of all three. The name travels with the
# function because each format states a winner differently, and reading it back is the only way
# to check none of them invented one.
RENDERERS: list[tuple[str, Renderer]] = [
    ("json", render_json),
    ("text", render_text),
    ("html", render_html),
]

# The two formats that print prose. JSON carries the machine verdict instead: the sentence is
# outside the schema on purpose (see :func:`format_verdict`).
PROSE_RENDERERS: list[tuple[str, Renderer]] = RENDERERS[1:]

# Text that could only have come from the repository under evaluation - a path, an identifier
# and a commit subject, each recognisable on sight in any of the three outputs.
SECRET_PATH = "src/secret_module.py"
SECRET_IDENT = "AcmeInternalClient"
SECRET_SUBJECT = "fix ACME-1234 auth bypass"
SENTINELS = (SECRET_PATH, SECRET_IDENT, SECRET_SUBJECT)

# Prices are the reader's, never Assay's, and never this repository's: no rate anybody could
# mistake for a maintained figure goes into a file here (ADR-0046). A hundred and two hundred
# dollars per million tokens are plainly nobody's price, and they divide by hand.
PRICES_SOURCE = "an invented rate card, used to test arithmetic and priced against nothing"
INPUT_USD_PER_MTOK = Decimal("100.000000")
OUTPUT_USD_PER_MTOK = Decimal("200.000000")


def _fixture_report(name: str) -> RedactedReport:
    """Build a report the way the pipeline does, from one of the two recorded result sets.

    Wrapped rather than redacted: the fixtures carry no sentinel, and a test that reads a
    number off a rendered page needs the tool names and task ids the fixture recorded, not
    tokens. The cast is the declaration that this report skipped the boundary on purpose.
    """
    result_set = read_result_set(FIXTURES / name)
    # Unredacted on purpose - see this helper's docstring.
    return RedactedReport(build_report(result_set, summarise(result_set)))


def _priced_report() -> RedactedReport:
    """The disjoint bracket, priced for the tool that spent tokens and for neither other.

    ground-truth recorded 10240 input and 960 output tokens over its ten trials, so at the two
    invented rates above it cost (10240 * 100 + 960 * 200) / 1e6 = $1.216000 and, over the five
    tasks it solved, $0.243200 each. null recorded nothing at all, which is the case the report
    has to keep apart from a spend of zero.
    """
    result_set = read_result_set(FIXTURES / "results_disjoint.json")
    prices = PriceTable(
        source=PRICES_SOURCE,
        prices=(
            ToolPrice(
                tool="ground-truth",
                input_usd_per_mtok=INPUT_USD_PER_MTOK,
                output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
            ),
            ToolPrice(
                tool="null",
                input_usd_per_mtok=INPUT_USD_PER_MTOK,
                output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
            ),
        ),
    )
    # Unredacted on purpose: these tests read dollars and tool names back off the page.
    return RedactedReport(build_report(result_set, summarise(result_set), prices))


def _seeded_report() -> RedactedReport:
    """A one-trial report whose every repo-derived field holds a sentinel, unredacted.

    The sentinels wear :data:`Redacted` before anything has hashed them, exactly as a miner's
    raw output would: constructing a task line from a raw string is not a type error, so the
    test has to travel through :func:`redact` to prove the boundary rather than assume it.

    Wrapped unredacted for that reason - a helper that redacted here would leave nothing for
    the sentinel test to prove the renderers ever print.
    """
    # Unredacted on purpose - see this helper's docstring.
    return RedactedReport(
        Report(
            suite_hash=SUITE_HASH,
            tools=(
                ToolSummary(
                    tool="ground-truth",
                    trials=1,
                    pass_at_1=1.0,
                    pass_at_1_interval=Interval(low=1.0, high=1.0),
                    pass_caret_n=1.0,
                    pass_caret_n_interval=Interval(low=0.75, high=1.0),
                ),
            ),
            comparisons=(),
            costs=(
                ToolCost(
                    tool="ground-truth",
                    input_tokens=1_000_000,
                    output_tokens=500_000,
                    solved_tasks=1,
                    input_usd_per_mtok=INPUT_USD_PER_MTOK,
                    output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
                    total_usd=Decimal("200.000000"),
                    usd_per_solved_task=Decimal("200.000000"),
                    basis=CostBasis.PRICED,
                ),
            ),
            prices_source=PRICES_SOURCE,
            tasks=(
                TaskLine(
                    task_id=SECRET_IDENT,
                    repo_path=Redacted(SECRET_PATH),
                    commit_subject=Redacted(SECRET_SUBJECT),
                    outcome=Outcome.PASSED,
                ),
            ),
        )
    )


def _empty_report() -> RedactedReport:
    """A run that recorded nothing: no tools, so no comparisons and no trials."""
    # Unredacted on purpose: an empty report has nothing in it to redact.
    return RedactedReport(
        Report(
            suite_hash=SUITE_HASH,
            tools=(),
            comparisons=(),
            costs=(),
            prices_source=None,
            tasks=(),
        )
    )


def _readable(fmt: str, out: str) -> str:
    """The text a reader sees, with HTML's escapes resolved.

    The page escapes every string it prints, so ``other's`` reaches the file as ``other&#x27;s``.
    Undoing that here keeps the assertions about *what the report says* from turning into
    assertions about how one format spells a quote.
    """
    return html.unescape(out) if fmt == "html" else out


def _names_a_winner(fmt: str, out: str) -> bool:
    """Whether a rendered report claims a winner, read the way that format would state one."""
    if fmt == "json":
        document = json.loads(out)
        return any(c["verdict"]["winner"] is not None for c in document["comparisons"])
    return "Winner: " in out


def _trial_count(fmt: str, out: str) -> int:
    """How many trials a rendered report shows, counted in that format's own structure."""
    if fmt == "json":
        document = json.loads(out)
        return len(document["tasks"])
    if fmt == "html":
        return out.count('<tr class="trial">')
    # The trial log is the last section of the text report, one non-blank line per trial
    # under its heading.
    body = out.split("Trials")[-1]
    return len([line for line in body.splitlines()[1:] if line.strip()])


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_a_renderer_shows_one_line_per_recorded_trial(fmt: str, render: Renderer) -> None:
    # build_report emits one TaskLine per *result*, not per task: the overlapping fixture has
    # 4 tasks x 2 tools x 2 trials = 16. The report is a trial log, and a renderer that showed
    # 4 rows would be silently aggregating a measurement M4 has not yet decided how to pool.
    report = _fixture_report("results_overlapping.json")

    assert _trial_count(fmt, render(report)) == 16


@pytest.mark.parametrize("fixture", ["results_overlapping.json", "results_disjoint.json"])
@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_no_renderer_names_a_winner_the_verdict_withheld(
    fmt: str, render: Renderer, fixture: str
) -> None:
    # The overlapping fixture's leader is ahead on both point estimates and still wins nothing.
    # Every format has to inherit that from the Verdict rather than compare the two numbers it
    # is printing (SPEC §4, KICKOFF item 6).
    report = _fixture_report(fixture)
    (comparison,) = report.comparisons

    named = _names_a_winner(fmt, render(report))

    assert named is (comparison.verdict.winner is not None)


@pytest.mark.parametrize("fixture", ["results_overlapping.json", "results_disjoint.json"])
@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_a_prose_renderer_prints_the_shared_verdict_sentence(
    fmt: str, render: Renderer, fixture: str
) -> None:
    # One sentence, one source. Two formats phrasing the same verdict differently would be two
    # claims about one measurement.
    report = _fixture_report(fixture)
    (comparison,) = report.comparisons

    assert format_verdict(comparison.verdict) in _readable(fmt, render(report))


def test_the_json_document_round_trips_through_the_schema() -> None:
    # The canonical format is API (CLAUDE.md): whatever it emits has to load again as the same
    # report, or a consumer is reading a document Assay could not have produced.
    report = _fixture_report("results_disjoint.json")

    assert Report.model_validate(json.loads(render_json(report))) == report


def test_the_json_document_carries_the_bands_without_the_prose() -> None:
    # Both intervals travel as two numbers each; the caption naming the two methods does not
    # travel at all, and neither does the paired test's sentence. They are worded for a human,
    # and a key holding either would freeze one wording as a compatibility promise - the rule
    # the deleted M0 notice was held to, applied to its successors.
    report = _fixture_report("results_disjoint.json")
    out = render_json(report)
    (comparison,) = report.comparisons

    null, ground_truth = json.loads(out)["tools"]
    assert ground_truth["pass_caret_n_interval"]["low"] > null["pass_caret_n_interval"]["high"]
    assert _INTERVAL_METHODS not in out
    assert format_paired(comparison) not in out


@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_a_prose_report_names_the_method_behind_each_band(fmt: str, render: Renderer) -> None:
    # Verbatim, in both formats a human reads. Two bands printed side by side read as one
    # measurement taken twice unless the report says otherwise, so the caption names both
    # procedures and the resample count and seed that make the second one reproducible.
    out = _readable(fmt, render(_fixture_report("results_disjoint.json")))

    assert _INTERVAL_METHODS in out
    assert "Wilson" in _INTERVAL_METHODS
    assert "bootstrap" in _INTERVAL_METHODS
    assert "seed" in _INTERVAL_METHODS


def test_the_text_report_names_the_methods_where_the_scores_are() -> None:
    # On the Tools heading, not in a footnote at the end: the caveat has to be readable
    # without scrolling past the numbers it qualifies.
    out = render_text(_fixture_report("results_disjoint.json"))

    heading = next(line for line in out.splitlines() if line.startswith("Tools"))

    assert _INTERVAL_METHODS in heading


def test_the_html_tools_table_is_captioned_with_the_marker() -> None:
    # A table caption, escaped like every other string on the page, and attached to the table
    # holding the scores rather than floated at the top of the document.
    out = render_html(_fixture_report("results_disjoint.json"))

    tools_section = out.split("<h2>Tools</h2>", 1)[1]
    caption, _, _ = tools_section.partition("</caption>")

    assert _readable("html", caption).endswith(f"<caption>{_INTERVAL_METHODS}")


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_no_format_captions_a_measured_interval_as_invented(fmt: str, render: Renderer) -> None:
    # M0 printed a placeholder caption above every number because the band was invented -
    # pass^n +/-0.25, clamped. The band is measured now, so the caption is gone from all three
    # formats along with the arithmetic it described: a measured interval still captioned
    # "placeholder" lies in the other direction (ADR-0034).
    out = _readable(fmt, render(_fixture_report("results_disjoint.json")))

    assert "placeholder" not in out.lower()


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_a_renderer_prints_repo_derived_text_it_is_given(fmt: str, render: Renderer) -> None:
    # The negative test below is only worth anything if these fields are rendered at all. This
    # is the control: unredacted, every sentinel shows up.
    out = render(_seeded_report())

    assert all(sentinel in out for sentinel in SENTINELS)


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_a_renderer_leaks_nothing_from_a_redacted_report(fmt: str, render: Renderer) -> None:
    # The report is the one artefact that leaves the customer's machine (SPEC §5.4). Not a byte
    # of the path, the identifier or the commit subject may survive the boundary in any format.
    redacted = redact(_seeded_report(), RedactionPolicy(salt=bytes([7]) * 32))

    out = render(redacted)

    for sentinel in SENTINELS:
        assert sentinel not in out


@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_a_prose_report_says_that_it_is_redacted(fmt: str, render: Renderer) -> None:
    # A column of `i:9f3a...` reads as a truncated identifier unless the page says what it is,
    # and a reader who cannot tell a token from an abbreviation cannot tell a redacted report
    # from a careless one. Verbatim, the whole constant, for the reason the interval caption is
    # asserted that way: a rewording that dropped the per-render salt would survive a substring
    # match, and the salt is the half of the claim that matters (ADR-0009).
    out = _readable(fmt, render(redact(_seeded_report(), RedactionPolicy.from_random())))

    assert _REDACTION_STATEMENT in out


def test_the_text_report_states_the_redaction_in_its_header() -> None:
    # On its own line under the suite hash, above every number: a caveat a reader meets after
    # the trial log is a caveat about a document they have already finished reading.
    out = render_text(_fixture_report("results_disjoint.json"))

    title, suite, redaction = out.splitlines()[:3]

    assert title == "Assay report"
    assert suite.startswith("Suite: ")
    assert redaction == f"Redaction: {_REDACTION_STATEMENT}"


def test_the_html_report_states_the_redaction_under_the_suite_line() -> None:
    # Escaped like every other string on the page, and in document order directly after the
    # hash it qualifies. The escaped spelling is asserted rather than read back through
    # `_readable`, so a later wording that gains an apostrophe has to reach the file escaped.
    out = render_html(_fixture_report("results_disjoint.json"))

    _, separator, below_suite = out.partition("</code></p>\n")
    statement = html.escape(_REDACTION_STATEMENT, quote=True)

    assert separator
    assert below_suite.startswith(f'<p class="redaction">Redaction: {statement}</p>')


def test_the_html_report_declares_a_viewport() -> None:
    # One column of tables, read on a phone as readily as on a laptop. Without this a mobile
    # browser lays the page out at a desktop width and scales the whole document down, which
    # makes the numbers the report exists to show illegible without a pinch.
    out = render_html(_fixture_report("results_disjoint.json"))

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in out


def test_the_json_document_carries_the_tokens_without_the_redaction_sentence() -> None:
    # The third sentence written for a human and kept out of the schema, for the reason the
    # other two are: a key holding it would freeze this wording as a compatibility promise in a
    # document CLAUDE.md treats as API. What the sentence describes is in there already - the
    # tokens themselves - and a consumer reads those rather than prose about them.
    redacted = redact(_fixture_report("results_disjoint.json"), RedactionPolicy.from_random())

    out = render_json(redacted)

    assert _REDACTION_STATEMENT not in out
    assert "Redaction" not in out
    assert Report.model_validate(json.loads(out)) == redacted


@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_two_renders_of_one_report_share_the_statement_and_no_token(
    fmt: str, render: Renderer
) -> None:
    # What the sentence claims, asserted rather than trusted. The salt is drawn per render and
    # never stored (ADR-0009), so one result set rendered twice shares no token and the two
    # documents cannot be cross-referenced line by line - and the sentence saying so is the one
    # thing that does not move between them.
    report = _seeded_report()

    first = render(redact(report, RedactionPolicy.from_random()))
    second = render(redact(report, RedactionPolicy.from_random()))

    assert first != second
    assert _REDACTION_STATEMENT in _readable(fmt, first)
    assert _REDACTION_STATEMENT in _readable(fmt, second)


def test_an_unredacted_report_is_statically_rejected_by_the_prose_renderers() -> None:
    # LOAD-BEARING IGNORE - do not delete. The sentence both prose formats print says every
    # identifier and path *here* is a token, and the only thing backing that claim is the type
    # of the argument: `redact` alone mints a `RedactedReport`. The call below is what the
    # sentence would be false about - a report straight out of `build_report`, never redacted -
    # and the ignore is the assertion that mypy --strict still rejects it. ``warn_unused_ignores``
    # is on (pyproject.toml), so if the fence ever dissolves this ignore becomes unused and CI
    # fails here. Deleting it deletes the check. Same arrangement as the `Redacted` negative in
    # `tests/report/test_redaction.py` (ADR-0058).
    result_set = read_result_set(FIXTURES / "results_disjoint.json")
    unredacted = build_report(result_set, summarise(result_set))

    rendered = render_text(unredacted)  # type: ignore[arg-type]

    # It still runs: NewType is erased at runtime, which is why the guarantee is enforced
    # statically rather than by a check inside a renderer that could not tell a token from
    # text shaped like one.
    assert _REDACTION_STATEMENT in rendered
    assert render_text(redact(unredacted, RedactionPolicy.from_random())).startswith("Assay")


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_a_renderer_survives_a_report_with_nothing_to_compare(fmt: str, render: Renderer) -> None:
    # A run with one tool - or none - produces no comparisons. Rendering it is not an error
    # case: "we could not compare anything" is a finding, and an IndexError is not a way to
    # report it.
    empty = _empty_report()
    single = _seeded_report()

    assert render(empty).strip()
    assert render(single).strip()


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_a_renderer_emits_ascii_only(fmt: str, render: Renderer) -> None:
    # Reports are read on a Windows console as often as in a browser, and a mojibake section
    # sign in a number's caption is a defect in a document whose subject is precision.
    assert render(_fixture_report("results_overlapping.json")).isascii()


def test_the_html_report_is_offline_only() -> None:
    # A report is rendered inside the environment it was measured in and read anywhere. It may
    # not fetch anything: a remote font or stylesheet would turn opening the file into a
    # network callback that says which machine read which report.
    out = render_html(_fixture_report("results_overlapping.json"))

    assert "http://" not in out
    assert "https://" not in out
    assert "src=" not in out
    assert "@import" not in out
    assert "Content-Security-Policy" in out
    assert "<style>" in out


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_every_format_carries_the_bootstrap_band_beside_pass_at_1(
    fmt: str, render: Renderer
) -> None:
    # The disjoint bracket makes the two bands distinguishable on sight: null's pass@1 band is
    # [0.000, 0.000] and ground-truth's is [1.000, 1.000], neither of which is that tool's
    # Wilson band ([0.000, 0.434] and [0.566, 1.000]). A format that printed the pass^n band
    # twice, or reused one tool's band for the other, fails this rather than passing quietly.
    out = render(_fixture_report("results_disjoint.json"))

    if fmt == "json":
        null, ground_truth = json.loads(out)["tools"]
        assert null["pass_at_1_interval"] == {"low": 0.0, "high": 0.0}
        assert ground_truth["pass_at_1_interval"] == {"low": 1.0, "high": 1.0}
    else:
        readable = _readable(fmt, out)
        assert "[0.000, 0.000]" in readable
        assert "[1.000, 1.000]" in readable


@pytest.mark.parametrize("fixture", ["results_overlapping.json", "results_disjoint.json"])
@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_a_prose_renderer_prints_the_shared_paired_sentence(
    fmt: str, render: Renderer, fixture: str
) -> None:
    # As with the verdict: one sentence, one source. A p-value printed with no stated reading -
    # or with two readings, one per format - is the unexplained output ADR-0035 refuses.
    report = _fixture_report(fixture)
    (comparison,) = report.comparisons

    assert format_paired(comparison) in _readable(fmt, render(report))


def test_the_json_document_carries_the_paired_test_as_numbers() -> None:
    # Five tasks, ground-truth solved every one and null none, so the tools disagree about all
    # five in ground-truth's favour: 2 * C(5,0)/2^5 = 2/32 = 0.0625. The document carries the
    # four integers and the p, and leaves the sentence about them to the formats a person reads.
    report = _fixture_report("results_disjoint.json")

    document = json.loads(render_json(report))

    assert document["comparisons"][0]["paired"] == {
        "tasks_compared": 5,
        "only_tool_a": 0,
        "only_tool_b": 5,
        "p_value": 0.0625,
    }


def test_a_prose_format_keeps_the_p_out_of_the_line_that_ranks() -> None:
    # The rendering half of ADR-0044. This report does name a winner - the Wilson bands are
    # disjoint - and the p is the strongest the fixture can offer (five discordant tasks, all
    # one way: 2/2^5 = 0.0625). The two claims still travel as two elements, so a reader cannot
    # take the p as part of the ranking, and neither can a reader of a report where the bands
    # overlap and the ranking is a refusal (asserted on the summaries in test_summarise.py).
    report = _fixture_report("results_disjoint.json")
    (comparison,) = report.comparisons

    paired_line = next(line for line in render_text(report).splitlines() if "exact McNemar" in line)

    assert comparison.paired.p_value == 0.0625
    assert format_paired(comparison) in paired_line
    assert "Winner" not in paired_line


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_every_format_carries_a_costs_section_without_any_prices(
    fmt: str, render: Renderer
) -> None:
    # The default path, and the one every report takes today: no --price flag, so every row
    # reads no_price_supplied. The section is still there. Omitting it when it had no dollars
    # in it would make its absence the report's way of saying something, which is the
    # unexplained blank ADR-0035 refuses by name (ADR-0046).
    report = _fixture_report("results_disjoint.json")

    out = render(report)

    assert [cost.basis for cost in report.costs] == [CostBasis.NO_PRICE_SUPPLIED] * 2
    if fmt == "json":
        document = json.loads(out)
        assert [c["basis"] for c in document["costs"]] == ["no_price_supplied", "no_price_supplied"]
        assert document["prices_source"] is None
    else:
        readable = _readable(fmt, out)
        assert _NO_PRICES in readable
        assert all(format_basis(cost) in readable for cost in report.costs)


@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_a_prose_renderer_states_the_reason_behind_every_cost_line(
    fmt: str, render: Renderer
) -> None:
    # Two bases in one report, and the pair is the whole point: ground-truth spent tokens and
    # is priced, null recorded none and so has no total at all - not a total of zero. A reader
    # who saw two blanks with no sentence would read the second as free (ADR-0046).
    report = _priced_report()
    null, ground_truth = report.costs

    readable = _readable(fmt, render(report))

    assert null.basis is CostBasis.NO_TOKENS_RECORDED
    assert ground_truth.basis is CostBasis.PRICED
    assert format_basis(null) in readable
    assert format_basis(ground_truth) in readable
    assert _COST_METHOD in readable


@pytest.mark.parametrize(("fmt", "render"), PROSE_RENDERERS)
def test_a_prose_renderer_names_where_the_prices_came_from(fmt: str, render: Renderer) -> None:
    # Assay knows no prices. The dollars are the reader's own figure, so the report says whose
    # they are: a total nobody can attribute is not a measurement (SPEC 5.5).
    readable = _readable(fmt, render(_priced_report()))

    assert PRICES_SOURCE in readable
    assert _NO_PRICES not in readable


def test_the_json_document_carries_the_money_as_numbers_and_no_prose() -> None:
    # ground-truth spent 10240 input and 960 output tokens at $100 and $200 per million:
    # (10240 * 100 + 960 * 200) / 1e6 = (1024000 + 192000) / 1e6 = $1.216000. It solved five of
    # the five tasks, so 1.216000 / 5 = $0.243200 each. The rates travel with the line, because
    # a dollar figure that cannot be re-derived from the report is a claim rather than a
    # measurement - and the sentence explaining the basis does not travel at all.
    report = _priced_report()

    out = render_json(report)
    document = json.loads(out)
    null, ground_truth = document["costs"]

    assert ground_truth == {
        "tool": "ground-truth",
        "input_tokens": 10240,
        "output_tokens": 960,
        "solved_tasks": 5,
        "input_usd_per_mtok": "100.000000",
        "output_usd_per_mtok": "200.000000",
        "total_usd": "1.216000",
        "usd_per_solved_task": "0.243200",
        "basis": "priced",
    }
    assert null["total_usd"] is None
    assert document["prices_source"] == PRICES_SOURCE
    assert all(format_basis(cost) not in out for cost in report.costs)
    assert _COST_METHOD not in out


def test_the_costs_section_is_ordered_like_the_tools_it_prices() -> None:
    # The two tables are read across from each other, so a cost under the wrong tool's name is
    # worse than no cost at all. Both come from the order the result set first mentions a tool.
    report = _priced_report()

    assert [cost.tool for cost in report.costs] == [summary.tool for summary in report.tools]


def test_the_html_costs_table_escapes_the_source_the_reader_supplied() -> None:
    # prices_source is the one string in a report that comes from a command line rather than
    # from Assay or from the repository, and it is printed on a page. The schema keeps it to
    # one line and the page escapes it, like every other string here.
    result_set = read_result_set(FIXTURES / "results_disjoint.json")
    prices = PriceTable(
        source="<script>alert('priced')</script>",
        prices=(
            ToolPrice(
                tool="null",
                input_usd_per_mtok=INPUT_USD_PER_MTOK,
                output_usd_per_mtok=OUTPUT_USD_PER_MTOK,
            ),
        ),
    )

    # Unredacted on purpose: what is on trial here is the escaping of the reader's own text.
    report = RedactedReport(build_report(result_set, summarise(result_set), prices))

    out = render_html(report)

    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_the_html_report_declares_a_light_canvas() -> None:
    # The page was legible only because it silently inherited the user agent's white canvas:
    # no background, no colour, and `color-scheme: normal`, which lets Chrome's Auto Dark
    # Theme repaint it. A report whose greys were measured against white has to be served on
    # white, so the document says so rather than hoping.
    out = render_html(_fixture_report("results_disjoint.json"))

    assert "color-scheme: light;" in out
    assert "background-color: #fff;" in out
    assert "color: #1a1a1a;" in out


def test_every_html_table_scrolls_inside_its_own_container() -> None:
    # At 375px the widest table ran to 679px and took the whole document with it, so the only
    # unscrolled view of the tools table ended inside the pass@1 interval column: the
    # flattering number on screen and the pass^n band that refuses to name a winner off it.
    # One container per table rather than one for the page, so a reader who scrolls the costs
    # table has not also scrolled the scores out from under the heading that names them.
    lines = render_html(_priced_report()).splitlines()
    opened = [i for i, line in enumerate(lines) if line == "<table>"]
    closed = [i for i, line in enumerate(lines) if line == "</table>"]

    assert ".scroll { overflow-x: auto;" in "\n".join(lines)
    assert len(opened) == 3
    assert all(lines[i - 1] == '<div class="scroll">' for i in opened)
    assert all(lines[i + 1] == "</div>" for i in closed)


def test_the_html_suite_hash_wraps_rather_than_widening_the_page() -> None:
    # 71 unbreakable characters, 507px of them, and the digest is the report's core provenance
    # claim (ADR-0049) - so it wraps mid-token and stays whole and copyable. Truncating it
    # would shorten the one line that says which task set these numbers were measured on.
    report = _fixture_report("results_disjoint.json")

    out = render_html(report)

    assert "overflow-wrap: anywhere;" in out
    assert f"<code>{report.suite_hash}</code>" in out


def test_every_html_table_cell_has_a_header_in_scope() -> None:
    # 18 header cells across the three tables (6 + 8 + 4) and, until now, no scope on any of
    # them and no row header at all: a screen reader read "0.875" under a column name with no
    # row to attach it to. The first cell of every body row is the tool or the task it
    # describes, which makes it a header rather than a datum.
    out = render_html(_fixture_report("results_overlapping.json"))

    header_rows = out.count("<thead>")
    body_rows = out.count("<tr") - header_rows

    assert out.count('<th scope="col">') == 18
    assert out.count('<th scope="row">') == body_rows
    assert "<th>" not in out


def test_the_html_greys_clear_the_contrast_floors() -> None:
    # Both greys were measured on white and both fell short: #777 text at 4.478:1 against the
    # 4.5:1 WCAG AA floor, #999 borders at 2.849:1 against the 3:1 non-text floor. The absent
    # cells are exactly the ones that keep "not recorded" apart from "measured zero", which is
    # a distinction the report cannot afford to render faintly. Pinned so a later tidy-up
    # cannot drift back under the line without failing here.
    out = render_html(_seeded_report())

    assert ".absent { color: #6b6b6b; }" in out
    assert "border: 1px solid #8a8a8a;" in out


def test_the_html_prose_is_set_to_a_readable_measure() -> None:
    # The redaction sentence ran to 120 characters a line at a desktop width, against the
    # 45-75 a reader tracks comfortably: the paragraph ADR-0049 says has to be read first was
    # set at the width hardest to read. The tables keep the 60rem they need; the prose does
    # not need it.
    out = render_html(_fixture_report("results_disjoint.json"))

    assert "max-width: 34rem;" in out
    assert "line-height: 1.5;" in out
    assert "max-width: 60rem;" in out


def test_the_scroll_containers_leave_the_redaction_above_every_number() -> None:
    # The layout fix moves markup around the tables, and the one thing that may not move is
    # the sentence that qualifies the whole document: it stays the third element of the body,
    # ahead of the first table and of every score in it (ADR-0049).
    out = render_html(_priced_report())
    body = out.split("<body>\n", 1)[1]
    elements = body.splitlines()

    assert elements[2].startswith('<p class="redaction">')
    assert body.index('<p class="redaction">') < body.index("<table>")


def test_the_html_report_shows_no_clock() -> None:
    # A renderer is a pure function from a Report to a string, and two renders of one recorded
    # result set have to agree byte for byte (ADR-0049). Restyling is where a "generated at"
    # line arrives, so the page is scanned for one: no date, no time, no generator string.
    out = _readable("html", render_html(_priced_report()))

    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}", out)
    assert not re.search(r"generated|timestamp|\bUTC\b|\bGMT\b", out, re.IGNORECASE)
