# ADR-0057: The report page declares its canvas, scrolls per table, and wraps rather than truncates

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0049](0049-the-report-states-its-redaction-and-carries-no-clock.md) settled what the
published page *says*. This record settles what it does when the page is opened somewhere other
than the machine that produced it - which in M5 is the point: the README shows a report, the demo
writes one to `build/demo/report.html`, and both are read by somebody who did not run them, on a
device nobody here chose. The page was measured at 375px in a real browser, and three of its
properties turned out to be accidents rather than decisions.

**The page was legible only because it inherited somebody else's canvas.** `_HTML_STYLE` declared
no background colour, no text colour and `color-scheme: normal`, so the document was white because
the user agent's default is white. Every grey on the page had been chosen against that white -
and the greys are not decoration here: `.absent` is what keeps "not recorded" apart from "measured
zero", which is the distinction
[ADR-0046](0046-a-cost-line-carries-the-reason-it-has-no-dollars.md) spends a whole `CostBasis`
enum on. A browser applying an automatic dark theme is free to repaint a document that
declares nothing, and the repaint lands on exactly those cells. A report whose contrast was
measured against white cannot be served on a canvas it never named.

**A table wider than the screen moved the whole document, and it moved it in one direction.** The
widest table renders 679px wide; at 375px, with no container, the body scrolled sideways with it.
That is a layout defect in most documents and a measurement defect in this one, because the
columns are ordered and the overflow is therefore not neutral: the only unscrolled view of the
tools table ended inside the pass@1 interval column, which put the flattering band on screen and
left the pass^n band - the one that decides the ranking, and which on the published fixture
refuses to name a winner (SPEC §4) - off it. A reader who never scrolls reads the number this
project exists to distrust.

**The suite hash is 71 characters with no break in them.** 507px of unbreakable text, and it is
the report's core provenance claim: the digest names the exact task set the numbers were measured
on, and ADR-0049 made it the first line under the title for that reason. Something has to give at
375px - the line wraps, the page widens, or the digest gets shorter.

## Decision
**Three rules, each of them an answer to one of those measurements, and all three inline.** The
stylesheet stays inside the document: an external one would make opening a report a network
request, and a report describes a private repository (ADR-0049).

**`:root { color-scheme: light; }`, with `background-color: #fff` and `color: #1a1a1a` stated
beside it.** The report is a light document and now says so rather than happening to be one. The
declaration is what tells a browser not to synthesise a dark rendering of a palette that was
measured on white.

**One `.scroll { overflow-x: auto; }` container per table, not one for the page.** Each table
overflows inside its own box, so the document itself never moves sideways and no table's heading
scrolls out from under it while a reader is scrolling a different table. The columns keep their
alignment, which is the entire job of a table of numbers.

**`overflow-wrap: anywhere` on `code`.** The digest wraps mid-token and stays whole and copyable.

## Alternatives considered
- **A dark palette, or a second palette under `prefers-color-scheme`.** Rejected. Every grey in
  this document was chosen by measuring contrast against white - #6b6b6b at the 4.5:1 text floor,
  #8a8a8a at the 3:1 non-text floor - and a second palette means a second set of those
  measurements, permanently, for a page whose faint cells carry a distinction the report cannot
  afford to render faintly. One measured palette, declared, is the honest arrangement; two
  palettes where only one was measured is worse than the accident this replaces.
- **One scroll container around the whole page.** Rejected, and it is the tempting version because
  it is a single rule. It reintroduces the failure in a smaller frame: scrolling the costs table
  scrolls the tools table sideways too, so a reader who went looking for a dollar figure comes
  back to a scores table whose visible columns have moved under a heading that did not.
- **Card reflow: each table row becoming a stacked label/value card below some breakpoint.** The
  standard responsive answer to a wide table, and rejected on what this table is for. A row here
  is not a self-contained fact; it is one term of a comparison, and the reader's question is "how
  do these two tools' pass^n bands compare", which a column answers by putting the two numbers
  above one another. Reflowed into cards, that comparison becomes a scroll between two cards with
  the digits no longer aligned - and pass@1 and pass^n, two different instruments (ADR-0035,
  [ADR-0043](0043-pass-at-1-is-a-percentile-bootstrap-over-tasks.md)), stop being visibly two
  columns. It would also give a phone reader a differently shaped document from a laptop reader,
  which is two presentations of one measurement to keep honest instead of one.
- **Truncating the digest to fit, with the full value in a `title` attribute.** Rejected. A
  shortened hash cannot be checked against anything, so the line that says what was measured
  stops being a claim a reader can verify - the same defect ADR-0049 named in an unlabelled column
  of tokens, in the one field that is not redacted precisely because it is verifiable (SPEC §5.5).
  A tooltip is also not available to the phone reader this change is for.
- **Letting the body scroll and trusting the reader to do it.** Rejected: it makes the report's
  honesty conditional on a gesture. The pass^n band is the ranking, and a band that is only
  reachable by scrolling is a band some readers will not reach.
- **A viewport-relative font scale, so the tables fit.** Rejected: the numbers shrink to fit the
  widest table on the smallest screen, and the document's whole content is numbers.
- **Dropping columns at narrow widths - the trial counts, say, or the rates a cost line priced
  with.** Rejected outright. Every column on this page is there because a reader would otherwise
  have to take a figure on trust: the rates are what make a dollar amount re-derivable (SPEC
  §5.5), and the counts are what make a proportion mean anything. A device is not a reason to
  publish less of the measurement.

## Consequences
**Three tests pin the three rules**, in `tests/report/test_renderers.py`: the canvas declaration
and both colours, three tables each wrapped in exactly one `.scroll` container, and the digest
rendered whole beside the wrap rule. They assert the CSS text, which is unusual for this suite and
deliberate - each rule is an answer to a measurement, so a later tidy-up that deletes one has to
delete an assertion that says why it exists.

**The measurements live at the point of use.** `render.py` carries the pixel and contrast figures
in the comment above `_HTML_STYLE`, because a rule whose reason is a number is unmaintainable
without the number. This record carries what that comment cannot: the alternative that was
weighed and lost. Card reflow is the one a reviewer would ask about, and until now nothing in the
tree said it had been considered.

**Two further rules landed in the same measurement pass and are not decisions.** The two greys
were raised to clear published contrast floors, and the paragraph measure was set to 34rem so the
redaction sentence sets at a readable line length. Both are arithmetic against a published
standard rather than a choice between options, so both are recorded where they are applied and
neither is re-decided here.

**No byte of the canonical JSON changes, and neither does the text report.** This is a decision
about one of the three formats, and specifically about the one that is published as a file. The
freeze M5 applies to the schema (CLAUDE.md treats it as API once public) is untouched.

**The page still fetches nothing.** Inline style, no font, no stylesheet, and the
Content-Security-Policy that refuses the attempt is unchanged - opening a report must not tell
anybody that it was opened.

**A saved page keeps behaving.** All three rules survive being saved to disk and reopened,
because there is nothing to fetch and no breakpoint that depends on anything but the viewport -
which matters here, since the artefact the demo produces is a file somebody mails on.

**The three rules are now the floor, not the ceiling.** A later change that widens a table has to
keep the scores' first screen honest, and one that adds a long unbreakable string has to say how
it wraps. Both are visible failures in the tests rather than judgement calls in review.
