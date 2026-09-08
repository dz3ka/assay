# ADR-0052: A repository with no remote names itself by its root commit, never by where it sits

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0007](0007-suites-are-content-addressed-and-versioned.md) decided that a suite is an
envelope around a hashed body, and that everything whose value is incidental to the measurement
— the clock, the generator string — sits *outside* the digest, because a digest covering an
incidental gives one task set two addresses. `Task.repo_url` (`src/assay/suite/models.py:60`) is
inside that body, so whatever names the repository is part of the suite's content address.

**Until this record, what named an unremoted repository was its absolute path on the host.**
`GitHistory.repo_url` asked `git remote get-url origin` and, on failure, returned
`str(self._repo)`. The docstring called that fallback deliberate, which is why this is a design
question rather than a bug report: somebody decided it, and nothing in the repository said why.

**The consequence is exactly the failure ADR-0007 exists to prevent, arriving through the one
field nobody looked at.** Two checkouts of one history — same commits, same tests, same ground
truth — mined from `/tmp/a` and `/tmp/b` produce two suite bodies differing in one string, so
they hash to two addresses and their result sets are formally incomparable. SPEC §5.5 asks that
any result be reproducible, and a reproduction in a second directory could not even be
recognised as being about the same task set.

**This is not a hypothetical shape.** Assay never clones and never fetches (SPEC §5.1), so a
repository with no `origin` is a perfectly ordinary thing to mine — and it is what M5's own demo
does: `scripts/demo.py` builds the synthetic fixture
([ADR-0050](0050-the-demo-runs-against-the-fixture-and-says-so-first.md)) into a fresh directory
and mines it, so the repository the release ships a recipe for was the one whose address moved
with the temp directory it landed in.

## Decision
**`repo_url` names a declared origin when there is one, and otherwise names the repository by
what it contains.** In `src/assay/host/git.py:134-174`, in order:

1. `git remote get-url origin` with `check=False`. Exit 0 with non-empty stripped output is
   returned verbatim — **unchanged behaviour**, because a declared URL is the repository's own
   statement about its identity and is not Assay's to rewrite.
2. Otherwise `git rev-list --max-parents=0 HEAD`, also `check=False`.
3. Every non-empty line is passed through the module's existing `_checked_revision`, the set is
   `sorted()`, joined with `"+"`, and returned behind `_ROOT_COMMIT_PREFIX`
   (`src/assay/host/git.py:63`, `= "root-commit:"`) — so the value reads
   `root-commit:89c5b206…` and can never be mistaken for a URL by anything that reads a task.
4. A non-zero exit, or no non-empty line, raises `GitError` naming the repository and *both*
   missing sources.

**A root commit is the right name because it is derived from the history rather than from where
the history is sitting.** It needs no network, it is identical in every copy of one history, and
somebody holding the suite can check it offline against a candidate checkout — which a host path
can only be checked against on the machine that produced it.

**Every root is named, sorted into one spelling.** `rev-list --max-parents=0` prints one line per
root, and a history that absorbed an unrelated one has several. Git's traversal order is not a
contract, so taking the first line would let the order git happened to walk in decide the suite's
address — the same defect one layer down.

**An empty repository is refused rather than named.** No remote and no commit means there is
nothing to mine, and [ADR-0048](0048-a-refusal-names-its-own-cause.md) puts the sentence at the
site that knows the cause: the message names the repository and says there was neither an
`origin` to cite nor a commit to take a root object name from. A fallback would fail the history
walk one call later, under a frame that could no longer say why.

**`_checked_revision` is applied to output that is hashed rather than executed, on purpose.** The
value never reaches an argv, so the pattern is not guarding a shell — it is defence in depth
against git answering with an unexpected shape, and it keeps this call site consistent with every
other place in the module where git's answer is validated before Assay passes it on.

**This extends ADR-0007 and supersedes nothing.** 0007 decides *what* is hashed and closes three
places the property would leak: task order, verify-after-parse, and the doubled `schema_version`.
Nothing here changes any of that. This record adds the fourth refusal in the same series —
**nothing incidental to the host may enter the hashed body** — and it is the first ADR in the
repository to record the no-remote fallback at all, which lived until now only in a docstring and
a test. Editing 0007 to describe a rule it did not make would be retroactive rationalisation.

**No schema version bump.** `Task.schema_version` stays `1`: the field's name, type and position
are untouched and only the value a miner writes changes, so existing suite files load and still
verify their own digest.

**Verified, because this record's whole subject is a claim about reproducibility.** Two builds of
the fixture repository under two different temp parents both answered
`root-commit:89c5b2060bf6736daa8d0098a8e1f9097096d99f`, containing no host path
(`GitHistory(build_fixture_repo(tempfile.mkdtemp()), …).repo_url()`, run twice, 2026-09-07), and
the §5 recipe in [`m5-public-release.md`](../milestones/m5-public-release.md) run end to end from
two different parent directories produced the byte-identical suite digest
`sha256:bfa6e5bc2efe5d2966a937eabe5d51ee8999fefc0b4445aa1184375efd011344`.

**One thing is decided *not* to be fixed, and it is stated plainly: `origin` URLs are not
normalised.** One repository addressed as `git@example.invalid:me/repo.git` and as
`https://example.invalid/me/repo.git` still yields two different suite hashes — the same defect
this record removes, narrowed to where the difference is a human's spelling rather than a
directory's accident. It remains open.

## Alternatives considered
- **Name the repository by its directory name instead of its full path.** Rejected: it narrows
  the defect rather than removing it. `assay` cloned twice under two names is still one history
  with two addresses, and the failure would now be rarer and therefore harder to notice.
- **A fixed sentinel, or the empty string, for every unremoted repository.** Rejected: the suite
  could then no longer say which repository it came from, and every locally-mined suite would
  collide with every other one in the field that is supposed to distinguish them.
- **Move `repo_url` out of `SuiteBody` into the unhashed `SuiteFile` envelope, beside
  `generated_at`.** Correct in the abstract — it is provenance, not content — and rejected on
  cost: it breaks the `Task` schema *and* the `SuiteFile` schema at the milestone that makes both
  public, to fix a field that has a well-defined content-derived value available to it.
- **`repo_url: str | None`, with `None` for a repository that has no remote.** Rejected: the same
  schema break, carrying strictly less. Every consumer gains a branch and the suite loses the
  ability to name what it was mined from.
- **Take the first line of `rev-list --max-parents=0`.** Rejected: git's traversal order is not
  documented as stable, so the address would depend on it.
- **Refuse to mine a multi-root repository.** Rejected: a vendored history merged in with
  `--allow-unrelated-histories` is legitimate, and this would make it unmineable for a reason
  that has nothing to do with its commits.
- **Give an empty repository the fallback too, and let the failure surface later.** Rejected
  under ADR-0048: the walk fails one call afterwards, at a site that cannot name this cause.
- **Normalise `origin` spellings in the same change.** Rejected as scope, not as wrong: it is a
  URL-parsing rule with its own judgement calls (ports, trailing `.git`, capitalisation), and it
  would be decided here in a paragraph rather than designed. Recorded above as a residual.

## Consequences
**A suite mined from a repository with no remote changes its address once, and never again for
this reason.** ADR-0007's Consequences already record that improving the miner yields a new hash
and an incomparable result set; this is one of those, taken deliberately at the last milestone
before the schema is public.

**The demo's digest is now a figure that can be quoted.** It was previously true only of the
directory that produced it, which made the §5 "reproducing this" recipe unable to deliver the
thing its name promised.

**The residual is on the record rather than in a reviewer's memory.** Two spellings of one
`origin` still give two addresses, and this is where somebody arriving with that symptom finds it
already known. A record claiming the field is now path-independent *and* canonical would be the
overstatement this project treats as fatal.

**`root-commit:` is a public prefix from M5 onward.** It appears in suite files that ship, so
changing its spelling later is a schema change in substance whatever the version field says.
