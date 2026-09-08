# ADR-0054: A premise of ADR-0050 is overtaken by M5's public-repo yield, and its decision stands

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0050](0050-the-demo-runs-against-the-fixture-and-says-so-first.md) decided what the
repository's first command is allowed to point at: `scripts/demo.py` runs the whole pipeline
against SPEC §9's synthetic fixture repository, and prints `FIXTURE_NOTICE` to stderr before the
first subprocess starts. **That decision is right, it is what the script does, and this record does
not move it.** What this record is about is one paragraph of the argument underneath it, which a
measurement taken three days later has overtaken.

The paragraph is the second in 0050's Context, and its lead sentence is the claim: **"Pointing it
at real software does not work, and that is measured rather than assumed."** The evidence it cites
is two runs against httpie — 743 commits examined for 0 valid tasks in M1
([`m1-yield-httpie.md`](../milestones/m1-yield-httpie.md)), 40 commits and 3 candidates for 0 valid
tasks in M2 ([`m2-yield-httpie-pinned.md`](../milestones/m2-yield-httpie-pinned.md)) — and the
conclusion it draws for the demo is that a first command pointed at real software "prints an empty
suite".

**Later in the same milestone, the shipped `assay mine` was pointed at three public repositories
and did not print an empty suite.**
[`m5-yield-public-repos.md`](../milestones/m5-yield-public-repos.md) records 600 single-parent
commits examined for **14 valid tasks** — `itsdangerous` 1, `python-dotenv` 0, `tenacity` 13, at
`--limit 200` each — measured with the shipped command on the host path
([ADR-0053](0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md)), under a
selection rule and a limit fixed before the first clone. Both httpie figures 0050 cites are
untouched and remain what they were. What is no longer true is the generalisation stacked on top of
them: pointing the miner at real software produced tasks, on two of the three targets.

**What that number is, and what it is not, is fixed by the document that reports it and is not
re-argued here.** §4 of `m5-yield-public-repos.md` states the limits in its own words, and every
one of them binds this record: the three repositories were chosen against a rule that selects for
the narrow shape this miner reaches, so they are not a sample of anything and 2.3% is not an
estimate of a population parameter; [ADR-0019](0019-m1-cannot-mine-unpinned-test-dependencies.md)'s
reach limit is unrepealed, because nothing in the run bears on a repository whose test dependencies
are unpinned; and the 14 tasks have never been re-validated by `assay validate` or run by
`assay run` or by any tool. **M5 measured how far the miner already reached. It did not widen the
reach, and this record claims no widening.**

**Every ground 0050's decision actually rests on is untouched by the new number**, and 0050 states
all three itself. The fixture's yield is a *specification* rather than an observation — its history
is written so each of the gate's verdicts fires exactly once, and CLAUDE.md forbids adjusting its
expected yield to match a changed miner — where the public figures are pinned to three recorded
clone HEADs, so a clone made next month walks a different 200 commits while the fixture is rebuilt
identically from code in this tree. `src/` may not import `tests/`, so the demo is a script and not
a fifth subcommand whatever it points at. And the three walks took **15m08.2s** between them, one
of them 10m12.2s on its own, over clones a first command would have to fetch from the network —
which is not a first minute, and breaks 0050's promise that the demo costs nothing and reaches
nowhere.

## Decision
**This record amends ADR-0050; it does not supersede it. ADR-0050 keeps Status `Accepted`, its text
is not edited, and its decision is unchanged:** one script, `scripts/demo.py`, against the fixture
repository, with `FIXTURE_NOTICE` printed to stderr before the first subprocess starts. The demo
points where it pointed yesterday.

**One claim is narrowed and may not be relied on as written**: "pointing it at real software does
not work", in 0050's Context. The measured form it can still carry is the one its own citations
support — *the two attempts on httpie yielded zero valid tasks, twice* — and that form is enough
for the paragraph's argument, since a demonstration cannot depend on the reader's target having a
mineable history. Where the fuller answer is pinned, for anyone auditing either record:
`m5-yield-public-repos.md` §3 for the figures and §4 for what they are not, and ADR-0053 for what
produced them.

**The paragraph is left standing rather than rewritten.** It was correct on the evidence it cited
when it was written, and a record whose value is that it is evidence of the reasoning at the time
cannot be edited into hindsight without destroying the thing it is for.

**What survives is the whole of the decision, on grounds the new number does not reach.**

- **The fixture is still the only target whose numbers are a specification.** A demonstration's job
  is to show the pipeline doing what it claims, against an answer a reader can check against the
  tree rather than take on trust. 14 tasks mined from three moving upstreams are an observation;
  11 commits, 7 candidates and 2 accepted are a rule this repository's tests enforce.
- **The empty-suite argument is weakened for two repositories and holds for the third.**
  `python-dotenv` returned 0 valid tasks under the same rule and the same limit as the two that did
  not. A demo whose first impression depends on which clone the reader was handed is not a
  demonstration, and choosing the target that yielded would be selecting on the outcome — the one
  rejection ADR-0053 says is not about cost.
- **The placement argument never mentioned yield at all.** `src/` cannot import `tests/` in an
  installed wheel and SPEC §6 freezes the surface at four commands
  ([ADR-0047](0047-the-version-line-names-the-milestone.md)); neither sentence is affected by what
  a mine of `tenacity` returns.
- **The frame is needed either way.** 0050's other half — that a fixture is the thing a
  demonstration can lie with, so the notice states the target and the yield before anything runs —
  argues *for* disclosure, not for the target, and a demo pointed at real software would need a
  longer notice rather than none.

## Alternatives considered
- **Edit ADR-0050 in place, or add a dated amendment block to its Context.** Rejected, and the
  in-file note is the tempting middle: it is the one form that puts the correction where the reader
  who opens 0050 will actually see it. `docs/adr/README.md` states that ADRs are immutable once
  accepted, and [ADR-0023](0023-the-image-installs-declared-test-extras.md) already answered this
  exact question for 0018 — a back-pointer written into the amended record "is a second place for
  the two to disagree", and the amendment belongs in the amending record and in the index row.
  [ADR-0031](0031-an-errored-trial-never-leaves-the-denominator.md) took the same route for 0028
  with the same cost accepted. Taking a different route here would make the directory's convention
  depend on who was writing that week.
- **Fold the relation into ADR-0053, which is where the measurement lives.** Rejected: 0053 is an
  accepted record of a decision about how a number was produced, and completing it after the fact
  is the immutability problem moved one file over. It would also mis-file the content — the
  question of what a yield figure does to the demo's premise is not a question about which miner
  measured it.
- **Supersede ADR-0050 and restate the decision with the corrected premise.** Rejected. Supersession
  marks a decision as dead, and this decision is alive and running on every `python scripts/demo.py`
  — `Superseded` in the index would be a false status pointing readers away from the record that
  still governs the script. The narrower `amends` relation exists for precisely this case, and the
  index already carries it six times over: 0021 amends 0019, 0023 amends 0018, 0025 amends 0019
  and 0021, 0031 amends 0028, 0043 amends 0035, 0053 amends 0025.
- **Leave it alone: the decision is right, no code reads the sentence, and both httpie runs are
  still zero.** Rejected, though it is the cheapest option and nothing breaks tomorrow. A reader can
  open 0050 and the M5 yield document in either order, and in one of those orders the ADR reads as a
  claim the milestone next to it contradicts. A premise known to be overtaken and left unmarked in a
  public repository whose subject is measurement honesty is the failure this project exists to
  refuse — the same reason ADR-0031 refused it, and the same reason
  [ADR-0042](0042-the-readme-withdraws-the-promise-of-a-live-run.md) withdrew a README promise
  nobody had complained about.
- **Record the correction in `m5-public-release.md` instead of an ADR.** Rejected: a reader reaches
  0050 through the index or through `scripts/demo.py`'s docstring, not through a milestone document,
  so the correction has to live where the index can point at it from the row beside 0050's own.

## Consequences
**This record changes no code, no test and no behaviour.** `scripts/demo.py` runs the same five
steps against the same fixture with the same notice before and after it; the demo's argvs, the
suite hash it produces and the report it renders are byte-for-byte unaffected. The only edits it
lands are its own file, its row in the index, and the ADR count the index test asserts.

The cost of amending rather than editing is a real one and is accepted with open eyes: **ADR-0050's
text does not know it has been amended.** A reader who opens that file directly reads the overtaken
sentence with nothing beside it, and the only signpost is the `amends 0050` relation in the index
row here. That is the same contract 0028 already has with 0031 and 0019 with 0021 and 0025, so the
directory is consistent rather than newly compromised — but it means the index is load-bearing
navigation, not decoration, and a reader who greps the ADR prose alone will miss the relation.

**Two smaller echoes in 0050 are named rather than fixed.** Its Decision says `FIXTURE_NOTICE`
"cites both httpie runs with their real numbers", and its Consequences enumerate the notice's
rotting numbers as "11 commits, 2 tasks, 743, 40". The notice now also cites the M5 public-repo run
— 600 commits, 14 tasks — so both sentences under-count what the string contains. They are
descriptions of a constant, they move nothing, and correcting them would be an edit to an accepted
record; this record is the authority for reading them as under-inclusive rather than wrong.

**Nothing here licenses pointing the demo at a public repository later.** If that is ever wanted, it
needs its own record and its own measurement: a clone step, a network dependency the demo currently
does not have, a wall clock in minutes, and an answer to which repository and why that is not
chosen after seeing its yield. This record settles only that the existing decision survives the new
number intact.
