# ADR-0065: A throwaway clone writes no reflog and keeps no origin, and byte-identity across hosts is not the property on offer

- **Status:** Accepted
- **Date:** 2026-09-10
- **Deciders:** Bogdan Dzekic

## Context

ADR-0062 made the image build context a standalone clone and recorded, among its residues, that
the clone's `.git/config` names its `origin` as the absolute host path it was cloned from — and
that this file is now inside image content. It was accepted on the same terms as the layer-size
residue beside it: local images, content-addressed, never pushed.

That record is **incomplete in a way that matters**, and the way it is incomplete is worse than
the thing it names. Naming `.git/config` as *the* carrier makes the residue look like a one-line
fix — `remote remove origin` — that a later reader could apply in passing and believe closed.
Measured on this host (2026-09-10), it is not:

```
0000000000000000000000000000000000000000 a4309a…  Bogdan Dzekic
<36361781+dz3ka@users.noreply.github.com> 1789018964 +0200   clone: from C:/Users/…/src
```

That is `.git/logs/HEAD`, written by the clone itself, in plaintext, inside the build context.
One line, three separate leaks: **the absolute path on this machine**, **the operator's real name
and email** — read from the ambient `~/.gitconfig`, not from anything the fixture or the harness
pinned — and **a wall clock**. `remote remove origin` does not touch it. Nothing in ADR-0062
mentions it, because nobody looked.

Two things make this a decision rather than tidying:

**ADR-0052's rule is closer than 0062 allowed.** That record says a repository with no remote
names itself by its root commit, never by its path on the host, because a path is a fact about
the machine that ran the harness rather than about the repository being measured. ADR-0062
reasoned that the rule does not *apply* here, since `.git/config` reaches no content address.
True, and beside the point once identity is in the picture: an image is content the author of
this repository publishes, and a published artefact carrying a real name, an email address and a
home-directory path is a privacy leak whether or not it moves an address.

**The clock makes it a reproducibility claim too.** A wall-clock timestamp inside image content
means two builds of the same commit differ in bytes for no reason but when they happened. That is
the shape of defect this project is least entitled to ship, given what it measures.

## Decision

The clone in `GitHistory.standalone_checkout` becomes

```
git clone --local --no-checkout -c core.logallrefupdates=false <src> <path>
```

and is followed, before the detach, by `git remote remove origin`.

**Both are required and neither subsumes the other**, which is the whole reason this is written
down. Measured on this host: with `core.logallrefupdates=false` set *on the clone invocation*,
`.git/logs` is never created at all and the subsequent `checkout --detach` does not recreate it.
`remote remove origin` strips the `[remote "origin"]` stanza **and** the `[branch "master"]`
stanza that references it — the two places `.git/config` holds the source path. Without the flag,
the reflog line above appears regardless of what happens to the remote.

`git describe --tags --long --always --abbrev=40` still answers correctly afterwards, so
`_checked_context`'s address input (ADR-0063) is unmoved and the clone remains exactly as useful
to a build backend as it was.

**What this buys is bounded, and the bound is the point.** It removes *a host path, an identity
and a clock*. It does **not** make two builds of one commit on two machines byte-identical, and
this record does not claim it does:

- `.git/index` stores per-file stat data — mtime, size, inode/device where the platform supplies
  them — captured when the checkout is written. Two runs write two different indexes.
- `.git/config` records platform-derived settings: `filemode`, `symlinks` and `ignorecase` are
  probed at clone time and differ between a Windows dev host and Linux CI by construction.

Byte-identity across hosts is therefore **not a property on offer here**, and a later reader
should not treat this record as the start of a path toward it. What is on offer is that the image
stops saying who built it and where.

## Alternatives considered

**Leave it as a recorded residue, the way ADR-0062 did.** The honest default, and it is how the
layer-size residue beside it is still handled. Rejected because the two residues are not the same
kind: layer size is a cost the author accepts, an operator's name and email inside a published
artefact is a fact about a third party — the operator — that they did not accept. And the fix
measured out at two flags with no behaviour change, which is not a cost worth deferring.

**`git remote remove origin` alone.** The obvious reading of ADR-0062's residue, and the reason
that residue had to be corrected rather than extended: it is **measured incomplete**. It leaves
`.git/logs/HEAD` holding `clone: from C:/Users/…/src` with the operator's name, email and a Unix
timestamp on the same line. Anyone applying ADR-0062's residue literally would have shipped this
believing it closed.

**Scrub `.git/logs` after the fact.** Delete the directory once the checkout is made. Rejected:
it writes the secret and then removes it, which is a strictly weaker property — every later
operation that touches a ref re-creates the file, so the guarantee would hold only for as long as
nobody added a git call to this method. Configuring the clone not to write it makes the file's
absence a property of the repository rather than of the sequence of calls.

**A multi-stage build that keeps `.git` out of the final layer.** Already rejected by ADR-0062 as
disproportionate, and this decision does not reopen it. It would also solve the wrong problem:
the history is in the image *on purpose*, because a build backend reads it.

**Chase byte-identity across hosts.** Rejected as **impossible**, not merely expensive. The index
records stat data the filesystem supplies and the config records capabilities the platform
supplies; no amount of scrubbing makes a Windows checkout and a Linux checkout the same bytes.
Pursuing it would mean either excluding `.git` again — the defect ADR-0062 exists to fix — or
rewriting git's own on-disk state, which is a harness editing a repository it is supposed to
observe.

## Consequences

**The clone stops carrying an identity, a host path and a clock into image content**, so a task
image can be inspected by someone other than its builder without telling them who built it. The
assertion is a byte scan over every file under `.git` — a plaintext `<…@…>` ident and both
spellings of the source path — rather than two filenames, so a future mechanism that reintroduces
either is caught by the same test
(`test_a_standalone_checkout_writes_neither_this_machines_path_nor_its_operator`).

**ADR-0062's second residue is corrected, not merely extended.** Its text stands as written — ADRs
are immutable — but a reader arriving at that bullet should arrive here next. The correction is
factual: `.git/config` was not the only carrier and was not the more revealing one.

**Nothing about the address moves.** No recipe text changes, no `context` key changes, and
`git describe` still answers with the tag, so this decision re-addresses nothing on its own. It
ships in the same goal as ADR-0064, which re-addresses everything — so no separate rebuild is
attributable to it.

**Image content still differs between hosts, and this record is where that is stated.** The two
mechanisms above (`.git/index` stat data, platform-derived `.git/config` keys) mean the same
commit built on Windows and on Linux CI produces different bytes under one address. That was
already true before this decision, it stays true after it, and it is inside the tolerance ADR-0062
accepted: the address is over the recipe, the base image, the commit and the context description,
none of which those bytes touch.

- `unverified:` **nobody has diffed two `.git/index` files from two runs on one host.** The index
  format's stat fields were read, not measured, and no two built images were compared byte for
  byte to see what actually differs. The claim above about *what makes* hosts differ is therefore
  reasoning from the format rather than an observation, and it is marked the way ADR-0062 marks
  its `alternates` residue. The failure direction is benign — a difference nobody claims is
  absent — so it is left for whoever needs image byte-comparison to establish properly.
