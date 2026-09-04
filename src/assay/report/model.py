"""The report schema, and the one place in Assay that decides which tool won.

Two rules shape everything here. The first is SPEC §4: when two confidence intervals
overlap, the report declares no winner. That decision is taken once, in
:func:`decide_verdict`, and every renderer reads the :class:`Verdict` it produced - a
renderer that compared two numbers itself could publish a ranking the statistics do not
support, which is the exact failure this project exists to avoid.

That rule holds against a second statistic, which is the thing worth noticing here. A report
also carries the exact McNemar p for each pairing (:class:`PairedTest`), and a small p is not a
licence to name a winner the overlapping intervals refused. The p answers "did these two tools
differ on the tasks they were both given"; the ranking answers "is either one better by enough
to publish", and only the second question decides a :class:`Verdict`. :func:`decide_verdict`
never sees a p-value, which is why it cannot be talked into using one (ADR-0005, ADR-0044).

It holds against money in the same way. A report also carries what each tool spent per task it
solved (:class:`ToolCost`), and a cheaper tool does not thereby win: Assay ranks on executable
signal alone (CLAUDE.md), so :func:`decide_verdict` never sees a dollar either. What a cost
line does carry beside its amounts is a :class:`CostBasis` - the reason an amount is absent -
because every adapter in this repository records zero tokens today, and printing $0.00 for a
tool nobody instrumented is exactly the confident number nobody should trust (ADR-0046).

The second is that prose is not part of the schema. A :class:`Verdict` carries a machine
reason; the English sentence is built by :func:`format_verdict`, outside the document. Once
a report's JSON is public it is API (CLAUDE.md), and a headline string would freeze one
wording as a compatibility promise. :func:`format_paired` is the same arrangement for the
paired test - a p printed with no stated reading is read as whichever claim the reader
expected - and :func:`format_basis` for the reason a cost line has no dollars in it.

A report is the one Assay document that is deliberately *not* content-addressable: an
interval is a float, floats have no stable canonical encoding (ADR-0008), so a report is
rendered rather than hashed.

Pure: this module builds models from models. No I/O, no git, no clock.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from itertools import combinations
from typing import Annotated, NewType, Self

from pydantic import Field, model_validator

from assay.core import AssayError, SchemaModel
from assay.results import AdapterName, Outcome, ResultSet, SuiteHash
from assay.stats import bootstrap_mean_interval, mcnemar_exact_p, wilson_interval

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

# A count of tasks, for the three integers a paired test reads. Negative is not a small count,
# it is a pairing that went wrong upstream, and a p derived from one would be a number nobody
# measured - the same stance :func:`assay.stats.mcnemar_exact_p` takes on its own arguments.
type TaskCount = Annotated[int, Field(ge=0)]

# A probability. Constrained like :data:`Proportion` and named separately because it is not one:
# a p-value is not a fraction of anything the report counted, and the two must not be averaged,
# compared or plotted against each other by a later renderer that saw the same type.
type PValue = Annotated[float, Field(ge=0.0, le=1.0)]

# A count of tokens, as the trials recorded them. Every adapter in this repository writes zero
# here today, which is why a cost line has to say whether a zero means "spent nothing" or "not
# instrumented" rather than pricing it (ADR-0046).
type TokenCount = Annotated[int, Field(ge=0)]

# Money, wherever a report carries it: never negative, and never finer than the microdollar
# ADR-0010 fixed for an attempt's cost. A Decimal rather than a float because money is the one
# number a buyer checks against an invoice, and the scale is bounded because a total quoted to
# more places than the trials could distinguish is a precision nobody measured.
USD_DECIMAL_PLACES: int = 6
type Usd = Annotated[Decimal, Field(ge=0, decimal_places=USD_DECIMAL_PLACES)]

# Prices are quoted per million tokens, so the totals divide by this. Per-token would be
# unspellable at six places: a tool billed under a dollar per million tokens prices at zero
# (ADR-0046).
TOKENS_PER_MTOK: int = 1_000_000

# What a report may print about where its prices came from: free text, held to one rule - it
# prints as a single line. The value is interpolated verbatim into the text report, so one
# carrying a newline renders a fabricated section beneath the heading it was printed under.
# The shape is the one ``assay.results`` pins on an adapter name, spelled again rather than
# imported: this is a different field with the same requirement, and borrowing that constant
# would make a change to the results schema a silent change to this one.
type PriceSource = Annotated[str, Field(pattern=r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029]+$")]

# The two inputs to every bootstrap band Assay prints, fixed here rather than in
# :mod:`assay.stats`: that package is a leaf and has no standing to set a reporting policy, so
# :func:`assay.stats.bootstrap_mean_interval` demands both and defaults neither.
#
# 2000 is the conventional floor for a 95% percentile interval - the band's width is set by how
# many tasks were mined, not by how many times they were resampled, and beyond a couple of
# thousand draws the endpoints only stop jittering in digits the report does not print.
BOOTSTRAP_RESAMPLES: int = 2000

# A frozen constant, and deliberately not a CLI flag. A seed a run could vary is a knob on a
# measurement: run it enough times and one draw gives the flattering band, which is exactly the
# band-shopping this repository exists to refuse (CLAUDE.md). The value is the date the decision
# was taken, so it is obviously arbitrary rather than tuned.
BOOTSTRAP_SEED: int = 20260904


class Interval(SchemaModel):
    """A closed confidence interval on a proportion, ``low <= high``, both in ``[0, 1]``.

    Closed, not half-open: the endpoints are attainable values of the estimate, and whether
    two intervals that meet at a point count as overlapping is decided by :func:`overlaps`,
    not by an off-by-one in how the ends are spelled.

    The band itself is computed by :func:`assay.stats.wilson_interval`, which knows nothing
    about reports. Refusing a backwards interval here means a bug in that arithmetic surfaces
    as a validation error rather than as a silent comparison against nonsense.
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
    """One tool's scores over the whole task set, and the uncertainty around each of them.

    pass^n leads and pass@1 is carried for comparability (SPEC §4). Both carry a band, and the
    two bands are not the same instrument. pass^n is the fraction of tasks every trial of which
    passed - a binomial proportion over tasks - so it gets a Wilson interval. pass@1 is the mean
    of the per-task pass rates, which is not a proportion at all, so a Wilson band on it would
    be arithmetic applied to the wrong shape of number (ADR-0035); its uncertainty is the
    uncertainty of the task sample, estimated by a percentile bootstrap over tasks (ADR-0043).

    Both bands are reported at 95%, and the renderers name both procedures, because two bands
    printed side by side read as one measurement taken twice unless the report says otherwise.
    Only the pass^n band decides a ranking.
    """

    tool: AdapterName
    # Trials behind the summary, so a reader can see how little (or much) it rests on.
    trials: TrialCount
    pass_at_1: Proportion
    pass_at_1_interval: Interval
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


class PairedTest(SchemaModel):
    """The exact McNemar test over the tasks two tools were both given.

    Only the tasks in both tools' task sets are compared, and of those only the ones the tools
    disagreed about carry anything: a task both solved, or neither, is evidence about the suite
    rather than about the tools (see :mod:`assay.stats.mcnemar`). ``tasks_compared`` is carried
    alongside the two discordant counts so a reader can see how much of the run the p rests on -
    a p from three shared tasks and a p from three hundred are not the same claim.

    Solved means pass^n: every trial of that task passed. Counting on pass@1 would make a task
    one tool half-passed count as a disagreement, and the report would be testing a different
    metric than the one its verdict is decided on.

    The p-value is here and the winner is not. A significant p says these two tools differ; it
    does not say either is better by enough to publish, and it may not be read as licence for a
    ranking the pass^n intervals refused (ADR-0005, ADR-0044). :func:`format_paired` prints that
    reading beside the number, because a p with no stated meaning acquires one from the reader.
    """

    tasks_compared: TaskCount
    only_tool_a: TaskCount
    only_tool_b: TaskCount
    p_value: PValue

    @model_validator(mode="after")
    def _check_discordant_within_compared(self) -> Self:
        discordant = self.only_tool_a + self.only_tool_b
        if discordant > self.tasks_compared:
            raise ValueError(
                f"{discordant} discordant tasks were counted over only "
                f"{self.tasks_compared} tasks_compared; the tasks one tool solved and the "
                "other did not are a subset of the tasks both tools ran"
            )
        return self


class Comparison(SchemaModel):
    """One pairing of two tools, named by tool, and what comparing them concluded.

    The two tools are cited by name rather than embedded: their summaries are already in
    the report once, and a second copy could disagree with the first.

    ``verdict`` and ``paired`` answer different questions and are kept apart on purpose. The
    verdict is the ranking, decided on the two pass^n intervals alone; the paired test is
    whether the tools differed at all on the tasks they shared. A report can carry a significant
    p and no winner, and that pairing of values is the intended output rather than a defect.
    """

    tool_a: AdapterName
    tool_b: AdapterName
    verdict: Verdict
    paired: PairedTest


def format_paired(comparison: Comparison) -> str:
    """Render a comparison's paired test as the one sentence every prose renderer prints for it.

    Never names a winner, in any of its three cases. The sentence states what the test measured
    and hands the ranking back to the intervals, because a p sitting silently beside "No winner"
    reads as either coyness or a licence and the reader picks whichever they came in with
    (ADR-0035 refuses unexplained output; ADR-0044 fixes this wording).

    Takes the whole :class:`Comparison` rather than the :class:`PairedTest`, so the tool names
    in the sentence are the ones the comparison was built from. Copying them into the paired
    test would put a second spelling of each name in the document, and two copies can disagree.
    """
    paired = comparison.paired
    if paired.tasks_compared == 0:
        return "no shared tasks; no paired comparison"
    if paired.only_tool_a + paired.only_tool_b == 0:
        return "the tools solved the same tasks; nothing to test"
    # "1 tasks" is a grammatical error in a document whose subject is precision, and a paired
    # test over a single discordant task is a case this repository's suites reach often. The
    # second clause has no noun to agree with - it is the first clause's, elided - so it keeps
    # the bare number ADR-0044 fixed for it.
    tasks = "task" if paired.only_tool_a == 1 else "tasks"
    return (
        f"{comparison.tool_a} solved {paired.only_tool_a} {tasks} {comparison.tool_b} did not, "
        f"and {comparison.tool_b} solved {paired.only_tool_b} {comparison.tool_a} did not "
        f"(exact McNemar p = {paired.p_value:.4f}). This measures whether they differ, not "
        "which ranks higher - ranking is the pass^n intervals' decision alone."
    )


class CostOutOfRangeError(AssayError):
    """A computed cost is too large to round to the scale money is reported at.

    A rate can pass every rule a rate has - a number, at or above zero, no finer than a
    millionth of a dollar - and still multiply out to a figure :mod:`decimal` cannot quantise
    inside its context's precision. That is a refusal about the price somebody supplied, so it
    is one of Assay's own errors carrying its own sentence, rather than ``decimal``'s signal
    escaping to a caller: ``str(InvalidOperation)`` is ``[<class 'decimal.InvalidOperation'>]``,
    which tells a reader nothing about what they typed (ADR-0048).

    It names no flag. This module is pure logic and must not learn that a command line exists;
    the CLI frames the sentence with the file it was rendering.
    """


def quantize_usd(amount: Decimal) -> Decimal:
    """Round a computed amount to the microdollar a report prints money at (ADR-0010).

    ``ROUND_HALF_UP`` rather than the banker's rounding :mod:`decimal` defaults to, and never
    down: an amount that lands halfway is reported as the larger one, because between two
    readings of what a tool cost this project takes the one that does not flatter it. The same
    rule makes a sub-microdollar spend round up to a microdollar rather than disappear.

    Raises :class:`CostOutOfRangeError` when the amount is too large to round at all. ``from
    None`` because the signal carries nothing the sentence lacks: ``InvalidOperation`` is
    raised with no message, so chaining it would append the repr this refusal exists to keep
    out of a user's terminal.
    """
    try:
        return amount.quantize(Decimal(1).scaleb(-USD_DECIMAL_PLACES), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise CostOutOfRangeError(
            f"a computed cost of {amount:.3E} cannot be rounded to the microdollar money is "
            "reported at - the price supplied is larger than any figure a report can state"
        ) from None


class ToolPrice(SchemaModel):
    """What one tool's tokens cost, in dollars per million, as somebody supplied them.

    Assay knows no prices. This is the reader's own figure, handed to ``assay report`` at the
    moment the report is rendered and never recorded anywhere: a table baked into this
    repository would be a maintained public price list that decays silently, and a dollar
    computed at trial time would freeze a rate into a result set that outlives it (ADR-0046).

    Per million tokens rather than per token, because a per-token rate is unspellable at six
    decimal places: every tool billed under a dollar per million would price at exactly zero.
    """

    tool: AdapterName
    input_usd_per_mtok: Usd
    output_usd_per_mtok: Usd


class PriceTable(SchemaModel):
    """The prices one report was rendered against, and the reader's own name for them.

    ``source`` is required and free text - "the vendor's published list, 2026-09-04", "our
    negotiated rate" - because a dollar figure whose provenance the report cannot state is a
    number nobody can check, and SPEC §5.5 asks that a result be reproducible from what the
    report says. It is carried through redaction verbatim: it came from the reader, not from
    the repository under evaluation, so hashing it would destroy the only attribution the
    dollars have.

    Unlike every other schema here this one carries no ``schema_version``. There is no
    document: a price table is assembled from repeated ``--price`` flags and exists for the
    length of one command, so a version key would be a compatibility promise about a file
    Assay neither writes nor reads (ADR-0046).
    """

    source: PriceSource
    prices: tuple[ToolPrice, ...]

    @model_validator(mode="after")
    def _check_each_tool_is_priced_once(self) -> Self:
        seen: set[str] = set()
        for price in self.prices:
            if price.tool in seen:
                raise ValueError(
                    f"two prices name the tool {price.tool!r}; a report has one row per tool, "
                    "so a second rate for one of them is an answer to a question nobody can "
                    "tell from the first"
                )
            seen.add(price.tool)
        return self

    def price_for(self, tool: str) -> ToolPrice | None:
        """The price supplied for ``tool``, or ``None`` when the table does not mention it.

        A partial table is a normal thing to supply: a reader who is pricing one vendor's tool
        against a baseline they run themselves has a rate for one of them. The tool without a
        rate is reported as unpriced rather than as free.
        """
        return next((price for price in self.prices if price.tool == tool), None)


class CostBasis(StrEnum):
    """Why a cost line carries the amounts it carries - and, more often, why it does not.

    Four states, all of them live in this repository today rather than defensive: no price was
    supplied (the default, and what every report without a ``--price`` flag says); no tokens
    were recorded (every adapter here hard-codes zero, so a spend of zero is indistinguishable
    from an uninstrumented one); no tasks were solved (the null adapter, in every report, and
    any tool that burns tokens on a suite it cannot solve); priced.

    A machine reason rather than a sentence, like :class:`VerdictReason`: the English for each
    member lives in :func:`format_basis`, outside the document that is API.
    """

    PRICED = "priced"
    NO_PRICE_SUPPLIED = "no_price_supplied"
    NO_TOKENS_RECORDED = "no_tokens_recorded"
    NO_TASKS_SOLVED = "no_tasks_solved"


# Which of a cost line's four amounts each basis promises: the two rates, the total, and the
# cost per solved task. The table *is* the invariant, and it reads as a staircase - each basis
# carries everything the one above it does and one thing more. Rates come first because a rate
# is what the reader supplied rather than what Assay derived, which is why they are present
# even in the ``no_tokens_recorded`` case: a price was given, the tokens were not.
_BASIS_AMOUNTS: dict[CostBasis, tuple[bool, bool, bool, bool]] = {
    CostBasis.NO_PRICE_SUPPLIED: (False, False, False, False),
    CostBasis.NO_TOKENS_RECORDED: (True, True, False, False),
    CostBasis.NO_TASKS_SOLVED: (True, True, True, False),
    CostBasis.PRICED: (True, True, True, True),
}

_AMOUNT_FIELDS = ("input_usd_per_mtok", "output_usd_per_mtok", "total_usd", "usd_per_solved_task")


class ToolCost(SchemaModel):
    """What one tool spent, what it spent per task it solved, and why either number is absent.

    The nullable-amount-plus-reason arrangement :class:`Verdict` uses for the winner, applied
    to money. Collapsing the four bases into two nullable decimals would print ``$0.00`` for a
    tool whose spend was never instrumented, and a confident number nobody should trust is
    worse than no number (CLAUDE.md). It would also lose the distinction that matters to the
    reader: "you gave me no price" is theirs to fix, "this adapter records no tokens" is
    Assay's documented gap, and the report is the only place that gap is visible.

    The rates the line priced with travel with it, so the dollars can be re-derived from the
    report alone (SPEC §5.5) rather than from a command line nobody kept.

    ``input_tokens`` and ``output_tokens`` are totals over *every* recorded trial, errored
    ones included: a trial that crashed spent what it spent before it crashed, and excluding
    those would price the tool that fails most as the cheapest one (ADR-0031).

    Cost ranks nothing. It sits beside the verdict, never inside it - Assay ranks on
    executable signal, so the cheaper of two tools has not thereby won anything.
    """

    tool: AdapterName
    input_tokens: TokenCount
    output_tokens: TokenCount
    # Tasks solved at pass^n: every recorded trial of the task passed. The same definition the
    # ranking and the paired test use, so the report does not acquire a third one (ADR-0044).
    solved_tasks: TaskCount
    input_usd_per_mtok: Usd | None
    output_usd_per_mtok: Usd | None
    total_usd: Usd | None
    usd_per_solved_task: Usd | None
    basis: CostBasis

    @model_validator(mode="after")
    def _check_basis_matches_the_amounts(self) -> Self:
        carried = (
            self.input_usd_per_mtok is not None,
            self.output_usd_per_mtok is not None,
            self.total_usd is not None,
            self.usd_per_solved_task is not None,
        )
        promised = _BASIS_AMOUNTS[self.basis]
        disagreeing = [
            field
            for field, want, got in zip(_AMOUNT_FIELDS, promised, carried, strict=True)
            if want != got
        ]
        if disagreeing:
            raise ValueError(
                f"basis {self.basis.value!r} disagrees with this line's amounts: "
                f"{', '.join(disagreeing)} is the wrong way round. The basis is the reason an "
                "amount is absent, so a line whose basis and amounts disagree describes two "
                "different measurements"
            )
        return self


def format_basis(cost: ToolCost) -> str:
    """Render a cost line's basis as the one sentence every prose renderer prints for it.

    Every basis gets a sentence, including :attr:`CostBasis.PRICED`, because the dollars are
    the reader's own arithmetic rather than a rate Assay verified and the report should not
    let them read as a quoted price. The three absences get one for ADR-0035's reason: an
    omission is stated, never left as a blank the reader fills in.
    """
    if cost.basis is CostBasis.NO_PRICE_SUPPLIED:
        return f"no price was supplied for {cost.tool}, so no dollar figure is shown"
    if cost.basis is CostBasis.NO_TOKENS_RECORDED:
        return (
            f"{cost.tool} recorded no tokens, so what it spent is unknown rather than zero - "
            "every adapter Assay ships today reports zero here"
        )
    if cost.basis is CostBasis.NO_TASKS_SOLVED:
        return (
            f"{cost.tool} solved no tasks, so it has a total and no cost per solved task - "
            "dividing by zero solved tasks is not an infinite price, it is no measurement"
        )
    return f"{cost.tool} is priced at the rates supplied with this report, and at nothing else"


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

    ``costs`` is always present and always has one line per tool, whether or not anybody
    supplied a price. A section that appeared only when it had dollars in it would make its
    absence the report's way of saying something, which is the unexplained blank ADR-0035
    refuses by name; ``prices_source`` is null in exactly that case and names the reader's own
    provenance otherwise.
    """

    suite_hash: SuiteHash
    tools: tuple[ToolSummary, ...]
    comparisons: tuple[Comparison, ...]
    costs: tuple[ToolCost, ...]
    prices_source: PriceSource | None
    tasks: tuple[TaskLine, ...]


def build_report(
    rs: ResultSet, summaries: tuple[ToolSummary, ...], prices: PriceTable | None = None
) -> Report:
    """Assemble a report from a result set and the per-tool summaries computed for it.

    Every unordered pair of tools is compared once, in the order the summaries arrive, and each
    pairing carries two answers to two questions: a :class:`Verdict`, which ranks, and a
    :class:`PairedTest`, which does not.

    The paired test is derived from ``rs`` rather than from the summaries. A summary is a
    whole-suite score and has already forgotten which tool solved which task, which is the only
    thing a paired test reads; the same grouping :func:`summarise` builds is rebuilt here from
    the same results, so the two cannot disagree. A tool the result set does not mention pairs
    over zero shared tasks: p = 1.0, which the sentence reads as "no comparison", not "no
    difference".

    Results are copied through exactly as recorded - not deduplicated, not reordered. A
    repeated ``(task_id, adapter_name, trial_index)`` triple loads today by design, because
    what to do with one is an aggregation decision that lands in M4 (SPEC §7); collapsing it
    here would drop a measurement the store accepted, silently.

    ``prices`` defaults to none supplied, which is a report with a costs section reading
    ``no_price_supplied`` on every row rather than a report without one. Assay has no prices of
    its own to fall back on, and a default rate would be a number this project invented
    (ADR-0046).

    Pure: no I/O, no git, no network, no clock.
    """
    outcomes_by_tool = _group_by_tool(rs)
    comparisons = tuple(
        Comparison(
            tool_a=a.tool,
            tool_b=b.tool,
            verdict=decide_verdict(a, b),
            paired=_paired_test(a.tool, b.tool, outcomes_by_tool),
        )
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
        tools=summaries,
        comparisons=comparisons,
        costs=_tool_costs(rs, outcomes_by_tool, prices),
        prices_source=None if prices is None else prices.source,
        tasks=tasks,
    )


def _tool_costs(
    rs: ResultSet, outcomes_by_tool: dict[str, dict[str, list[Outcome]]], prices: PriceTable | None
) -> tuple[ToolCost, ...]:
    """One cost line per tool, in the order the result set first mentions each one.

    The same order as the scores, because they are read across from each other, and it comes
    from the same grouping :func:`summarise` and :func:`_paired_test` read - a second traversal
    that sorted differently would put a tool's cost on another tool's row.

    Tokens are summed here rather than taken off a :class:`ToolSummary`, which does not carry
    them, and the sum spans every recorded trial including the errored ones (ADR-0031).
    """
    tokens_by_tool: dict[str, tuple[int, int]] = {}
    for result in rs.results:
        so_far = tokens_by_tool.get(result.adapter_name, (0, 0))
        tokens_by_tool[result.adapter_name] = (
            so_far[0] + result.attempt.input_tokens,
            so_far[1] + result.attempt.output_tokens,
        )
    return tuple(
        _cost_line(
            tool=tool,
            tokens=tokens_by_tool[tool],
            solved_tasks=sum(1 for outcomes in by_task.values() if _solved(outcomes)),
            price=None if prices is None else prices.price_for(tool),
        )
        for tool, by_task in outcomes_by_tool.items()
    )


def _cost_line(
    tool: str, tokens: tuple[int, int], solved_tasks: int, price: ToolPrice | None
) -> ToolCost:
    """Price one tool's tokens, or say which of the four things stopped it being priced.

    The branch order is load-bearing and settled (ADR-0046). No price first, because without
    one nothing else can be computed. No tokens second, before any arithmetic, because a tool
    that recorded ``(0, 0)`` is ambiguous between "spent nothing" and "was never instrumented"
    and Assay cannot tell the two apart at report time - so it reports neither. The total is
    computed next, and only then does a solved count of zero suppress the per-task figure: a
    tool that burned tokens on a suite it did not solve has a real total and no denominator,
    and dropping the total there would hide the spend that makes the finding interesting.
    """
    input_tokens, output_tokens = tokens
    total_usd: Decimal | None = None
    usd_per_solved_task: Decimal | None = None
    if price is None:
        basis = CostBasis.NO_PRICE_SUPPLIED
    elif input_tokens == 0 and output_tokens == 0:
        basis = CostBasis.NO_TOKENS_RECORDED
    else:
        total_usd = quantize_usd(
            (input_tokens * price.input_usd_per_mtok + output_tokens * price.output_usd_per_mtok)
            / TOKENS_PER_MTOK
        )
        if solved_tasks == 0:
            basis = CostBasis.NO_TASKS_SOLVED
        else:
            basis = CostBasis.PRICED
            usd_per_solved_task = quantize_usd(total_usd / solved_tasks)
    return ToolCost(
        tool=tool,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        solved_tasks=solved_tasks,
        input_usd_per_mtok=None if price is None else price.input_usd_per_mtok,
        output_usd_per_mtok=None if price is None else price.output_usd_per_mtok,
        total_usd=total_usd,
        usd_per_solved_task=usd_per_solved_task,
        basis=basis,
    )


def _paired_test(
    tool_a: str, tool_b: str, outcomes_by_tool: dict[str, dict[str, list[Outcome]]]
) -> PairedTest:
    """Count the tasks two tools disagreed about, and test whether that split is lopsided.

    Shared tasks only. A task one tool never ran has no second measurement to disagree with,
    and treating an absent trial as a failure would score a tool on a task it was not given.

    ``mcnemar_exact_p`` is called unguarded: it accepts any two non-negative counts, including
    the zeroes this produces for tools with no tasks in common, and returns 1.0 for them.
    """
    a_tasks = outcomes_by_tool.get(tool_a, {})
    b_tasks = outcomes_by_tool.get(tool_b, {})
    shared = [task for task in a_tasks if task in b_tasks]
    only_a = sum(1 for task in shared if _solved(a_tasks[task]) and not _solved(b_tasks[task]))
    only_b = sum(1 for task in shared if _solved(b_tasks[task]) and not _solved(a_tasks[task]))
    return PairedTest(
        tasks_compared=len(shared),
        only_tool_a=only_a,
        only_tool_b=only_b,
        p_value=mcnemar_exact_p(only_a, only_b),
    )


def _solved(outcomes: list[Outcome]) -> bool:
    """Whether a tool solved a task, in the one sense a comparison uses: pass^n.

    Every recorded trial of the task passed. One flaky success out of five is not a solved
    task, and the paired test has to read the same metric the ranking is decided on.
    """
    return all(outcome is Outcome.PASSED for outcome in outcomes)


def _group_by_tool(rs: ResultSet) -> dict[str, dict[str, list[Outcome]]]:
    """Group a result set's outcomes by tool and then by task, in first-appearance order.

    The shape both halves of a report are derived from: :func:`summarise` reads it down the
    tasks of one tool, :func:`_paired_test` reads it across the tasks two tools share. Ordering
    is the order the file mentions each tool and each task, so a report's columns match the run
    it was rendered from rather than an alphabet.
    """
    outcomes_by_tool: dict[str, dict[str, list[Outcome]]] = {}
    for result in rs.results:
        by_task = outcomes_by_tool.setdefault(result.adapter_name, {})
        by_task.setdefault(result.task_id, []).append(result.outcome)
    return outcomes_by_tool


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

    Each score gets the band its shape allows: Wilson over tasks for pass^n (ADR-0035), a
    percentile bootstrap over the same tasks for pass@1 (ADR-0043). The reasoning is on
    :class:`ToolSummary`.

    Pure: no I/O, no clock, and the same result set always gives the same summaries - including
    the bootstrap band, which draws from a fixed seed rather than from the shared RNG.
    """
    return tuple(_summarise_tool(tool, by_task) for tool, by_task in _group_by_tool(rs).items())


def _summarise_tool(tool: str, outcomes_by_task: dict[str, list[Outcome]]) -> ToolSummary:
    """Score one tool from its outcomes, grouped by task.

    No denominator can be zero here: a tool is only in the mapping because it has a result,
    and a task is only in it because it has a trial - which is also what lets the two interval
    calls below be unguarded. Wilson refuses a zero denominator and the bootstrap refuses an
    empty sample; this caller cannot present either.
    """
    task_pass_rates = [
        sum(1 for outcome in outcomes if outcome is Outcome.PASSED) / len(outcomes)
        for outcomes in outcomes_by_task.values()
    ]
    fully_passed = sum(1 for outcomes in outcomes_by_task.values() if _solved(outcomes))
    tasks = len(outcomes_by_task)
    # Tasks, not trials, in both the numerator and the denominator: pass^n is the fraction of
    # tasks every trial of which passed, which is a binomial proportion over tasks. Handing
    # Wilson the trial count would narrow the band by rerunning one task (ADR-0035).
    low, high = wilson_interval(successes=fully_passed, trials=tasks)
    # The bootstrap resamples the *tasks*, for the same reason: the sample whose uncertainty is
    # worth reporting is the handful of tasks the miner happened to accept, not the trials run
    # on them. Both endpoints are means the tasks could have produced, so the band cannot leave
    # [0, 1] and :class:`Interval` will not have to clamp one.
    at_1_low, at_1_high = bootstrap_mean_interval(
        task_pass_rates, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED
    )
    return ToolSummary(
        tool=tool,
        trials=sum(len(outcomes) for outcomes in outcomes_by_task.values()),
        pass_at_1=sum(task_pass_rates) / len(task_pass_rates),
        pass_at_1_interval=Interval(low=at_1_low, high=at_1_high),
        pass_caret_n=fully_passed / tasks,
        pass_caret_n_interval=Interval(low=low, high=high),
    )
