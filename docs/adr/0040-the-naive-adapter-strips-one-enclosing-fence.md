# ADR-0040: The naive baseline strips one enclosing code fence, and the repair is on the record

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Bogdan Dzekic

## Context
The naive baseline's entire output is one chat reply. It is recorded as `Attempt.diff`, applied
with `git apply` in a second checkout the model never saw (ADR-0038), and scored on whether the
failing test turns green (ADR-0003). Nothing else about the reply is looked at.

The system prompt asks for a bare unified diff and says *no markdown code fence* in the same
sentence. Models return one anyway — a fenced block is the shape a chat completion has, and
saying otherwise in a system prompt is a request rather than a control. When it happens, the
reply's first line is ```` ```diff ```` , `git apply` refuses the patch on line 1, and the trial
scores `FAILED`.

That verdict is not wrong about the patch; it is wrong about what it is measuring. The number
that reaches the report says "the naive baseline could not fix the bug" when what happened is
"the naive baseline wrapped a correct patch in markdown", and nothing in the report tells the
two apart. CLAUDE.md puts this adapter in every report for one reason: it is the floor the
sophisticated tool has to clear, and *if the sophisticated tool cannot beat it, that is the
finding*. A floor pinned at zero by a formatting habit hands the agentic tool a win for free —
which is precisely the direction of error a harness about measurement honesty cannot afford.
M3's headline comparison would become an artefact of markdown.

The uncomfortable half is the other side of the same sentence. **Stripping the fence is the
harness editing what the tool produced.** This project's whole subject is being able to tell
whether an AI feature is working rather than merely responding; a harness that quietly improves
its subject's answers has stopped being able to tell. So the question was never "is this
convenient" — it was whether there is a line between repairing an *encoding* and assisting a
*score*, and whether this repair is on the safe side of it.

The user ruled: **strip.** One named, bounded repair; nothing else transformed; and recorded in
an ADR, because a harness that edits a tool's output must say so where a reader will find it.

## Decision
**The naive adapter removes one enclosing markdown code fence from the reply before it becomes
`Attempt.diff`. Nothing else about the reply is transformed, and this record is the disclosure.**

The shape is a *pair*, and both halves must be there. The first non-blank line has to open a
fence — three or more backticks or tildes at the very start of the line, plus CommonMark's
optional info string — and the last non-blank line has to close it with the same marker, no
shorter, and nothing else on it. The text between them is *sliced* out of the reply's own lines,
never rebuilt from them, so a diff that came in with CRLF endings, trailing whitespace or a
missing final newline goes out with exactly those. The repair is a pure function over the reply
string ([`_strip_code_fence`](../../src/assay/adapters/naive.py)), so every branch of it is
tested with no transport, no workspace and no daemon.

**Why this is not scoring assistance.** The fence is not part of the answer; it is packaging
around the answer. Removing it changes how the diff was encoded and leaves what the diff *does*
untouched: the text inside still has to apply cleanly, still has to avoid every test path
(ADR-0037), and still has to turn a failing test green in a freshly prepared checkout under a
container with no network. Every input to the verdict survives the repair unchanged. That is the
test this decision applies, and it is what separates the fence from the things on the other side
of the line — fixing hunk offsets, adding missing `a/` and `b/` prefixes, dropping hunks that
touch a test file. Each of those edits the patch's behaviour, and each is refused.

It applies to the naive adapter alone, because it is the only adapter whose output is prose. The
agentic adapter harvests its diff from a git tree (ADR-0038) and has no fence to strip; the two
oracles produce their patches from the suite.

## Alternatives considered
- **Leave the reply verbatim and report a fenced answer as the finding.** The status quo, and
  the WP5 handoff's recorded open risk. Rejected by the user, and it is the alternative with the
  strongest abstract case: "the model did not follow instructions" is a true sentence about a
  fenced reply. It loses on what the number then means. A `pass^n` of 0 for a baseline that may
  have written the correct patch on all five trials is a confident figure nobody should trust,
  and CLAUDE.md's opening claim is that such a figure is worse than no harness at all.
- **Treat a fence as `Attempt.error`.** Rejected twice over. ADR-0031 keeps errored trials in the
  denominator, so this scores the baseline down exactly as before while relabelling the cause —
  the honest-looking option that changes nothing. And it is the wrong label: `error` in this
  adapter means the seam failed (a refusal, a timeout, an unreadable workspace), and here
  nothing went wrong on the call at all.
- **Extract the first fenced block from anywhere in the reply.** Rejected as too greedy. A reply
  with commentary around a block is a reply that ignored the system prompt, and the report should
  record that it did; an extractor hides it. "The first block" is also a guess whenever there is
  more than one, and a guess is the thing this repair is defined not to be.
- **Repair the half-pair too — an opener with no closer.** Rejected. That reply is one the
  endpoint cut off at `max_tokens`, and a truncated diff does not apply whether or not its first
  line is removed; repairing it buys nothing and widens the rule from a shape to a heuristic.
- **Retry the call with a stricter prompt when the reply is fenced.** Rejected. n trials per task
  is how this harness measures variance (SPEC §4); a hidden retry inside one of them flatters the
  tool under test, which is why this adapter has never had one.

## Consequences
**The repair can only move a verdict in one direction, and only for answers that were already
correct.** For the strip to change a result, the fenced text has to have been a patch that
applied, avoided the test paths, and made the failing test pass. When that trial moves from
`FAILED` to `PASSED`, the `FAILED` was the wrong number. There is no input on which this repair
manufactures a pass out of a wrong answer — that asymmetry is the whole argument, and it is the
first thing to re-check if the live run's naive column ever looks surprising.

**What the attempt records is the repaired diff, not the raw reply.** So a reader cannot tell
from a result set how many of the baseline's passes were fenced. That is a real gap, named here
rather than left to be discovered: M3 does not need the answer, but a milestone that wanted to
report "how often does the baseline ignore its instructions" would have to record both texts,
and until it does, that question cannot be asked of the data.

**The size cap is still measured on the raw reply, before the strip.** The ceiling on
`Attempt.diff` therefore holds by construction — the repair can only shorten the text — at the
cost that a fenced reply a few bytes over the cap is refused where its stripped form would have
fitted. Deliberate: the cap is a statement about what the endpoint sent.

**The adapter's docstring can no longer say it never repairs the answer, and it no longer does.**
It names this one repair and points here. The line that matters is the one about *everything
else*: an adapter that tidied the output would be measuring the tidying, and that sentence is
now load-bearing for a specific, enumerated exception rather than for a blanket claim.
