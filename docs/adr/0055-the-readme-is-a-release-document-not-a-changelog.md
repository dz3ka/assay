# ADR-0055: The README is a release document, and the milestone narrative moves to `docs/milestones/`

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
The README has been public since M0, and it grew the way a public README grows when a milestone
closes every few days: each one appended its own paragraph. By the end of M4 the front page opened
with a 23-line block that walked a reader through M0's schemas, M1's gate, M2's container and
executable scoring, M3's `run` and Wilson bands and M4's bootstrap, McNemar and cost arithmetic, in
that order, before saying what the tool is. A second block of fifteen lines then narrated two
by-hand httpie mines with their wall clocks. Both blocks are accurate. Neither answers the
question a stranger arrives with.

**The failure mode is specific and it is not verbosity.** A changelog is written for someone who
was here last month; it says *what changed*. A release document is written for someone who has
never been here; it says *what this is, what it has measured, and what it has not*. The two
disagree about ordering, which is the part that matters in a repository whose subject is
measurement honesty. The changelog's ordering puts capability first and limits last, because each
paragraph was written in the week its capability landed. The release ordering puts the limit
beside the claim it bounds, because a reader who has priced the tool before reaching a caveat has
already been misled and a caveat cannot un-mislead them. That is the same argument
[ADR-0051](0051-m5s-two-tools-are-two-oracles.md) made about `m5-public-release.md`'s section
order, applied to the document that is read first and most.

**M5 makes the collapse necessary rather than merely tidy**, for two reasons that arrived
together. The milestone records now exist: `docs/milestones/` holds one document per milestone
from M1 forward, each of which states at length what its milestone did and did not establish, and
each of which is more precise than the paragraph on the front page that summarises it. The front
page was therefore carrying a lossy second copy of six documents, which is the drift setup
[ADR-0012](0012-the-task-id-pattern-is-spelled-twice.md) exists to refuse — except that prose has
no constant to pin, so the drift is silent.

The second reason is that a sentence in the httpie block was falsified while M5 was being written.
It read *"Mining has been run by hand over a real repository twice, and the second run is the one
to read."* [`m5-yield-public-repos.md`](../milestones/m5-yield-public-repos.md) records a third
run, over three further repositories: **600 single-parent commits examined → 14 valid tasks**,
measured with the shipped command on the host path
([ADR-0053](0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md)). A front
page whose zero-yield framing has been overtaken by the milestone it is shipping with is not a
cosmetic problem, and the same defect class had already been cleaned out of
`m5-public-release.md` one file over. The changelog form is what let it sit there: a paragraph
nobody rereads because it is "the M2 paragraph" is a paragraph that ages without anyone noticing.

## Decision
**The README is a release document. It states what Assay does today, what it has measured, and
what it has not, and the milestone-by-milestone narrative lives in `docs/milestones/`, which the
front page links to rather than paraphrases.**

Four things are settled by that, and they are the whole of what this record binds.

**1. The status block names the milestone and the shape of the published results, and nothing
else.** It says which milestone the tree is at, that the results published in this repository are
the two oracles, and that no model has been called in any milestone — then it points at
`docs/milestones/`. It does not recite what each milestone contained. `SPEC.md` §7 holds the plan
and the milestone records hold the outcomes; the front page holds neither, because a third copy of
both is a third thing to keep true.

**2. "What it does not do" stays, and stays load-bearing.** It is the section this document exists
for, it is written to understate, and nothing in the collapse is allowed to shorten it. It keeps:
that Assay is not a leaderboard; that it is not a SWE-bench competitor; that numbers are
meaningful only for the repository they were mined from, with the yield form beside them; that it
does not answer portcall's question; that no real tool has been scored, by any milestone including
this one; and — added here — that Assay has mined very few real repositories, all of them either
zero-yield or chosen in advance to fit what the miner reaches.

**3. Every sentence about the public-repo yield preserves what `m5-yield-public-repos.md` §4 says
it is.** The number may be stated. What may not be stated, in any compression of it, is that the
reach limit moved. The three repositories were chosen under a rule written down before the first
clone existed — small single-package pytest libraries with pinned dev dependencies and no service
dependencies — and that rule selects for the shape the miner already reached, so this is a reach
limit **sidestepped by advance selection, not lifted**.
[ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md) is unrepealed, three repositories
chosen that way are not a sample of anything, and the 14 tasks have never been re-validated or run
by any tool. The front page carries all four of those clauses in the same breath as the number,
not in a footnote below it.

**4. [ADR-0042](0042-the-readme-withdraws-the-promise-of-a-live-run.md)'s rule is unweakened by
the move, and this record is not an occasion to revisit it.** The README makes no dated promise
about a milestone that has not shipped. A shorter document is exactly where such a promise gets
re-inserted as a convenience — "the live run is next" reads as forward momentum and costs one
clause — so the rule is restated here rather than left to be inferred from a document that no
longer contains the withdrawn sentence's neighbours. No milestone owns the live run, the README
says so, and the blank stays blank.

The three strings `tests/docs/test_readme.py` pins are untouched by all of this and stay verbatim
and unwrapped on one line each: `HOST_EXECUTION_SENTENCE`, and the fixture yield in the two forms
composed from `tests.fixture_repo.EXPECTED_YIELD`.

## Alternatives considered
- **Leave the changelog and append an M5 paragraph.** The cheapest option, and the one four
  previous milestones took. Rejected because it is the mechanism that produced the falsified
  sentence: each paragraph is correct when written and nobody owns the whole, so the front page
  drifts one milestone at a time while every individual edit looks fine. A fifth append would also
  have put the 14-task result at the bottom of a 38-line preamble, which is precisely where a
  reader who stops early never reaches it.
- **Keep the narrative and add a "Changelog" heading over it.** Rejected as the same content with
  a label that makes it a promise. A section named changelog is one a reader expects to be
  complete and maintained, so it would commit this repository to appending forever — and it would
  still be a lossy copy of `docs/milestones/`, now with a heading asserting it is the canonical
  one.
- **Move the narrative to `docs/milestones/README.md` as an index and link that.** Rejected for
  now, though it is the closest rejected option and may be right later. Six documents in one
  directory with self-describing filenames do not need an index yet, and an index is a seventh
  document that can disagree with the six — the same drift, one directory down. If a seventh
  milestone record ever lands, this is the alternative to revisit.
- **Cut "What it does not do" down as part of the tidy.** Rejected outright, and named here
  because it is the collapse's obvious next step and would be the one real harm. That section is
  the reason this README is worth reading; shortening a document by removing its limits is how a
  release document becomes marketing. The collapse removes a recital of what happened and adds a
  limit; it does not trade one for the other.
- **State the 14-task yield as the headline and put the qualifications in the milestone
  document.** Rejected. It is the strongest sentence M5 has and the compression is tempting — "600
  commits → 14 valid tasks" reads as a capability. Detached from the selection rule it is an
  overstatement of the kind CLAUDE.md calls fatal for this project, and
  [ADR-0054](0054-a-premise-of-adr-0050-is-overtaken-and-the-decision-stands.md) had already
  established that this number narrows one claim without widening any capability. A number whose
  qualifications live in another file is a number quoted without them.
- **Delete the httpie block entirely, since M5's yield supersedes it.** Rejected: it does not
  supersede it. Two zero-yield runs over 743 commits of a repository nobody selected for
  mineability are the *other* half of the reach picture, and dropping them would leave a front
  page reporting only the run that worked. Both stay, in the order they happened.

## Consequences
**The front page is shorter and says less about the past.** A reader who wants the
milestone-by-milestone account now needs one more click, into `docs/milestones/`. That is an
accepted cost: the account they land on is the fuller and more careful one, and the version they
would have read on the front page was the lossy copy.

**One falsified sentence is corrected and the correction is visible.** The README no longer says
mining has been run over a real repository twice, and no longer implies that every attempt against
real software returned zero. It says what the three runs were, in order, with the fourth clause of
the qualification attached to the one that did not return zero.

**Nothing here changes code, and no number in the README moves.** The two httpie figures stay as
they were — a 40-commit pilot and a full 743-commit walk under the same pinned-image harness, both
zero, both true of different runs recorded in the same document — and the fixture yield stays
pinned to `EXPECTED_YIELD` by `tests/docs/test_readme.py`. The only executable consequence of this
record is its own file, its index row, and the two parametrised cases the ADR-index suite adds for
it.

**The rule binds the next milestone too, if there is one.** A milestone that closes does not
append a paragraph to the front page; it writes its record in `docs/milestones/`, and it edits the
README only where the present tense there has stopped being true. That is a smaller and better-
defined edit than the one this project had been making, and it is the one a reviewer can check.

**The `docs/milestones/` directory is now load-bearing navigation.** If it is ever reorganised,
the README's links break and the front page loses its account of what was measured. No test
asserts those links resolve, which is a real gap and is named rather than fixed here — the ADR
index has such a test (`tests/docs/test_adr_index.py`) and the milestone directory does not.
