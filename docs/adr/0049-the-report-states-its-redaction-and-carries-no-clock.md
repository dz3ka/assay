# ADR-0049: The published report states its redaction, and carries no clock

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
M5 is the milestone in which a report stops being something the author reads on the machine that
produced it. The README will show one, the demo will write one to `build/demo/report.html`, and
the oracle run's numbers are published beside them. A published report is read by somebody who
did not run it, cannot see the result set behind it, and has no way to ask.

**The page is a column of tokens and says nothing about what they are.** `redact` replaces every
task identifier, path and commit subject with `f"{kind[0]}:{digest[:TOKEN_HEX_CHARS]}"`, so the
trial log reads `i:5e7a...`, `p:90ba...`, `m:4d73...` and nothing on the page explains the
convention. Two wrong readings are available to a reader who is not told. One is that these are
real identifiers, abbreviated for width - which would mean the report leaks exactly what SPEC
§5.4 says it must not. The other is that they are stable handles, so two reports on one suite
could be laid side by side and their rows matched. That is the cross-referencing a per-render
salt exists to prevent ([ADR-0009](0009-redaction-is-hmac-with-a-per-render-salt.md)), and it is
a property the recipient cannot check from the document: the salt is drawn inside `run_report`
and never written anywhere. An unverifiable security property that is also unstated is worth
very little.

**Every artefact of this shape wants a timestamp, and this one must not have one.** "Generated
2026-09-04 by assay 0.1.0 (M5)" is the line a release document reaches for. But a renderer here
is a pure function from a `Report` to a string - `render.py` says "No I/O, no clock, no network",
and `build_report` and `summarise` say the same - so a clock would have to be read somewhere and
threaded in, and two renders of one recorded result set would then differ in a byte that has
nothing to do with the measurement. That is the property content addressing exists to give
([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)), and it is why `SuiteFile` keeps
`generated_at` and `generator` *outside* `suite_hash` rather than out of the file.

**The provenance that matters is already on the page.** `Suite: sha256:...` is the first thing
under the title. It names the exact task set the run was measured on, and the suite file it names
carries the clock and the generator string in its envelope. A reader who wants to know when
anything happened opens the artefact that recorded it; a reader who wants to know what was
measured has the digest.

**Where the sentence lives is the same question the other two prose sentences already answered.**
The interval caption and the paired-test sentence are render-local constants, deliberately absent
from the canonical JSON, because a key holding a wording freezes that wording as a compatibility
promise ([ADR-0035](0035-the-interval-is-on-pass-caret-n-over-tasks.md),
[ADR-0008](0008-pydantic-v2-over-canonical-json.md)). CLAUDE.md treats the schema as API once
public, and M5 is when it becomes public - which makes this the last milestone in which adding a
field is cheap, and the first in which it is permanent.

## Decision
**One sentence, one constant, two prose formats, no schema change.**
`_REDACTION_STATEMENT` sits in `render.py` beside `_INTERVAL_METHODS` and `_COST_METHOD`, spelled
once and used twice: as the third line of the text header, under `Suite:`, and as
`<p class="redaction">` immediately under the HTML suite line. It makes three claims, because
each is one the recipient would otherwise have to take on trust - that the tokens are HMAC-SHA-256
under a salt, that the salt is drawn per render and never stored, and that no flag turns the
treatment off.

**It claims only what `redact` does.** "Every task identifier and path here" is the scope, not
"this report is anonymised": tool names are the finding, and `prices_source` and the rates beside
it are the reader's own text, so none of them is hashed and the sentence does not pretend they
are.

**The canonical JSON does not change - byte for byte.** Both recorded fixtures render to the same
SHA-256 after this decision as before it. The document carries the tokens; prose about the tokens
is for a person.

**The report gains no clock, no generator string and no `--out`.** It names its suite and stops.
`assay report` still writes the document to stdout, and where the file lands is the caller's
business.

**The HTML head gains `<meta name="viewport" content="width=device-width, initial-scale=1">`**,
the one other change a published page needs: without it a phone lays out this column of wide
tables at desktop width and scales the numbers to unreadable. It requests nothing, and the
Content-Security-Policy is untouched.

## Alternatives considered
- **A `redaction_notice: str` field on `Report`, so all three formats read one source.** The
  arrangement that looks tidiest, and rejected for the reason the interval caption is not a field
  either: prose in the schema is a promise to every consumer that the wording will not move, and
  M5 is the milestone that makes it one.
- **A `redacted: bool` field instead of prose.** Rejected: `redact` is total and has no opt-out,
  so the field would read `true` in every document Assay can emit. A flag with one reachable
  value carries no information and quietly invites a second value later - which is a
  `--no-redact` flag arriving through the schema.
- **Put the sentence at the foot of the page, as a note.** Rejected on the same ground the
  interval caption sits on its table rather than in a footnote: a caveat a reader meets after the
  trial log is a caveat about a document they have already read.
- **Print a timestamp anyway, accepting one impure renderer.** Rejected: it makes two renders of
  one file differ, it puts a clock in the layer whose docstring promises none, and the honest
  timestamp - when the tasks were mined and when the trials ran - is not the renderer's to know.
- **Print the generator and version, as the suite envelope does.** Rejected: it would name the
  version that *rendered* the document, not the one that measured it, and those can differ. That
  is provenance in the misleading direction. `--version` already answers "what is installed"
  ([ADR-0047](0047-the-version-line-names-the-milestone.md)).
- **Spell the token's truncation width into the sentence.** Rejected: the width is visible in
  every token on the page, and a sentence that recites parameters stops being read. The claim a
  recipient cannot check for themselves is the salt, and that is what the sentence spends its
  words on.
- **Leave the HTML paragraph unclassed.** Rejected: `.absent` and `.trial` are already hooks for
  anybody restyling a saved page, and the redaction line is the one paragraph a reader might want
  to pull out of it.

## Consequences
**The text report's header is three lines and the HTML's masthead is two elements**, and both are
asserted in `tests/report/test_renderers.py` - the text header positionally, the HTML paragraph in
its escaped spelling and in document order under the suite hash.

**The statement is asserted verbatim, and also against the property it claims.** One report
rendered twice through two fresh salts shares the sentence and shares no token. A wording that
drifted away from what `redact` does would pass the first assertion and has to pass the second.

**The JSON stays exactly as consumers already have it**, which is what makes this a safe change to
publish in the milestone that freezes the surface.

**The report still cannot say when it was produced, and that is now on the record rather than an
omission.** If a published artefact needs a date, it belongs beside the artefact - in the
milestone document - not inside a pure renderer.

**A future `--no-redact`, should anybody ever argue for one, now has to delete a printed sentence
in two formats to ship.** That is deliberate: it was already refused in `redact`'s docstring, and
it is now refused in the document a customer reads.
