"""The decision record is a document set with a shape, so the shape is asserted, not trusted.

Three properties carry this module, and each one fails a different way in practice.

The first is that the set is *closed*: ADRs are numbered sequentially from 0001 and none of
the numbers is missing, so a file added out of band - or a number quietly skipped - shows up
here rather than in a reader's head.

The second is that every ADR answers the four questions the template asks (`docs/adr/README.md`).
An ADR that records a decision without the alternatives that lost is the failure mode CLAUDE.md
names: a record written retroactively, which reads as a rationalisation.

The third is that the index and the directory agree *in both directions*. An ADR missing from
the index is invisible; a row pointing at a file that does not exist is a dead link in the one
document whose job is navigation. Neither half implies the other, so both are asserted.

The files are discovered by glob rather than listed: a test that hardcodes ten paths passes for
as long as somebody remembers to edit it, which is precisely the discipline these tests replace.
The one exception is the count, because there the number *is* the assertion.
"""

import re
from pathlib import Path

import pytest

ADR_DIR = Path(__file__).parent.parent.parent / "docs" / "adr"
INDEX = ADR_DIR / "README.md"

# Sequentially numbered ADRs only; `README.md` is the index, not a decision.
ADRS = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
ADR_IDS = [path.name for path in ADRS]

# The four headings `docs/adr/README.md` templates, verbatim and in the order it lists them.
REQUIRED_HEADINGS = (
    "## Context",
    "## Decision",
    "## Alternatives considered",
    "## Consequences",
)

# SPEC section 8 names seven decisions; M0's implementation forced five more and M1's forced
# seven. ADR-0020 is a process decision adopted from M1's retro; ADR-0021 is M2's first, forced
# by the pinned re-mine measuring zero, ADR-0022 is what auditing 0021's cutoff found, ADR-0023
# is the second half of the one widening 0021 allowed itself, 0025 and 0026 are what the
# post-fix re-mine forced, 0027 is what reviewing them found (an image's address claims a commit,
# so its build context is checked against that claim), 0028 is how a cgroup kill scores, 0029 is
# where a selector no runner would accept is decided, 0030 is the exit-code band 0028 carves that
# kill out of, 0031 is the wrap's audit of 0028, which argued from a denominator this codebase
# does not have, and 0032 is that same wrap at the other end of the same denominator: the rule
# deciding which of a commit's changed paths are its test half admits more than "test-anchored
# fix", so the yield is made to say what it counts rather than the rule narrowed on no
# measurement. 0024 is the one number the directory did not take in order: it was held
# vacant while two sandbox modules cited a decision M2 still owed, and written in that
# milestone's wrap once the code it describes had settled. 0033 is M3's first: n trials per
# task need a trial number, and the number was the adapter's until the harness took it. 0034 and
# 0035 are the pair that pays off 0005's pinned follow-up early - the real interval arrives a
# milestone before it was scheduled, so the placeholder apparatus is deleted rather than left
# saying "invented" over a measured number, and what the band is computed over, and which of the
# two scores does not get one, is decided where the numbers are. 0036 is M3's first decision
# about the outside world: the naive baseline is the first thing Assay has ever built that
# sends anything off this machine, so where the socket may be opened - one module, fenced by
# module path rather than by directory - is settled before the adapter that uses it is written.
# 0037 and 0038 are the pair M3's other first forces: a diff is model-authored now, so the
# cheapest route to green is to rewrite the failing test, and 0037 refuses a diff that names a
# test path before it is applied. 0038 is what that refusal needs to be worth anything - the
# tool works in one checkout and the measurement happens in another, so the recorded diff is
# the whole of what the tool did rather than a filtered account of it. 0039 names the tool M3
# measures and where it runs: Claude Code, non-interactively, inside a container phase of its
# own - which is the first time anything in a trial has been allowed a network, and therefore
# the first time the adapter phase and the measurement phase are two policies rather than one.
# 0040 is the one M3 owes a reader rather than the code: the naive baseline's answer is prose, so
# a markdown fence around it fails `git apply` and scores the floor of every report at zero for a
# formatting habit. Removing that fence is the harness editing what the tool produced, which in
# this project is a decision to be disclosed rather than a helper to be written quietly. 0041 is
# the smallest edit in the set and is recorded for where it sits rather than for its size: the
# default model is what an unflagged run measures and what both adapters write into their
# version strings, so moving it off the generation the adapters were written on decides what the
# outstanding live run will say - and it is taken before that run, so no recorded number moves.
# 0042 is M4's first, and it corrects this repository rather than deciding anything about it: the
# README promised that the first live run would be M4's, M4 was then scoped to machinery with no
# model called and nothing spent, and a promise about the future is the one kind of sentence a
# milestone can turn false without anybody editing it. The record is what makes the withdrawal
# visible instead of a quiet deletion.
# 0043 is M4's arithmetic, and the first record here about a number that is not a function of the
# data alone: pass@1 is a mean of per-task rates rather than a proportion, so its band is a
# bootstrap over the tasks, and a bootstrap has an input Wilson never had. The decision is
# therefore as much about the generator as about the interval - seeded inside the call, drawn with
# the one method CPython documents as stable across versions, and fixed in the source rather than
# offered as a flag, because a seed a run can vary is a knob on a measurement.
# 0044 is M4's other arithmetic and the first record here whose second half is about what a number
# is not allowed to do: the tools are run on the same tasks, so comparing them is a paired
# question the two marginal bands cannot answer, and the exact McNemar sum answers it over the
# tasks exactly one tool solved. The p is then printed beside the verdict and forbidden from
# moving it - a significant p under overlapping intervals is a finding, not a licence, and
# letting the more permissive of two statistics unlock the winner claim is 0005's failure mode
# with an extra step.
# 0045 decides nothing about Assay's code and is here for the same reason 0020 is: it edits the
# pipeline this repository is built with, and the trail should be readable from the repository
# whose retro produced it. A rule against briefing sub-agents with unverified facts had been in
# force for three milestones and was broken four times anyway, so what changes is not the
# obligation but the format - a figure now travels with the command that produced it, because a
# claim that cannot show its working is indistinguishable from one that was measured. It is
# recorded rather than quietly applied because it is deliberately weaker than the escalation the
# previous retro asked for, and a fifth occurrence is supposed to find that admission waiting.
# 0046 is M4's last, and the one whose subject is what a report may say when it has no number to
# print: every adapter in this repository records zero tokens, so a priced run cannot tell a tool
# that spent nothing from one nobody instrumented. The decision is to carry the reason beside the
# amount rather than collapse the two, and to print the costs section even when it has no dollars
# in it - both of which follow 0035's standing rule that an omission is stated rather than left
# blank. It also settles where prices come from: a command line, never a file in this repository,
# because a rate committed here would be a public price list nobody is maintaining.
# 0047 is the smallest question M4 asks and the one it could not leave unanswered: an installed
# Assay could not say what it was. The package version has read 0.1.0 through four milestones,
# so the line carries the milestone beside it, built from the same constant every suite records
# as its `generator` - one string on two surfaces, which is the arrangement 0013's warning
# sentence already has and a drift test already enforces. Its second half withdraws a claim
# rather than making one: the machinery for scheduling an unbuilt command is empty and no fifth
# command is coming, so what keeps it alive is a published exit code, and retiring that is M5's
# freeze to do.
# 0048 is M4's last, and it is about a sentence rather than a number: a price large enough to
# overflow decimal's precision was reported to the user as decimal's own bare class repr, under
# a frame claiming a file could not be read that had just been read. The decision is that the
# raise site owns the refusal's prose and the handler claims only what the code inside its
# `try` can have failed at - which is a narrower claim than the two handlers wrapping a single
# read may make, and the difference is now written down in both. It is here rather than folded
# into 0046 because misattributing a cause is the same defect as overstating a result, reached
# from the side of the output nobody reads until something has already gone wrong.
#
# The set is contiguous, and that is the assertion. Forty-eight files is the number a reviewer
# should find, numbered 0001 through 0048 with nothing missing.
EXPECTED_NUMBERS = {f"{number:04d}" for number in range(1, 49)}

# A markdown link target that names an ADR file: `[0005](0005-no-winner-....md)`.
_ADR_LINK = re.compile(r"\]\((\d{4}-[a-z0-9-]+\.md)\)")


def indexed_filenames() -> set[str]:
    """The ADR filenames the index's `## Index` table links to.

    Only that section counts. ADRs cross-reference each other by the same link form, and the
    index's own template block shows the file-naming rule, so reading the whole document would
    let a link from anywhere stand in for a row in the table.
    """
    text = INDEX.read_text(encoding="utf-8")
    _, separator, table = text.partition("\n## Index\n")
    assert separator, "docs/adr/README.md has no '## Index' section"
    return set(_ADR_LINK.findall(table))


def test_the_decision_record_is_exactly_the_numbers_expected() -> None:
    # With no gaps: a number skipped is a decision nobody remembers deciding to skip, and a
    # number added out of band is a record the index below has never heard of.
    assert {path.name[:4] for path in ADRS} == EXPECTED_NUMBERS


@pytest.mark.parametrize("adr", ADRS, ids=ADR_IDS)
def test_every_adr_answers_the_four_questions_the_template_asks(adr: Path) -> None:
    lines = adr.read_text(encoding="utf-8").splitlines()
    headings = [line for line in lines if line.startswith("## ")]

    assert headings == list(REQUIRED_HEADINGS)


@pytest.mark.parametrize("adr", ADRS, ids=ADR_IDS)
def test_every_adr_has_a_row_in_the_index(adr: Path) -> None:
    assert adr.name in indexed_filenames()


def test_the_index_lists_no_adr_that_does_not_exist() -> None:
    # The cheap half of the same agreement, and the one a rename breaks: moving a file updates
    # the glob above silently while the index keeps pointing at the old name.
    missing = {name for name in indexed_filenames() if not (ADR_DIR / name).is_file()}

    assert missing == set()
