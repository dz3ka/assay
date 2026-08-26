# ADR-0009: Redaction is HMAC-SHA-256 under a per-render salt that is never persisted

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** Bogdan Dzekic

## Context
Assay runs inside a customer's environment on a customer's private repository, and the report is
the single artefact that leaves it. SPEC §5.4 says why the report is redacted by default: so that
results can be shared **with a vendor when the code cannot be shared**.

That sentence names the adversary, and it is an unusual one. Not an attacker who stole the file —
a vendor, reading a report they were legitimately given, who has every incentive to learn what
the customer's codebase looks like and who has a very good prior on what its files are called.
`src/billing/invoice.py` is not a secret to be guessed at random; it is a wordlist entry. Any
scheme that turns a path into a deterministic, unkeyed token is a lookup table away from failing
at exactly the job it was written for.

## Decision
A token is `hmac.new(salt, f"{kind}\0{raw}", sha256)`, truncated to 12 hex characters and
prefixed with the kind's initial (`p:`, `i:`, `m:`). The NUL domain separator cannot occur in a
path, an identifier or a commit subject, so no two `(kind, raw)` pairs can spell one message.

The salt is 32 bytes — full digest width, so that no search over plausible salts is in reach —
drawn from the OS entropy source by `RedactionPolicy.from_random()`. It has no default: a policy
that fell back to a constant would still produce plausible-looking tokens while being reversible
by anyone holding the same build. It is never written into a report and never persisted anywhere.
One policy per report.

`redact` is total: a whole `Report` in, a whole `Report` out, with no per-field opt-out and no
`--no-redact` flag in M0.

## Alternatives considered
- **Bare SHA-256 of the path.** Rejected, and this is the whole reason the ADR exists: an
  unsalted digest is a lookup. A vendor with a wordlist recovers the directory tree one guess and
  one hash at a time, which defeats SPEC §5.4's purpose against precisely the recipient it was
  written for.
- **A per-suite salt persisted in a file.** Rejected on three counts. It puts a secret on disk in
  a project that is public from M0, one `.gitignore` mistake from publication; file-permission
  semantics differ between Windows and Linux, so "protected" would mean two different things on
  the two platforms this runs on; and nothing at M0 needs the cross-report correlation it buys.
- **Encrypt rather than hash, so the owner can reverse it.** Rejected: a reversible report is the
  repository leaving the machine under a key, which is the first non-negotiable in CLAUDE.md with
  an extra step.
- **A `--no-redact` flag for local inspection.** Rejected: it makes redaction a habit callers
  remember rather than a property the pipeline has, and the first renderer written in a hurry is
  where a private path escapes.
- **Truncate to 8 hex instead of 12.** Rejected: collisions across a suite of a few thousand
  tasks stop being theoretical, and a collision in a report is two different files reading as one.

## Consequences
**Cross-run token correlation is unavailable.** "Is this the same file that failed last week?"
cannot be answered by comparing two reports — tokens are comparable inside one document and
meaningless across two, which is the same property that stops a recipient joining two reports on
a shared path. If a later milestone needs that correlation, it is a new decision with its own
key-management story, not a patch to this one.

Three fields are deliberately not hashed, because hashing them would destroy the document rather
than protect the repository: `suite_hash` is a digest of the task set and is what makes a result
attributable ([ADR-0007](0007-suites-are-content-addressed-and-versioned.md)); the tool names are
the finding itself; the enum members are Assay's own vocabulary.

The totality test walks the serialised document rather than a field list, so a provenance field
added by M1's miner fails the suite until it is classified here. That is the mechanism keeping
"total" true as the schema grows, rather than the word "total" in this ADR.
