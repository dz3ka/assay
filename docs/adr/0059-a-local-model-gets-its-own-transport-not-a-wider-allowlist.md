# ADR-0059: A model on this machine gets its own transport, not a wider allowlist

- **Status:** Accepted
- **Date:** 2026-09-08
- **Deciders:** Bogdan Dzekic

## Context
Five milestones in, Assay has never called a model. Every band, every p and every cost line in
this repository came from the two oracles ADR-0051 names - `ground_truth`, which scores 1.0 by
construction, and `null`, which scores 0.0 - or from hand-written fixtures. The adapters that
would call a model exist and are wired; nothing has ever pointed them at one, and ADR-0042
already had to withdraw a README promise that the first live run was coming.

The reason is a standing ruling and it is not being revisited here: **no paid model call, ever,
on any path.** A run that spends money is a run this project cannot repeat in CI, cannot hand to
a reader, and cannot afford to leave in a script somebody runs by accident.

A model served on this machine settles that. Ollama listens on `http://127.0.0.1:11434` and
serves an OpenAI-compatible route at `/v1/chat/completions`; a call to it costs nothing, needs no
key, and produces a completion a real - not oracular - adapter can be scored on.

**The transport this repository has cannot make that call, on two counts.** `_checked_endpoint`
refuses any scheme but `https`, and refuses any host outside `ALLOWED_HOSTS`, which is the single
entry `api.anthropic.com`. Both refusals are deliberate and both are load-bearing: the prompt
carries the source of the repository under evaluation, so the endpoint *is* the trust boundary
(SPEC §5.1 and §5.3), and ADR-0036 put the whole of the outbound capability in one module with an
AST fence over every other module in `src/assay` to prove it.

So the question is not "how do we allow loopback" but **what the allowlist is a control on**.
It is a control on bytes leaving this machine. A POST to `127.0.0.1` does not leave it: no
packet reaches an interface, no third party receives the repository's source, and there is
nothing for a transcript on somebody else's server to retain. The exfiltration property SPEC
§5.1 states is untouched by a loopback call, which is why this is not a widening.

The complication is that the *shape* of a loopback URL is easy to arrive at by accident or by
misdirection. `localhost` is a name in a file this harness does not own. `http://127.0.0.1:8080`
is what a forwarder to anywhere looks like from inside this process. And a hosted endpoint typed
into the wrong flag would be a prompt going somewhere nobody approved. The decision has to be
about which class of endpoint is reachable from which code path, not about a string comparison.

One more force: the response shape is **documentation, not measurement**. The daemon is not
installed on the machine this was written on, so `usage.prompt_tokens` and
`usage.completion_tokens` are read from Ollama's documentation and have never been observed
here.

> **Amended 2026-09-09 — this force is retired.** The text above stands as written on 2026-09-08;
> it is no longer true. A daemon is installed and has answered. See the amendment under
> Consequences for what was and was not checked.

## Decision
**A second transport class, `LocalModelTransport`, in the same module, with its own endpoint
check. `ALLOWED_HOSTS` is unchanged and the https-only rule is unchanged.**

`_checked_local_endpoint` refuses, in order: credentials in the URL, any scheme but `http`, and
any host but the **literal** `127.0.0.1`. `localhost` and `::1` are refused - a name is resolved
by a hosts file this harness does not own, and a machine where that file has been pointed
elsewhere would send the repository there. `https` is refused because the endpoint this class
exists for is a plaintext daemon, and a TLS listener at that address is a different thing
(a tunnel, a proxy) and would be a different decision.

**The class carries no API key and has no keyword to pass one.** A daemon on loopback is not
authenticated. A class that cannot be handed a credential cannot leak one, and the absence is
enforced by the signature rather than by an empty string.

**It lives in `host/model_api.py`,** because ADR-0036's fence exempts one module *path*. A second
module that opened a socket would be a second exemption, and the fence's worth is that there is
exactly one.

**Everything below the endpoint check is shared, not copied.** The redirect refusal, the 1 MiB
pre-parse cap, the mandatory timeout, the status check and the one-error contract are extracted
into `_post` and called by both transports - one policy about a socket, not two. Only the
request body and the response parse differ, because only the dialect differs.

**`_parse_chat_completion` is strict to the point of rudeness, and says why in its docstring.**
Nothing defaults, nothing coerces, a missing token count is not zero, and `True` is not `1`. The
shape is unverified, so the only honest failure mode is a loud one: a fabricated token count in
a report about token counts is the failure this project exists to be incapable of. The docstring
names the assumption so the milestone that first meets a live daemon can retire it.

**The security checklist is followed in substance and deviated from in letter, and this record is
where that is disclosed.** `~/agent-atlas/references/security-checklist.md:65` says to block
private and reserved IP ranges, which is the SSRF rule: an attacker-supplied URL must not be
allowed to reach the loopback interface. Here the relationship is inverted - the URL is a
compile-time constant on a class the operator reaches by naming an adapter on the command line,
there is no attacker-supplied fetch target anywhere in the path, and loopback is the *only*
destination permitted rather than the one excluded. The substance of the rule - an allowlist, a
literal host, no user-supplied URL - is followed. The letter of it is inverted on purpose.

## Alternatives considered
- **A `dialect` parameter on `HttpModelTransport`: one class, two request shapes, and an endpoint
  check that branches on it.** Rejected, and this is the alternative the decision is really
  against. It looks like the smaller change and it is the more dangerous one: a single class
  holding both "https at an allowlisted host" and "http at 127.0.0.1" makes a mistyped hosted
  endpoint *reachable through the loopback branch* if the dialect argument is wrong, and the
  wrongness is a runtime value nobody sees. With two classes, pointing the local transport at
  `api.anthropic.com` is refused at construction and pointing the keyed one at loopback is
  refused at construction, and the choice of which to build is a line of code a reviewer reads.
- **Add `127.0.0.1` to `ALLOWED_HOSTS` and relax `https` to `https|http`.** Rejected as the worst
  of the options, because it launders a narrow permission through the mechanism that carries the
  broad one. The keyed transport would then accept `http://127.0.0.1:8080` - a forwarder to
  anywhere, holding the API key, reached by a path whose whole job is to refuse exactly that.
  The frozenset would also stop meaning what its comment says it means: "every name here is
  somewhere the repository under evaluation is allowed to end up" would be false of the new
  entry, because a loopback address is not a destination at all.
- **A separate module, `host/local_model.py`, so the two rules are visibly separate files.**
  Rejected on ADR-0036. The fence is a module path, so a second socket-opening module is a second
  exemption in the one test whose value is that it has only one. Separation by class inside the
  fenced module buys the same legibility at no cost to the fence.
- **Accept `localhost` too, since it resolves to `127.0.0.1` on every machine anybody will run
  this on.** Rejected because "on every machine anybody will run this on" is the assumption, and
  the hosts file is a trust input this harness does not control. The cost of refusing it is one
  confused user reading an error message that tells them what to type. The cost of accepting it
  is a resolution this project cannot audit standing between the prompt and the socket.
- **Delete or soften the hosted transport's `loopback` refusal case, now that a loopback endpoint
  is legitimate somewhere in the module.** Rejected, and confronted rather than left alone: the
  case is renamed to `loopback-https` and carries a comment pointing here. It stays red because
  it is about the *keyed* path, and an operator pointing the credential-carrying transport at a
  local forwarder is precisely the routing-around the allowlist was written to stop. The two
  transports disagreeing about `https://127.0.0.1` is the design working, not an inconsistency.
- **Leave the "no model has ever been called" gap open until a paid run is affordable.**
  Rejected. Five milestones of oracles bracket every result at 1.0 and 0.0 and prove the harness
  arithmetic; they prove nothing about whether the harness can measure a tool that sometimes
  works. A local model is the first thing this repository can honestly score, and it is free.

## Consequences
**The egress fence is unchanged and still green with `EGRESS_MODULE` untouched.** One module may
open a socket, and it is still `host/model_api.py`.

**The two refusal matrices are asserted separately and against each other.** The hosted set keeps
its six cases with one renamed id; the local set adds seven, including the three shapes that look
like loopback and are not (`localhost`, `::1`, `127.0.0.2`) and the two that are loopback and are
still refused (`https`, userinfo). `https://127.0.0.1` now appears in both matrices, refused by
both, for opposite reasons - which is the clearest single statement of what these two classes are.

**No test gates on a running daemon.** ADR-0024 leaves this repository with no skip path by
design, so a test that needed Ollama would be a test that failed on every machine without it. The
local transport's response paths are stubbed, and its one real socket goes to a
`ThreadingHTTPServer` this test file starts on 127.0.0.1 and serves a canned chat-completion body
from - which exercises construction, the real `open_request`, the cap and the parse, and proves
nothing at all about Ollama.

**One claim in this repository is now documentation rather than measurement, and it is written
down in three places** - the parser's docstring, the fixture body in the test file, and here. The
milestone that first runs against a live daemon owes a check of the recorded response against
`GOOD_CHAT_BODY`, and a correction to `_parse_chat_completion` if the shape differs.

> **Amended 2026-09-09 — the debt above is discharged, and the discharge is partial.** A live
> `qwen2.5-coder:7b` daemon answered through the CLI on that date. Two `naive-local` trials parsed
> without raising and recorded non-zero counts in both directions (275/264 and 237/231) beside the
> diff text the model wrote, so every field `_parse_chat_completion` reads was present and
> well-typed on real bodies. **No correction to the parser was needed.** What this ADR asked for
> and did *not* get is the literal check: the raw bodies were not retained, so `GOOD_CHAT_BODY`
> has not been diffed against a recorded body byte for byte. The fields are measured; the literal
> is not. The three sites named above were updated to say exactly that and no more. Evidence:
> `docs/milestones/local-model-live-run.md` §2.

**This transport is transport only.** The adapter that drives it, and the CLI wiring that lets a
run name it, are separate decisions and are not taken here. Nothing in `src/assay` constructs a
`LocalModelTransport` yet; it is exported from `assay.host` and used by tests.

**Deletion path:** if a local model is never scored, the class, its check, its parser and its
tests come out together and `_post` folds back into `HttpModelTransport.send`. Nothing else in
the tree refers to any of them.
