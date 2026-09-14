# ADR-0071: The `setuptools` floor is declined for good, and the two builds it would have rescued are reported rather than patched

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Bogdan Dzekic

## Context

[ADR-0025](0025-the-one-widening-is-spent.md) spent the one widening budget
[ADR-0021](0021-resolution-is-pinned-to-the-base-commit-era.md) allowed itself, and refused the
three patches that were visibly available with the failing commits on screen: install `gcc`,
constrain `setuptools`, pin the interpreter per era. It named the second of them the closest call
of the set and said why it lost:

> They are refused because they were chosen *after* seeing which commits failed and what they
> printed, which is the definition of the tuning this project exists to detect. A `setuptools` pin
> is also not a small change dressed as one: it would put a resolution decision Assay invented into
> an environment that is supposed to be the commit's, so a task mined under it would be measured in
> a world that never existed.

That settled M2 and it deliberately did not settle the future. The same record's Consequences left
a door open — "a third widening now needs its own ADR arguing from something other than a
disappointing number" — so the floor remained a thing a later milestone could propose properly,
rather than a thing forbidden outright.

**It was proposed, and never decided.** Through this goal's sessions the same sentence travelled
in the handoff, verbatim, five times: whether a follow-on milestone should deliberately supersede
ADR-0025 and try the `setuptools` floor as a disclosed second widening. Each session read it,
re-costed it, carried it forward, and answered nothing. Two things have since made it answerable
from the record that already exists.

**The blocker that made it feel urgent was solved another way, and the two shared a word rather
than a cause.** The thirteen `jd/tenacity` task images that would not build on 2026-09-10 failed
inside *setuptools-scm*, deriving a version from a `.git` Assay's own build context had excluded —
a linked worktree, not the commit's fault. [ADR-0062](0062-the-build-context-is-a-standalone-checkout-the-workspace-is-not.md)
records that as a defect in how Assay checks out rather than a reach limit of the repository,
[ADR-0063](0063-what-the-context-excludes-and-its-history-enter-the-address.md) puts what the
context excludes and what history it carries into the image's address,
[ADR-0064](0064-the-measurement-image-carries-a-pinned-git.md) gives the measurement image a pinned
`git` so that history is legible, and [ADR-0065](0065-a-throwaway-clone-writes-no-reflog-and-keeps-no-origin.md)
makes the clone a throwaway that keeps no origin. **None of the four touches the resolver, widens
an install, or puts an Assay-invented version constraint into a commit's environment.** The
blocker closed with the era pin exactly as ADR-0021 left it.

**ADR-0025's actual residue is unchanged, and the harness can now report it instead of dying on
it.** The scored run of 2026-09-11 against the pre-registered suite covers **11 of 13 tasks**, and
the two it could not provision failed with `No module named 'distutils'` — resolved as of December
2020 and July 2021, built on CPython 3.12. That is the 90-commit failure mode ADR-0025 measured at
scale on `httpie` (743 commits examined, 125 `unprovisioned`, 124 of 126 base images failing, every
one of them older than March 2024), arriving unchanged on a second repository. It is precisely the
case a `setuptools` floor would patch, and it now costs two named tasks on a coverage line rather
than a run: [ADR-0067](0067-the-result-set-carries-its-own-denominator-and-names-what-it-could-not-measure.md)
through [ADR-0070](0070-the-report-publishes-its-coverage-and-names-what-it-could-not-measure.md)
recorded it, printed it, and let the other eleven tasks be published.

## Decision

**The `setuptools` floor is formally declined. It is not deferred, not scheduled, and not carried
any further.**

**ADR-0025's argument is the reason, and it has not weakened by a word.** A floor is a resolution
decision Assay invented, imposed on an environment whose entire purpose is to be the commit's; a
task mined or scored under it is measured in a world that never existed. Nothing in the fourteen
months of Python history between the two failing `tenacity` commits and today changes that, and
nothing in the local-model run changes it either — the run is the second measurement to show what
the limit is, not the first to show it can be argued away.

**It is declined rather than deferred, and that is the second half of this record.** No milestone
owes it, no handoff carries it, and no future session re-reads it as an open item. A question that
survives five sessions unanswered is not free: it is re-read, re-briefed and re-costed every time
it moves, and it pays no dividend at any point because the record needed to answer it was complete
before the first carry. Carrying an unanswered question across sessions is a cost paid in
instalments, and closing it here is how that debt is settled rather than refinanced. Anyone wanting
the floor after this argues against two records, from a fresh measurement, at the bar ADR-0025
already set: something other than a disappointing number.

**ADR-0025 is not edited, not amended and not superseded.** Its decision stands in full; this
record answers the question its Consequences left open, which is the arrangement
[ADR-0054](0054-a-premise-of-adr-0050-is-overtaken-and-the-decision-stands.md) and
[ADR-0061](0061-the-local-baseline-is-the-substitute-adr-0051-rejected.md) already use — a later
record speaks, the earlier file stays exactly as it was accepted, and the two never disagree
because only one of them was ever written.

**What the two unmeasured tasks get instead of a patch is a sentence on the page.** "11 of 13 tasks
measured; 2 could not be provisioned and so appear in no number on this page", with both task
tokens named. That is ADR-0025's posture — report the limit and the zero — made cheap by machinery
that did not exist when it was written.

## Alternatives considered

**Take the floor as a disclosed second widening, in a milestone of its own.** The proposal exactly
as it was carried, and the one this record refuses. Disclosure is not what is wrong with it: the
objection is that the change itself is a measurement error, because the environment stops being the
commit's and becomes one Assay composed. It would also be chosen after seeing which commits failed
and what they printed — for the second time, on a second repository, which makes it a worse version
of the decision ADR-0025 declined rather than a better-argued one. And the yield is two tasks of
thirteen in a run whose published pass^n is 0.000 for the measured eleven; a widening that cannot
move the finding is tuning with nothing even to show for it.

**Supersede ADR-0025 and re-run the pre-registered suite under a floor.** Rejected twice over. The
decision to be superseded is not wrong, so the supersession would be machinery for changing a
correct record; and re-running the suite under a different image recipe after seeing the figure is
the re-roll the pre-registration forbids
([ADR-0066](0066-the-provisioning-asymmetry-gets-a-milestone-not-a-deferral.md), Decision 3).

**Pin the interpreter per era — the third of ADR-0025's three patches.** Not decided here, and
named so that this record is not misread as closing all three. It is a different kind of change:
it makes the environment *more* the commit's rather than less, which is why ADR-0025's own
Consequences call per-era base images "the decision M3 has to take" rather than a widening. It is
still owed a record by whoever takes it, and this declination neither blesses nor blocks it.

**Defer it one more time, with a note in the next handoff.** Rejected: that is what the last five
sessions did, and the note is now longer than the decision. Deferral is the right answer when new
evidence is coming; none is, because the evidence the question needs is ADR-0025's measurement and
this run's coverage line, and both are on the record.

**Leave it undecided on the grounds that it changes no code.** Rejected. ADR-0066 is the precedent
and it changed no code either: a record whose subject is what Assay will *not* do is exactly what
the directory is for, and an unwritten refusal is indistinguishable from an oversight to anyone
reading this repository from outside.

## Consequences

**Assay's reach over pre-2024 Python is unchanged, and is now measured on two repositories rather
than one.** An era-pinned resolution meeting CPython 3.12 fails, the failure is a property of the
pairing rather than of the repository, and Assay says so in a count rather than patching until
something passes. The `httpie` walk and the `tenacity` run agree on that, four months and two
codebases apart.

**A build failure of this class now costs its own task and nothing else.** Before ADR-0068 it ended
the run; on 2026-09-10 it took 105 scored trials with it. The published run of 2026-09-11 lost two
tasks and kept eleven, which is what makes declining the patch affordable rather than merely
principled.

**Two `tenacity` tasks are permanently unmeasured under the current recipe,** and the denominator
on every report that includes them says so. That is the cost of this record, stated where a reader
meets the number rather than in a footnote here.

**The open-question list is one item shorter, and the item was not closed by being done.** It was
closed by being answered, which is the only way a carried question ever leaves a list without
becoming work. A future session that finds the floor proposed again should find this file first.

**What remains open is named and not confused with this:** `gcc` and the per-era interpreter stand
as ADR-0025 left them, and the provisioning asymmetry between the host-path gate and the image-path
scorer is still owed the milestone ADR-0066 gave it.
