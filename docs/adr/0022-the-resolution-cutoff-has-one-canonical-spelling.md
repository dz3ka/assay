# ADR-0022: The resolution cutoff has one canonical spelling, produced at the git seam

- **Status:** Accepted
- **Date:** 2026-09-01
- **Deciders:** Bogdan Dzekic

## Context
[ADR-0021](0021-resolution-is-pinned-to-the-base-commit-era.md) renders the base commit's committer
date into the task image's Dockerfile, and `image_tag` is a SHA-256 over that Dockerfile text. The
cutoff is therefore not a build argument that happens to be a string; it is *part of a content
address*, and SPEC §5.5 makes an address that two honest hosts compute differently a defect rather
than a cosmetic one.

Git does not hand out one string. Measured on this host, `git show -s --format=%cI` prints
`2023-11-14T22:13:20Z` under git 2.55.0; older builds print `2023-11-14T22:13:20+00:00` for the
same commit and the same instant. Both are valid RFC3339, both are accepted by
`uv --exclude-newer`, and the two differ by six characters inside a line that is hashed. Two
developers on one task, one on each git build, would compute two tags, build two images, and score
trials that no longer share an address — the exact failure Assay exists to catch, committed inside
Assay.

The old `_CUTOFF_PATTERN` also admitted a bare `YYYY-MM-DD`, offered as a convenience for a caller
passing a cutoff by hand. Measured on uv 0.12.5, `uv help pip install` says of `--exclude-newer`
that a bare date "is resolved based on your system's configured time zone". That is the same defect
wearing a different hat: the recipe would pin an address whose *meaning* is decided by the
container's `TZ` rather than by the bytes being hashed. A tolerant input surface at the boundary
that computes an address is not tolerance, it is an unaddressed degree of freedom.

## Decision
One canonical spelling — `YYYY-MM-DDTHH:MM:SSZ`, UTC, second precision, literal `Z`, no fractional
part — and one producer.

`GitHistory.committed_at` owns it. It is the seam every git answer already passes through and
already normalises on the way out (`_checked_revision`, `_checked_path`), so the new
`_as_utc_instant` sits beside them: parse what git printed, refuse anything that is not an instant
or that carries no offset at all, and re-emit it in the canonical form. `%cI` is already
second-precision, so nothing is lost in the rewrite. This is the one place in `host/git.py` that
*repairs* rather than refuses, and deliberately: the two spellings are git's, not the repository's,
and failing a mining run because of the host's git build would be a reach limit invented out of a
formatting difference.

`sandbox/image._checked_cutoff` stays a **validator, never a canonicaliser**, and its pattern
narrows to exactly the canonical shape. Bare dates are refused with it. The producer is what makes
old-git hosts work; the narrowed pattern is what makes the second spelling *unconstructible* at the
boundary that computes the address, so a future caller cannot reintroduce the split by passing a
string it read somewhere else. This applies [ADR-0011](0011-string-constraints-live-on-the-schema.md)
one layer out: the constraint belongs where the value is committed to, not in the caller's
discipline.

## Alternatives considered
- **Accept both spellings in `_CUTOFF_PATTERN` and treat them as equal.** Rejected, and it is the
  tempting one, because both really are the same instant and uv really does accept both. It fails
  on the only thing that matters here: the address is a digest of bytes, not of meanings, so
  "equally valid" is precisely what a hash cannot see.
- **Canonicalise inside `sandbox/image`, at the point of use.** Rejected. It would give one tag,
  but by silently rewriting a caller's value — the sanitising posture `_checked_cutoff`'s own
  docstring rejects — and it would put a git formatting concern inside the module that must not
  know git exists (`assay.sandbox` never asks git anything; ADR-0021).
- **Hash a parsed cutoff rather than the recipe text.** Rejected as a much larger change for a
  smaller fix: the recipe text is what BuildKit actually builds, and addressing anything other
  than the thing built is how an address stops meaning what it says.
- **Require git ≥ 2.55.** Rejected: a stated reach limit is a real cost, and paying it to avoid
  eleven lines of normalisation would be trading a fixable defect for an unfixable one.
- **Keep the bare date as an accepted input.** Rejected on the measurement above. A cutoff whose
  resolution depends on the container's time zone cannot be part of a reproducible address, and
  "callers only ever pass `committed_at`'s output" is a convention, not a constraint.

## Consequences
Every cutoff-bearing tag computed on an old-git host before this change is orphaned: nothing will
compute that address again, and the image is rebuilt once under the canonical one. That is the
correct direction — the alternative is two live addresses for one task — and it costs one build.
Tags built with `exclude_newer=None` are untouched, because that path renders no cutoff at all.

`_FIXTURE_ERA` in `tests/sandbox/test_image.py` becomes `2023-11-14T00:00:00Z`. Midnight UTC on that
day is still November 2023, so the era assertion it feeds (pytest 7.4.3 under the cutoff, 9.x
without) is unchanged.

The regression test for the `+00:00` spelling is written against `_as_utc_instant` directly rather
than through `committed_at`, and carries a comment saying so. This host's git cannot be made to
print the old spelling, so the trigger is unreproducible through the public route: a test that went
that way would pass without ever running the case it names. The control has to run or the result is
meaningless, and here the control only exists as a literal.

Nothing else in the tree interpolates a git-derived string into a content address. If a second such
value appears — a tag, a branch, an author — it takes this rule with it: canonicalise at the seam
that produces it, validate narrowly where it is committed to.
