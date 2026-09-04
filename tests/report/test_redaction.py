"""The redaction boundary: a report carries evidence, never the repository (SPEC §5.4).

Assay is meant to run inside a customer's environment on a customer's private repository, and
the report is the one artefact that leaves it. So the property under test is not "paths are
usually hashed" but that a redacted report contains *no* repo-derived text at all: every
string in its serialised form is either a token from :func:`hash_token` or one of the few
values the report exists to publish - the suite digest, the tool names, and the enum members.
That whitelist is written out below rather than implied, so a field added to the schema in M1
fails this file until someone classifies it.

The last test is a static one. It asserts that mypy still refuses a raw ``str`` where a
:data:`Redacted` is required; the type fence is what stops the boundary being bypassed by a
renderer that never calls :func:`redact` at all.
"""

import re
from collections.abc import Iterator
from decimal import Decimal

import pytest
from pydantic import ValidationError

from assay.report import (
    Comparison,
    CostBasis,
    Interval,
    PairedTest,
    Redacted,
    RedactionPolicy,
    Report,
    TaskLine,
    ToolCost,
    ToolSummary,
    Verdict,
    VerdictReason,
    hash_token,
    redact,
)
from assay.results import Outcome

SUITE_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"

# ``p:`` / ``i:`` / ``m:`` from the kind, then twelve hex characters of HMAC-SHA256.
TOKEN = re.compile(r"^[pim]:[0-9a-f]{12}$")

RAW_PATH = "/home/alice/acquisition-target/src/pricing/margin.py"
RAW_SUBJECT = "fix margin rounding for the Northwind contract"
RAW_TASK_ID = "pricing-margin-rounding-4f21a9"

# The reader's own words about the reader's own prices. Not repo-derived, and deliberately not
# a real rate card: no price anybody could mistake for a maintained figure is written down in
# this repository (ADR-0046).
PRICES_SOURCE = "an invented rate card, quoted here so the report can be attributed"


def _policy(fill: int) -> RedactionPolicy:
    """A policy whose salt is fixed by the test, so a token can be compared across calls."""
    return RedactionPolicy(salt=bytes([fill]) * 32)


def _summary(tool: str, low: float, high: float) -> ToolSummary:
    return ToolSummary(
        tool=tool,
        trials=5,
        pass_at_1=high,
        pass_at_1_interval=Interval(low=high, high=high),
        pass_caret_n=low,
        pass_caret_n_interval=Interval(low=low, high=high),
    )


def _populated_report() -> Report:
    """A report with every string field filled, including the provenance M1 will supply.

    The raw values below wear the :data:`Redacted` type before anything has hashed them. That
    is the one place the claim is allowed to be false: :func:`redact` is what makes it true,
    and it runs between the miner that produces these values and any renderer that reads them.
    """
    tools = (_summary("ground-truth", 0.9, 1.0), _summary("null", 0.0, 0.1))
    return Report(
        suite_hash=SUITE_HASH,
        tools=tools,
        comparisons=(
            Comparison(
                tool_a="ground-truth",
                tool_b="null",
                verdict=Verdict(winner="ground-truth", reason=VerdictReason.INTERVALS_DISJOINT),
                paired=PairedTest(tasks_compared=2, only_tool_a=2, only_tool_b=0, p_value=0.5),
            ),
        ),
        costs=(
            ToolCost(
                tool="ground-truth",
                input_tokens=2_000_000,
                output_tokens=1_000_000,
                solved_tasks=2,
                input_usd_per_mtok=Decimal("100.000000"),
                output_usd_per_mtok=Decimal("200.000000"),
                total_usd=Decimal("400.000000"),
                usd_per_solved_task=Decimal("200.000000"),
                basis=CostBasis.PRICED,
            ),
            ToolCost(
                tool="null",
                input_tokens=0,
                output_tokens=0,
                solved_tasks=0,
                input_usd_per_mtok=Decimal("100.000000"),
                output_usd_per_mtok=Decimal("200.000000"),
                total_usd=None,
                usd_per_solved_task=None,
                basis=CostBasis.NO_TOKENS_RECORDED,
            ),
        ),
        prices_source=PRICES_SOURCE,
        tasks=(
            TaskLine(
                task_id=RAW_TASK_ID,
                repo_path=Redacted(RAW_PATH),
                commit_subject=Redacted(RAW_SUBJECT),
                outcome=Outcome.PASSED,
            ),
            TaskLine(
                task_id="second-task",
                repo_path=None,
                commit_subject=None,
                outcome=Outcome.FAILED,
            ),
        ),
    )


def _publishable(report: Report) -> set[str]:
    """The strings a redacted report may still carry verbatim, each one justified.

    The suite digest is the reproducibility anchor (SPEC §5.5) and is already a hash of the
    task set, not of the code. The tool names are the finding itself - a report shared with a
    vendor has to say which tool is theirs. The enum members are Assay's own vocabulary. The
    money and the source it was priced from came from the reader's own command line, and a
    hashed provenance would leave the dollars unattributable, which is the one thing SPEC §5.5
    asks of them. Nothing else in the document comes from anywhere but the repository under
    evaluation.
    """
    winners = {c.verdict.winner for c in report.comparisons}
    amounts = {
        str(amount)
        for cost in report.costs
        for amount in (
            cost.input_usd_per_mtok,
            cost.output_usd_per_mtok,
            cost.total_usd,
            cost.usd_per_solved_task,
        )
        if amount is not None
    }
    return (
        {report.suite_hash}
        | {s.tool for s in report.tools}
        | {c.tool_a for c in report.comparisons}
        | {c.tool_b for c in report.comparisons}
        | {w for w in winners if w is not None}
        | {cost.tool for cost in report.costs}
        | amounts
        | ({report.prices_source} if report.prices_source is not None else set())
        | {o.value for o in Outcome}
        | {r.value for r in VerdictReason}
        | {b.value for b in CostBasis}
    )


def _strings(value: object) -> Iterator[str]:
    """Every string *value* anywhere in a serialised report, however deeply nested.

    Keys are skipped: they are field names fixed in the schema's source, not text that came
    from the repository. A future field keyed *by* repo-derived text would need this walk
    widened along with it.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _strings(item)


def test_the_same_salt_and_input_always_produce_the_same_token() -> None:
    # Redaction has to be stable or the report becomes unreadable: two lines about the same
    # file must be recognisable as the same file by whoever receives the report.
    policy = _policy(0x11)

    first = hash_token(policy, "path", RAW_PATH)
    second = hash_token(policy, "path", RAW_PATH)

    assert first == second
    assert TOKEN.match(first)


def test_a_different_salt_produces_a_different_token_for_the_same_input() -> None:
    # The salt is what stops a recipient with a guess at the path from confirming it by
    # recomputing the hash, and what stops two reports from being cross-referenced.
    same_input = hash_token(_policy(0x11), "path", RAW_PATH)
    other_salt = hash_token(_policy(0x22), "path", RAW_PATH)

    assert same_input != other_salt


def test_the_same_text_under_different_kinds_produces_different_tokens() -> None:
    # The kind is inside the HMAC message as well as in the visible prefix, separated from the
    # text by a NUL: a path that happens to read like a commit subject must not collide with
    # it, and the separator keeps that true if a fourth kind is ever added.
    policy = _policy(0x11)
    shared = "src/pricing/margin.py"

    tokens = {hash_token(policy, kind, shared) for kind in ("path", "ident", "message")}

    assert len(tokens) == 3
    assert {t[0] for t in tokens} == {"p", "i", "m"}


def test_a_token_carries_a_kind_prefix_and_twelve_hex_characters() -> None:
    policy = _policy(0x11)

    assert TOKEN.match(hash_token(policy, "path", RAW_PATH))
    assert TOKEN.match(hash_token(policy, "ident", RAW_TASK_ID))
    assert TOKEN.match(hash_token(policy, "message", RAW_SUBJECT))


def test_an_empty_string_is_still_hashed_rather_than_passed_through() -> None:
    # Only ``None`` means "absent". An empty subject is a value, and a value gets a token.
    assert TOKEN.match(hash_token(_policy(0x11), "message", ""))


def test_a_policy_salt_must_be_thirty_two_bytes() -> None:
    with pytest.raises(ValidationError, match="salt"):
        RedactionPolicy(salt=b"too short")


def test_a_policy_may_not_be_constructed_without_a_salt() -> None:
    # No default: a policy that silently salted with a constant would redact nothing.
    with pytest.raises(ValidationError, match="salt"):
        RedactionPolicy.model_validate({})


def test_a_random_policy_is_thirty_two_bytes_and_differs_run_to_run() -> None:
    first = RedactionPolicy.from_random()
    second = RedactionPolicy.from_random()

    assert len(first.salt) == 32
    assert first.salt != second.salt


def test_the_salt_never_appears_anywhere_in_a_redacted_report() -> None:
    # The token is only unlinkable while the salt stays out of the artefact that ships.
    policy = _policy(0xAB)

    dumped = redact(_populated_report(), policy).model_dump_json()

    assert policy.salt.hex() not in dumped
    assert policy.salt.hex().upper() not in dumped
    assert policy.salt.decode("latin-1") not in dumped
    assert repr(policy.salt) not in dumped


def test_every_repo_derived_string_in_a_report_is_replaced_by_a_token() -> None:
    # Totality: this walks the whole serialised document rather than the fields the author
    # remembered, so a provenance field added in M1 fails here until redact() covers it.
    report = _populated_report()
    allowed = _publishable(report)

    redacted = redact(report, _policy(0x11))

    leaked = [
        s
        for s in _strings(redacted.model_dump(mode="json"))
        if s not in allowed and not TOKEN.match(s)
    ]
    assert leaked == []


def test_the_raw_values_are_absent_from_the_serialised_report() -> None:
    dumped = redact(_populated_report(), _policy(0x11)).model_dump_json()

    assert RAW_PATH not in dumped
    assert RAW_SUBJECT not in dumped
    assert RAW_TASK_ID not in dumped
    assert "alice" not in dumped
    assert "Northwind" not in dumped


def test_absent_provenance_stays_absent_rather_than_becoming_a_token() -> None:
    # A hashed ``None`` would invent evidence: it would read as "this task came from some
    # path we are not showing you" when in fact no path was ever recorded.
    redacted = redact(_populated_report(), _policy(0x11))

    assert redacted.tasks[1].repo_path is None
    assert redacted.tasks[1].commit_subject is None


def test_redaction_agrees_with_the_token_function_field_by_field() -> None:
    policy = _policy(0x11)

    line = redact(_populated_report(), policy).tasks[0]

    assert line.task_id == hash_token(policy, "ident", RAW_TASK_ID)
    assert line.repo_path == hash_token(policy, "path", RAW_PATH)
    assert line.commit_subject == hash_token(policy, "message", RAW_SUBJECT)


def test_the_findings_survive_redaction_unchanged() -> None:
    # A report nobody can act on is not a redacted report, it is a deleted one. The scores,
    # the interval and the winner are the whole point of shipping the document.
    report = _populated_report()

    redacted = redact(report, _policy(0x11))

    assert redacted.suite_hash == report.suite_hash
    assert redacted.tools == report.tools
    assert redacted.comparisons == report.comparisons
    assert [line.outcome for line in redacted.tasks] == [line.outcome for line in report.tasks]


def test_the_money_and_its_provenance_survive_redaction_verbatim() -> None:
    # The dollars are the reader's own arithmetic over the reader's own rates, and the source
    # is the reader's own sentence: none of it came from the repository under evaluation, and
    # a tokenised source would leave the money attributable to nothing at all (SPEC 5.5).
    report = _populated_report()

    redacted = redact(report, _policy(0x11))

    assert redacted.costs == report.costs
    assert redacted.prices_source == PRICES_SOURCE


def test_redacting_twice_with_one_policy_is_stable() -> None:
    # Two runs of the same report must ship the same tokens, or a recipient cannot tell a
    # re-run from a different task set.
    report = _populated_report()
    policy = _policy(0x11)

    assert redact(report, policy) == redact(report, policy)


def _render_repo_path(value: Redacted) -> str:
    """Stands in for a renderer: it accepts only text that came through the boundary."""
    return f"path {value}"


def test_a_raw_string_is_statically_rejected_where_a_redacted_one_is_required() -> None:
    # LOAD-BEARING IGNORE - do not delete. This is a static negative: the call below is the
    # bypass the boundary exists to prevent (a renderer handed an unredacted path), and the
    # ignore is the assertion that mypy --strict still rejects it. ``warn_unused_ignores``
    # is on (pyproject.toml), so if the Redacted fence ever stops rejecting a raw ``str``,
    # this ignore becomes unused and CI fails here. Deleting it deletes the check.
    rendered = _render_repo_path(RAW_PATH)  # type: ignore[arg-type]

    # It still runs: NewType is erased at runtime, which is exactly why the guarantee has to
    # be enforced statically rather than by a check inside the renderer.
    assert rendered.endswith(RAW_PATH)
    assert _render_repo_path(hash_token(_policy(0x11), "path", RAW_PATH)).startswith("path p:")
