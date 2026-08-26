"""What the three renderers are allowed to say about a measurement nobody made yet.

Three properties are load-bearing here and each is asserted for all three formats, because a
report that is honest in JSON and confident in HTML is not an honest report.

The first is the M0 admission. :data:`STUB_INTERVAL_NOTICE` is asserted *verbatim* - the whole
constant, never a fragment of it - so that these tests are the tripwire that fires when M4's
Wilson intervals land and the placeholder text outlives the placeholder arithmetic. A
substring match would let a reworded notice keep passing and defuse it.

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
from pathlib import Path

import pytest

from assay.report import (
    STUB_INTERVAL_NOTICE,
    Interval,
    Redacted,
    RedactionPolicy,
    Report,
    TaskLine,
    ToolSummary,
    build_report,
    format_verdict,
    redact,
    render_html,
    render_json,
    render_text,
    summarise,
)
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


def _fixture_report(name: str) -> Report:
    """Build a report the way the pipeline does, from one of the two recorded result sets."""
    result_set = read_result_set(FIXTURES / name)
    return build_report(result_set, summarise(result_set))


def _seeded_report() -> Report:
    """A one-trial report whose every repo-derived field holds a sentinel, unredacted.

    The sentinels wear :data:`Redacted` before anything has hashed them, exactly as a miner's
    raw output would: constructing a task line from a raw string is not a type error, so the
    test has to travel through :func:`redact` to prove the boundary rather than assume it.
    """
    return Report(
        suite_hash=SUITE_HASH,
        intervals_are_placeholders=True,
        tools=(
            ToolSummary(
                tool="ground-truth",
                trials=1,
                pass_at_1=1.0,
                pass_caret_n=1.0,
                pass_caret_n_interval=Interval(low=0.75, high=1.0),
            ),
        ),
        comparisons=(),
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
        intervals_are_placeholders=True,
        tools=(),
        comparisons=(),
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


def test_the_json_document_admits_the_placeholder_without_prose() -> None:
    # The admission travels as a boolean. The wording lives outside the schema so it can be
    # reworded without breaking a consumer, which means it must not leak into the document.
    out = render_json(_fixture_report("results_disjoint.json"))

    assert json.loads(out)["intervals_are_placeholders"] is True
    assert STUB_INTERVAL_NOTICE not in out


def test_the_text_report_opens_with_the_placeholder_notice() -> None:
    # Verbatim and unwrapped, at the very top, before a single number: a reader who stops after
    # the first paragraph must already know the intervals were invented.
    out = render_text(_fixture_report("results_disjoint.json"))

    assert out.startswith(STUB_INTERVAL_NOTICE + "\n\n")


def test_the_html_report_opens_with_the_placeholder_notice() -> None:
    # First element inside <body>, ahead of any table or number, and byte-identical to the
    # constant - the notice is quoted, never re-wrapped or summarised.
    out = render_html(_fixture_report("results_disjoint.json"))

    body = out.split("<body>", 1)[1].lstrip()
    first_element, _, _ = body.partition("</p>")

    assert _readable("html", first_element) == (
        f'<p class="placeholder-notice">{STUB_INTERVAL_NOTICE}'
    )


@pytest.mark.parametrize(("fmt", "render"), RENDERERS)
def test_a_measured_report_carries_no_placeholder_notice(fmt: str, render: Renderer) -> None:
    # M4's report is the same document with the flag flipped. The notice is keyed to the flag
    # rather than to the milestone, so a measured interval is never captioned as invented.
    measured = _fixture_report("results_disjoint.json").model_copy(
        update={"intervals_are_placeholders": False}
    )

    out = _readable(fmt, render(measured))

    assert STUB_INTERVAL_NOTICE not in out
    assert "PLACEHOLDER" not in out


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
