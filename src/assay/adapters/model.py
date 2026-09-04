"""The seam a model-backed adapter drives, and the vocabulary the two ends of it share.

The naive baseline is one raw model call with no agent loop (CLAUDE.md), which makes it the
first adapter that has to reach off this machine at all. Everything it needs of that call is
here - a request's five arguments and a response's three fields - and nothing here knows how
the bytes travel. The implementation is :class:`assay.host.HttpModelTransport`, the one module
in ``src/assay`` permitted to open a socket (ADR-0036), and it satisfies this protocol
*structurally*: nothing imports it but :mod:`assay.cli.main`, which binds it.

The split is the same one ``RunnerFactory`` already buys the miner. ``score`` imports
``adapters`` and must never import ``host``, so if the transport lived beside the adapter the
package the scorer depends on could open a socket, and "the repository under evaluation never
leaves the machine" would stop being checkable by reading one file. It also means every branch
of the baseline adapter - a refused endpoint, an unfunded account, a truncated response - is
reachable in CI on a fake transport that never touches a network.

The arguments are flat rather than a request object because there are five of them and they
are all the endpoint's own vocabulary; a ``ModelRequest`` would be a second schema to version
for a value that is never serialised, never stored and read by exactly one implementation.
"""

from dataclasses import dataclass
from typing import Protocol

from assay.core import AssayError


class ModelTransportError(AssayError):
    """The model endpoint did not produce a response this harness can read.

    One error for every way the seam fails - an endpoint refused by the allowlist, an
    unreachable host, a timeout, an HTTP status, a body over the size cap, a payload that is
    not the declared shape - because the adapter does the same thing with all of them: record
    it in ``Attempt.error``, score the trial ``ERRORED``, and start no container. A failure of
    the tool being measured is data about that tool; a failure of the wire is not.

    It lives here, beside the protocol, rather than beside the implementation that raises it,
    which is the one deliberate exception to this repository's "errors live in the module that
    raises them". The adapter that catches it may not import :mod:`assay.host`, so an error
    declared there would be uncatchable by name at the only place that needs to catch it.

    Never carries the API key. The message is read by a CLI that prints it and by an
    ``Attempt`` that is written to a result set (plan §7a).
    """


@dataclass(frozen=True)
class ModelResponse:
    """One completion, and what it cost in tokens.

    ``text`` is the completion's text content and nothing else: a response that carried no
    text block at all arrives as ``""``, which is an answer ("the model produced no diff")
    rather than a fault, in the same way the null adapter's empty diff is an answer.

    The token counts are the endpoint's own accounting, recorded rather than estimated. M3
    records tokens and not money: SPEC §7 puts cost accounting in M4, so ``cost_usd`` on the
    attempt built from this stays zero and no renderer reads it.
    """

    text: str
    input_tokens: int
    output_tokens: int


class ModelTransport(Protocol):
    """One call to a model endpoint. No retries, no streaming, no session.

    Deliberately not ``runtime_checkable``: conformance is proved by ``mypy --strict`` where
    the implementation is bound, exactly as ``TestRunner``'s is.
    """

    def send(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_output_tokens: int,
        timeout_s: int,
    ) -> ModelResponse:
        """Send one prompt and return the completion, or raise :class:`ModelTransportError`.

        ``max_output_tokens`` and ``timeout_s`` are required rather than defaulted because an
        uncapped call to a metered endpoint is not a measurement anyone can repeat: the
        implementation puts the first on the request and the second on the socket, and
        neither is the transport's to choose.

        One call. A transport that retried would spend a trial's budget on an outcome the
        harness never sees, and n trials per task is how this harness measures variance
        (SPEC §4) - a hidden retry loop inside one of them would flatter the tool under test.
        """
