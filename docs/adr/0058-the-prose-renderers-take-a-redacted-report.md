# ADR-0058: The prose renderers take a redacted report, so the sentence they print is backed by a type

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0049](0049-the-report-states-its-redaction-and-carries-no-clock.md) put one sentence under
the suite hash in both prose formats: "every task identifier and path **here** is an HMAC-SHA-256
token under a salt drawn for this render and never stored, so two reports on one suite share no
token, and there is no flag that turns it off". The word doing the work is *here*. The sentence is
not a description of what `redact` does in general - it is a claim about the page the reader is
holding, which is the only form of the claim worth anything to somebody who cannot see the result
set behind it.

**Nothing backed that claim.** `render_text` and `render_html` took a `Report`, printed the
sentence unconditionally, and performed no check of any kind - correctly, since `render.py`'s
docstring pins the module as string building only. Any `Report` renders, including one straight
out of `build_report` that never went near the boundary.

**This repository produces the counterexample itself.** `tests/report/test_renderers.py` calls the
two prose renderers on unredacted fixture reports, from every helper in the file that builds
one, on purpose: a test that reads a
tool name or a task id back off the page needs the recorded text rather than a token, and the
sentinel test has to render an unredacted report first to prove the renderers print those fields
at all. Every one of those pages carries a sentence asserting that every identifier on it is a
token. They are in-tree, they are correct as tests, and they are proof that the sentence was a
statement the code did not enforce.

**The seam already existed one level down.** `Redacted` is a `NewType` over `str` declared beside
the fields that hold one, and `tests/report/test_redaction.py` carries a load-bearing static
negative for it: a raw path handed to a function that wants a `Redacted` is a `# type: ignore`
that CI checks is still needed. What was missing was the same fence one level up, around the
whole document rather than around a field.

**This is a claim about a claim, which is the project's own subject.** A harness that prints a
confident number nobody should trust is worse than no harness (CLAUDE.md), and a sentence is a
number's twin here: printed with nothing behind it, it acquires whatever authority the reader
brings. Assay cannot ship an unbacked assertion about its own redaction.

## Decision
**`RedactedReport = NewType("RedactedReport", Report)`, declared in `assay.report.model` beside
`Redacted`, minted by `redact` and by nothing else.** `render_text` and `render_html` take one.
The sentence they print is then true of every page they can produce, because the only way to
obtain the argument is to have been through the boundary.

**No renderer gains a check, and `_REDACTION_STATEMENT` does not change by a byte.** The
guarantee moves into the signature, where it costs nothing at runtime and is verified once, at
type-check time, over every call site in the repository.

**`render_json` keeps taking a plain `Report`.** The asymmetry is the point rather than an
oversight: the JSON document prints no prose, so it makes no claim its input could falsify. It
carries the tokens and a consumer reads them; there is no sentence there to back, and fencing it
would be a restriction the document's own contents do not ask for.

**The change alters no rendered document.** Every existing assertion about the sentence - verbatim
in the text header, escaped and in document order in the HTML, and the two-salt property test that
checks the sentence against what `redact` actually did - passes unedited. That invariance is the
acceptance test for this record: a fix to a claim that changed the artefact would have been a
different decision.

## Alternatives considered
- **A runtime check inside the renderer: sniff each `task_id` for the `i:`/`p:`/`m:` prefix and a
  12-hex tail, and refuse or drop the sentence otherwise.** Rejected, and it is worth being exact
  about why, because it is the first thing anybody proposes. It would assert *by appearance* what
  it cannot prove - which is the same failure as the unbacked sentence, one layer down and harder
  to see: a repository containing a path that happens to look like a token would pass, and a raw
  `p:`-prefixed path passes trivially. It would also put a heuristic inside a function whose
  module docstring pins it as string building only, and, worst of the three, on a report with no
  tasks it would find nothing to inspect and *drop the sentence* - so the honest empty report
  would be the one that stops saying it was redacted.
- **Accept the gap and record it: soften the sentence to describe `redact` rather than this
  page.** Rejected because "here" is the whole job of the sentence. ADR-0049 wrote it to tell
  *this page's reader* that *this column* is tokens rather than truncated identifiers. Drop the
  word and the sentence stops doing that job while still occupying the position of a claim; keep
  it and the claim stays unbacked. There was no third reading in which the status quo was fine.
- **A wrapper class - `class RedactedReport: report: Report` - instead of a `NewType`.** Rejected
  for the reason `Redacted` is a `NewType`: a redacted report must still *be* a `Report`
  everywhere one is written out, and a wrapper makes every renderer, test and CLI path unwrap
  before it can read a field. The cost lands on every reader to fence one function pair.
- **A `was_redacted: bool` on `Report`.** Rejected twice over. ADR-0049 already refused it - the
  field would read `true` in every document Assay can emit, and a flag with one reachable value
  quietly invites a second - and it would be provenance in the schema, which M5 freezes as API.
- **Retyping `TaskLine.task_id` to `Redacted`, which looks like the same fix.** Rejected, and
  deliberately so. `build_report` constructs a task line's id from raw result text, so the
  annotation would be a lie inside the schema itself. The field's comment already defers the
  question it belongs to - whether a report may name a task the suite never minted - to the
  milestone that can answer it. This record does not answer it by accident.

## Consequences
**The guarantee is static, and it holds over exactly the population that is exposed to it.**
`NewType` is erased at runtime, so a caller who wants to can construct a `RedactedReport` from
anything. What that buys is the thing worth having: every typed caller in this repository is
checked by `mypy --strict`, which is CI, and there is no untyped caller. The in-repo casts are the
mechanism rather than a leak - a `NewType` converts an invisible default ("any report at all")
into a greppable `RedactedReport(...)` call site that somebody wrote on purpose, which is exactly
the rationale already recorded for `Redacted`.

**A new static negative carries the fence**, modelled on the `Redacted` one:
`test_an_unredacted_report_is_statically_rejected_by_the_prose_renderers` hands `render_text` a
report straight out of `build_report` under a load-bearing `# type: ignore[arg-type]`, asserts it
still renders (the erasure, stated rather than hidden), and renders the redacted version beside
it. `warn_unused_ignores` is on, so if the fence ever dissolves the ignore goes unused and CI
fails on that line.

**The five wrapped call sites in the renderer tests now say so** - four helpers and one report
built inline, which is what `grep -c "RedactedReport(" tests/report/test_renderers.py` returns.
Each carries an explicit `RedactedReport(...)` and a comment naming the reason - the sentinel test
needs unredacted text to prove the renderers print it, the fixture tests need recorded tool names
to read numbers back. What was an unremarked default is now a written intention at each site.

**`assay report` is unchanged.** `_report_document` already redacted before rendering, with a
fresh policy per invocation; it now happens to satisfy a type it previously satisfied by habit.
The `RENDERERS` dict still typechecks with `render_json` in it, since parameters are
contravariant.

**A future `--no-redact` has one more thing to get past.** It was refused in `redact`'s docstring,
refused again in the printed sentence by ADR-0049, and now cannot reach the two prose formats at
all without deleting a type.

**This applies the redaction line rather than superseding anything.** ADR-0009 chose the HMAC and
the per-render salt, ADR-0049 chose to say so on the page; this record makes the saying enforced.
Neither is amended.
