# ADR-0060: The local baseline is exempt from the baseline rule, and does not discharge it

- **Status:** Accepted
- **Date:** 2026-09-09
- **Deciders:** Bogdan Dzekic

## Context
CLAUDE.md fixes one rule about what a report must contain: **always include the naive baseline
adapter in every report — one raw model call, no agent loop. If the sophisticated tool cannot beat
it, that is the finding.** It is enforced in code rather than left to discipline, by
`_adapter_refusal` in `src/assay/cli/main.py`, which refuses a run naming a tool without
`--adapter naive` before the suite is read and long before an image exists.

The rule was written when there was exactly one baseline and calling it cost money. Both halves of
that sentence have now moved.

**The money half moved with ADR-0059.** A model served on this machine — Ollama on loopback —
answers a prompt for nothing, and `LocalModelTransport` is the transport that may call it. The
naive adapter answers to a second name over it, `naive-local`, because the same code asking the
same question of a different endpoint is a different tool and a report separates tools by name.

**The one-baseline half moved with it.** `--adapter` now offers two baselines, and a rule phrased
as "the naive baseline" no longer picks out a single row. Two questions fall out, and they are not
the same question:

1. A run of the two oracles and `naive-local` names no tool anybody is being asked to trust and
   spends nothing at all. Must it also name the metered `naive`?
2. A run of `agentic` and `naive-local` names a tool. Does the local baseline satisfy the rule?

The standing fact behind both is the one five milestone records already carry: **nothing in this
repository has ever called a model.** The paid run was cut from M3, from M4 and from M5
([ADR-0042](0042-the-readme-withdraws-the-promise-of-a-live-run.md),
[ADR-0051](0051-m5s-two-tools-are-two-oracles.md)), and no milestone owns it. So question 1 is
asked in a repository where "also name `naive`" means "do not run", and question 2 is asked in a
repository that would very much like a tool number to exist.

That second pressure is exactly why the answer has to be decided here, on the record, rather than
in whichever direction makes a run go green.

## Decision
**The exemption is asymmetric. `naive-local` is exempt from being *asked* for a baseline; it does
not *supply* one.** The refusal reads:

```python
if named - ORACLE_ADAPTERS - {LOCAL_NAME} and NAIVE_NAME not in named:
```

The subtraction answers question 1 with yes-it-may-run: `--adapter ground-truth --adapter null
--adapter naive-local` passes the refusal and needs no metered call. The second conjunct still
reads `NAIVE_NAME` and nothing else, which answers question 2 with no: `--adapter agentic
--adapter naive-local` is still refused, with the same sentence, still naming `naive`.

**The change is behaviour-neutral for every run that was expressible before it.** `LOCAL_NAME` was
not in `ADAPTER_NAMES` until this package, so no set of names a caller could previously type
contains it, and subtracting a member a set cannot hold removes nothing. Every existing case —
`agentic` alone refused, `agentic naive` accepted, the two oracles accepted — is decided by the
identical expression it was decided by before. `tests/cli/test_main.py` keeps those three
unedited and adds four, one of which is the first test the repeated-name half of the refusal has
ever had.

**The refusal's own sentence is unchanged and still demands `naive` by name.** It is not widened to
mention the local baseline, because a message that listed both names beside "must also name" would
read as an offer of either. What the local baseline is, and what it is not, is stated where a
caller meets it instead: in `--adapter`'s help text, which now says `naive-local` is the same call
to a model on this machine and does not stand in for `naive`.

**The reason is that a measurement rule you can satisfy by choosing your opponent is not a rule.**
A frontier agent measured against a 7B model running on a laptop, with that model occupying the row
a reader has been told is *the* baseline, is a flattering comparison — and flattering comparisons
are the specific failure this project exists to be incapable of producing. The rule's purpose is a
floor under the tool's number, not a ritual naming of some baseline or other, and a floor a tool
may pick for itself is not a floor.

## Alternatives considered
- **Let `naive-local` satisfy the rule when a tool is named.** Rejected, and this is the
  alternative the decision is really against. It is defensible on its face: the substitution is not
  hidden, since the row is labelled `naive-local` and the adapter's version string carries the
  model that answered, so a reader who checks can see what the tool was compared against. The
  objection is not visibility, it is incentive. Under that rule, every future run naming a tool has
  a free path and a paid path to the same green, the free one produces the larger margin, and
  nothing in the harness ever pushes back. This project's whole claim is that it tells whether an
  AI feature is genuinely working; a harness whose cheapest route is also its most flattering has
  conceded that claim in exchange for one runnable command.
- **Require both baselines whenever a tool is named.** Rejected as the same refusal wearing a
  stricter costume: `naive` is already required, so adding `naive-local` to the demand changes
  nothing about what is refused today and only makes a future paid run more expensive. If a live
  comparison ever happens, naming both is a good idea and remains one the caller may act on.
- **Exempt nothing: leave the rule exactly as it was, so the oracle-plus-local run is refused
  too.** Rejected because the refusal's own sentence would be false of that run. "A tool that
  cannot beat one raw model call is the finding" is about a tool, and a run of two oracles and one
  baseline names none — it would be refused for failing to buy a comparison it has nothing to
  compare. That is the rule spending money to protect a report that does not exist.
- **Add `naive` automatically instead of refusing, so the rule is satisfied by construction.**
  Rejected on the ground the existing docstring already gives: adding it would spend money nobody
  asked to spend, and a harness that opens a metered connection the operator did not name is worse
  than one that refuses.
- **Downgrade the rule to a warning printed with the report.** Rejected on CLAUDE.md, which puts
  the measurement rules in code "not left to discipline". A warning is discipline with extra steps,
  and the one reader who most needs it is the one who already decided to skip the baseline.
- **Add `naive-local` to `ORACLE_ADAPTERS` and let the existing exemption cover it.** Rejected as
  a lie about what it is. That frozenset means "answers from the task itself" — the recorded fix
  and nothing at all — and its members' outcomes are known before they run, which is what makes a
  bracket a bracket. The local baseline makes a real model call with a genuinely unknown result.
  It would also silently change every other reader of that set, `scripts/demo.py` among them,
  which takes the names it demonstrates from it.
- **A `--allow-local-baseline` escape hatch on the refusal.** Rejected twice over. A flag with no
  second reader is dead wiring, which this CLI has ruled against before (`DEFAULT_MAX_OUTPUT_TOKENS`
  carries the argument in its comment); and an escape hatch on a measurement rule is that rule's
  deletion, differing only in that the deletion is now the operator's fault.

## Consequences
**There is now a run in this repository that measures a real model and spends nothing:**
`--adapter ground-truth --adapter null --adapter naive-local`. It is runnable, not run — no daemon
has served this repository a completion, and the response shape `_parse_chat_completion` reads is
still documentation rather than measurement (ADR-0059).

**The agentic tool remains unmeasurable without money, deliberately.** This record does not close
the gap ADR-0042 opened and ADR-0051 restated; a tool comparison still costs a paid baseline, and
no milestone owns it. What the local baseline unblocks is a baseline against the oracles' bracket,
which is the first real signal this harness can get for free — not the tool number the README does
not claim to have.

**Both directions are tested, in the same file, at the same level.** The accepted case asserts the
run gets past the refusal and fails on the suite it was pointed at; the refused case asserts exit
1, one sentence on stderr, `--adapter naive;` inside it, and that the suite path is *not* mentioned
— which is how "the refusal arrived first" is asserted without a suite existing.

**A report can now say on its face which baseline was bought.** The two names are separate rows and
neither is renameable in silence, so a report holding `naive-local` and no `naive` states that the
metered baseline was not run, without a caveat anybody has to remember to write.

**Deletion path:** if the local baseline is never scored, the exemption is one subtraction in one
expression, and removing it restores the previous line character for character.
