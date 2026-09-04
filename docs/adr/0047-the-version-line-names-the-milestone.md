# ADR-0047: `--version` names the milestone beside the package version, and the unbuilt-command machinery outlives its argument

- **Status:** Accepted
- **Date:** 2026-09-04
- **Deciders:** Bogdan Dzekic

## Context
Assay is a harness whose output is only worth anything if a reader can say what produced it.
Every suite file records a `generator` for that reason
([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)), and every result cites the
suite digest it was measured on. The one thing missing from that chain is the obvious one: an
installed Assay cannot be asked what it is. `assay --version` is a usage error today, exit 2,
because the flag has never been registered.

**The package version cannot answer the question on its own.** `version("assay")` has read
`0.1.0` since M0 and will keep reading it until something is released. Four milestones have
landed under that string: M0's four-command skeleton with invented intervals, M1's miner, M2's
sandbox and executable scoring, M3's live adapters, M4's statistics and cost. A user holding a
`0.1.0` and a suite written by a `0.1.0` learns nothing from the match. `MILESTONE`
(`cli/main.py`) is the only token in the tree that moves when the harness does, and it exists
already, quoted into the "not implemented" message the surface has carried since M0.

**`GENERATOR` is the seam, and it is not a new one.** `GENERATOR = f"assay/{version('assay')}"`
is what `save_suite` writes into every suite's `generator` field. If the version line is built
from anything else, the repository acquires two spellings of one fact, and this project's own
rule about a warning worded two ways
([ADR-0013](0013-mining-runs-on-the-host-in-m1.md)'s host-execution sentence, pinned by a drift
test) applies with equal force to a build identifier.

`core/versioning.py` is not relevant here, and the resemblance is worth naming so nobody wires
the two together later. It probes a *document's* `schema_version` to decide whether Assay can
read a file somebody else's build wrote. That is a compatibility question about data. This is a
provenance question about an installation, and the two senses of "version" share nothing but
the word.

**The second force is a claim this module makes that is no longer true.** `PLANNED` and
`_UNBUILT_HELP` are the machinery that let an unbuilt command be reachable and honest: it named
the milestone that would build it and exited `EXIT_NOT_IMPLEMENTED`, so a script driving Assay
failed loudly rather than reading silence as a result. Both have been empty since M3 built
`run`, and the docstring justified keeping them by saying a fifth command would be declared the
same way. SPEC §6 publishes exactly four commands and SPEC §7's M5 adds none, so there is no
fifth command coming, and the branch that raises `NotImplementedInMilestone` is provably
unreachable. A record that reads as a capability the code does not have is a defect by
`docs/adr/README.md`'s own rule, and the same is true of a comment.

## Decision
**`assay --version` prints `assay/0.1.0 (milestone M4)` - one line, on stdout, exit 0 - built
as `f"{GENERATOR} (milestone {MILESTONE})"`. The `PLANNED`/`_UNBUILT_HELP` machinery stays, with
its argument withdrawn and its deletion deferred to a named milestone.**

**Both halves of the line, sourced once each.** The leading token is `GENERATOR` itself, not a
second read of the distribution metadata, so the string a reader sees on their terminal is the
string in the `generator` field of every suite this build writes, matchable byte for byte. The
milestone is the part the package version cannot supply. A drift test asserts
`out.split(" ")[0] == GENERATOR`, in the same mould as the one pinning the host-execution
sentence across the README and the `mine` help.

**On the top-level parser only, registered before `add_subparsers`.** Which build is installed
is a fact about the installation, not about `mine` or `report`, so it is asked once and answered
once. `action="version"` fires while argparse consumes options, which is *before* it enforces
the `required=True` subcommand, so `assay --version` works with no command named - the case a
user actually types. `assay report --version` is consequently a usage error rather than a silent
success, which is the conventional behaviour and the correct one: the flag is not part of the
`report` contract.

**Nothing on stderr, ever, for this.** `run_report` promises a successful report is silent apart
from the document, and `mine` and `validate` own the one warning banner the surface carries
(ADR-0013). A build identifier printed beside every command's output would either break that
promise or add a stream write nobody asked for.

**`PLANNED`, `_UNBUILT_HELP` and `EXIT_NOT_IMPLEMENTED` are kept, and the reason is restated
backwards.** They are no longer "how a fifth command would be declared"; they are a published
exit code with no live producer. Deleting them retires exit code 3 from a surface that has
advertised it since M0 and leaves `NotImplementedInMilestone` (`core/errors.py`, with its own
tests) without a caller. That is a compatibility decision about a public surface, and it is
taken where the surface is frozen. **Trigger: M5's public-release surface freeze**, at which
point the branch either gains a consumer or is deleted along with the exit code and the error
class.

## Alternatives considered
- **Print the milestone alone - `M4`.** Rejected: the only concrete consumer this flag has is a
  reader matching an installation against a suite file, and a line with no `assay/x.y.z` token
  in it cannot be matched against a `generator` at all. It would answer the question nobody is
  holding a document about.
- **Print the package version alone, as argparse's `%(prog)s %(version)s` default does.** The
  conventional line, and useless here for the reason the Context gives: it has not moved in four
  milestones and cannot distinguish any two of them.
- **Bump the package version each milestone instead - `0.4.0` for M4 - and print it alone.**
  Tempting because it needs no second token. Rejected: a version number is a release promise,
  nothing here is released, and the compatibility surface Assay actually versions is the
  document schemas ([ADR-0008](0008-pydantic-v2-over-canonical-json.md)). Minting semver for an
  unreleased harness would put a promise on the package that the schemas already make properly
  elsewhere, and every bump would silently restate what past suites claim about their maker.
- **Read the milestone from a git tag or a `VERSION` file.** Rejected: the repository has no
  tags, and either route puts filesystem or subprocess I/O behind a flag whose whole job is to
  print a constant. `MILESTONE` is already in the source and already correct.
- **Register `--version` on all four subparsers too.** Rejected: four spellings of one fact, and
  it implies a subcommand could be at a different milestone than the build it ships in.
- **Print a build banner on stderr at the start of every command.** Rejected: it breaks the
  silent-success contract `run_report` and its tests hold, and it would put a line in front of
  every piped `assay report --format json` run for the benefit of a question the user did not
  ask.
- **Extend the line with the document schema versions.** Rejected: that is `core/versioning.py`'s
  sense of the word, it is a property of files rather than of the build, and one line should
  state one fact.
- **Delete `PLANNED`, `_UNBUILT_HELP` and `EXIT_NOT_IMPLEMENTED` now, in this package.** The
  honest end state and the one this record expects M5 to reach. Rejected here on scope: it
  retires a published exit code and strands an error class with live tests, on a tree with one
  verification gate left before the milestone closes. A deferral that names its milestone is
  this repository's stated way to hold that (`docs/adr/README.md`); a quiet deletion in a
  package about a version flag is not.

## Consequences
**One string now appears in two places a reader can compare**, and a test fails if they drift.
That is the whole value of the flag: `assay/0.1.0` on the terminal and `assay/0.1.0` in a
suite's `generator` mean the same build wrote both.

**The version line changes shape once per milestone, deliberately.** M5 will print
`(milestone M5)` with no other edit, because `MILESTONE` is the single source. The test matches
`assay/\d+\.\d+(\.\d+)? \(milestone M\d\)` rather than the literal, so it pins the shape a
reader relies on without pinning a number that is supposed to move.

**`--version` is public surface from now on.** It joins the exit-code table and the four
commands as something M5's freeze publishes, and the wording of the line is part of what is
frozen there.

**The exit-code table keeps a code nothing can currently produce.** `EXIT_NOT_IMPLEMENTED` is
documented, tested and unreachable, and this record is the reason it is not a bug: it is a
withdrawn promise waiting for the milestone that can retire it properly.

**If Assay is ever released, the milestone suffix needs revisiting.** A `1.0.0` announcing
"milestone M5" would be two release identifiers in one line, one of them redundant. That is
M5's problem to take with the freeze, and it is named here so it is taken rather than
inherited.
