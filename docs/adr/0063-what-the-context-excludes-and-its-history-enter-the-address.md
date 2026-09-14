# ADR-0063: What the build context excludes, and what history it carries, enter the image's address

- **Status:** Accepted
- **Date:** 2026-09-10
- **Deciders:** Bogdan Dzekic

## Context

A task image's tag is a content address over everything that decides what ends up inside it —
that is the whole reason `image_tag` exists, and the reason ADR-0021's cutoff and ADR-0022's
canonical spelling were made to reach the recipe rather than sit beside it. An address that
misses an input is worse than no address: two different environments share one tag, and every
later step reads the tag.

ADR-0062 removes `.git` from `_CONTEXT_EXCLUSIONS`. That changes image *contents* — the history
is copied now — while `base_image`, `dockerfile` and `base_commit` all stay exactly where they
were. Left alone, one address would name two environments, which is the failure this module
exists to prevent, committed inside the module that exists to prevent it.

Two inputs are involved and they arrive from the same place, so they are recorded together.

**`_DOCKERIGNORE` is an unhashed determinant of image content.** It has been one since ADR-0027
derived it from `_CONTEXT_EXCLUSIONS`: it decides which of the checkout is copied, it is written
beside the Dockerfile rather than into it, and so it appears in no hashed value. It has simply
never moved before. The module already hashes a module constant for precisely this reason —
`_BASE_IMAGE` is passed in as `base_image` rather than trusted to be itself — so this is that
argument applied to the constant beside it.

**A clone's visible history is the other one, and it is new.** From ADR-0062 onwards, history is
a *build input*: a backend that derives the project version from `git describe` reads it during
the build. And it is a property of the **clone**, not of the commit — a clone missing tags
derives a different version from an identical `base_commit`. `git clone --local` is expected to
carry the parent's tag set, but "expected to" is not a thing an address may rest on.

## Decision

`image_tag` grows **one optional key**, `context: Mapping[str, str] | None = None`, hashed under
`"context"` when it is present. `build_task_image` passes
`{"dockerignore": …, "git_description": …}`.

`git_description` is `git describe --tags --long --always --abbrev=40`, and it is asked **of the
build context directory**, not of the parent history. That is deliberate: asking the context is
what removes the unverified assumption that `clone --local` carried the tags — if it did not,
the description differs and the address differs with it. It also puts the question where
`assay.sandbox` already asks git about its context, inside `_checked_context` (ADR-0027), so no
`git_description=` parameter has to be threaded through `build_task_image` and out into the CLI.
The flags are each load-bearing: `--tags` counts a lightweight tag, `--long` distinguishes a
checkout sitting on a tag from one a commit past it, `--always` makes an untagged repository an
answer rather than a failure, and `--abbrev=40` fixes the width, because an abbreviation is as
long as a repository needs it to be and this string goes into a hash.

**One optional key rather than two required keyword arguments.** Two required arguments would
force a placeholder at the two call sites that send an *empty* build context —
`build_agent_image` and the extras phase, both of which build from an empty temporary directory
because the repository is already inside the base tag — and a placeholder inside a content
address is exactly the untruth this module exists to prevent. `context=None` keeps both of those
addresses **byte-identical**, which is pinned against a literal tag in
`test_a_build_that_sends_no_context_addresses_itself_exactly_as_it_always_has` rather than
recomputed from the module under test. The shape is the one `exclude_newer=None` already uses
here, and `assay.core.canonical.content_hash` already accepts a nested dict
(`src/assay/core/canonical.py:45`).

**No `_checked_description` validator.** `_checked_cutoff`'s precedent rests on two properties
this value does not have: a cutoff reaches a shell `RUN` line, and git spells one instant two
ways (ADR-0022), so refusing the second spelling is what makes the address single-valued. A
description has one spelling and reaches only a hash dict, and a git that could not answer has
already raised `GitError`. Validating it would be validating the impossible.

## Alternatives considered

- **Two ADRs, one per input.** Rejected on the razor's grounds: they are one change to one hash
  key, made for one reason, and two records for it would drift — the same argument ADR-0023 and
  ADR-0031 make about splitting a decision that has one cause.
- **Hash `_DOCKERIGNORE` only, and let the description ride on `base_commit`.** It does not ride:
  the description is a property of the clone and `base_commit` is a property of the commit, which
  is the entire point. Two clones of one commit with different tag sets build two environments.
- **Two required keyword arguments instead of one optional mapping.** Rejected because it forces
  a placeholder into the address of every image built from an empty context, and because it would
  move two addresses that have no reason to move.
- **Ask the parent `GitHistory` for the description and pass it down.** It restates the
  assumption instead of testing it, and it threads a `git_description=` parameter through
  `build_task_image` and into the CLI for a value the sandbox package can already see.
- **Leave the address alone and rely on the rebuild happening anyway.** It would happen this
  once, by luck, because `.git` changes the tree BuildKit hashes. It would not happen the next
  time `_DOCKERIGNORE` moves, and an address that is right by accident is not an address.

## Consequences

**Every task image address changes exactly once, deliberately.** Old tags are orphaned and each
task image is rebuilt once — the pattern ADR-0021 and ADR-0022 each set out in their own
Consequences. Nothing in the daemon's cache changes *meaning*; the old tags simply stop being
produced.

**The two empty-context addresses do not move.** `build_agent_image` and the extras phase pass
no context, hash no `"context"` key, and produce the strings they always produced. That is
asserted against a literal, so the claim is pinned rather than restated.

**Suite hashes and published figures are untouched.** Verified against the files on 2026-09-10:
`SuiteBody` hashes `schema_version`, `suite_name` and `tasks` only
(`src/assay/suite/models.py:81-86`), and no image input reaches it; neither `Result` nor
`ResultSet` records an image tag (`src/assay/results/models.py`). The registered suite hash
`sha256:f00d81732e3389728b44fd69bc479fcafba4b1085fdb12bfe33336bb3feb1106` stands, and M5's
published mining-yield numbers are unaffected because no image address enters them.

**`_checked_context` now returns a value.** It refuses a context the address would misdescribe,
as before, and hands back the description that goes into that address — one git seam, asked
once, rather than a second call site that could be given a different directory.

**A third input to the address would be a third key, not a third argument.** The `context`
mapping is where anything the build reads out of its context — but that the recipe cannot show —
belongs from here on.
