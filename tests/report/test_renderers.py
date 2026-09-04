"""What the three renderers are allowed to say about the measurement they are handed.

Three properties are load-bearing here and each is asserted for all three formats, because a
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
"""

import html
import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import pytest

from assay.report import (
    CostBasis,
    Interval,
    PriceTable,
    Redacted,
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
from assay.report.render import _COST_METHOD, _INTERVAL_METHODS, _NO_PRICES
from assay.results import Outcome, read_result_set

FIXTURES = Path(__file__).parent.parent / "fixtures"

SUITE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

type Renderer = Callable[[Report], str]

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


def _fixture_report(name: str) -> Report:
    """Build a report the way the pipeline does, from one of the two recorded result sets."""
    result_set = read_result_set(FIXTURES / name)
    return build_report(result_set, summarise(result_set))


def _priced_report() -> Report:
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
    return build_report(result_set, summarise(result_set), prices)


def _seeded_report() -> Report:
    """A one-trial report whose every repo-derived field holds a sentinel, unredacted.

    The sentinels wear :data:`Redacted` before anything has hashed them, exactly as a miner's
    raw output would: constructing a task line from a raw string is not a type error, so the
    test has to travel through :func:`redact` to prove the boundary rather than assume it.
    """
    return Report(
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


def _empty_report() -> Report:
    """A run that recorded nothing: no tools, so no comparisons and no trials."""
    return Report(
        suite_hash=SUITE_HASH,
        tools=(),
        comparisons=(),
        costs=(),
        prices_source=None,
        tasks=(),
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

    out = render_html(build_report(result_set, summarise(result_set), prices))

    assert "<script>" not in out
    assert "&lt;script&gt;" in out
