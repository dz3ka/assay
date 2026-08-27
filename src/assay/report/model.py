"""The report schema, and the one place in Assay that decides which tool won.

Two rules shape everything here. The first is SPEC §4: when two confidence intervals
overlap, the report declares no winner. That decision is taken once, in
:func:`decide_verdict`, and every renderer reads the :class:`Verdict` it produced - a
renderer that compared two numbers itself could publish a ranking the statistics do not
support, which is the exact failure this project exists to avoid.

The second is that prose is not part of the schema. A :class:`Verdict` carries a machine
reason; the English sentence is built by :func:`format_verdict`, outside the document. Once
a report's JSON is public it is API (CLAUDE.md), and a headline string would freeze one
wording as a compatibility promise.

A report is the one Assay document that is deliberately *not* content-addressable: an
interval is a float, floats have no stable canonical encoding (ADR-0008), so a report is
rendered rather than hashed.

Pure: this module builds models from models. No I/O, no git, no clock.
"""

from enum import StrEnum
from itertools import combinations
from typing import Annotated, NewType, Self

from pydantic import Field, model_validator

from assay.core import SchemaModel
from assay.results import AdapterName, Outcome, ResultSet, SuiteHash

# A string that has been through the redaction boundary (SPEC §5.4). The type is declared
# here, next to the fields that hold one, so that :mod:`assay.report.redact` depends on the
# schema and not the other way round. It is a NewType rather than a class because a redacted
# value must still *be* a string everywhere it is written, while being impossible to satisfy
# by accident with a raw path a caller never redacted.
Redacted = NewType("Redacted", str)

# A proportion in the closed unit interval: pass@1, pass^n, and both ends of the interval
# around them. Anything outside [0, 1] is an arithmetic bug upstream, not a measurement.
type Proportion = Annotated[float, Field(ge=0.0, le=1.0)]

# A report is built from a result set and prints what that set recorded, so the two string
# constraints it carries over - ``AdapterName`` and ``SuiteHash`` - are imported
# from ``assay.results`` rather than restated, and a report constructed directly (as several
# report tests do) gets the same guarantee as one ``build_report`` produced. ``Count`` is not
# on that public surface, so the count below is spelled inline rather than reaching into
# ``assay.results.models`` past it.
type TrialCount = Annotated[int, Field(ge=0)]


class Interval(SchemaModel):
    """A closed confidence interval on a proportion, ``low <= high``, both in ``[0, 1]``.

    Closed, not half-open: the endpoints are attainable values of the estimate, and whether
    two intervals that meet at a point count as overlapping is decided by :func:`overlaps`,
    not by an off-by-one in how the ends are spelled.

    M0 stores whatever interval it is handed; the Wilson computation that produces one lands
    in M4 (SPEC §7). Refusing a backwards interval here means a later bug in that arithmetic
    surfaces as a validation error rather than as a silent comparison against nonsense.
    """

    low: Proportion
    high: Proportion

    @model_validator(mode="after")
    def _check_ordered(self) -> Self:
        if self.low > self.high:
            raise ValueError(f"interval low {self.low} is above its high {self.high}")
        return self


def overlaps(a: Interval, b: Interval) -> bool:
    """Return whether two closed intervals share at least one point.

    Touching endpoints count: ``[0.4, 0.6]`` and ``[0.6, 0.8]`` overlap. The intervals are
    closed, so 0.6 is a value both estimates are consistent with, and a harness that ranked
    two tools on a hair's breadth of separation would be claiming more than it measured.
    """
    return a.low <= b.high and b.low <= a.high


class ToolSummary(SchemaModel):
    """One tool's scores over the whole task set, and the uncertainty around pass^n.

    pass^n leads and pass@1 is carried for comparability (SPEC §4). The interval is on
    pass^n because that is the number a comparison is decided on, and a number reported
    without its interval is what this project refuses to publish.
    """

    tool: AdapterName
    # Trials behind the summary, so a reader can see how little (or much) it rests on.
    trials: TrialCount
    pass_at_1: Proportion
    pass_caret_n: Proportion
    pass_caret_n_interval: Interval


class VerdictReason(StrEnum):
    """Why a comparison did or did not name a winner.

    A machine-readable reason rather than a sentence: the report's JSON is API, and the
    English for each member lives in :func:`format_verdict`, where it can be reworded
    without breaking a consumer.
    """

    INTERVALS_OVERLAP = "intervals_overlap"
    INTERVALS_DISJOINT = "intervals_disjoint"


class Verdict(SchemaModel):
    """The outcome of comparing two tools: a winner, or an explicit refusal to name one.

    ``winner`` and ``reason`` are required to agree. Making the overlap rule an invariant of
    the schema rather than a habit of :func:`decide_verdict` means a report that names a
    winner its intervals could not separate is not a document Assay can even construct.
    """

    # The winning tool's name, or null when the evidence does not separate the two.
    winner: AdapterName | None
    reason: VerdictReason

    @model_validator(mode="after")
    def _check_winner_matches_reason(self) -> Self:
        if self.reason is VerdictReason.INTERVALS_OVERLAP and self.winner is not None:
            raise ValueError(
                f"winner {self.winner!r} is named although the intervals overlap; "
                "overlapping intervals declare no winner (SPEC §4)"
            )
        if self.reason is VerdictReason.INTERVALS_DISJOINT and self.winner is None:
            raise ValueError("winner is null although the intervals are disjoint")
        return self


def decide_verdict(a: ToolSummary, b: ToolSummary) -> Verdict:
    """Compare two tools on pass^n and return the only winner claim Assay ever makes.

    This is the single winner rule in the codebase. Nothing downstream may re-derive one
    from the point estimates: a higher pass^n whose interval overlaps its rival's is not a
    better tool, it is a smaller sample (SPEC §4, KICKOFF item 6).
    """
    if overlaps(a.pass_caret_n_interval, b.pass_caret_n_interval):
        return Verdict(winner=None, reason=VerdictReason.INTERVALS_OVERLAP)
    ahead = a if a.pass_caret_n_interval.low > b.pass_caret_n_interval.high else b
    return Verdict(winner=ahead.tool, reason=VerdictReason.INTERVALS_DISJOINT)


def format_verdict(v: Verdict) -> str:
    """Render a verdict as the one sentence every renderer prints for it.

    JSON, HTML and text all call this, so the three cannot drift into three different
    claims about the same measurement.
    """
    if v.reason is VerdictReason.INTERVALS_OVERLAP:
        return "No winner: the pass^n confidence intervals overlap."
    return f"Winner: {v.winner} - its pass^n confidence interval is entirely above the other's."


class Comparison(SchemaModel):
    """One pairing of two tools, named by tool, and what comparing them concluded.

    The two tools are cited by name rather than embedded: their summaries are already in
    the report once, and a second copy could disagree with the first.
    """

    tool_a: AdapterName
    tool_b: AdapterName
    verdict: Verdict


class TaskLine(SchemaModel):
    """One recorded trial as the report shows it: which task, and how it ended.

    The provenance fields are ``None`` throughout M0, and that is absent information rather
    than a lookup this function skipped: a :class:`~assay.results.ResultSet` genuinely does
    not carry where a task came from. M1's miner is what supplies them. They are declared
    now, typed :data:`Redacted`, because a report is redacted by default (SPEC §5.4) and a
    field that could only ever hold a hashed value should say so in the schema rather than
    in a convention some later renderer has to remember.
    """

    # NOT pinned to TaskId, unlike the results schema's spelling of the same field. A report
    # line's id is repo-derived text that the redaction boundary covers, and the renderer
    # tests exercise it with values the mined-task shape rejects. Whether a report may name a
    # task the suite never minted is a schema question M1 answers; until it does, pinning
    # here would decide it by accident. See the open question in the M0 handoff.
    task_id: str
    repo_path: Redacted | None
    commit_subject: Redacted | None
    outcome: Outcome


class Report(SchemaModel):
    """Everything a rendered report shows, attributed to the suite it was measured on.

    ``suite_hash`` is carried straight from the result set: results are only comparable to
    other results from the same task set (SPEC §8.7), and a report that dropped the digest
    would be a table of numbers nobody could reproduce.

    ``intervals_are_placeholders`` is the machine-readable form of the M0 admission; the prose
    is :data:`STUB_INTERVAL_NOTICE`, printed by the renderers.
    """

    suite_hash: SuiteHash
    # True while every interval is the M0 placeholder band rather than a measurement. A
    # boolean, not a sentence: the wording lives in STUB_INTERVAL_NOTICE outside the schema,
    # so it can be reworded without breaking a consumer (see this module's docstring). No
    # default - a report that did not say whether its numbers were measured is exactly the
    # confident-untrustworthy document CLAUDE.md refuses to produce. M4 flips it to False.
    intervals_are_placeholders: bool
    tools: tuple[ToolSummary, ...]
    comparisons: tuple[Comparison, ...]
    tasks: tuple[TaskLine, ...]


def build_report(rs: ResultSet, summaries: tuple[ToolSummary, ...]) -> Report:
    """Assemble a report from a result set and the per-tool summaries computed for it.

    Every unordered pair of tools is compared once, in the order the summaries arrive.

    Results are copied through exactly as recorded - not deduplicated, not reordered. A
    repeated ``(task_id, adapter_name, trial_index)`` triple loads today by design, because
    what to do with one is an aggregation decision that lands in M4 (SPEC §7); collapsing it
    here would drop a measurement the store accepted, silently.

    Every M0 interval is a placeholder, so the report is built saying so; M4 flips this
    literal.

    Pure: no I/O, no git, no network, no clock.
    """
    comparisons = tuple(
        Comparison(tool_a=a.tool, tool_b=b.tool, verdict=decide_verdict(a, b))
        for a, b in combinations(summaries, 2)
    )
    tasks = tuple(
        TaskLine(
            task_id=result.task_id,
            repo_path=None,
            commit_subject=None,
            outcome=result.outcome,
        )
        for result in rs.results
    )
    return Report(
        suite_hash=rs.suite_hash,
        intervals_are_placeholders=True,
        tools=summaries,
        comparisons=comparisons,
        tasks=tasks,
    )


# The half-width of the invented band M0 puts around every pass^n. Module-private: it is an
# admission rather than a knob, and the notice below is the only place its value is quoted -
# spelling 0.25 as a literal there would let the arithmetic and the caption drift apart.
_STUB_HALF_WIDTH = 0.25

# Printed wherever an M0 interval is shown. When the Wilson computation lands in M4 (SPEC §7)
# this constant and :func:`stub_interval` must die in that same change: a measured interval
# still captioned "placeholder" lies in the other direction, and the renderers assert this
# text verbatim, so their tests are the tripwire that fires if it outlives the stub.
STUB_INTERVAL_NOTICE = (
    "M0 PLACEHOLDER - intervals are not measured. Every interval is pass^n "
    f"+/-{_STUB_HALF_WIDTH} clamped to [0, 1]: a fixed band that does not depend on the "
    "number of trials, and not a Wilson interval. It exists only so that the rule refusing "
    "a winner when intervals overlap (SPEC section 4) is exercised end to end. Real Wilson "
    "intervals land in M4."
)


def stub_interval(pass_caret_n: Proportion) -> Interval:
    """Return the placeholder band M0 reports around ``pass_caret_n``.

    This is the one symbol in Assay where a number is invented rather than measured, which
    is why it is a named function and not two ``max``/``min`` calls inside
    :func:`summarise`: M4 has a single seam to delete, and a grep for it finds every caller.
    It is deliberately not exported - nothing outside this module may manufacture an
    interval, and every M0 export is API that M4 would have to keep or break.

    Read :data:`STUB_INTERVAL_NOTICE` for what the band does and does not claim.
    """
    return Interval(
        low=max(0.0, pass_caret_n - _STUB_HALF_WIDTH),
        high=min(1.0, pass_caret_n + _STUB_HALF_WIDTH),
    )


def summarise(rs: ResultSet) -> tuple[ToolSummary, ...]:
    """Derive one :class:`ToolSummary` per tool from the trials a run recorded.

    Tools appear in the order the result set first mentions them, and so do the tasks within
    a tool: the numbers are a view of a file, and sorting them would make a report's column
    order stop matching the run it was rendered from.

    pass@1 is the mean over the tool's *tasks* of that task's pass rate, not the pooled
    ratio of passing trials to trials. Pooling would let a task that happened to be run more
    often carry more of the score, so two tools with different trial counts would be scored
    on differently weighted task sets while appearing to share a metric.

    Three things this deliberately does not do, each an M4 aggregation decision (SPEC §7):

    * A repeated ``(task_id, adapter_name, trial_index)`` triple counts as one more trial.
      Nothing raises and nothing is deduplicated - the store accepted the measurement, and
      dropping it here would be silent, which is the same stance :func:`build_report` takes.
    * ``errored`` is not a pass and is not removed from the denominator. Excluding harness
      failures would flatter the tool that crashes most.
    * ``not_scored`` is likewise counted and is likewise not a pass.

    Every interval is :func:`stub_interval`'s placeholder, not a measurement; see
    :data:`STUB_INTERVAL_NOTICE`.

    Pure: no I/O, no clock, and the same result set always gives the same summaries.
    """
    # tool -> task -> the outcomes recorded for that pairing, all in first-appearance order.
    outcomes_by_tool: dict[str, dict[str, list[Outcome]]] = {}
    for result in rs.results:
        by_task = outcomes_by_tool.setdefault(result.adapter_name, {})
        by_task.setdefault(result.task_id, []).append(result.outcome)

    return tuple(_summarise_tool(tool, by_task) for tool, by_task in outcomes_by_tool.items())


def _summarise_tool(tool: str, outcomes_by_task: dict[str, list[Outcome]]) -> ToolSummary:
    """Score one tool from its outcomes, grouped by task.

    No denominator can be zero here: a tool is only in the mapping because it has a result,
    and a task is only in it because it has a trial.
    """
    task_pass_rates = [
        sum(1 for outcome in outcomes if outcome is Outcome.PASSED) / len(outcomes)
        for outcomes in outcomes_by_task.values()
    ]
    fully_passed = sum(
        1
        for outcomes in outcomes_by_task.values()
        if all(outcome is Outcome.PASSED for outcome in outcomes)
    )
    pass_caret_n = fully_passed / len(outcomes_by_task)
    return ToolSummary(
        tool=tool,
        trials=sum(len(outcomes) for outcomes in outcomes_by_task.values()),
        pass_at_1=sum(task_pass_rates) / len(task_pass_rates),
        pass_caret_n=pass_caret_n,
        pass_caret_n_interval=stub_interval(pass_caret_n),
    )
