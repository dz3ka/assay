# ADR-0039: The agentic tool is Claude Code, it runs inside the container, and the shared family is flagged

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Bogdan Dzekic

## Context
M3 measures two tools against each other and against the two oracles. One is the naive baseline
CLAUDE.md requires in every report — one raw model call, no agent loop. The other is the
sophisticated thing the baseline exists to embarrass, and until now it had no name.

Three questions had to be answered together, because the answers constrain each other.

**Which tool.** The comparison is only interesting if the agentic tool is one people actually
use. It is only *clean* if the tool and the baseline come from different model families,
because CLAUDE.md's last measurement rule is about exactly this hazard: a judge from the same
family as a tool under test has to be flagged. The rule names judges, and M3 ships no judge, but
the reason behind it — a family measuring itself is a result a reader must be told about —
applies just as well when the baseline and the tool share a family.

**Where it runs.** SPEC §5.2 says model-generated code only ever runs inside the sandbox, and
§5.3 says networking is disabled inside a trial except for an allowlisted model endpoint. The
second sentence only has meaning if something inside a trial may reach a model; until M3 nothing
did, and `run_in_sandbox` gave every container `--network none`. An agentic tool has to reach
its endpoint to work at all, so one of the two sentences has to give — or the trial has to be
split into phases with different postures.

**What the harness may claim about that network.** Docker has no native hostname allowlist. A
container either has an interface or it does not; which host it then connects to is not a
question the flags answer. This was known before the decision, not discovered after it, and it
is what the third part of this record is about.

## Decision
**The agentic tool is Claude Code, driven non-interactively (`claude -p`). It is installed into
an image at build time and runs inside a container, in an adapter phase that precedes the
measurement phase and has a different network posture. Because it shares a model family with the
naive baseline, the report and the milestone record must both say so.**

*Representativeness over cross-family cleanliness.* Claude Code is a tool a reader recognises,
and a harness whose headline comparison is against a tool nobody runs is measuring something
nobody asked about. The cost is paid in the open: the finding "the agentic tool beat the naive
baseline" is, in M3, a finding about one family measured against itself, and a reader who is not
told that has been misled by omission. So the flag is not editorial — it is written into the
milestone record beside the numbers, for the same reason the winner suppression is a code path
rather than a habit.

*Inside the container.* A trial now has two container phases and they are not the same policy.
The adapter phase mounts the throwaway workspace **writable**, because the tool's entire output
is the tree it leaves and the diff is harvested from it (ADR-0038); it has a network, because a
tool that cannot reach a model is not a tool. The measurement phase is untouched — `--network
none`, workspace `:ro`, exactly as M2 built it — and it is a *second, freshly prepared checkout*
that the tool never saw. Both SPEC sentences survive: model-generated code still only runs in a
container, and the trial's measurement still has no network at all.

The two argvs live in one module,
[`src/assay/sandbox/container.py`](../../src/assay/sandbox/container.py), because the difference
between them is the security-relevant fact and a reader has to be able to check both at once.
The adapter itself, [`src/assay/adapters/agentic.py`](../../src/assay/adapters/agentic.py),
never learns any of this: it is handed an executable, an environment and a
`ToolProcess`, and where that argv runs is the binding's business. That is what keeps every
branch of it — the tool that exits non-zero, the tool killed at its budget, the tool that
changed nothing — reachable on a fake in CI, with no daemon and no tool installed.

*And the allowlist is not enforced by the network stack.* The adapter phase gets docker's
default bridge: an interface with unrestricted egress. `api.anthropic.com` is what the tool is
configured to reach, not what it is constrained to reach. The constant that spells this,
`ADAPTER_PHASE_NETWORK`, says so where it is defined, a test asserts it negatively, and this
record and the milestone record both carry it. Stating the gap is the only honest option
available: the alternatives are a filtering proxy the tool would have to be persuaded to honour
and host firewall rules requiring privileges this package does not have, and neither is a
milestone's worth of work hidden inside an adapter.

## Alternatives considered
- **aider, or another cross-family agentic tool.** Rejected by the user, and it was the better
  answer to the honesty question: a tool from a different family would have made the baseline
  comparison clean and needed no flag at all. It loses on representativeness, which is what this
  harness is being read for. The rejection is why the flagging duty above exists — it is the
  cost of this choice, paid explicitly.
- **Run `claude -p` on the host.** Rejected. It is simpler by a whole container phase and by the
  image build below, and it bends SPEC §5.2 until it breaks: the tool writes model-authored code
  into a worktree on the developer's machine and then runs whatever the repository's own test
  configuration says, on the host. The sentence "model-generated code only ever runs inside the
  sandbox" is not a sentence with a convenience exception in it.
- **Give the measurement phase a network so one container can do both jobs.** Rejected outright.
  A trial that can reach an index can `pip install` its way to a passing test, and one will —
  the whole reason the environment is baked into the image (ADR-0006).
- **Install the tool into the task image itself, in `render_base_dockerfile`.** Rejected. Every
  task image is addressed by that recipe's text, so a node toolchain in it would re-address the
  environment every M2 trial was measured in, for a tool no measurement phase ever runs. The
  agent image is a third phase layered over the task image with an address of its own, the shape
  ADR-0023 already uses for test extras.
- **Claim the allowlist and implement it as "the tool only knows one endpoint".** Rejected, and
  it is the alternative this project must refuse most loudly. A harness whose subject is
  measurement honesty does not get to describe a control it does not have; an unenforced
  allowlist in a report is worse than a stated open network, because a reader can act on the
  second.

## Consequences
M3's headline comparison is within one model family, and every artefact that carries the numbers
has to say so. That is a real cost of ruling 4, and the record of it is deliberately in three
places — here, the report, and `docs/milestones/m3-*.md` — because the one place a reader is
guaranteed to look is the one with the numbers in it.

A trial now costs an extra image build. The agent image is `FROM` the task image plus a node
toolchain and one npm install; it is built once per commit and cached like every other tag. The
npm install is **not version-pinned by default**, so an agent image's address does not capture
which build of the tool is inside it: `build_agent_image` takes a `tool_version` for exactly
this reason, and until M3's live run observes one, two runs months apart can measure two
different tools under one tag. That is the weakest pin in the tree and it is named here so the
next milestone can close it.

The adapter records **zero tokens and zero tool calls** for every agentic trial. The only way to
learn them is to parse the CLI's output format, which is not a stable contract, and a harness
that inferred the numbers would be reporting an estimate as a measurement. A stated zero is
readable as "not measured"; an invented number is not.

Nothing about the harvest depends on any of this. ADR-0038 fixes what the adapter records —
stage, baseline tree, run, stage, diff, no exclusions — and that contract holds whichever tool
is on the other end of the seam and wherever it runs. If the flags this milestone drives
`claude` with turn out to be wrong, or the image cannot install it, what changes is one tuple in
the adapter and one recipe in `sandbox/image.py`.
