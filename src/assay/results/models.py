"""The attempt, result and result-set schemas - what a trial records and a report reads.

An attempt is the cost and latency accounting SPEC §4.2 asks for: tokens, wall clock, tool
calls, retries and money. Money is a ``Decimal`` written to exactly six decimal places. A
float has no stable canonical encoding, and two spellings of one amount - ``1.5`` and
``1.500000`` - would give the same measurement two content addresses, so the scale is fixed
rather than left to whoever computed it.

The suite schema's rules carry over. No field has a default, so a document and the model
built from it correspond key for key and re-encode to the bytes they were read from. Nothing
is normalised on the way in: a value that would re-encode differently is refused rather than
quietly rewritten. And an outcome is carried, never computed here - the scorer that decides
one lands in M2 (SPEC §7).

Pure: validation only, no I/O. Result-set files live in :mod:`assay.results.store`.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from assay.core import HASH_PREFIX, SchemaModel

# Six decimal places is a microdollar: fine enough for per-token pricing on a single trial,
# coarse enough that every adapter can hit it exactly.
_COST_EXPONENT = -6

# The address :func:`assay.core.content_hash` writes, pinned exactly: the ``sha256:``
# prefix and 64 lowercase hex digits. Two reasons, either sufficient. An abbreviated or
# uppercased digest cannot be checked against the suite whose results it attributes
# (SPEC §5.5); and this value is interpolated into the text report verbatim, so an
# unconstrained one can carry a newline and render a fabricated section beneath it -
# including a Comparisons block naming a winner nothing measured, the one claim this
# project exists to make impossible (CLAUDE.md).
_SUITE_HASH_PATTERN = rf"^{HASH_PREFIX}[0-9a-f]{{64}}$"

# An adapter name is a tool's name rather than an identifier this schema mints, so it stays
# free text with one requirement: it prints as a single line. No C0 or C1 control
# character, no DEL, neither Unicode line separator, and not empty. The text report prints
# one tool per row, name first, so a name carrying a newline renders a second row for a
# tool that ran nothing, scored however the name spells it.
_ADAPTER_NAME_PATTERN = r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029]+$"

# The same shape :mod:`assay.suite.models` pins on a mined task's id, spelled again rather
# than imported: a result set is read on its own, by a build that may never load the suite it
# attributes, so the results schema does not depend on the suite package for its own
# guarantees. The duplication is held closed by a test that asserts the two patterns are
# character-for-character identical, so a change to one fails until the other follows.
_TASK_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"

# All three constraints live here, at the schema, and not in the renderer that prints them:
# escaping in one format would leave every other format - and the ones M4 has yet to
# write - to rediscover the same hole. Only the HTML page escapes today.

# Counts of things that happened. None of them can be negative, and all of them are ints
# rather than floats because a float cannot be canonicalised (ADR-0008).
type Count = Annotated[int, Field(ge=0)]

# One tool's name, wherever it is recorded. A result names its adapter twice - itself and
# in the attempt it carries - and the two must agree, so both spellings take the same
# constraint rather than leaving the cross-check to carry it.
type AdapterName = Annotated[str, Field(pattern=_ADAPTER_NAME_PATTERN)]

# The suite a result set is attributed to, as the address :func:`assay.core.content_hash`
# writes it.
type SuiteHash = Annotated[str, Field(pattern=_SUITE_HASH_PATTERN)]

# One mined task's id, wherever it is recorded. Like an adapter name, a result carries it
# twice - itself and in the attempt it carries - and the text report prints it as the first
# column of a trial row, so an unpinned one forges a row the same way an unpinned adapter
# name forges a tool.
type TaskId = Annotated[str, Field(pattern=_TASK_ID_PATTERN)]


def _six_decimal_places(amount: Decimal) -> Decimal:
    """Return ``amount`` unchanged, or refuse a money value this schema cannot spell uniquely.

    Rounding here instead would re-encode a document to bytes it was not written with, and
    accepting any scale would let two equal amounts serialise two ways - each with its own
    content address, which is the ambiguity content addressing exists to remove.
    """
    if amount.as_tuple().exponent != _COST_EXPONENT:
        raise ValueError(f"money must be written to exactly six decimal places, found {amount}")
    return amount


class Budget(SchemaModel):
    """The ceiling one trial runs under, handed to an adapter (SPEC §6).

    Every cap is optional in type but required in the document: ``X | None`` means a caller
    that does not want a ceiling has to write ``null`` and say so. An absent key and a
    deliberately uncapped run must not be the same document, because the second is a policy
    and the first is a mistake.

    ``max_wall_clock_s`` has no ``None`` case at all: a trial that may run forever is not a
    measurement anyone can repeat.
    """

    max_wall_clock_s: int = Field(gt=0)
    max_input_tokens: Count | None
    max_output_tokens: Count | None
    max_tool_calls: Count | None
    # Decimal, never float: money is the one number a buyer checks against an invoice.
    max_usd: Decimal | None = Field(ge=0)


class Outcome(StrEnum):
    """How a trial ended.

    ``errored`` is the harness or the adapter failing, which is not the same as the tool
    producing a wrong answer; ``not_scored`` is a trial that ran but that no executable
    signal could rank (SPEC §4), and it is reported rather than counted as a failure.
    """

    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"
    NOT_SCORED = "not_scored"


class Attempt(SchemaModel):
    """One adapter's run against one task: the diff it produced and what it cost.

    ``adapter_version`` is recorded next to ``adapter_name`` because a tool that changed
    between two runs is a different tool, and a report that cannot say which one it measured
    is not reproducible.

    ``diff`` is ``""`` when the adapter produced no change at all - the null adapter's whole
    output, and the floor every real result is read against.
    """

    schema_version: Literal[1]
    adapter_name: AdapterName
    adapter_version: str
    task_id: TaskId
    # 0..n-1 over the n trials this task was run for (SPEC §4, default n=5).
    trial_index: Count
    diff: str
    input_tokens: Count
    output_tokens: Count
    wall_clock_ms: Count
    tool_calls: Count
    retries: Count
    cost_usd: Decimal = Field(ge=0)
    # The reason a trial produced nothing usable, or null when it produced something.
    error: str | None

    @field_validator("cost_usd")
    @classmethod
    def _check_cost_scale(cls, cost_usd: Decimal) -> Decimal:
        return _six_decimal_places(cost_usd)


class Result(SchemaModel):
    """One scored trial: the attempt, and the outcome that was recorded for it.

    The trial is named twice - here, and inside ``attempt`` - because each is readable on its
    own, so the two are required to agree. A result whose attempt belongs to another task
    attributes a measurement to a trial that did not produce it (SPEC §5.5).

    At M0 ``outcome`` is whatever the document says: there is no scorer yet, and inventing
    one here would put an unexecuted claim in a report.
    """

    schema_version: Literal[1]
    task_id: TaskId
    adapter_name: AdapterName
    trial_index: Count
    attempt: Attempt
    outcome: Outcome

    @model_validator(mode="after")
    def _check_attempt_is_this_trial(self) -> Self:
        if self.attempt.task_id != self.task_id:
            raise ValueError(
                f"attempt task_id {self.attempt.task_id!r} is not the result's {self.task_id!r}"
            )
        if self.attempt.adapter_name != self.adapter_name:
            raise ValueError(
                f"attempt adapter_name {self.attempt.adapter_name!r} "
                f"is not the result's {self.adapter_name!r}"
            )
        if self.attempt.trial_index != self.trial_index:
            raise ValueError(
                f"attempt trial_index {self.attempt.trial_index} "
                f"is not the result's {self.trial_index}"
            )
        return self


class ResultSet(SchemaModel):
    """Everything one run produced, and the suite it produced it against.

    ``suite_hash`` is the attribution: results are only comparable to other results from the
    same task set, and a regression between two runs is a tool change only if that digest
    stayed the same (SPEC §8.7). Its shape is pinned to the one
    :func:`assay.core.content_hash` writes, so a digest a report shows is one that could
    have addressed something.

    ``schema_version`` sits on the envelope because :func:`assay.results.store.read_result_set`
    probes it before parsing anything, and a top-level key this model did not declare would
    make every valid file fail under ``extra="forbid"``.
    """

    schema_version: Literal[1]
    suite_hash: SuiteHash
    results: tuple[Result, ...]
