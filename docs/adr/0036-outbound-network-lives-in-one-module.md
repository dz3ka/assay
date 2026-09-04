# ADR-0036: Outbound network lives in one module, and an AST fence proves nothing else opens a socket

- **Status:** Accepted
- **Date:** 2026-09-02
- **Deciders:** Bogdan Dzekic

## Context
M3 adds the naive baseline: one raw model call, no agent loop, in every report (CLAUDE.md). It
is the first thing Assay has ever built that talks to anything off this machine, and it lands
against a promise made in SPEC §5.1 and repeated in the README — the repository under
evaluation never leaves the machine, no upload, no telemetry — with exactly one carve-out, the
allowlisted model endpoint a trial may reach.

That promise is unusual among this codebase's rules in that a reader cannot check it by reading
one file. The claims about mining are local: a mined repository's tests run under
`host.run_command` and nowhere else, and one AST test proves it by walking every module for the
name `subprocess`. "Nothing is uploaded" is a claim about *all* the code at once, and the prompt
is what makes it load-bearing rather than decorative: the naive baseline's prompt carries the
task's own source and its failing test files, which is private repository text, sent to a
third party.

The tempting shape is the small one. `urllib.request.urlopen` inside `adapters/naive.py` is
fewer files, no seam, no protocol, and the adapter reads top to bottom. It is also the shape
that makes the promise uncheckable: `score` imports `adapters`, so the package the scorer
depends on would be a package that can open a socket, and any future adapter — or anything
`adapters` grows — inherits the capability with nothing to notice it.

There is a second question underneath the first, which is what an exemption is an exemption
*of*. The subprocess fence exempts a directory: any module whose parent is `host` may import
`subprocess`, which is right for that rule, because concentrating process execution in one
audited package is the whole point and there are five modules in it that legitimately run
things. Copying that shape here would exempt `host/git.py` — a module whose module docstring
and ADR-0013's reasoning both rest on it never cloning and never fetching, only ever operating
on a local clone the user already has. Under a directory-wide exemption, the day somebody adds
a `git fetch` to refresh a stale clone, nothing goes red.

## Decision
**Outbound network access lives in `host/model_api.py` alone, behind a `ModelTransport`
protocol declared in `adapters/model.py`, and `tests/host/test_network_egress.py` walks the AST
of every module in `src/assay` asserting that no other one imports `socket`, `ssl`, `urllib`,
`http` or a third-party HTTP client. The exemption is that exact module path, not its
directory.**

The seam is the shape `RunnerFactory` already has. The adapter is a pure driver over an
injected transport, `cli.main` binds the real one, and `score` — which may not import `host` at
all — never sees it. Every branch of the baseline is therefore reachable in CI on a fake
transport: the endpoint refusal, the unfunded account, the truncated response, none of which
can be provoked on demand from a real endpoint.

The fence reads import statements rather than file text, as both existing fences do, so a
module that explains the rule in its docstring is obeying it rather than breaking it. It is
also exercised against a synthesised tree, not only the real one: a fence nobody has watched go
red is a fence nobody has tested, so there are cases pinning that a network import moved into
`adapters/` is caught, and that the same import in `host/git.py` is caught while
`host/model_api.py` is not.

Concentrating egress in one module is also what makes the rest of the controls affordable, so
they live there and are tested there: the endpoint is refused unless it is `https` at an
allowlisted host, checked at construction before any prompt exists; a redirect is declined
rather than followed, because `urllib` copies the request's headers — the API key among them —
to whatever host a `302` names, which is precisely how an allowlist checked once gets routed
around; the API key is read from `ASSAY_MODEL_API_KEY` and never from an argv flag any other
process could read out of the process list; the response body is size-capped before it is
parsed; and every failure of the seam arrives as one `ModelTransportError` the adapter records
in `Attempt.error` rather than as an exception nobody declared.

## Alternatives considered
- **`urllib.request` directly in `adapters/naive.py`.** Rejected, and this is the alternative
  the record exists to argue against. It is genuinely smaller — no protocol, no seam, no second
  file — and every other consideration goes the other way. `score` imports `adapters`, so the
  capability lands in the scorer's own dependency graph; the adapter's failure branches become
  untestable without a network or a monkeypatched module; and the promise stops being
  checkable, because there is no longer any file you can read to know where bytes leave.
- **Exempt the `host` package, as the subprocess fence does.** Rejected. It would be one line
  shorter and consistent-looking, and it would silently license `host/git.py` to fetch. The two
  rules are not the same rule: `host` exists to concentrate process execution among several
  modules that legitimately execute processes, while exactly one module has any business
  opening a socket, so the natural unit of exemption differs.
- **Denylist nothing and rely on code review.** Rejected on the same grounds as the subprocess
  fence: a habit is not a control, and the specific failure — a contributor adding `requests`
  to a new adapter because it is the obvious way to call an API — is one a reviewer under time
  pressure passes.
- **A runtime egress control (a socket monkeypatch, a seccomp filter, a proxy).** Rejected as
  the wrong layer for this milestone. It would catch a dependency's egress as well as Assay's,
  which the static fence cannot, but it is a runtime mechanism to maintain, it does not fail at
  review time where it is cheap to fix, and the container's `--network none` already covers the
  place hostile code actually runs. Worth revisiting only if Assay grows a dependency that
  could plausibly phone home; pydantic is the entire runtime dependency list today.
- **Put `ModelTransportError` beside the implementation that raises it,** as every other error
  in this codebase is. Rejected because the adapter that catches it may not import `assay.host`,
  so the error would be uncatchable by name at the only place that needs to catch it. It lives
  with the protocol, which is the vocabulary both ends share.

## Consequences
There are now two audited seams in `host` with two fences over them, and they are worded
differently on purpose — one names a package, one names a module. `host/__init__.py` says both,
because a reader arriving at the package has to know which rule they are under.

Adding a second allowlisted endpoint means editing `ALLOWED_HOSTS` in one place and writing the
ADR that says why a prompt may go there. That is the intended cost. Adding an HTTP client
library means the fence goes red until its name is added to the forbidden list *and* the import
is inside the exempt module — which is a review conversation rather than a merge.

The fence is a static check and is honest about being one. It proves no module in `src/assay`
imports something that can open a socket; it does not prove that pydantic never phones home,
and it would not catch egress through a subprocess — although the subprocess fence plus
`minimal_env` means every child is started from one place with an allowlisted environment, so
the two fences overlap where it matters. `tests/fixture_repo.py` and the tests themselves are
outside the walk, which is deliberate: the loopback `http.server` the transport is tested
against would otherwise be an offender, and a test that binds a socket on `127.0.0.1` is not
what the promise is about.

The seam has one cost worth naming: `HttpModelTransport` takes an opener argument that defaults
to the real one, which exists so the response paths — an oversized body, a junk payload, a 402
from an account with no funds — are reachable without a network. A stub cannot widen where a
prompt may go, because the allowlist is enforced above it, but it is a test seam in production
code and it should be read as one.
