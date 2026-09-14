# ADR-0064: The measurement image carries a pinned git, and the recipe says which one

- **Status:** Accepted
- **Date:** 2026-09-10
- **Deciders:** Bogdan Dzekic

## Context

ADR-0062 put the repository's history back into the build context, because thirteen `tenacity`
task images could not be built: the context was a linked worktree with `.git` excluded, and a
project that versions itself from git — setuptools-scm, hatch-vcs, pdm-backend, versioneer — has
nothing to derive a version from in a tree like that. That record closed one half of the blocker
and said so, naming the other half with the measurement inline: **the base image ships no `git`
executable**, so the history it now copies is inert.

The measurement is unchanged and stands (2026-09-10, this host, Docker Desktop server 29.7.2).
Inside an image built from `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, `git --version`
answers `sh: 1: git: not found`, and a setuptools-scm project whose `.git` is present and whose
tag is present nevertheless aborts the build with
`LookupError: setuptools-scm was unable to detect version for /workspace`. Adding a git to the
recipe was measured to fix it: the same project then derives its version from its own tag.

So the remaining question was never whether it works. It is what the fix costs, and the cost is
paid in the one currency this module is about. `render_base_dockerfile`'s text **is** the content
address (ADR-0007, `image_tag`): a line added to it re-addresses every task image ever built.
That is a decision, not a repair, which is why ADR-0062 declined to make it in passing.

Three further forces shaped which fix is acceptable:

**An unpinned install would reopen the hole `_BASE_IMAGE`'s digest pin exists to close.** A bare
`apt-get install git` resolves against whatever the Debian archive serves that day, so the
contents of a *measurement* image could change while `base_image`, `dockerfile` and
`base_commit` all held still — one address naming two environments, committed inside the module
written to prevent it. This is ADR-0063's argument about unhashed determinants of image content,
applied to the one input this change introduces.

**Where the layer sits decides what it costs.** Everything after `COPY` varies with the commit,
so a layer below it is commit-dependent by construction and BuildKit stores one copy per task
image. Above `COPY`, its parent chain and command are identical across every image in a suite
and the daemon holds exactly one.

**It widens ADR-0021's asymmetry, and that has to be said out loud.** ADR-0021 pins dependency
*resolution* to the base commit's era via `uv --exclude-newer`, while the base image itself is
today's. A git installed from today's archive is a second component of a 2020 commit's
environment dated now. It is a version-control tool rather than a dependency of the project
under test — nothing the repository imports, nothing its tests resolve against — so the era
argument does not bite the same way. But the asymmetry is now two components wide, not one.

## Decision

`render_base_dockerfile` renders one new layer, **above `COPY`**, installing a
**version-pinned** git and dropping the apt lists in the same layer:

```
FROM <pinned base>
ENV UV_LINK_MODE=copy
RUN apt-get update \
 && apt-get install -y --no-install-recommends git=1:2.39.5-0+deb12u3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY . /workspace
RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python -e /workspace pytest
```

The version lives in `_GIT_PACKAGE` beside `_BASE_IMAGE`, for the reason the two are neighbours:
both are pins whose whole purpose is that a tag cannot move underneath an address.

`rm -rf /var/lib/apt/lists/*` is in the same layer rather than a later one, and it is not
housekeeping. The lists are a dated snapshot of the archive — precisely the host-and-date scratch
state `_CONTEXT_EXCLUSIONS` refuses to let into image content — and a file removed in a *later*
layer is still in the image.

`exclude_newer=None` therefore no longer renders "the recipe every existing tag was addressed
by". It renders today's index over a pinned git, and the docstring that promised the other thing
is deleted rather than softened.

## Alternatives considered

**Install git, use it, and purge it in the same layer.** Keeps the tool out of the shipped image,
which is the only real argument for it. Rejected: the reader is needed by `uv pip install`, which
is a *later* layer, so the install and the purge would have to be folded into the install layer —
below `COPY`, commit-dependent, and paid per image. It would also make the largest layer in the
recipe rebuild for a reason unrelated to what changed.

**Bare `apt-get install git`.** Rejected on the second force above: it puts an unpinned
determinant of image content outside every hashed value. The unpinned `nodejs npm` in
`render_agent_dockerfile` is not a counter-precedent — that is the *agent* image, whose
`_checked_tool_version` docstring already names its unpinned state as an honesty compromise about
a tool under test, not about the environment a measurement happens in.

**A non-slim base image that ships git.** One line shorter and a digest pin already covers it.
Rejected: it changes the base image, which re-addresses every image *and* silently changes
CPython, uv and the whole userland the M2 numbers were measured in, to fix one missing binary. A
larger blast radius than the thing being fixed.

**`SETUPTOOLS_SCM_PRETEND_VERSION`.** Re-rejected by reference to ADR-0062, which rejected it
already: injecting a version into the build makes Assay the author of a fact the repository is
supposed to state, and it is backend-specific — hatch-vcs, pdm-backend and versioneer each want a
different incantation, so the harness would carry a table of other projects' environment
variables.

**Install git only for repositories that need it.** Rejected outright: it makes the recipe — and
therefore the address — depend on a property of the repository under test that Assay would have
to *detect*, so a detector's mistake becomes an environment difference. Two images for one commit
depending on how a heuristic read a `pyproject.toml` is the failure mode this whole module is
built against.

**`snapshot.debian.org`, to date the apt install at the commit's era too.** Attractive in
principle: it would close the asymmetry above rather than widen it. Rejected for now as
disproportionate and unmeasured — it adds a mirror this project has never used, a snapshot date
threaded into the recipe, and a second era-pinning mechanism beside `--exclude-newer`, all to
date a version-control tool the project under test does not import. Named here so it is on the
record as available if the era argument ever does bite.

**Do nothing, and publish that setuptools-scm projects are unscoreable.** Rejected: it is not
true, and publishing it would be the kind of confident wrong number this project exists to
refuse. A plain `git clone` builds `tenacity` fine. The defect is in Assay's image, so "the
repository is unscoreable" would be Assay reporting its own bug as a property of someone else's
code — the distinction ADR-0025 draws and ADR-0062 already applied once.

## Consequences

**Every task image is re-addressed, for the second time inside one goal.** ADR-0063 moved every
address by adding the `context` key; this moves every address again by changing the recipe text.
Nothing already built is invalid — the old images are still exactly what they always were — but
no daemon holds an image at the new addresses, so the first run after this pays for a cold
rebuild of every image in a suite. Doing both inside one goal is deliberate: two re-addressings
in one release cost one cold rebuild, not two.

**The layer is paid for once and shared across every image in a suite,** because it precedes
`COPY`. Below `COPY` the same layer would have been commit-dependent by construction and paid for
once per image — for a 213-task suite, 213 copies of it rather than one. `unverified:` the
layer's actual size on disk. An earlier draft of this record put it at about 84 MB and multiplied
that out to a concrete total; neither figure was ever measured on this host, so both are struck.
The ordering argument does not rest on the size — it holds at any size, because it is about how
many copies exist, not how large each one is.

**A git binary is now reachable by a tool under test in the adapter phase.** The agent image
layers over the task image, so Claude Code — or any future tool — can now run git inside its
container. This is a **convenience delta rather than a new capability**, and both halves matter.
It is not a new *exfiltration* path: the adapter phase already runs with a network path open to
an allowlisted model endpoint (ADR-0036, ADR-0059), so a tool that wanted to send the workspace
somewhere already had a channel, and one more client binary does not widen the allowlist. It is
not a new *answer-key* path either: the trial workspace is a bind-mounted linked worktree whose
`.git` is a pointer at a clone outside the container (ADR-0062), so a git that can now run has
nothing there to read. What it does give is convenience — a tool can now `git diff` its own work
instead of reasoning about a tree. `naive-local`'s exposure is **zero**, because that adapter
never starts a tool container at all.

**Layer byte-reproducibility over time is explicitly not claimed.** `git` is pinned;
`--no-install-recommends` keeps the closure small but not empty, and its members — `git-man`,
`less`, `perl`, `libcurl3-gnutls` — are resolved by apt at build time and are *not* pinned.
Rebuilding this layer in six months may well produce different bytes under the same address. That
is a real gap and it is stated rather than papered over: what the address pins is the *recipe*,
and the recipe now names one version of one package.

**When the pin leaves the archive, builds fail loudly.** Debian moves point releases out of the
main archive, and when `1:2.39.5-0+deb12u3` goes, `apt-get install` exits non-zero with
`E: Version '...' was not found`. That is the intended failure: a loud break that forces a
deliberate re-pin, and re-addresses every image when it happens, rather than a silent
substitution. The alternative posture — install whatever is there — is the one rejected above.

**A Debian mirror outage now breaks image builds that previously needed only PyPI and ghcr.io.**
One more network dependency at build time, in a project whose non-negotiables are about the
network at *trial* time. It does not touch SPEC §5.3: the trial still has no network, and this
is a dependency installed when the image is built, which is exactly where §5.3 puts them.
