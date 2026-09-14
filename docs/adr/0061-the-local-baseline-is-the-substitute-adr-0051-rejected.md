# ADR-0061: The local baseline is the substitute ADR-0051 rejected, named, over a constant endpoint

- **Status:** Accepted
- **Date:** 2026-09-09
- **Deciders:** Bogdan Dzekic

## Context
Two days ago [ADR-0051](0051-m5s-two-tools-are-two-oracles.md) settled what M5 was allowed to say
about a release that had never called a model, and rejected six ways of making it say more. The
sixth is this record's whole subject, quoted verbatim from that file's lines 105–109:

> **Substitute a free or locally hosted model so that something answers a prompt.** Rejected: it
> changes what was measured without changing what may be claimed. The in-container allowlist
> targets `api.anthropic.com` and has never been exercised against it, `naive.py`'s cost path
> records what an API reported and would be recording something else, and a headline number
> produced by an unnamed substitute is a worse artefact than the absence of one.

That rejection was right about M5 and it is being overturned here, so the ground it stood on has to
be stated exactly. It carries three objections: the substitute would be **unnamed**; the
**allowlist** it needs is one nothing has exercised; and the **cost path** would record something
other than what it says it records. None of the three is an objection to the idea of a free model.
All three are objections to an artefact — a number in a published report whose provenance the
document does not carry.

**What moved is that the substitute can now be named.** On 2026-09-07 there was one naive adapter,
one name, one transport and one endpoint, so pointing it at a local daemon would have produced a
row labelled `naive` holding a number no reader could attribute. Since then
[ADR-0059](0059-a-local-model-gets-its-own-transport-not-a-wider-allowlist.md) has given the local
call a transport of its own that cannot carry a key and cannot reach anything but loopback, and the
naive adapter answers to a second name over it. The substitution is no longer a silent swap behind
one row; it is a second row, and this package is what puts it on the command line.

**ADR-0051's ordering rule is not weakened by any of this — it is what makes the overturn
possible.** "The record says what produced them before it prints them" is exactly the discipline
being satisfied: the record here says what produced the number, in the name, before there is a
number.

There is a second decision in this package that belongs with the first, because it is the same
question asked about the endpoint rather than the model: **where the local call is allowed to go,
and who may change it.** ADR-0059's `_checked_local_endpoint` refuses anything but `http` at the
literal `127.0.0.1` — but it permits **any port**, because a daemon's port is a local matter. So
the check alone does not decide whether the operator may point the prompt at a listener of their
choosing on this machine. The CLI does, by whether the endpoint is a constant or a flag.

## Decision
**Assay ships the substitute ADR-0051 rejected, under the three conditions that answer its three
objections, and this record is where each is discharged.**

**1. It is named, three times over.** `naive-local` is a member of `ADAPTER_NAMES`, so it is one of
`--adapter`'s printed choices; it is the `adapter_name` on every `Attempt` and every `Result` in
the result set on disk, which is the document a report is computed from; and it is the row name a
report prints, unhashed, because redaction hashes repository-derived text and never tool names
(ADR-0009). The model itself is recorded beside it: the adapter's version is
`0.1.0+qwen2.5-coder:7b`, since the model *is* the tool. Nothing in this path can produce a number
whose provenance the artefact does not carry, which is the property 0051's objection asked for.

**2. The in-container allowlist is untouched, because this adapter starts no container.** The
naive baseline is built in `_adapters_needing_no_image` and drives a transport, not a process: its
one call is made on the host through `host/model_api.py`, the only module in `src/assay` that may
open a socket. `ALLOWED_HOSTS` is unchanged and still holds `api.anthropic.com` alone (ADR-0059).
The agent image and its `--network bridge` adapter phase are built only when `agentic` is named
(`_task_adapters`), and the measurement phase every trial is scored in is still `--network none`.
A `naive-local` run therefore exercises no allowlist at all rather than an unexercised one, which
is a stronger answer than 0051's objection asked for.

**3. The cost path records absence rather than a zero.** Assay stores no prices (ADR-0046); a rate
enters only through `--price TOOL=IN/OUT`, so a report over local trials lands on
`NO_PRICE_SUPPLIED` and prints the sentence for it. The token counts are the daemon's own, read
strictly (ADR-0059) and never defaulted. So the cost path records what it has always recorded —
what the endpoint reported, and the reason there are no dollars — rather than something else.

**And the endpoint is a compiled-in constant, not a flag.** `LOCAL_MODEL_ENDPOINT` sits beside
`MODEL_ENDPOINT` in `cli/main.py` and carries the same argument in a sharper form: **an endpoint a
command line can redirect is one the prompt can be redirected to, and the prompt carries the
repository under evaluation.** `_checked_local_endpoint` would still refuse a non-loopback URL, so
the flag could not send the repository off this machine — but it permits any port, and a port on
this machine is where a tunnel, a proxy or a forwarder listens. The exfiltration control would then
be one hop away from an operator's typo rather than a line of source a reviewer reads.
`DEFAULT_LOCAL_MODEL` is a constant on the same reasoning plus one of its own: `--model` names a
hosted alias (ADR-0041), and feeding it to a local daemon would ask Ollama for a model it has never
heard of.

## Alternatives considered
- **Leave 0051's sixth rejection standing and do not wire the local model at all.** Rejected. The
  three objections in it are about an artefact's provenance, not about the idea of a free call, and
  all three are now answerable — the first by a second name that did not exist when they were
  written, the second and third by facts that were already true and had not been checked. Leaving
  a rejection in force after its premises have been answered is how a record becomes a rule nobody
  can revisit.
- **Edit ADR-0051 to strike or soften that bullet.** Rejected on `docs/adr/README.md`: ADRs are
  immutable once accepted. Editing the paragraph would also destroy the thing that makes this
  decision auditable — that a rejection was recorded, its grounds named, and each ground answered
  in public two days later.
- **Mark ADR-0051 Superseded outright.** Rejected, and this is a deliberate narrowing of the brief
  that produced this record. What is overturned is one of six rejected alternatives. 0051's
  decision — that M5 publishes two oracles and says so before it prints a number — is untouched,
  still governs the shipped release, and is cited above as the rule this record obeys. Superseding
  the whole document to overturn one bullet would retire a rule that is still in force. The status
  says `amends 0051`, and the cost is disclosed rather than hidden: **the link is one-way.** A
  reader who opens 0051 alone will not be told its sixth alternative was answered; the index row
  and this file are what carry the connection.
- **A `--local-endpoint` flag, so a daemon on another port is reachable.** Rejected twice. It is
  dead wiring — no second reader, the shape this CLI has already ruled against — and it is a
  redirect for the one payload this project promises never leaves the machine. An operator running
  Ollama elsewhere edits one constant, in a repository they have cloned, and that edit is visible
  in a diff.
- **Read the endpoint from the environment (`OLLAMA_HOST`), which is where the daemon's own
  clients read it.** Rejected as the same redirect with less visibility. An environment variable is
  not recorded in the result set, so two runs with different endpoints would produce documents
  nothing could tell apart — and this repository's whole claim is that a result can be reproduced.
- **Let `--model` name the local model too, so one flag covers both baselines.** Rejected: one flag
  naming two models on two endpoints cannot be right for both. A run naming both baselines would
  send one alias to two daemons, and the one that had never heard of it would fail inside a trial
  rather than at the command line.
- **Price the local call at zero, since it costs no money.** Rejected. Money at zero and money
  unknown are different claims, which is why `CostBasis` has four states rather than a number that
  might be `0.000000`. The call also is not free in the sense a cost column means: it spends this
  machine's electricity and minutes, neither of which Assay measures.

## Consequences
**This is the first path in the repository that can produce a number about a model rather than
about the harness, and it costs nothing to run.** It has not been run. No daemon has served this
repository a completion, the response shape is still documentation rather than measurement
(ADR-0059), and nothing here changes what the README claims.

**A `naive-local` number is not evidence about `naive`.** The two rows are one adapter over two
endpoints and two models; a local 7B model solving a mined task says what a small local model does,
and a report holding one and not the other says exactly that on its face. Any claim comparing them
needs the paid run no milestone owns (ADR-0042, ADR-0051).

**The endpoint and the model are two more unmeasured constants in `cli/main.py`,** joining
`TRIAL_LIMITS`, `IMAGE_BUILD_TIMEOUT_S` and `DEFAULT_TRIAL_TIMEOUT_S`. `qwen2.5-coder:7b` is a
starting point chosen from the model's public description, not from anything observed here, and
their comments say so.

**Deletion path:** the two constants, the `elif` branch that reads them, and the name in
`ADAPTER_NAMES` come out together with ADR-0060's subtraction, and `cli/main.py` returns to one
baseline over one endpoint.
