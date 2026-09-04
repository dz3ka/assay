# ADR-0046: A cost line carries the reason it has no dollars, and the costs section is always printed

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
SPEC §4.2 records what a trial spent and SPEC §7 puts *cost per solved task* in M4's exit
criteria. The arithmetic is the easy half: tokens times a rate, divided by the tasks the tool
solved. Everything difficult here is about what the report may say when one of those three
numbers is not available — and in this repository, today, one of them never is.

**No adapter records tokens.** `null.py`, `ground_truth.py` and `agentic.py` all hard-code zero
input and output tokens, and `naive.py` records zero on its error paths. Every result set Assay
has ever written therefore carries `(0, 0)` for at least one tool, and that pair is genuinely
ambiguous: it is what a tool that spent nothing looks like, and it is also what a tool nobody
instrumented looks like. At report time the two are indistinguishable. Multiplying the pair by a
rate and printing `$0.00` would put the cheapest number in the report against the tool Assay
knows least about — the confident number nobody should trust that CLAUDE.md names as worse than
no harness at all.

**Assay has no prices, and must not acquire any.** A rate table committed here would be a public
price list nobody is maintaining, decaying silently in the one repository whose subject is
measurement honesty; and a dollar figure computed at trial time would freeze a quote into a
result set that outlives it. The user's ruling for M4 is explicit: prices are supplied at report
time, result sets record token counts only, and no pricing number enters any file in this
repository — not source, not fixture, not a docstring example that reads as real.

**Money already has a scale.**
[ADR-0010](0010-money-is-a-decimal-at-six-decimal-places.md) writes money as a `Decimal` at
exactly six decimal places, which cannot spell a per-token rate at all: every
tool billed under a dollar per million tokens would price at exactly zero.

**And two standing rules constrain the output.**
[ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md) fixed that an omission or an
asymmetry is stated, never left blank for the reader to fill in.
[ADR-0005](0005-no-winner-when-intervals-overlap.md) and
[ADR-0044](0044-the-paired-test-is-exact-mcnemar-on-pass-caret-n.md) fixed that the pass^n
intervals decide the ranking alone — a rule that has to survive the arrival of a second number
a reader would happily rank on.

## Decision
**Prices arrive on the command line, a cost line carries a `CostBasis` saying why an amount is
absent, and the costs section is printed in every report whether or not anybody supplied a
price.**

**Where prices come from.** `assay report` takes `--price TOOL=INPUT/OUTPUT`, repeatable once
per tool, in dollars per million tokens, and `--prices-source TEXT` naming where the reader got
them. The two are required together in both directions: dollars with no stated source cannot be
attributed (SPEC §5.5), and a source that priced nothing describes a table the report does not
carry. `ToolPrice` and `PriceTable` are pure frozen models in `report/model.py` — no file, no
reader, no `schema_version`, and no new `SchemaKind`, because there is no document. The table
keys on adapter name, which is what the report's rows are keyed by and what a buyer reasons
about; nothing parses `adapter_version`'s embedded model suffix.

**What a cost line says.** `ToolCost` carries the token counts, the tasks solved, the two rates
it priced with, the total, the cost per solved task — and a `CostBasis`, which is a machine
reason with the same nullable-value-plus-reason invariant `Verdict` holds the winner to. Four
states, every one of them live in this repository today rather than defensive:
`no_price_supplied`, `no_tokens_recorded`, `no_tasks_solved`, `priced`. The invariant is a table
in the schema, and the model refuses a line whose basis and amounts disagree.

**The branch order is load-bearing.** No price → no tokens (input and output both zero) →
compute the total → no tasks solved → priced. So a *priced null adapter is
`no_tokens_recorded`*, with no total at all rather than a total of zero; and a tool that burned
tokens on a suite it did not solve keeps its total and loses only the ratio, because that total
is the finding and dividing by no solved tasks is not an infinite price, it is no measurement.
Totals cover every recorded trial including errored ones, the denominator
[ADR-0031](0031-an-errored-trial-never-leaves-the-denominator.md) already fixed for the scores,
and are quantised `ROUND_HALF_UP` so a reported cost never understates the one incurred.

**The section is unconditional.** Without prices every row reads `no_price_supplied` and states
it in prose through `format_basis`, in both formats a person reads; JSON carries the enum member
and no sentence, which is where an English wording is allowed to live (ADR-0005). "Solved" means
pass^n throughout, so the cost denominator, the ranking and the paired test describe one
quantity.

**Cost ranks nothing.** `decide_verdict` never sees a dollar. Assay ranks on executable signal
(CLAUDE.md), so the cheaper of two tools has not thereby won anything, and the caption above the
costs table says so.

## Alternatives considered
- **A user-supplied JSON price table read from a path** — the plan's original shape, and the
  richer one. Rejected in the razor pass: it opens the `report` package's first filesystem I/O,
  mints a document format Assay would then have to stay compatible with, and carries four
  loader-error tests — all to do what a repeatable keyed flag does without any of it. A
  `schema_version` on a file the *user* authors is also a compatibility promise Assay is in no
  position to keep.
- **One `--input-price/--output-price` pair.** Simpler, and the target D7 originally knocked
  down. Rejected because it cannot price two adapters differently, and every report contains at
  least two adapters by CLAUDE.md's naive-baseline rule.
- **Ship a price table in the repository.** Rejected twice over: it decays into a stale public
  price list, and it is the one thing the user's ruling forbids outright.
- **Compute dollars at trial time into `Attempt.cost_usd`.** Rejected: it freezes a quote into a
  result set that outlives it, and it prices a run against whatever the rate was on the day
  rather than against the rate the reader is deciding with.
- **Two nullable decimals and no reason.** The obvious smaller schema. Rejected because it
  cannot tell "you gave me no price" — the reader's to fix — from "this adapter records no
  tokens", which is Assay's own documented gap, and the report is the only place that gap ever
  becomes visible.
- **Price the zero-token tools anyway and print `$0.00`.** Rejected: it is a confident number
  produced from an absence, and it would rank the least instrumented tool cheapest. Suppressing
  a genuinely zero cost for the null adapter costs nothing, because nobody buys a null adapter.
- **Test `no_tasks_solved` before `no_tokens_recorded`.** The order the plan first wrote, and a
  defect the razor pass caught: the null adapter has both zero tokens *and* zero solved tasks,
  so that order labels it `no_tasks_solved` and then has to suppress a total it never computed.
- **Omit the costs section when no price was supplied.** Rejected: it reproduces exactly the
  unexplained blank ADR-0035 refuses, and it makes the report's contents depend on its own
  inputs in a way a reader has to reverse-engineer.
- **Per-token rates instead of per-million.** Rejected as arithmetic: unspellable at ADR-0010's
  six decimal places.
- **Let cost break a tie the intervals could not.** Rejected for the same reason ADR-0044
  rejected it for the p-value: it is ADR-0005's failure mode reached by a route that looks
  economic instead of statistical.

## Consequences
**No price number exists anywhere in this repository, and the tests are written so that none is
ever tempting.** The fixtures price at $100 and $200 per million tokens — plainly nobody's rate,
and divisible by hand, which is what the test comments do.

**Every report Assay can render today reads `no_price_supplied` or `no_tokens_recorded`.** The
priced path is exercised only by fixtures. That is not a gap being hidden: it is the gap being
*printed*, in the one artefact a reader sees, in a sentence naming the adapters as the reason.
When an adapter starts recording tokens, its rows become `priced` with no code change here.

**`Report` gains two required keys, `costs` and `prices_source`, and loses none.** A real
public-schema change, safe only because a report is rendered rather than read back
([ADR-0008](0008-pydantic-v2-over-canonical-json.md),
[ADR-0034](0034-wilson-lands-in-m3-and-the-placeholder-is-deleted.md)).

**A report's dollars can be re-derived from the report alone.** The rates travel on each cost
line, not only in the command that produced it, which is what `prices_source` on its own could
not deliver.

**`assay report` grows two flags and one refusal that exits `EXIT_USAGE` rather than
`EXIT_FAILED`** — a malformed price is a command line, like `--limit 0` and `--trials 0` before
it, and it lands before the result set is opened.
