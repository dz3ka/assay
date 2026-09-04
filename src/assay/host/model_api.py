"""The one module in Assay that opens a socket. Everything that leaves this machine leaves here.

SPEC §5.1 says the repository under evaluation never leaves the machine, and SPEC §5.3 carves
out the single exception this module is: an allowlisted model endpoint, reachable because a
naive baseline that cannot call a model measures nothing. A promise like that is only worth
what it can be checked against, so the exception is one file with one call in it and
``tests/host/test_network_egress.py`` walks every other module in ``src/assay`` asserting that
none of them so much as imports ``socket``, ``ssl``, ``urllib`` or an HTTP client (ADR-0036).

The fence exempts *this module path*, not the ``host`` package: ``host/git.py``'s standing
claim is that it never clones and never fetches, and a directory-wide exemption would let it
quietly start doing both.

Four properties are load-bearing, and the prompt is why: it carries the private repository's
own source text, so the endpoint is the trust boundary (plan §7).

* **The endpoint is allowlisted, at construction, before anything is sent.** ``https`` only,
  and the host must be one of :data:`ALLOWED_HOSTS`. This is the exfiltration control.
* **A redirect is refused rather than followed.** ``urllib`` follows one by default and copies
  the request's headers to the new location - the API key with them - which would hand both
  the key and the prompt to a host the allowlist never approved. :func:`open_request` installs
  a redirect handler that declines, so a 3xx surfaces as an error instead of a second request.
* **Consumption is bounded.** One call and no retry loop, a mandatory timeout on the socket,
  ``max_tokens`` on the request, and the body size-capped *before* it is parsed.
* **The response is parsed strictly and the key never travels into an error.** Anything that
  is not the declared shape raises :class:`ModelTransportError`, which the adapter records as
  ``Attempt.error``; nothing here raises an exception the adapter has not been told about.

TLS verification is ``urllib``'s default and is never disabled - there is no context argument
here to disable it with. What this module does *not* do is judge the completion: a response
truncated at ``max_tokens`` arrives as text like any other and fails later as a diff that will
not apply, because the transport's job is to report what the endpoint said.
"""

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from http.client import HTTPMessage
from typing import IO, Final, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from assay.adapters.model import ModelResponse, ModelTransportError

# The hosts a prompt may be sent to. One entry, and widening it is a decision with an ADR
# rather than a configuration change: every name here is somewhere the repository under
# evaluation is allowed to end up (ruling 6).
ALLOWED_HOSTS: Final = frozenset({"api.anthropic.com"})

# The API version header Anthropic's Messages endpoint requires. Pinned rather than tracked:
# a response shape that changed under us must fail the strict parse below, not be absorbed.
_ANTHROPIC_VERSION: Final = "2023-06-01"

# The most response body this module will read into memory. A completion capped at a few
# thousand output tokens is tens of kilobytes of JSON, so a megabyte is ample headroom and
# still small enough that an endpoint answering with a stream of bytes cannot exhaust this
# process. Checked before `json.loads`, which is the call that would spend the memory.
_MAX_RESPONSE_BYTES: Final = 1024 * 1024

# How much of a refusal's own body is quoted into the error message. Enough for the sentence
# that matters - "your credit balance is too low" is the one M3 expects to meet (ruling 6) -
# and bounded because the text comes from the far side of the trust boundary.
_ERROR_EXCERPT_CHARS: Final = 300


class HttpReply(Protocol):
    """The half of an HTTP response this module reads: a status, and bounded bytes.

    Narrow on purpose. It is what lets the transport be driven by a stub in tests without
    those tests having to imitate ``http.client.HTTPResponse``, and it is small enough that
    reading it says exactly how much of a response is trusted: a number and a read of at
    most n bytes.
    """

    status: int

    def read(self, amount: int, /) -> bytes: ...


# How a request becomes a reply. The seam exists so that every response path below - the
# oversized body, the junk payload, the 402 from an unfunded account - is reachable in CI
# without a network; the default is the real thing and the endpoint allowlist is enforced
# above it either way, so a stub cannot widen where a prompt may go.
type HttpOpener = Callable[[Request, float], AbstractContextManager[HttpReply]]


class _RefuseRedirects(HTTPRedirectHandler):
    """Decline every redirect, which turns a 3xx into an error rather than a second request.

    The reason is the API key. ``urllib``'s default handler builds the follow-up request from
    the original's headers, so an allowlisted endpoint answering ``302 Location: evil`` would
    send both the key and the prompt to a host that was never allowlisted - and the allowlist
    is checked once, at construction, which is exactly what a redirect routes around.

    Returning ``None`` means "not handled" to :class:`urllib.request.OpenerDirector`, which
    then falls through to the default error handler and raises the 3xx as an
    :class:`urllib.error.HTTPError`.
    """

    def redirect_request(
        self,
        req: Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> Request | None:
        return None


_OPENER: Final = build_opener(_RefuseRedirects)


def open_request(request: Request, timeout_s: float) -> AbstractContextManager[HttpReply]:
    """Send ``request`` and hand back the reply. This is the line that opens the socket.

    Separate from :class:`HttpModelTransport` because it is the one thing in this module that
    cannot be exercised without a server: the tests drive it against a loopback
    ``http.server`` - including the redirect it must refuse - and stub it everywhere else.

    The scheme is not checked here; the transport has already refused anything that is not
    ``https`` at an allowlisted host, and putting the check in both places would make the
    loopback test impossible without proving anything the allowlist does not already prove.
    """
    reply: AbstractContextManager[HttpReply] = _OPENER.open(request, timeout=timeout_s)
    return reply


class HttpModelTransport:
    """One HTTP call to an allowlisted model endpoint, per :class:`ModelTransport`.

    Satisfies that protocol structurally; nothing imports this class except
    :mod:`assay.cli.main`, which binds it to the naive baseline adapter.
    """

    def __init__(self, *, endpoint: str, api_key: str, opener: HttpOpener = open_request) -> None:
        """Refuse an endpoint or a key this transport must not use, before anything is sent.

        Both refusals happen here rather than at the first ``send`` so that a run configured
        wrongly fails before a container is built and before a task's prompt exists at all.
        """
        self._endpoint = _checked_endpoint(endpoint)
        if not api_key:
            raise ModelTransportError(
                "no model API key: set ASSAY_MODEL_API_KEY in the environment. It is read "
                "from there and never from a command-line flag, which any other process on "
                "this machine could read out of the process list."
            )
        self._api_key = api_key
        self._opener = opener

    def send(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_output_tokens: int,
        timeout_s: int,
    ) -> ModelResponse:
        """Send one prompt, once, and parse exactly what came back.

        Raises:
            ModelTransportError: for every failure of the seam - unreachable host, timeout,
                HTTP status, oversized body, or a payload that is not the declared shape.
        """
        body = json.dumps(
            {
                "model": model,
                "max_tokens": max_output_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        ).encode("utf-8")
        request = Request(
            self._endpoint,
            data=body,
            method="POST",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )

        try:
            with self._opener(request, float(timeout_s)) as reply:
                status = reply.status
                # One byte past the cap, so "there was more" is answerable without reading it.
                raw = reply.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            # The status carries the meaning M3 cares about: 401 is a bad key, 400 or 402 is
            # an account with no funds, 429 is a rate limit, and each of them is a trial that
            # errored rather than a tool that failed. Quoted, capped, and never the key.
            raise ModelTransportError(
                f"the model endpoint refused the request: HTTP {error.code}{_excerpt(error)}"
            ) from error
        except OSError as error:
            # URLError, socket timeouts and TLS failures are all OSError, and there is nothing
            # to tell apart: the call did not happen, so the trial is errored either way.
            raise ModelTransportError(
                f"the model endpoint could not be reached within {timeout_s}s: {error}"
            ) from error

        if status != 200:
            raise ModelTransportError(f"the model endpoint answered HTTP {status}, not 200")
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise ModelTransportError(
                f"the model endpoint's response is too large to parse: over "
                f"{_MAX_RESPONSE_BYTES} bytes"
            )
        return _parse(raw)


def _checked_endpoint(raw: str) -> str:
    """Return ``raw`` unchanged, or refuse an endpoint a prompt must not be sent to.

    Refused rather than repaired, as every value on its way into something irreversible is in
    this codebase: the irreversible thing here is that the repository's own source has left
    the machine, and there is no upgrading ``http`` to ``https`` after the fact.

    The host is read with :func:`urllib.parse.urlsplit`, which is the same parse ``urllib``
    itself will do, so ``https://api.anthropic.com@evil.example/`` is refused on the host it
    would actually connect to rather than on the name in front of the ``@``.
    """
    split = urlsplit(raw)
    # Checked first, and the URL is never echoed afterwards: a credential written into the
    # endpoint would otherwise be copied into an error message, a log and a report.
    if split.username is not None or split.password is not None:
        raise ModelTransportError(
            "the model endpoint must not carry credentials in its URL; the key is read from "
            "ASSAY_MODEL_API_KEY"
        )
    if split.scheme != "https":
        raise ModelTransportError(
            f"the model endpoint must be https, not {split.scheme!r}: the prompt carries the "
            "repository under evaluation"
        )
    if split.hostname not in ALLOWED_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_HOSTS))
        raise ModelTransportError(
            f"the model endpoint host {split.hostname!r} is not allowlisted; Assay sends a "
            f"prompt to {allowed} and nowhere else"
        )
    return raw


def _excerpt(error: HTTPError) -> str:
    """The first few hundred characters of a refusal's body, or nothing at all.

    The endpoint's own sentence is the difference between "402" and "your credit balance is
    too low", which is what a user reads in ``Attempt.error``. It is untrusted text from the
    far side of the boundary, so it is bounded here and escaped by whatever renders it.
    """
    try:
        detail = error.read(_ERROR_EXCERPT_CHARS).decode("utf-8", errors="replace").strip()
    except OSError:
        return ""
    return f": {detail}" if detail else ""


def _parse(raw: bytes) -> ModelResponse:
    """Read the declared response shape out of ``raw``, or refuse it.

    Strict in the sense that matters: every field this harness reads is checked to be the type
    it is read as, and anything missing or mistyped raises rather than defaulting. It is
    deliberately *not* strict about fields it does not read - an endpoint that adds a key must
    not break a measurement - and a content block of a kind this module has no vocabulary for
    is skipped rather than refused, because "the model produced no text" is an answer.
    """
    try:
        payload: object = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ModelTransportError(f"the model endpoint's response is not JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ModelTransportError("the model endpoint's response is not a JSON object")

    content: object = payload.get("content")
    if not isinstance(content, list):
        raise ModelTransportError("the model endpoint's response has no 'content' list")
    texts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            raise ModelTransportError("a content block is not a JSON object")
        if block.get("type") != "text":
            continue
        text: object = block.get("text")
        if not isinstance(text, str):
            raise ModelTransportError("a text content block has no 'text' string")
        texts.append(text)

    usage: object = payload.get("usage")
    if not isinstance(usage, dict):
        raise ModelTransportError("the model endpoint's response has no 'usage' object")
    return ModelResponse(
        text="".join(texts),
        input_tokens=_token_count(usage, "input_tokens"),
        output_tokens=_token_count(usage, "output_tokens"),
    )


def _token_count(usage: dict[object, object], name: str) -> int:
    """One of the endpoint's own token counts, refused unless it is a non-negative integer.

    ``bool`` is rejected explicitly for the reason :mod:`assay.core.versioning` rejects it:
    ``True`` is an ``int`` in Python and ``1`` input token is not what a ``true`` in a JSON
    payload meant.
    """
    value: object = usage.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelTransportError(f"the model endpoint's {name!r} is not a token count: {value!r}")
    return value
