"""The one socket Assay is allowed to open, and the fence proving there is only the one.

The repository under evaluation never leaves this machine (SPEC §5.1) except in the prompt
handed to one allowlisted model endpoint, which is the whole of M3's naive baseline. That
sentence is only checkable if exactly one module can reach the network, so two properties are
pinned here and they defend each other.

The first is structural: no module in ``src/assay`` other than ``host/model_api.py`` imports
``socket``, ``ssl``, ``urllib``, ``http`` or a third-party HTTP client. The exemption is **that
exact module path**, not the ``host`` package - ``host/git.py``'s standing claim is that it
never clones and never fetches, and a directory-wide exemption would let it grow a ``fetch``
without this file noticing (ADR-0036). The fence is exercised against a synthesised tree as
well as the real one, because a fence nobody has seen go red is a fence nobody has tested.

The second is behavioural: what the permitted module does with its socket. The endpoint is
refused unless it is ``https`` at an allowlisted host, the API key never appears in an error
message, the body is size-capped before it is parsed, the parse is strict, and every failure
of the seam - refusal, timeout, HTTP status, junk payload - arrives as one
:class:`ModelTransportError` the adapter can turn into an ``Attempt.error`` rather than as an
unhandled exception (plan §7).

Most of that is driven through an injected opener, which is how the response paths are
reachable without a network. The opener itself - the line that actually opens the socket, and
its refusal to follow a redirect, which is what stops an allowlisted host from handing the
API key to an unallowlisted one - is driven against a real HTTP server on loopback.
"""

import ast
import io
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from assay.adapters import ModelResponse, ModelTransportError
from assay.host import HttpModelTransport
from assay.host.model_api import HttpOpener, open_request

SOURCE_ROOT = Path(__file__).parent.parent.parent / "src" / "assay"

# The module path that may open a socket, relative to ``src/assay``, exactly as the fence in
# :mod:`tests.host.test_network_egress` spells it. One string, so a rename of the module is a
# deliberate edit here rather than a silently widened exemption.
EGRESS_MODULE = "host/model_api.py"

# Top-level module names that can put bytes on a wire: the standard library's four, and the
# third-party clients a future contributor would reach for first. A name not on this list is
# not proof of innocence - it is the next entry, added when somebody adds the dependency.
NETWORK_MODULES = (
    "aiohttp",
    "http",
    "httpx",
    "requests",
    "socket",
    "ssl",
    "urllib",
    "urllib3",
)

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_KEY = "sk-ant-not-a-real-key"

# A well-formed Anthropic Messages response, as the strict parse expects to find it.
GOOD_BODY = json.dumps(
    {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "diff --git a/a.py b/a.py\n"}],
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
).encode("utf-8")


def _imports_a_network_module(path: Path) -> list[str]:
    """Every network module this file imports, read from the import statements only.

    Duplicated from the fence under test on purpose: this helper is the *specification* the
    test tree is built against, and importing the implementation to check itself would make
    the two agree by construction.
    """
    reached: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            reached.update(
                alias.name.split(".")[0]
                for alias in node.names
                if alias.name.split(".")[0] in NETWORK_MODULES
            )
        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in NETWORK_MODULES:
                reached.add(root)
    return sorted(reached)


def egress_offenders(source_root: Path) -> list[str]:
    """Every module under ``source_root`` that imports a network module and may not.

    Takes the root as an argument so the fence can be run against a synthesised tree; the
    exemption is compared as a path relative to that root, which is what makes it a module
    identity rather than a directory.
    """
    return [
        f"{path.relative_to(source_root).as_posix()} imports {module}"
        for path in sorted(source_root.rglob("*.py"))
        if path.relative_to(source_root).as_posix() != EGRESS_MODULE
        for module in _imports_a_network_module(path)
    ]


def _write(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")


class _StubReply:
    """One canned HTTP response, read the way the transport reads a real one."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._stream = io.BytesIO(body)

    def read(self, amount: int, /) -> bytes:
        return self._stream.read(amount)

    def __enter__(self) -> "_StubReply":
        return self

    def __exit__(self, *unused: object) -> None:
        return None


class _RecordingOpener:
    """An opener that answers with a canned reply and keeps what it was asked to send."""

    def __init__(self, status: int = 200, body: bytes = GOOD_BODY) -> None:
        self._status = status
        self._body = body
        self.requests: list[Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: Request, timeout_s: float) -> _StubReply:
        self.requests.append(request)
        self.timeouts.append(timeout_s)
        return _StubReply(self._status, self._body)


def _refusing_opener(error: Exception) -> HttpOpener:
    def opener(request: Request, timeout_s: float) -> _StubReply:
        raise error

    return opener


def _transport(
    opener: HttpOpener, *, endpoint: str = ENDPOINT, api_key: str = API_KEY
) -> HttpModelTransport:
    return HttpModelTransport(endpoint=endpoint, api_key=api_key, opener=opener)


def _send(transport: HttpModelTransport) -> ModelResponse:
    return transport.send(
        model="claude-sonnet-4-5",
        system="you are a patch generator",
        user="fix the failing test",
        max_output_tokens=1024,
        timeout_s=30,
    )


def test_no_module_outside_the_egress_seam_imports_a_network_module() -> None:
    """The invariant this file exists to hold (SPEC §5.1, ADR-0036)."""
    assert egress_offenders(SOURCE_ROOT) == []


def test_the_permitted_module_is_present_and_is_the_one_that_opens_the_socket() -> None:
    # Without this, deleting `model_api.py` would leave the fence above green and vacuous.
    assert (SOURCE_ROOT / EGRESS_MODULE).is_file()
    assert _imports_a_network_module(SOURCE_ROOT / EGRESS_MODULE) != []


@pytest.mark.parametrize(
    ("statement", "module"),
    [
        ("import urllib.request", "urllib"),
        ("from urllib.request import urlopen", "urllib"),
        ("import socket", "socket"),
        ("import ssl as tls", "ssl"),
        ("from http.client import HTTPSConnection", "http"),
        ("import httpx", "httpx"),
        ("import requests", "requests"),
    ],
    ids=["urllib", "urllib-from", "socket", "ssl-aliased", "http-client", "httpx", "requests"],
)
def test_the_fence_goes_red_when_a_network_import_moves_into_the_adapters_package(
    tmp_path: Path, statement: str, module: str
) -> None:
    _write(tmp_path, EGRESS_MODULE, "import urllib.request\n")
    _write(tmp_path, "adapters/naive.py", f"{statement}\n")

    assert egress_offenders(tmp_path) == [f"adapters/naive.py imports {module}"]


def test_the_exemption_is_one_module_path_and_not_the_host_directory(tmp_path: Path) -> None:
    # ADR-0036's reason for the shape: `host/git.py` claims it never clones and never
    # fetches, and a directory-wide exemption would let it start doing both in silence.
    _write(tmp_path, EGRESS_MODULE, "import urllib.request\n")
    _write(tmp_path, "host/git.py", "from urllib.request import urlopen\n")

    assert egress_offenders(tmp_path) == ["host/git.py imports urllib"]


def test_a_module_that_only_names_a_network_module_in_prose_is_not_an_offender(
    tmp_path: Path,
) -> None:
    # Read from the import statements rather than the file's text, for the reason
    # `tests/host/test_process.py` gives about its own fence: a module that explains the rule
    # in its docstring is obeying it, not breaking it.
    _write(tmp_path, "score/trial.py", '"""Never opens a socket, never imports urllib."""\n')

    assert egress_offenders(tmp_path) == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.anthropic.com/v1/messages",
        "https://api.anthropic.com.evil.example/v1/messages",
        "https://api.anthropic.com@evil.example/v1/messages",
        "https://127.0.0.1:8080/v1/messages",
        "file:///etc/passwd",
        "/v1/messages",
    ],
    ids=["plain-http", "suffixed-host", "userinfo-decoy", "loopback", "file-url", "no-host"],
)
def test_an_endpoint_that_is_not_allowlisted_https_is_refused_at_construction(
    endpoint: str,
) -> None:
    # The prompt carries the private repository's own source, so this is the exfiltration
    # control and it is checked before anything is sent, not after.
    with pytest.raises(ModelTransportError):
        _transport(_RecordingOpener(), endpoint=endpoint)


def test_an_endpoint_carrying_credentials_is_refused_without_echoing_them() -> None:
    with pytest.raises(ModelTransportError) as caught:
        _transport(_RecordingOpener(), endpoint="https://user:hunter2@api.anthropic.com/v1")

    assert "hunter2" not in str(caught.value)


def test_a_missing_api_key_is_refused_at_construction_rather_than_sent() -> None:
    # An unset `ASSAY_MODEL_API_KEY` arrives here as the empty string. Sending it would spend
    # a request to be told 401, and the message names the variable the user has to set.
    with pytest.raises(ModelTransportError, match="ASSAY_MODEL_API_KEY"):
        _transport(_RecordingOpener(), api_key="")


def test_a_well_formed_response_becomes_a_model_response_with_both_token_counts() -> None:
    response = _send(_transport(_RecordingOpener()))

    assert response.text == "diff --git a/a.py b/a.py\n"
    assert response.input_tokens == 11
    assert response.output_tokens == 7


def test_the_request_carries_the_key_as_a_header_the_model_name_and_the_output_cap() -> None:
    opener = _RecordingOpener()

    _send(_transport(opener))

    request = opener.requests[0]
    assert request.full_url == ENDPOINT
    assert request.get_method() == "POST"
    assert request.get_header("X-api-key") == API_KEY
    assert opener.timeouts == [30.0]
    body = request.data
    assert isinstance(body, bytes)
    sent = json.loads(body)
    assert sent["model"] == "claude-sonnet-4-5"
    assert sent["max_tokens"] == 1024
    assert sent["messages"] == [{"role": "user", "content": "fix the failing test"}]


def test_only_the_declared_text_blocks_are_read_out_of_a_response() -> None:
    # A tool_use block is a shape this transport has no vocabulary for, and skipping it is
    # not the same as failing on it: the adapter reads text and only text.
    body = json.dumps(
        {
            "content": [
                {"type": "text", "text": "one "},
                {"type": "tool_use", "id": "t1", "name": "edit", "input": {}},
                {"type": "text", "text": "two"},
            ],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        }
    ).encode("utf-8")

    assert _send(_transport(_RecordingOpener(body=body))).text == "one two"


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        b"[]",
        json.dumps({"usage": {"input_tokens": 1, "output_tokens": 2}}).encode(),
        json.dumps({"content": {}, "usage": {"input_tokens": 1, "output_tokens": 2}}).encode(),
        json.dumps({"content": [{"type": "text"}], "usage": {}}).encode(),
        json.dumps({"content": [], "usage": {"input_tokens": "eleven"}}).encode(),
        json.dumps({"content": []}).encode(),
    ],
    ids=[
        "not-json",
        "not-an-object",
        "no-content",
        "content-not-a-list",
        "text-block-without-text",
        "token-count-not-an-int",
        "no-usage",
    ],
)
def test_a_response_that_is_not_the_declared_shape_raises_rather_than_guessing(
    body: bytes,
) -> None:
    with pytest.raises(ModelTransportError):
        _send(_transport(_RecordingOpener(body=body)))


def test_a_response_over_the_size_cap_is_refused_before_it_is_parsed() -> None:
    # The cap is the bounded-consumption half of plan §7(d): a hostile or broken endpoint
    # must not be able to spend this process's memory, and JSON parsing is where it would.
    body = b'{"content": [{"type": "text", "text": "' + b"x" * (2 * 1024 * 1024) + b'"}]}'

    with pytest.raises(ModelTransportError, match="too large"):
        _send(_transport(_RecordingOpener(body=body)))


def test_a_refused_call_names_the_status_and_never_the_key() -> None:
    # Ruling 6's first-class path: an account with no funds answers 400/402, and the adapter
    # turns this into `Attempt.error`. The key must not travel into a report by that route.
    refusal = HTTPError(
        ENDPOINT,
        400,
        "Bad Request",
        {},  # type: ignore[arg-type]
        io.BytesIO(b'{"error": {"message": "credit balance is too low"}}'),
    )

    with pytest.raises(ModelTransportError) as caught:
        _send(_transport(_refusing_opener(refusal)))

    message = str(caught.value)
    assert "400" in message
    assert "credit balance is too low" in message
    assert API_KEY not in message


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timed out"), OSError("connection reset"), ConnectionRefusedError(61, "nope")],
    ids=["timeout", "reset", "refused"],
)
def test_a_transport_level_failure_arrives_as_one_error_the_adapter_can_record(
    error: Exception,
) -> None:
    with pytest.raises(ModelTransportError):
        _send(_transport(_refusing_opener(error)))


def test_a_status_other_than_200_is_refused_even_when_the_body_parses() -> None:
    with pytest.raises(ModelTransportError, match="204"):
        _send(_transport(_RecordingOpener(status=204)))


class _Handler(BaseHTTPRequestHandler):
    """A loopback endpoint: ``/messages`` answers, ``/redirect`` tries to send us elsewhere."""

    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # the method name BaseHTTPRequestHandler dispatches to
        self.server.paths.append(self.path)  # type: ignore[attr-defined]
        length = int(self.headers.get("content-length", "0"))
        self.rfile.read(length)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("location", "/somewhere-else")
            self.send_header("content-length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(GOOD_BODY)))
        self.end_headers()
        self.wfile.write(GOOD_BODY)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - base's own name
        """Silence: a passing test should not print an access log."""


@pytest.fixture
def loopback() -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.paths = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()


def _url(server: ThreadingHTTPServer, path: str) -> str:
    host, port = server.server_address[0], server.server_address[1]
    return f"http://{host!s}:{port}{path}"


def test_the_opener_really_speaks_http_to_a_server_on_this_machine(
    loopback: ThreadingHTTPServer,
) -> None:
    # The one test that exercises the socket itself. Everything above stubs the opener, so
    # without this the module's actual call to `urllib` would never run in CI.
    request = Request(_url(loopback, "/messages"), data=b"{}", method="POST")

    with open_request(request, 30.0) as reply:
        assert reply.status == 200
        assert json.loads(reply.read(len(GOOD_BODY) + 1))["usage"]["output_tokens"] == 7


def test_the_opener_refuses_a_redirect_rather_than_carrying_the_key_to_a_new_host(
    loopback: ThreadingHTTPServer,
) -> None:
    # A redirect is the hole an endpoint allowlist has if it is only checked once: urllib
    # follows one by default, and it copies the request's headers - the API key with them -
    # to whatever host the redirect names. The redirect is refused, and the proof is that the
    # target was never requested.
    request = Request(_url(loopback, "/redirect"), data=b"{}", method="POST")

    with pytest.raises(HTTPError) as caught:
        open_request(request, 30.0)

    assert caught.value.code == 302
    assert loopback.paths == ["/redirect"]  # type: ignore[attr-defined]
