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
# 0049 is M5's first, and it is the milestone's own subject applied to the report: the document
# stops being read by the person who produced it, so it says what its column of HMAC tokens is
# and that the salt behind them is drawn per render and never kept - the property 0009 provides
# and a recipient cannot check for themselves. Its second half is a refusal that costs nothing to
# state now and would be expensive to reverse later: no timestamp, no generator string, no field
# in the schema. A clock would put I/O in a layer whose renderers are pure and make two renders of
# one result set differ, the suite hash is already the provenance that matters, and prose inside
# the canonical document would freeze one wording as a compatibility promise in the milestone
# that makes the schema public.
# 0050 decides what the repository's first command is allowed to point at. The answer is the
# fixture, because the two runs against real software are on the record at 0 valid tasks and a
# demonstration that prints an empty suite teaches the wrong lesson - and because the fixture's
# yield is the one number in the project that is a specification rather than an observation. The
# cost of that choice is that the numbers are about the harness, so the frame is printed to stderr
# before the first subprocess starts rather than left to the README. The rest of the ADR is where
# the demo may live: a script and not a fifth subcommand, because `src/` may not import `tests/`
# and 0047 has just decided M5 freezes the surface rather than growing it.
# 0051 is the decision the release will be judged on. SPEC section 7 grades M5 on published
# results for two tools, and the two adapters that ran are oracles - the recorded fix and nothing
# at all - which bracket every real result precisely by not being one. The record is that the
# criterion is met in letter and short in substance, that both halves are written down, and that
# the disclosure sits above the figures rather than below them, because a reader who sees a
# pass^n table first has priced the repository before reaching a caveat. It extends 0042 from the
# front page to every published surface: 0042 forbade a dated promise about a milestone that had
# not shipped, and this forbids a number described as something other than what produced it.
# 0052 closes a hole in 0007 that had been open since M0 and sat in one field nobody read: a
# repository with no `origin` named itself by its absolute path on the host, and that path is
# inside the body a suite's content address is a hash of - so one history mined from two
# directories had two addresses, which is the exact failure content addressing exists to
# prevent. The name is now the repository's own root commit or commits, sorted and joined,
# because that is derived from what the history contains rather than from where it sits. It
# extends 0007 and supersedes nothing, and it records one residual it does not fix: two
# spellings of one `origin` URL still give two addresses.
# 0053 records what produced M5's public-repo yield, and it is the shipped `assay mine` on the
# host path: `run_mine` passes `host_runner_for` as a literal, so the pinned per-task image 0021
# and 0023 built lives in `assay run`'s trials and has never been wired into mining. The
# alternative was M2's uncommitted re-mine script, which would have published a headline figure
# nobody outside this machine could re-derive. It amends 0025 by naming where that spent widening
# lives, and it fixes the selection rule and the walk limit before the first run so that no
# threshold in the published document can have been chosen after seeing a number.
# 0054 marks one paragraph of 0050 as overtaken by the yield 0053 produced: the claim that
# pointing the miner at real software does not work was measured against two httpie runs, and
# three public repositories later returned 14 valid tasks out of 600 commits. The decision does
# not move, because none of the grounds it rests on does - the fixture's yield is still the only
# one in the project that is a specification, `src/` still may not import `tests/`, and a first
# command still cannot clone and mine for a quarter of an hour. It amends 0050 rather than
# editing it, for the reason 0023 and 0031 give: an ADR is immutable once accepted, and a
# back-pointer written into one is a second place for the two to disagree.
# 0055 turns the README from a changelog into a release document: the milestone-by-milestone
# narrative it accumulated from M0 to M4 moves to `docs/milestones/`, where one record per
# milestone already says what that milestone did and did not establish, and the front page keeps
# the present tense, the "What it does not do" section and the yield sentences the tests pin. It
# applies 0042 rather than weakening it - no dated promise returns with the shorter text - and it
# is the record for how M5's public-repo yield is worded on the front page: a reach limit
# sidestepped by advance selection, never one lifted.
# 0056 is the freeze 0047 scheduled, and what it records is a deletion. The machinery for
# declaring an unbuilt command has been empty since M3 built `run`, and the only thing keeping it
# alive was exit code 3, published since M0 and producible by no path in the tree. M5 freezes the
# surface, so the choice is between publishing a code nothing can return and retiring it, and
# this record retires it - the two dicts, the subparser loop over an empty one, the unreachable
# raise, `EXIT_NOT_IMPLEMENTED`, `NotImplementedInMilestone` and the README row all go. It
# discharges 0047 rather than amending it: 0047 named this milestone's freeze as the trigger and
# listed the deletion as the alternative it rejected on scope, so what happened here is the
# deferral being honoured, not the decision being revisited.
# 0057 records the HTML report's legibility rules - a light canvas declared rather than inherited
# from the reader, a scroll container per wide table, hashes that wrap rather than truncate - as an
# application of 0049, on the ground that a claim the reader cannot read whole is not on the page.
# 0058 gives the two prose renderers a `RedactedReport` parameter, so that 0049's sentence about
# the tokens on this page rests on the type of the argument rather than on a check the renderer
# never performs; it applies 0049 as well, and neither record supersedes anything.
#
# 0059 is the first record about calling a model at all: five milestones of oracles have never
# sent a prompt anywhere, a paid call is refused outright, and a model served on this machine is
# the way out - so the loopback transport is a second class beside the keyed one rather than a
# widened allowlist, on the ground that bytes which never leave the machine are not what the
# allowlist controls. It applies 0036 without touching the fence, and discloses where it departs
# from the SSRF rule it inverts.
#
# 0060 and 0061 are what wiring that transport into the CLI forces, and they are two decisions
# rather than one because they answer to different authorities. 0060 answers to CLAUDE.md's rule
# that the naive baseline is in every report: a free local baseline is exempt from being asked for
# a paid one, and does not stand in for one when a tool is named, because a measurement rule
# satisfiable by choosing a weaker opponent is not a rule. 0061 answers to ADR-0051, which
# rejected exactly this substitution two days earlier and named three grounds; it overturns that
# one bullet, discharges each ground, and leaves 0051's decision and its file alone - the only
# record here that amends another without touching a line of it. It also settles that the local
# endpoint is a compiled-in constant, since an endpoint a command line can redirect is one the
# prompt can be redirected to.
#
# 0062 and 0063 are what the local-model run's blocker forces, and the first pair here whose
# subject is Assay's own checkout rather than a repository it reads. Thirteen task images could
# not be built because the build context was a linked worktree with its `.git` excluded, and a
# repository that versions itself from git - setuptools-scm, hatch-vcs, pdm-backend, versioneer -
# has nothing to derive a version from in a tree like that. 0062 records that this is a defect in
# how Assay checks out rather than a reach limit of the commit, which is the distinction ADR-0025
# draws and the reason "tenacity is unscoreable" is not publishable: a plain clone builds it. The
# context becomes a standalone checkout carrying real history, and the *trial workspace*
# deliberately does not, because a workspace with every ref in it is a bind-mounted answer key.
# The record also states, with the measurement inline, the half the decision does not close: the
# base image has no git executable, so the history it now carries is still inert.
# 0063 is what that costs the address. Removing `.git` from the exclusions changes what is inside
# an image while every existing tag stays put, and the dockerignore that decides it had never been
# hashed - the same gap `_BASE_IMAGE` was closed against. A clone's visible history joins it,
# because history is a build input now and it is a property of the clone rather than of the
# commit. Both are one optional `context` key rather than two required arguments, so the two
# phases that build from an empty directory keep the addresses they already had.
#
# 0064 and 0065 finish what 0062 started, and each is a decision that record deliberately did not
# make. 0064 puts a git in the measurement image: the history 0062 restored is inert without a
# reader, the base image ships none, and the fix is a line in the recipe - which is the content
# address, so it re-addresses every task image ever built and is therefore a decision rather than
# a repair. It is pinned to a version for the reason `_BASE_IMAGE` is pinned to a digest, and it
# sits above `COPY` where nothing about it varies with the commit, so the daemon holds one copy
# instead of one per image. What it does not claim is written down beside it: the package's
# dependency closure is unpinned, so the layer is not byte-reproducible over time.
# 0065 corrects a residue 0062 recorded wrongly. That record named `.git/config` as the carrier of
# this machine's path, which makes a one-line `remote remove origin` read as sufficient; measured,
# `.git/logs/HEAD` independently holds the path, the operator's real name and email, and a wall
# clock, and the remote's removal never touches it. The clone writes no reflog at all now. The
# record is equally explicit that byte-identity across hosts is *not* what this buys and cannot
# be: the index holds stat data and the config holds platform-probed capabilities.
#
# 0066 is the only record here that changes no code, and its subject is what Assay will not do
# yet. `assay mine` provisions a candidate on the host while `assay run` scores one in an
# era-pinned image, so the gate that admits a task to a suite runs somewhere other than the thing
# that sells it - named in 0053, left open there deliberately, and narrowed rather than closed by
# 0062 through 0065, which bought both paths a real git repository and nothing beyond that. The
# standing recommendation across four sessions was an ADR deferring it indefinitely; this record
# overrules that and gives it a milestone, on the ground that a known measurement asymmetry made
# permanent is the thing this repository exists to refuse. What it declines to do is close it
# first: a mine run through the image path produces a different suite, a different hash and a
# different denominator, which voids a pre-registration written while no result existed - so the
# sequencing is the decision, and it is on the record before the number is. The wall clock that
# motivated it is marked `unverified:` in its own text, no per-image build time having ever been
# measured on this host, and the record says the argument does not rest on it.
#
# 0067 is the schema the next two write into, landed first so that they stay revertible without
# it. A result set said only which trials happened, so three trials of each of twelve tasks and
# three trials of each of twelve tasks out of thirteen were the same document, and pass^n over it
# was a rate whose denominator no reader could check - the numerator-alone failure CLAUDE.md
# names on the mining side, where `MiningYield` has carried its denominator beside its numerator
# since M1. `ResultSet` gains that denominator as a required field, because one that defaulted
# would read as zero beside twelve measured tasks, and a map of task id to the sentence that
# failed it rather than a tuple of two-field records, so a task named twice with two reasons is
# unwritable rather than merely invalid. The denominator is stored and not derived: nothing in
# this repo resolves a suite digest back to the suite, so a `--suite` argument at report time
# would let two readers of one file print two coverages, and the number wanted is a fact about
# the run rather than about a file someone points at later. Its validator compares with `<=`
# where the mining side's compares with `!=`, which is 0069's cadence showing through - a file
# covering one task of thirteen is a run in progress, not a counting bug - and what stays refused
# is the direction that can flatter: more coverage claimed than the suite holds, or one task
# counted on both sides at once.
#
# 0068 and 0069 fill the fields 0067 declared, and they are two records because they answer two
# different questions about the same loop. 0068 is what a run does about a task it cannot
# provision: one state for both causes, since an image that will not build and a test patch that
# refuses at its base commit are the same failure a layer apart and neither is the tool under
# test; and a task that fails partway keeps none of the trials it scored, because three surviving
# trials of five would be published as that task's pass^n with an exponent no reader can see.
# 0069 is when the file is written: after every task and once before the first, where it used to
# be written once at the end. That record quotes the reasoning it overturns and answers it rather
# than dropping it - the ambiguity write-once guarded against was "a short file cannot say what it
# is short of", and 0067's denominator is what makes the short file self-describing. Both premises
# of the old rule are gone, and the live run that lost 105 scored trials to a single unbuildable
# task is what made the second one false.
#
# 0070 is where 0067's fields reach a reader. The denominator had been in the file since 0067 and
# on no page at all: a run of twelve tasks out of thirteen rendered as pass^n, two bands and a
# costs table over twelve, under a heading carrying the suite digest and nothing else, which is
# the numerator alone that CLAUDE.md forbids by name. The coverage line goes in both prose
# formats on every report - including the run that missed nothing, because a section appearing
# only when it had bad news in it would make its absence the claim (0035, as 0046 already
# settled for the costs). The shape is the decision: three flat fields rather than a `Coverage`
# sub-model, because `redact` names every field one at a time and that is the guarantee rather
# than the style - a nested model would type-check while carrying an unhashed identifier onto a
# page whose own sentence says every identifier on it is a token (0058). The unprovisioned ids
# are hashed under the same `ident` kind a trial line's id gets, so the one task with no trials
# anywhere in the document is one a reader can look for in the log and confirm is absent.
#
# 0071 is the first record here whose subject is a question rather than a change, and it closes one
# that had been carried unanswered through five sessions: whether a later milestone should supersede
# 0025 and try the setuptools floor as a disclosed second widening. Two things make it answerable
# from the record that already existed. The blocker that made it feel urgent turned out to share a
# word with it and not a cause - the thirteen images that would not build failed in setuptools-scm,
# on a build context Assay itself had emptied, and 0062 through 0065 closed that without touching
# the resolver. And the residue 0025 actually named arrived again on a second repository: the scored
# run covers eleven of thirteen tasks, and both it could not provision failed on `distutils` under
# an era pin, which is the exact case a floor would patch. The decision is that the floor stays
# declined for 0025's unweakened reason - a version constraint Assay invented makes the environment
# one that never existed - and that it stops being carried, because a question re-read and re-costed
# every session while the evidence to settle it sits complete is a cost paid in instalments. 0025 is
# not edited, on the immutability pattern 0054 and 0061 set, and the two tasks get the coverage line
# 0070 prints rather than a patch.
#
# 0072 does for 0042 what 0054 did for 0050: two of its statements of fact are overtaken and its
# rule stands. 0042 told a reader the numbers printed here came from the two oracles, and that the
# bootstrap band and the McNemar p had never been computed over a run that called a model; the
# local baseline's run printed a third adapter's figures and a p over an adapter that had called
# one. Its surviving neighbour - no report has computed either over a *tool* that called a model -
# is kept on purpose, because 0060 makes the local baseline not a tool. It amends 0042 and 0055
# without editing either, carries the mark in the index row alone rather than a blockquote inside
# 0042, and binds no new general rule: the proposed one was argued from a run 0066 had already
# made a milestone, so it waits for a run that 0042's rule demonstrably fails to reach.
#
# 0073 gives one state one shape. The run already named each task it could not measure beside the
# sentence that failed it (0067, 0068); the mine only counted its unprovisioned commits, because the
# host seam caught the setup error and handed `None` back, dropping the one sentence that said why -
# and a sentence was the whole of 0071's finding. The user ruled for the mapping: `MiningYield`
# names each commit by full sha with the failure's own words, the factory returns an `Unprovisioned`
# value that carries them, and `assay mine` prints one reason line per commit on stderr while its
# yield line stays byte-identical. The partition counts the mapping's size, so the fixture's exact
# yield does not move, and no suite or content address changes because the yield is never
# serialised. It amends 0015, which is shipped and so is marked in its index row only, and 0066,
# which is not yet shipped and so carries a dated blockquote as well.
#
# The set is contiguous, and that is the assertion. Seventy-three files is the number a reviewer
# should find, numbered 0001 through 0073 with nothing missing.
EXPECTED_NUMBERS = {f"{number:04d}" for number in range(1, 74)}

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
