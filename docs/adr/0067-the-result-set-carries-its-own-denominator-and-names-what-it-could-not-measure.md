# ADR-0067: The result set carries its own denominator and names the tasks it could not measure

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Bogdan Dzekic

## Context

A run of the harness ends by writing one result-set file, and every number a report prints is
read back out of it. Until now that file said only which trials happened:

```python
schema_version: Literal[1]
suite_hash: SuiteHash
results: tuple[Result, ...]
```

Three trials for each of twelve tasks and three trials for each of twelve tasks out of a
thirteen-task suite produce **the same document**. Nothing in it distinguishes a whole run from a
short one, and `pass^n` computed over it is a rate whose denominator the reader cannot check.
CLAUDE.md's measurement rules name that exact failure on the mining side — *"Report yield, not
just totals"* — and `MiningYield` already answers it in the same words this record borrows:

> CLAUDE.md forbids reporting the task count alone, so the denominator travels with the
> numerator in one value rather than being reassembled by whoever prints it.
> — `src/assay/mine/models.py:207-208`

The run side had no equivalent, and the live `jd/tenacity` run of 2026-09-10 is what made the
absence concrete: one task of thirteen could not have an image built for it. Under the user's
ruling the run publishes twelve of thirteen and **names the thirteenth**. A file that cannot
express "twelve of thirteen, and here is the one and why" cannot carry that ruling.

This record covers the schema only. The loop that fills the fields is ADR-0068 and ADR-0069; the
report that prints them is ADR-0070.

## Decision

`ResultSet` (`src/assay/results/models.py:197`) gains two fields and one validator:

```python
suite_task_count: int = Field(ge=0)
unprovisioned: Mapping[TaskId, str] = Field(default_factory=dict)
```

**The denominator is stored, not derived.** There is no path from a result set back to the suite
it was measured against. `run_report` takes `results: Path` and nothing else
(`src/assay/cli/main.py:668`), and `assay.results.store` exposes no lookup from a `SuiteHash` to
the suite that hashes to it — a `grep -n "def .*suite" src/assay/results/store.py` returns
nothing. The digest is an attribution, not an address anything in this repo can resolve. So the
denominator travels in the document exactly as `commits_examined` does.

**It is required, not defaulted.** A file that omits it would otherwise validate to zero, and a
zero denominator beside twelve measured tasks is a lie the schema itself told. Omission now fails
at parse time (`test_a_result_set_document_may_not_omit_the_denominator`).

**`unprovisioned` is a mapping, not a tuple of models,** for the reason
`MiningYield.rejected: Mapping[GateRejection, int]` (`src/assay/mine/models.py:220`) is one: the
value is a per-key fact, the key is the thing being accounted for, and a key listed twice is
unrepresentable by construction rather than by a validator anyone has to write. The value is the
sentence saying why — the build error, in the words the failure produced.

**`unprovisioned` is the one defaulted field in this module,** and the module docstring now says
so. It defaults for the reason `MiningYield.unprovisioned` defaults to zero
(`src/assay/mine/models.py:236`): every M0–M5 fixture and both oracle result sets were written
before the run loop could record an unmeasured task, and they state the same coverage they always
did. The fixtures still spell it explicitly, so the byte-identical round trip in
`test_a_hand_written_result_set_round_trips_to_byte_identical_canonical_bytes` stays exact.

**The validator lives on the model,** not in the writer, for ADR-0011's and ADR-0014's reason: a
result set is read back from a file by a build that did not write it, and a rule only the producer
enforces is a rule a hand-edited or future-written document escapes.

**It compares with `<=`, where `MiningYield._check_partition` uses `!=`
(`src/assay/mine/models.py:267`). The divergence is deliberate.** A mining yield is written once,
after the walk finishes, so anything other than an exact partition of `commits_examined` is a
counting bug. A result set is rewritten in full after every task (ADR-0069), so a file covering
one task of thirteen is the normal state of a run in progress — the *only* durable record while
the run is alive. Demanding equality would make every intermediate write invalid and force the
loop back to writing once at the end, which is the behaviour the 2026-09-10 run lost 105 trials
to. What is still refused is the direction that can lie: more coverage claimed than the suite
holds, and a task counted on both sides at once.

**No schema bump.** The change is additive against `schema_version: Literal[1]`: one new required
key and one defaulted key. Version 1 documents in the tree gain the required key in this same
package, and a version 1 document from outside it fails loudly on the missing denominator rather
than being silently read as a complete run — which is the intended noise, not a migration.

## Alternatives considered

**An `UnprovisionedTask` model — `task_id` plus `reason`, held in a tuple.** Rejected in a razor
pass on the plan that proposed it. It is a two-field record whose first field is the key it would
be looked up by, so it buys a class, an import and an `extra="forbid"` surface in exchange for
making "this task appears twice with two different reasons" *representable*. The mapping makes
that document impossible to write. Where a genuine second attribute appears later — a timestamp,
a phase — the model can be reintroduced then, against a real field.

**Derive the denominator: give `assay report` a `--suite` argument and count the suite's tasks.**
Rejected on three counts. It makes a report's coverage depend on a file the caller happens to
point at, so two readers of the same result set can print different denominators — the exact
ambiguity content addressing exists to remove (ADR-0007). It requires the suite to still exist and
still be reachable at report time, which nothing guarantees. And the correct denominator is *the
number of tasks the run was launched over*, which is a fact about the run; reading it off a suite
file later re-derives it from a different artefact and calls the answer the same.

**Store a count of unmeasured tasks and nothing else**, mirroring `MiningYield.unprovisioned:
int`. Rejected against user ruling 1: the run must **name** the thirteenth task, not report that
there was one. A count discloses the shortfall's size and withholds the only part a reader can act
on.

**Let the file stay silent and put the coverage caveat in the report's prose.** Rejected. A caveat
a renderer adds is a caveat a second renderer omits, and the JSON output would carry the bare
numerator to anything downstream. CLAUDE.md's rules are "enforced in code, not left to
discipline"; the schema is where that enforcement lives (ADR-0011).

**Compute coverage from `results` alone — measured tasks are the ones with trials.** Rejected as
circular: it defines the denominator as the numerator and can never be short.

## Consequences

**A result set is now self-describing about its own coverage.** Any reader — the report builder,
a future format, a human with `jq` — can state "twelve of thirteen" from the file alone, with the
thirteenth named. Nothing downstream needs the suite.

**Every existing construction site had to state its denominator, and mypy made that mandatory
rather than optional.** Seven `ResultSet(` call sites plus three JSON fixtures
(`result_set_minimal.json` at 1, `results_overlapping.json` at 4, `results_disjoint.json` at 5 —
the distinct task ids each holds) were updated in this package. `uv run --frozen mypy --strict src
tests` reports `Success: no issues found in 113 source files`, and a missed site would have been a
type error, not a silent zero.

**This decision is inert on its own.** Nothing writes `unprovisioned` yet — the run loop that does
is ADR-0068/0069, and the report that publishes it is ADR-0070. Landing it first is what lets
those two be separate, revertible packages; reverting them leaves this schema in place with a
defaulted field nobody fills, and no migration.

**The exactness the module docstring promised is now qualified.** "No field has a default" was a
property of this module and is now a property of every field but one. The docstring states the
exception and its reason rather than leaving a reader to discover it from the model.

**`unprovisioned` is now shared vocabulary between the mine and the run**, and the two are not the
same measurement: `MiningYield.unprovisioned` counts commits whose workspace could not be given an
environment (`src/assay/mine/models.py:236`), this names suite tasks a run could not measure. They
describe the same kind of failure at two different stages. ADR-0066 already owes a milestone on
the provisioning asymmetry between those stages; this record makes the shared name deliberate
rather than accidental, and does not close that gap.
