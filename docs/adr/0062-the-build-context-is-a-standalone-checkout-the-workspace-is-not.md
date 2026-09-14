# ADR-0062: The image build context is a standalone checkout; the trial workspace stays a worktree

- **Status:** Accepted
- **Date:** 2026-09-10
- **Deciders:** Bogdan Dzekic

## Context

The zero-spend local-model run is blocked. All thirteen `tenacity` task images fail to build.
`tenacity` versions itself with `setuptools-scm`, which derives the project version from git at
build time; Assay's build context is a linked `git worktree`, whose `.git` is a ~168-byte pointer
file at a clone the build cannot reach — and `_CONTEXT_EXCLUSIONS` dropped `.git` from the
context anyway, so nothing about the repository's history arrived in the image at all.

The blocker is not vendor-specific. `hatch-vcs`, `pdm-backend` and `versioneer` all derive a
version the same way and fail identically. Between them that is a large fraction of the modern
Python packaging ecosystem, so "a repository that versions itself from git" is not an edge case
Assay can decline.

**The framing matters more than the fix.** ADR-0025 spent the one widening this project allows
itself and set the rule for everything after it: what the harness cannot reach is *reported*
rather than patched around. That rule is about limits of reach — a repository whose test
dependencies were never pinned is genuinely unreachable, and saying so is a finding. This is not
that. A plain `git clone && git checkout <sha>` — what any human does before running a
repository's tests — builds `tenacity` without incident. Assay's build context is strictly *less
faithful* than a plain checkout, and the deficit is an artifact of how Assay checks out, not a
property of the commit. Publishing "Assay cannot score tenacity" would be publishing a defect as
a finding, which is the precise inversion of what this project is for.

That argument is available without looking at which commits failed, which is the bar ADR-0025
sets for distinguishing a reach limit from a defect: no result was inspected before the decision
was taken.

The reason the exclusion looked free when it was written is worth stating, because it is the
thing that changed. The context has always been a `worktree`, and a worktree's `.git` is worth
nothing to a build: a pointer file holding an absolute host path. Excluding it removed a host
path from image content (ADR-0052's concern) and removed nothing a build could use. The
exclusion was correct *given* the worktree; the worktree is what is wrong.

## Decision

**The image build context becomes a standalone checkout with a real `.git` directory. The trial
workspace stays a linked worktree.** `GitHistory.standalone_checkout` is a second contextmanager
beside `worktree`: `git clone --local --no-checkout` from the user's clone, then
`checkout --detach`, destroyed on the way out. `.git` leaves `_CONTEXT_EXCLUSIONS`, so the build
copies the history.

**The two-kinds split is load-bearing and must not be collapsed into one.** A standalone clone
carries *all refs*, including branches and tags whose history contains a task's ground-truth
fix. The trial workspace is bind-mounted into the tool's own container
(`sandbox/container.py`, `-v …:/workspace:ro`), so making *it* standalone would hand every tool
under test `git show <fix commit>` — a machine-readable answer key that `--read-only` and
`--cap-drop ALL` do nothing about, because reading is exactly what is permitted. The build
context, by contrast, is never mounted: at run time `/workspace` is replaced by the mount, so
the history baked into the image is inert. Two tests pin the two halves —
`test_a_worktree_points_at_the_clone_rather_than_holding_a_repository` and
`test_the_workspace_a_trial_mounts_carries_no_history_the_image_would_have_answered_from`.

**Nothing is injected into the build.** `render_base_dockerfile` is unchanged. The repository's
own tags supply the version its own build backend derives, which is the only version anybody
chose. There is no `SETUPTOOLS_SCM_PRETEND_VERSION`, no synthesized commit, and no branch in the
recipe that depends on which repository is being built.

**A linked worktree is refused, not repaired.** With `.git` out of the exclusions, a worktree's
pointer *file* would now be copied — putting an absolute host path inside image content
(ADR-0052) and handing a build backend an obscure abort instead of a named refusal. So
`_checked_context` grows one clause: a `.git` that is a file is a `SandboxError` naming the
pointer file. It is a clause inside the function that already exists to refuse a context the
address would misdescribe (ADR-0027), not a new step, and it refuses rather than converting —
turning a worktree into a clone there would make the precondition the thing that decides what
gets built.

## Alternatives considered

- **`SETUPTOOLS_SCM_PRETEND_VERSION` in the recipe.** To produce the right string you would have
  to reimplement setuptools-scm's `guess-next-dev` scheme, including how it counts distance from
  the nearest tag and formats the local segment; anything less is a version nobody ever chose,
  baked into an image whose whole purpose is to be the environment the red→green gate validated.
  And it fixes one vendor of four: `hatch-vcs`, `pdm-backend` and `versioneer` each have their
  own escape hatch with its own spelling.
- **Detect setuptools-scm in the tree and branch on it.** A repo-conditional environment, which
  ADR-0021 and ADR-0022 forbid outright: the recipe is what the content address is a digest of,
  and a recipe that varies with a heuristic over the tree makes the address a claim about the
  heuristic rather than about the commit.
- **`git archive` into the context.** Produces the same tree with no `.git` at all. It fixes
  nothing — it is what the context already effectively was.
- **Synthesize a one-commit repository inside the image.** `git init && git commit` in the build
  yields `0.1.dev1+g<sha>`, a version upstream never chose, silently, for every repository. Worse
  than failing.
- **Refuse, and publish "tenacity is unscoreable".** The closest call, and the one ADR-0025's
  letter could be read to require. Rejected on the framing above: this is a defect in Assay's
  checkout, not a limit of the repository, and the difference is demonstrable without looking at
  a single result.
- **Make `worktree()` standalone everywhere.** One kind of checkout instead of two, which is
  simpler by every measure except the one that matters: it puts the answer key in the workspace
  the tool under test is handed.
- **A multi-stage build, to keep history out of the final layer.** Disproportionate. `/workspace`
  is shadowed by the `:ro` mount in every trial and the image is never pushed anywhere
  (SPEC §5.1), so the history in the layer is inert. It is recorded as residue below, with a
  test, rather than engineered away.

## Consequences

**Every task image address changes, once.** `.git` in the context changes image *contents*, and
ADR-0063 puts what the context excludes and what history it carries into the address, so old
tags are orphaned and each task image is rebuilt once. This is the pattern ADR-0021 and
ADR-0022 already set out in their own Consequences.

**Suite hashes are unchanged.** `SuiteBody` hashes `schema_version`, `suite_name` and `tasks`
(`src/assay/suite/models.py:81-86`) — verified against the file, 2026-09-10 — and no image input
reaches it. The pre-registered
`sha256:f00d81732e3389728b44fd69bc479fcafba4b1085fdb12bfe33336bb3feb1106`, 13 tasks, is
untouched. **No published figure moves either**: M5's numbers are host-path mining-yield figures
(`docs/milestones/m5-yield-public-repos.md` §4 already records that those tasks were never
re-validated or scored), and neither `Result` nor `ResultSet` records an image tag — verified
against `src/assay/results/models.py`, 2026-09-10. Nothing is restated and nothing is retracted.

**This does not yet make a git-versioned repository buildable, and that is stated here rather
than left to be discovered.** Measured 2026-09-10 on this host: the pinned base image carries no
`git` executable (`git --version` → `sh: 1: git: not found`), so an intact `.git` in the context
is inert and setuptools-scm still ends in
`LookupError: setuptools-scm was unable to detect version for /workspace`. Adding
`apt-get install -y --no-install-recommends git` to `render_base_dockerfile` was measured to
close it — the same fixture project then derives `3.1.4` from its own tag — but that changes the
recipe every existing tag was addressed by and puts a git binary inside the measurement image,
which is a decision with its own consequences and not one this record takes. What ADR-0062
settles is that the context is now a faithful checkout; **the remaining half is owed a decision
before the local-model run can proceed**, and `tests/sandbox/test_image.py` carries the
measurement inline so the next reader does not re-derive it.

**Residues, recorded rather than fixed:**

- `git clone --local` hardlinks the object store, but `COPY .` dereferences, so the repository's
  full history lands in each task image's layer — roughly 5–10 MB for `tenacity`, roughly 30 MB
  for a repository the size of `httpie`, once per task image. Acceptable: the images are local,
  content-addressed and never pushed.
- The clone's `.git/config` records its `origin` as the absolute host path it was cloned from,
  and that file is now inside image content. It does not reach any content address, and the
  derived version does not depend on it, but it means two hosts produce byte-different images
  under one address. Same class as the point above and accepted on the same terms; named here
  because ADR-0052's rule about host paths is close enough that a reader would otherwise have to
  work out for themselves that it does not apply.
- `unverified:` a *source* clone that itself uses `objects/info/alternates` would produce a
  checkout resolving on the host and not inside the image. The failure direction is closed — the
  build fails loudly rather than deriving a wrong version — so this is marked rather than
  asserted, and left for whoever meets it.

**Cleanup is not free on Windows.** Git writes loose objects at mode 444, which on Windows makes
them undeletable rather than merely unwritable, so a plain `shutil.rmtree` would leave a whole
second copy of the repository per build in the user's temp space. `_remove_repository` clears
the bit and retries.

**`assay run` is broken until the CLI is switched over.** `_task_image` in `src/assay/cli/main.py`
still hands `build_task_image` a worktree, which is now refused. That swap is the next work
package; this record is written at the moment the decision was made, not after the wiring.
