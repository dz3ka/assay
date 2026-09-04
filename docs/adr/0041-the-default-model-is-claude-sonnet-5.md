# ADR-0041: The default model is `claude-sonnet-5`, and nothing has been measured on either side of the change

- **Status:** Accepted
- **Date:** 2026-09-03
- **Deciders:** Bogdan Dzekic

## Context
`DEFAULT_MODEL` in `cli/main.py` is the id both real adapters ask for when the caller names
none: the naive baseline sends it to the allowlisted endpoint (ADR-0036), and the agentic tool
receives it as `--model` on the Claude Code command line inside the container (ADR-0039). It is
not an implementation detail of either. Each adapter writes it into `adapter_version` as
`<harness version>+<model>`, because a report that could not say which model answered could not
say what it measured — the model is half of what an adapter *is*.

The literal was `claude-sonnet-4-5`, chosen when the adapters were written and left behind by
the generation that followed. Nothing in the harness breaks: the id is a string these two
modules pass through, and no code here knows one generation from another. That is precisely
what makes it worth a record rather than a quiet edit — a default nothing complains about is a
default nobody re-reads.

What the staleness costs is not correctness, it is what the number would mean. An unflagged run
is what a reader reproducing this repository gets, and the default is therefore the
recommendation whether or not it was written as one. A headline that says the agentic tool
cleared or failed to clear the baseline, measured on a previous-generation model in both
columns, is a true sentence about a configuration nobody is choosing today. The version string
does carry the id, so the fact is recoverable — but a version string is where a reader checks a
suspicion, not where they form one, and this repository is public from M0 with measurement
honesty as its entire subject. Understating is fine here; presenting a dated measurement as the
current one is the failure mode the project exists to avoid.

The half that has to be stated plainly is that **this is not a correction of anything.** The
live paid run has not happened. Every figure in the tree today comes from fixtures, fakes and
the two bracketing oracles; no trial has ever reached a model endpoint. So this decision changes
what *will* be measured and no number that exists. Were it otherwise it would be a different and
much worse ADR: moving the model under a recorded result is the kind of edit that makes a figure
untrustworthy without making it wrong, and it would have to be a new run rather than a new
default.

## Decision
**`DEFAULT_MODEL` is `claude-sonnet-5`. It stays an alias rather than a dated snapshot, `--model`
still carries any other choice, and the id a run asked for is recorded in both adapters' version
strings.**

The constant is one literal in one place. The flag's `default=` and the help text that prints
the default both read it, so the command line and its documentation cannot disagree about what
an unflagged run does, and `tests/cli/test_main.py` asserts the parsed default *against the
constant* rather than against a second copy of the string — the test proves the flag defaults to
whatever this line says, which is the property worth pinning, and the line itself is the
decision.

Both adapters take the same id, and that is deliberate rather than incidental: M3's question is
what an agent loop adds over one raw call, so the two columns differ in the loop and in nothing
else. A run that wanted to compare two models is a run with two `--model` values and two result
sets, which the version string is what makes legible.

## Alternatives considered
- **Pin an exact dated snapshot (`claude-sonnet-5-YYYYMMDD` or similar).** The strongest case
  against this decision, and the one it concedes ground to. ADR-0007 content-addresses suites so
  a result can be reproduced, and an alias moves under a fixed suite digest — a re-run months
  later is a different model with nothing in the artefact to say so. Rejected on three counts.
  An alias is what a person running this tool actually types, and a harness that measures the
  configuration nobody uses has measured the wrong thing. A hardcoded snapshot id is a fact
  about a vendor catalogue at one moment, and a default that has been retired at the endpoint
  fails a run outright, which is worse than one that is a generation behind. And the
  reproducibility a pin buys is narrower than it looks: the tool under test is nondeterministic
  by construction — that is why n trials and pass^n exist at all (SPEC §4) — so the pin fixes the
  request and never the answer. Anyone who needs the stronger guarantee passes the dated id on
  the flag, which is exactly what the flag is for.
- **Leave the constant and let `--model` carry the burden.** Rejected, because it is an argument
  that a default is not a recommendation, and a default is a recommendation. It leaves every
  unflagged run — including the one a reader does first — measuring the previous generation, and
  it puts the correction in a place (the flag, remembered) that this project has repeatedly
  refused to rely on: a habit is not a control.
- **Bump to `claude-opus-5`.** Rejected on both cost and question. The live run is n = 5 trials
  per task per tool across a mined suite, paid per token in two columns, and the larger model
  multiplies that bill for a comparison it does not sharpen — raising both columns together
  leaves the gap between them, which is the entire measurement, roughly where it was. Sonnet is
  also the tier a reader is likeliest to run, and the tier the default should therefore name.
- **Delete the default and require `--model` on every run.** Rejected as honesty theatre. It
  makes every invocation carry a flag to buy a property the version string already provides,
  and the id a caller then types is chosen with less thought than this record was.
- **Update the fixture literals in the adapter and transport tests to match.** Rejected as a
  change that would weaken them. Those strings are arbitrary inputs to fake transports, asserted
  as "what went in came out"; matching them to the default would make a test that restates the
  constant look like a test of the default, and there is already one test of the default.

## Consequences
**No recorded number changes, because there is none to change.** The one thing this ADR must not
be read as is a revision of a measurement. It is a change to the configuration the outstanding
live run will be taken under, made before that run, and the result set it produces will name
`claude-sonnet-5` in every attempt's `adapter_version`.

**The recorded id is the one that was asked for, not the one that answered.** The transport
sends `model` and does not read the field back out of the response, so a result set proves which
alias a run requested and cannot prove which snapshot served it. That is a real gap, named here
rather than left to be discovered: it is a cost of choosing the alias, it does not matter while
there is one run and no comparison across time, and the change that would close it — recording
the endpoint's own `model` field on the attempt — belongs to whatever milestone first wants to
compare two runs taken months apart.

**This default will date again, and nothing here prevents it.** There is no resolution of
"latest" at the endpoint and no mechanism that keeps the literal current, deliberately: a
default that changed under a run would make the run unreproducible in the one way the alias is
already uncomfortably close to. The next generation is the next one-line commit with an ADR
beside it, and the cheapness of that is the point.

**ADR-0039's shared-family flag is unaffected.** The agentic tool and the baseline still call
the same family, M3's headline comparison is still within one, and the artefacts still say so.
Bumping a generation moves both columns together and changes nothing about which disclosures the
report owes.
