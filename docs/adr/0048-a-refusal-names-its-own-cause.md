# ADR-0048: A refusal carries its own sentence, and a handler claims only what its `try` block can know

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0046](0046-a-cost-line-carries-the-reason-it-has-no-dollars.md) gave `assay report` a
`--price TOOL=INPUT/OUTPUT` flag: rates arrive on the command line, in dollars per million
tokens, and nothing about them is stored. A rate is therefore user input, and it is validated
the way this repository validates input - a number, at or above zero, no finer than a millionth
of a dollar ([ADR-0010](0010-money-is-a-decimal-at-six-decimal-places.md)).

**A rate can pass every one of those rules and still break the report.** The ceiling is not a
property of the rate; it is a property of the rate multiplied by however many tokens the result
set recorded. `$1E30` per million tokens against the disjoint fixture's 10240 input and 960
output tokens is `$1.12E+28`, and rounding that to the microdollar asks `decimal` for 35
significant digits where its context carries 28. `Decimal.quantize` signals `InvalidOperation`,
and `InvalidOperation` is raised with no message at all: `str()` of it is
`[<class 'decimal.InvalidOperation'>]`. That repr was reaching the user's terminal.

**The frame around it was worse than the repr.** The line read
`assay report: cannot read <path>: [<class 'decimal.InvalidOperation'>]` about a file that had
just been read, parsed and validated without complaint. The frame was not incidentally wrong; it
was structurally wrong. `run_report`'s `try` wraps `_report_document`, which reads *and*
summarises *and* renders, so a handler around it cannot know which of the three failed - yet it
asserted one of them by name. The other two handlers with the same shape are correct precisely
because their scope is narrower: `run_validate` and `run_run` wrap `load_suite` and nothing
else, so `cannot read` is the only thing that can have happened inside them.

**A misattributed refusal is this project's own failure mode, arrived at from the other side.**
Assay exists to refuse confident claims the evidence does not support (CLAUDE.md). A stderr line
naming a cause the code cannot know is the same defect as a report naming a winner the intervals
cannot separate - smaller, cheaper, and in the one artefact a user sees when something has
already gone wrong.

**The convention it broke was already written down.** `core/errors.py` states the placement rule
for the whole package: an error lives in the module that raises it and subclasses `AssayError`.
`GitError`, `SandboxError` and `TrialSetupError` all follow it. The lapse here was not a missing
convention but a third-party library's signal escaping a function that should have owned the
refusal, and the CLI then widening its catch to `ArithmeticError` to receive it - a handler
reaching down to catch what a domain function declined to translate.

## Decision
**The raise site owns the sentence, and the handler frames it with only what it knows.** Two
edits, one record, because either alone leaves the user reading a line that misinforms them.

**`CostOutOfRangeError(AssayError)`, in `report/model.py`, beside `quantize_usd`.** The one
function that can hit the ceiling catches `InvalidOperation` and re-raises with the sentence a
reader needs:

```
a computed cost of 1.120E+28 cannot be rounded to the microdollar money is reported at -
the price supplied is larger than any figure a report can state
```

`raise ... from None`, because the signal carries nothing the sentence lacks - chaining it would
append the very repr this exists to keep out of a terminal. The amount is printed in scientific
notation, since the figure that broke the arithmetic is by construction too long to read any
other way. The message names the *price* and not `--price`: `report` is pure logic and must not
learn that a command line exists, which is the same boundary that keeps prose out of the schema
and renderers out of the filesystem.

**`run_report`'s handler stops asserting a cause.** `ArithmeticError` leaves the tuple - the
domain now raises an `AssayError`, so the four catches the other two handlers carry are enough
again - and the frame becomes `cannot produce a report from {results}`. That claim is true for
every member of the tuple: an unreadable file, a malformed document, a nesting depth the decoder
gave up on, or a price no report can state. The path is still named in Assay's own words,
because json's and pydantic's errors do not name it.

**The three handlers now agree, and their comments say why they may.** `run_validate` and
`run_run` keep `cannot read` - they earn the stronger claim by wrapping `load_suite` alone. The
comments that used to explain a fifth catch and its absence are reworded to explain the frames
instead, because the fifth catch is gone.

**No other raise site is rewritten.** The convention held everywhere else; this was one function
letting one library's signal through. A sweep would be a refactor in search of a defect.

## Alternatives considered
- **Fix only the repr - print `str(error) or type(error).__name__` in the handler.** The one-line
  fix, and it produces a readable `InvalidOperation` in place of the bracketed class. Rejected:
  it leaves the frame claiming the file could not be read, which is the half of the line that is
  actually false, and it teaches the CLI to paper over an error's missing message rather than
  fixing the error.
- **Fix only the frame.** Rejected symmetrically: `cannot produce a report from x.json:
  [<class 'decimal.InvalidOperation'>]` is honest about what it does not know and still tells
  the user nothing whatsoever about their price.
- **Catch `InvalidOperation` in the CLI and write the sentence there.** Rejected: it puts
  `decimal` in the CLI's import surface and makes the command line the place that knows why
  money rounds the way it does. The rule in `core/errors.py` exists to stop exactly that drift,
  and a caller catching `AssayError` would still not catch this one.
- **Refuse the rate at the argument surface with a maximum, as `--limit 0` and `--trials 0` are
  refused.** The shape ADR-0046 used for malformed prices, and it does not fit: the ceiling
  depends on the token counts in a result set the parser has not opened yet. Any constant
  maximum would be invented, would refuse rates that price a small suite perfectly well, and
  would still need this refusal behind it for the rates it let through.
- **Clamp the total at the largest figure six decimal places can hold, or saturate to
  "more than $X".** Rejected without much deliberation: printing a number nobody computed, in a
  report whose subject is measurement honesty, is the failure this repository exists to detect.
- **Widen `decimal`'s context precision so the quantise succeeds.** Rejected: it makes the
  report's output depend on a process-global setting, and the figure it would then print is a
  cost of `$1.12E+28` - arithmetically fine and still not a price any report should state.
- **Give the handler a ladder of frames, one per exception type.** Rejected: it re-implements in
  the CLI the sentence each error already carries, and it grows a branch every time a new
  refusal is added. The generic frame plus a specific error is the arrangement that does not.
- **Drop the frame entirely and print the error alone.** Rejected: json's decode error and
  pydantic's `ValidationError` do not name the file they came from, so the user would be told a
  document is malformed without being told which one.

## Consequences
**All three `except` tuples in the CLI are now identical**, which makes the next divergence a
question somebody has to answer rather than a difference that accumulated. A fifth catch would
have to justify itself against this record.

**The `report` frame is weaker, and for a genuinely unreadable file it reads slightly worse** -
`cannot produce a report from missing.json: [Errno 2] No such file or directory`. It is still
true, and it still names the file. A weaker claim that is always true beats a stronger one that
is sometimes false, which is the whole of this decision in one sentence.

**`CostOutOfRangeError` is on `assay.report`'s public surface**, exported beside the models like
`GitError` and `SandboxError` are from theirs. It subclasses `AssayError`, so every caller that
already catches "anything Assay refused to do" catches it with no change.

**Two tests are the tripwire, and they are worded as refusals rather than as expectations.**
`tests/report/test_summarise.py` asserts `"<class" not in str(error)`, and `tests/cli/test_main.py`
asserts `"cannot read" not in err` for the priced-too-high case. Both fail if either half of
this decision is reverted alone.

**Deferred, named: a malformed result set still prints pydantic's `ValidationError` as a
multi-line block under the new frame.** It is pre-existing, untouched by the flag work or by
this record, and collapsing it means deciding how much of a validation error a user is owed -
which fields, how many, in what order. That is a real decision about what the CLI's stderr
says, not a wording tweak. **Trigger: M5's public-release polish**, where the shapes stderr
takes become part of what is published.
