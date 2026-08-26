# ADR-0010: Money is a `Decimal` at exactly six decimal places, and any other scale is refused

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
An attempt records what one trial cost (SPEC §4.2), and cost per solved task is the number the
report leads on for a buyer — the number they will check against an invoice.

Two constraints meet on that field. Floats have no stable canonical encoding, so
`canonical_json` refuses one anywhere in a document
([ADR-0008](0008-pydantic-v2-over-canonical-json.md)). And a content address is over *bytes*:
`1.5` and `1.500000` are the same number and a different document. A schema that accepted any
scale would therefore hand one measurement two content addresses, which is the precise ambiguity
content addressing exists to remove
([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)).

So the type alone is not enough. The *scale* has to be part of the contract.

## Decision
Money is a `Decimal`. `Attempt.cost_usd` and `Budget.max_usd` are `Decimal` with `ge=0`, and the
`_check_cost_scale` validator on `Attempt.cost_usd` refuses any value whose exponent is not
exactly -6, naming the offending amount: *money must be written to exactly six decimal places*.

Six decimal places is a microdollar — fine enough for per-token pricing on a single trial, coarse
enough that every adapter can hit it exactly. `model_dump(mode="json")` writes a `Decimal` as a
string, so money crosses the canonical boundary without ever becoming a float.

Producers write the scale out rather than relying on a coercion: the ground-truth adapter's
`_NO_COST` is `Decimal("0.000000")`, because `Decimal(0)` is the same number and a different
document.

## Alternatives considered
- **Quantize silently on ingest.** Rejected: it hides a caller's precision bug — an adapter
  computing in cents and passing `Decimal("0.02")` is wrong about its own arithmetic and would be
  normalised into looking right — and it makes the content address depend on Assay's
  normalisation rather than on the bytes the caller actually wrote.
- **Use `float`.** Rejected: money is the one number a buyer checks against an invoice, and
  binary floating point cannot spell most of the amounts on one. It is refused by
  `canonical_json` in any case, so a float would have to be stringified somewhere — at which
  point the scale question returns, unanswered, in a worse place.
- **Integer microdollars.** Rejected: it is the same six decimal places in disguise, with the
  unit removed from the type. Every producer and reader has to remember the scale factor, and a
  caller who passes cents makes a silent 10,000× error instead of triggering a validation
  failure.
- **Accept any scale and normalise only at hash time.** Rejected: it splits one contract across
  two layers. The schema would accept a document the hasher then rewrites, so what the caller
  wrote and what the address describes are different bytes, and the mismatch surfaces where
  nobody is looking.
- **Put the rule on `SchemaModel`, for every `Decimal`.** Rejected: money is the only `Decimal`
  in the schema today, and a base-class rule would claim a generality that does not exist — it
  would have to be argued out again the first time a non-money `Decimal` appears.

## Consequences
The refusal is user-visible and it is meant to be: an adapter author who writes `Decimal("0.02")`
gets an error naming the value, not a quietly rewritten result set.

A deliberate asymmetry to record: `Budget.max_usd` carries `ge=0` but *not* the scale validator.
The rule exists to keep a recorded measurement's bytes unique, and a budget is a ceiling a caller
sets rather than a measurement — no document the store writes carries a `Budget` at M0. If a
later milestone records the budget a trial ran under, which M3's n-trial runner plausibly wants,
the validator moves onto it in that change.

Not answered here: currency. The field is USD by its name only, there is no currency code, and
multi-currency accounting is not a question M0 has. It would be a new decision, and a schema
version bump, rather than an extra field slipped in.
