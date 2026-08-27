# ADR-0011: String constraints live on the schema, not in the renderers

- **Status:** Accepted
- **Date:** 2026-08-27
- **Deciders:** Bogdan Dzekic

## Context
A report is printed three ways in M0 — JSON, HTML and text — and M4 adds more. Two of the three
build their output by interpolating model fields into a line-oriented document, so a string that
carries a newline does not merely look wrong: it *is* structure. `adapter_name` holding
`"claude\n| forged | 1.000 |"` writes a table row, and a reader has no way to tell the forged row
from a measured one.

The same hole was found half-open twice during M0, which is why this is a record and not a habit.
The first pass pinned `suite_hash` and `adapter_name` on `ResultSet`. The second found three more
fields of the same class still free — `Verdict.winner`, `Comparison.tool_a` and `tool_b` — and
`winner` is the worst of them, because it is read by `format_verdict`
([`report/model.py:155`](../../src/assay/report/model.py)), the one sentence *every* renderer
prints. The shortest path from an unpinned string to a fabricated ranking ran through the function
written specifically so the three renderers could not disagree about the result.

## Decision
A constraint that protects the document is a property of the **data**, declared once as a `type`
alias in `assay.results.models` — `AdapterName`, `SuiteHash` and `TaskId`
([`results/models.py:64`, `:68`, `:74`](../../src/assay/results/models.py)) — and **imported** by
the report schema rather than restated there. The report schema is downstream of the results
schema by design, so it takes the constraint the way it takes the type.

A value that could forge a line is therefore not constructible, and no renderer has to remember to
escape anything. The tests that hold this attack the models **directly**
(`tests/report/test_schema_constraints.py`), not through `build_report`.

## Alternatives considered
- **Escape in each renderer.** Rejected: it is the design that produced the bug twice. Three
  renderers is three places to remember, M4's formats are not written yet, and the failure is
  silent — an unescaped field renders as a plausible document, not as an error.
- **Escape once in a shared helper every renderer calls.** Rejected: better, but it only holds for
  as long as every renderer routes through it, and nothing in the type system says it must. It
  also cannot express *rejection* — an adapter name containing U+2028 is a bad name, not a name
  needing careful printing.
- **Validate in `build_report` only.** Rejected, and this is where the second hole actually lived:
  a report built by `build_report` already inherited the guarantee from the result set, so the
  gap was invisible until the report models were attacked on their own. Reports are constructed
  directly by tests today and by callers tomorrow.
- **Sanitise on the way in — strip the newline rather than refuse the value.** Rejected: silently
  rewriting a tool's name makes the report disagree with the run that produced it, and a caller
  passing a malformed name has a bug that should surface at the boundary.

## Consequences
Renderers M4 has yet to write inherit the guarantee without knowing it exists, which is the point.

**One field is deliberately exempt, and the exemption is load-bearing.** `TaskLine.task_id` is
bare `str`. `_redact_task_line` ([`report/redact.py:100`](../../src/assay/report/redact.py))
assigns `hash_token(policy, "ident", line.task_id)` straight back into the field, and reports are
redacted by default (SPEC §5.4) — so in the common case the field holds an HMAC token whose `i:`
prefix the mined-task-id shape rejects. A redacted task id is not a task id. Pinning it to
`TaskId` fails 25 tests for a real reason, and a comment at the field says so. Whether the report
schema should distinguish "a mined id" from "a token standing in for one" is left open for M1,
whose miner is what supplies provenance; deciding it here would decide it by accident.

**A regex-engine caveat rides along.** pydantic v2 defaults to `rust-regex`, where `$` is
end-of-haystack. Under `python-re`, `$` also matches before a trailing newline — so every pattern
here would admit a trailing newline if `model_config` ever set `regex_engine="python-re"`. The
patterns cannot spell `\z` and `\Z` in one expression, so the defence is explicit
trailing-newline cases in the test suite rather than the pattern text.
