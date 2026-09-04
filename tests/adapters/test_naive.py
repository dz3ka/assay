"""The naive baseline: one raw model call, and the floor every sophisticated tool is read against.

CLAUDE.md puts this adapter in every report, so what it does has to be exactly what it claims -
one call, no loop, no retry, nothing invented. These tests drive it on a fake transport, which
is the whole point of the seam (:mod:`assay.adapters.model`): the canned answer, the refusal an
unfunded account gives and the response too large to record are all reachable in CI without a
socket, and nothing in this file can reach one.

Three properties carry more weight than the rest. A refused call is ``Attempt.error`` and
therefore ``ERRORED`` - the trial is a failure of the wire, not a finding about the model - and
it costs no container, which is observable here as the runner factory never being asked for
one (ruling 6). The API key never reaches the attempt: the transport that holds one is handed
to the adapter, and the whole serialised attempt is searched for it. And an oversized response
is an error rather than an exception, because a trial that vanished into a traceback leaves a
hole in the denominator this project reports as its honest half.

The end-to-end tests drive :func:`assay.score.run_trial` over the same fakes ``tests/score`` uses,
spelled again rather than shared: they are each test module's own, and a fake that grew a feature
for one file's sake would quietly change what another file proves.
"""

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns
from uuid import uuid4

import pytest

# TestReport, TestRunner and TestStatus are imported under other names on purpose: pytest tries
# to collect any module-level name starting with "Test", and warns about these three otherwise.
from assay.adapters import (
    Adapter,
    ModelResponse,
    ModelTransport,
    ModelTransportError,
    NaiveBaselineAdapter,
)
from assay.adapters.naive import _strip_code_fence
from assay.mine import CommitRef
from assay.mine import TestReport as Report
from assay.mine import TestRunner as Runner
from assay.mine import TestStatus as Status
from assay.results import Attempt, Budget, Outcome
from assay.score import run_trial
from assay.suite import Task

_TARGET = "tests/test_widget.py::test_target"
_GUARD = "tests/test_widget.py::test_guard"

# The task's failing test file, and the text of it the prompt is required to carry: a model
# asked to fix a test it cannot see is being measured on a guess.
_TEST_FILE = "tests/test_widget.py"
_TEST_SOURCE = "def test_target():\n    assert widget() == 42\n\n\ndef test_guard():\n    pass\n"
_TEST_PATCH = f"--- a/{_TEST_FILE}\n+++ b/{_TEST_FILE}\n"

_PROMPT = "tests/test_widget.py::test_target fails at this commit. Change the source so it passes."

# A unified diff that touches source and no test path, which is what a well-behaved answer to
# the prompt above looks like (ADR-0037 refuses the other kind before it is applied).
_CANNED_DIFF = "--- a/widget.py\n+++ b/widget.py\n@@ -1,2 +1,2 @@\n-    return 41\n+    return 42\n"

# The same diff as the model habitually returns it: wrapped in a fence the system prompt asked
# twice for it not to use. ADR-0040's whole subject, and the only repair this adapter performs.
_FENCED_DIFF = f"```diff\n{_CANNED_DIFF}```\n"

# A diff that adds a fenced block to a markdown file - the answer a strip must not corrupt. Its
# last line *is* three backticks, behind the '+' every added line in a unified diff carries.
_DIFF_CONTAINING_A_FENCE = (
    "--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,4 @@\n intro\n+```python\n+print(42)\n+```\n"
)

_MODEL = "claude-sonnet-4-5"

# Held by the fake transport exactly as the real one holds it, and asserted never to appear in
# anything the adapter produces. The value is not a key and could not authenticate anything.
_API_KEY = "sk-ant-not-a-real-key"

# The trial these tests drive. Deliberately not 0: an adapter that stamped whatever the first
# trial's number happened to be would pass against 0 and only against 0 (ADR-0033).
_TRIAL_INDEX = 3

_TIMEOUT_S = 300

# The ceiling the tests hand the adapter. Both numbers are read by the adapter and passed to
# the transport, so they are deliberately unlike each other and unlike any default.
_MAX_OUTPUT_TOKENS = 2048
_MAX_WALL_CLOCK_S = 450

# The refusals ruling 6 puts on the first-class path, spelled the way
# :class:`assay.host.HttpModelTransport` spells them - a status and the endpoint's own sentence.
# 402 is the one M3 expects to meet: the account may simply have no funds.
_REFUSALS = (
    "the model endpoint refused the request: HTTP 401: invalid x-api-key",
    "the model endpoint refused the request: HTTP 402: your credit balance is too low",
    "the model endpoint refused the request: HTTP 429: rate limit exceeded",
)


@dataclass(frozen=True)
class _Sent:
    """One call the adapter made, recorded exactly as the transport received it."""

    model: str
    system: str
    user: str
    max_output_tokens: int
    timeout_s: int


class _CannedTransport:
    """A ``ModelTransport`` that answers with a prewritten response and records being asked.

    ``sent`` is a list rather than a single value so that "one call, no retry loop" is an
    assertion about its length: an adapter that quietly asked twice would be indistinguishable
    from one that asked once if the fake only kept the last call.
    """

    def __init__(self, response: ModelResponse) -> None:
        self._response = response
        self.sent: list[_Sent] = []

    def send(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_output_tokens: int,
        timeout_s: int,
    ) -> ModelResponse:
        self.sent.append(
            _Sent(
                model=model,
                system=system,
                user=user,
                max_output_tokens=max_output_tokens,
                timeout_s=timeout_s,
            )
        )
        return self._response


class _RefusingTransport:
    """A ``ModelTransport`` that refuses the way an unfunded, throttled or unauthorised one does.

    It holds an API key it never sends, exactly as the real transport holds one, so that the
    adapter under test is driven by an object that *has* the secret. The assertion that the key
    never reaches the attempt is then about the adapter rather than about an empty fake.
    """

    def __init__(self, *, api_key: str, message: str) -> None:
        self._api_key = api_key
        self._message = message
        self.calls = 0

    def send(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_output_tokens: int,
        timeout_s: int,
    ) -> ModelResponse:
        self.calls += 1
        raise ModelTransportError(self._message)


class _TrialHistory:
    """A ``History`` whose worktree is a plain directory and whose patches always apply.

    ``apply_patch`` writes the task's failing test file when it is handed the task's own test
    patch, because the adapter's prompt is built by *reading* that file out of the workspace -
    a fake that only recorded the patch would leave the adapter with nothing to read and the
    prompt assertions passing against an empty directory.

    Each checkout yields its own directory, the way ``GitHistory.worktree`` does, so the
    workspace the adapter worked in and the workspace that is measured stay distinguishable
    (ADR-0038). The walking members are never a trial's business, so they fail the test that
    reaches them.
    """

    def __init__(self, root: Path, *, test_source: str = _TEST_SOURCE) -> None:
        self.root = root
        self.applied: list[str] = []
        self.worktrees: list[Path] = []
        self._test_source = test_source

    def repo_url(self) -> str:
        return "https://example.invalid/widget.git"

    def commits(self, *, limit: int | None) -> Iterator[CommitRef]:
        raise AssertionError("a trial never walks history")

    def changed_paths(self, parent: str, commit: str) -> tuple[str, ...]:
        raise AssertionError("a trial never diffs commits")

    def diff(self, parent: str, commit: str, paths: Sequence[str]) -> str:
        raise AssertionError("a trial never diffs commits")

    @contextmanager
    def worktree(self, commit: str) -> Iterator[Path]:
        workspace = self.root / f"worktree-{uuid4().hex}"
        workspace.mkdir()
        self.worktrees.append(workspace)
        yield workspace

    def apply_patch(self, workspace: Path, patch: str) -> bool:
        self.applied.append(patch)
        if patch == _TEST_PATCH:
            _write_test_file(workspace, self._test_source)
        return True


class _ScriptedRunner:
    """A ``TestRunner`` that answers a fixed report and records each run it is asked for."""

    def __init__(self, report: Report) -> None:
        self._report = report
        self.runs: list[tuple[Path, tuple[str, ...], int]] = []

    def run(self, workspace: Path, selectors: Sequence[str], *, timeout_s: int) -> Report:
        self.runs.append((workspace, tuple(selectors), timeout_s))
        return self._report


class _RecordingFactory:
    """A ``RunnerFactory`` that records every workspace it is asked to equip.

    "No container was started" cannot be read off a verdict; it is this list staying empty.
    """

    def __init__(self, runner: Runner | None) -> None:
        self._runner = runner
        self.workspaces: list[Path] = []

    def __call__(self, workspace: Path) -> Runner | None:
        self.workspaces.append(workspace)
        return self._runner


def _write_test_file(workspace: Path, source: str) -> None:
    path = workspace / _TEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    # LF pinned: the adapter reads the file's bytes, so a platform that translated the
    # newlines on the way out would make this fixture disagree with itself on Windows.
    path.write_text(source, encoding="utf-8", newline="\n")


def _task() -> Task:
    return Task(
        schema_version=1,
        task_id="widget-fixture-000000000000",
        repo_url="https://example.invalid/widget.git",
        base_commit="0" * 40,
        test_files=(_TEST_FILE,),
        test_patch=_TEST_PATCH,
        ground_truth_patch="--- a/widget.py\n+++ b/widget.py\n",
        fail_to_pass=(_TARGET,),
        pass_to_pass=(_GUARD,),
        prompt=_PROMPT,
        metadata={},
    )


def _budget(*, max_output_tokens: int | None = _MAX_OUTPUT_TOKENS) -> Budget:
    return Budget(
        max_wall_clock_s=_MAX_WALL_CLOCK_S,
        max_input_tokens=None,
        max_output_tokens=max_output_tokens,
        max_tool_calls=None,
        max_usd=None,
    )


def _response(text: str = _CANNED_DIFF) -> ModelResponse:
    return ModelResponse(text=text, input_tokens=1234, output_tokens=56)


def _green() -> Report:
    return Report(
        statuses={_TARGET: Status.PASSED, _GUARD: Status.PASSED},
        uncollectable=(),
        exit_code=0,
        timed_out=False,
    )


def _workspace(tmp_path: Path, *, test_source: str = _TEST_SOURCE) -> Path:
    """A prepared workspace: the task's base state with its failing test file present."""
    _write_test_file(tmp_path, test_source)
    return tmp_path


def _adapter(transport: ModelTransport) -> NaiveBaselineAdapter:
    return NaiveBaselineAdapter(transport=transport, model=_MODEL)


def _canned_adapter() -> NaiveBaselineAdapter:
    """The adapter under a transport that answers ``_CANNED_DIFF`` and records the call."""
    return _adapter(_CannedTransport(_response()))


def _run(
    adapter: NaiveBaselineAdapter,
    workspace: Path,
    *,
    budget: Budget | None = None,
) -> Attempt:
    return adapter.run(
        _task(),
        workspace,
        budget if budget is not None else _budget(),
        trial_index=_TRIAL_INDEX,
    )


# Conformance is proved here, statically, by ``mypy --strict``; ``Adapter`` is deliberately not
# ``runtime_checkable``, and an ``isinstance`` check would only ask whether the names exist.
_: Adapter = NaiveBaselineAdapter(transport=_CannedTransport(_response()), model=_MODEL)


def test_the_diff_returned_is_the_models_own_answer(tmp_path: Path) -> None:
    # Verbatim but for one named repair (ADR-0040, below): what the model said is the
    # measurement, and an adapter that tidied the answer up would be measuring the tidying.
    attempt = _run(_canned_adapter(), _workspace(tmp_path))

    assert attempt.diff == _CANNED_DIFF
    assert attempt.error is None


def test_the_prompt_carries_the_task_and_the_text_of_the_failing_test(tmp_path: Path) -> None:
    transport = _CannedTransport(_response())

    _run(_adapter(transport), _workspace(tmp_path))

    assert len(transport.sent) == 1, "one raw model call, no agent loop and no retry"
    sent = transport.sent[0]
    assert _PROMPT in sent.user
    assert _TEST_SOURCE in sent.user
    assert _TEST_FILE in sent.user
    assert sent.model == _MODEL


def test_the_call_is_capped_by_the_budget_it_was_handed(tmp_path: Path) -> None:
    # The transport refuses to choose either number (:class:`assay.adapters.ModelTransport`),
    # so an uncapped call is only impossible if the adapter passes the trial's own ceiling on.
    transport = _CannedTransport(_response())

    _run(_adapter(transport), _workspace(tmp_path))

    assert transport.sent[0].max_output_tokens == _MAX_OUTPUT_TOKENS
    assert transport.sent[0].timeout_s == _MAX_WALL_CLOCK_S


def test_a_budget_that_caps_no_output_still_caps_the_call(tmp_path: Path) -> None:
    # ``max_output_tokens=None`` is a deliberate "no ceiling" (:class:`assay.results.Budget`),
    # and the transport still requires a number: a metered call with no cap on it is not a
    # measurement anyone can repeat, so the adapter supplies its own.
    transport = _CannedTransport(_response())

    _run(
        _adapter(transport),
        _workspace(tmp_path),
        budget=_budget(max_output_tokens=None),
    )

    assert transport.sent[0].max_output_tokens > 0


def test_a_test_file_too_large_for_the_cap_is_named_rather_than_smuggled(tmp_path: Path) -> None:
    # The prompt is the one thing that leaves this machine (SPEC §5.1), so its size is bounded
    # rather than whatever the repository happens to contain. What must not happen is a silent
    # truncation: the model is told the file was left out, so an answer written without it is
    # attributable to that rather than read as the model's best.
    huge = "# " + "x" * (1024 * 1024) + "\n"
    transport = _CannedTransport(_response())

    _run(
        _adapter(transport),
        _workspace(tmp_path, test_source=huge),
    )

    sent = transport.sent[0]
    # The module's cap, restated as a ceiling: a prompt that grew past it would fail here.
    assert len(sent.user.encode("utf-8")) <= 64 * 1024
    assert _PROMPT in sent.user
    assert huge not in sent.user
    assert _TEST_FILE in sent.user


def test_the_endpoints_own_token_counts_are_recorded(tmp_path: Path) -> None:
    attempt = _run(_canned_adapter(), _workspace(tmp_path))

    assert attempt.input_tokens == 1234
    assert attempt.output_tokens == 56
    # One call, no loop: nothing here uses a tool and nothing here retries.
    assert attempt.tool_calls == 0
    assert attempt.retries == 0


def test_the_cost_is_a_recorded_zero_written_to_six_decimal_places(tmp_path: Path) -> None:
    # M3 records tokens and not money (SPEC §7 puts cost accounting in M4), so the honest
    # figure is a written zero rather than a price this harness would have had to invent.
    attempt = _run(_canned_adapter(), _workspace(tmp_path))

    assert attempt.cost_usd == Decimal("0.000000")
    assert str(attempt.cost_usd) == "0.000000"


def test_the_wall_clock_is_measured_rather_than_declared(tmp_path: Path) -> None:
    before = monotonic_ns()

    attempt = _run(_canned_adapter(), _workspace(tmp_path))

    elapsed_ms = (monotonic_ns() - before) // 1_000_000
    assert 0 <= attempt.wall_clock_ms <= elapsed_ms


def test_the_attempt_names_the_tool_the_task_and_the_trial(tmp_path: Path) -> None:
    adapter = _canned_adapter()

    attempt = _run(adapter, _workspace(tmp_path))

    assert attempt.adapter_name == adapter.name == "naive"
    assert attempt.adapter_version == adapter.version
    # The model is what this adapter *is*, so a report that could not say which one answered
    # could not say which tool it measured.
    assert _MODEL in attempt.adapter_version
    assert attempt.task_id == _task().task_id
    assert attempt.trial_index == _TRIAL_INDEX
    assert attempt.schema_version == 1


def test_the_workspace_is_read_and_never_written(tmp_path: Path) -> None:
    # M3 runs the tool inside a container, and the diff is applied by the trial in a second
    # workspace (ADR-0038). The adapter's own reach into the checkout is a read.
    workspace = _workspace(tmp_path)
    before = sorted(path.name for path in workspace.rglob("*"))

    _run(_canned_adapter(), workspace)

    assert sorted(path.name for path in workspace.rglob("*")) == before


def test_a_canned_diff_scores_passed_end_to_end(tmp_path: Path) -> None:
    history = _TrialHistory(tmp_path)
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_canned_adapter(),
        budget=_budget(),
        history=history,
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.PASSED
    assert result.attempt.diff == _CANNED_DIFF
    assert result.adapter_name == "naive"
    # The diff the model wrote was applied in the measured workspace, not the adapter's.
    assert history.applied == [_TEST_PATCH, _TEST_PATCH, _CANNED_DIFF]


@pytest.mark.parametrize("message", _REFUSALS)
def test_a_refused_call_errors_the_trial_and_starts_no_container(
    tmp_path: Path, message: str
) -> None:
    # Ruling 6's first-class path. An account with no funds, a bad key and a rate limit are
    # failures of the wire, and a failure of the wire is not a finding about the model - so the
    # trial is ERRORED, nothing is measured, and no container is ever built for it.
    transport = _RefusingTransport(api_key=_API_KEY, message=message)
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_adapter(transport),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.ERRORED
    assert result.attempt.error == message
    assert result.attempt.diff == ""
    assert transport.calls == 1
    assert factory.workspaces == []


def test_a_refusal_never_carries_the_api_key(tmp_path: Path) -> None:
    # The transport's own guarantee is proved in ``tests/host/test_network_egress.py``; this is
    # the other end of it. The attempt is written to a result set and printed by the CLI, so
    # the whole serialised document is searched rather than only ``error``.
    transport = _RefusingTransport(api_key=_API_KEY, message=_REFUSALS[1])

    attempt = _run(_adapter(transport), _workspace(tmp_path))

    assert attempt.error is not None
    assert _API_KEY not in json.dumps(attempt.model_dump(mode="json"))


def test_a_response_too_large_to_record_is_an_error_not_a_crash(tmp_path: Path) -> None:
    # A diff is recorded in a result set and rendered into a report, so an answer that is not
    # one - a model that streamed a novel, an endpoint that ignored ``max_tokens`` - is refused
    # here rather than allowed to become a megabyte of "diff" in a document somebody reads.
    transport = _CannedTransport(_response(text="x" * (4 * 1024 * 1024)))
    factory = _RecordingFactory(_ScriptedRunner(_green()))

    result = run_trial(
        task=_task(),
        adapter=_adapter(transport),
        budget=_budget(),
        history=_TrialHistory(tmp_path),
        runner_for=factory,
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.ERRORED
    assert result.attempt.error is not None
    assert "too large" in result.attempt.error
    assert result.attempt.diff == ""
    assert factory.workspaces == []


def test_the_attempt_round_trips_through_its_own_schema(tmp_path: Path) -> None:
    attempt = _run(_canned_adapter(), _workspace(tmp_path))

    assert Attempt.model_validate(attempt.model_dump(mode="json")) == attempt


def test_a_workspace_missing_a_declared_test_file_errors_rather_than_crashes(
    tmp_path: Path,
) -> None:
    # A prepared workspace holds every file the task declares, so a missing one is the harness
    # or the suite being broken rather than the model - and it costs one errored trial instead
    # of an exception out of the middle of a run. The call is never made.
    transport = _CannedTransport(_response())

    attempt = _run(_adapter(transport), tmp_path)

    assert attempt.error is not None
    assert attempt.diff == ""
    assert transport.sent == []


# ADR-0040: the one repair. Driven as a pure function over the reply string, which is what it
# is - no transport, no workspace - and then once through the adapter and once end to end, so
# that "the repair reaches the measured workspace" is asserted and not assumed.


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        # The common case, and the one the live run is expected to meet.
        (_FENCED_DIFF, _CANNED_DIFF),
        # No info string, which is just as common.
        (f"```\n{_CANNED_DIFF}```\n", _CANNED_DIFF),
        # Tildes are a fence too, and their info string may hold a backtick.
        (f"~~~diff\n{_CANNED_DIFF}~~~\n", _CANNED_DIFF),
        # Longer runs, and CommonMark's rule that a closer may be longer than its opener.
        (f"````diff\n{_CANNED_DIFF}````\n", _CANNED_DIFF),
        (f"```diff\n{_CANNED_DIFF}`````\n", _CANNED_DIFF),
        # Blank lines around the fence are the model's formatting, not the answer.
        (f"\n```diff\n{_CANNED_DIFF}```\n\n", _CANNED_DIFF),
        # Trailing spaces after either marker: still a fence, still the same diff.
        (f"```diff  \n{_CANNED_DIFF}```   \n", _CANNED_DIFF),
        # The sharpest one: a fenced answer whose own content ends in a fence. The outer pair
        # goes, the diff's '+```' line stays, and the result is the patch byte for byte.
        (
            f"```diff\n{_DIFF_CONTAINING_A_FENCE}```\n",
            _DIFF_CONTAINING_A_FENCE,
        ),
        # Line endings are not the adapter's business: the kept text is sliced, not rebuilt.
        ("```diff\r\n--- a/w.py\r\n+++ b/w.py\r\n```\r\n", "--- a/w.py\r\n+++ b/w.py\r\n"),
        # A reply that is nothing but a fence pair is the empty diff it always was: it applies,
        # changes nothing, and the tests stay red. Not an error - the model answered, badly.
        ("```diff\n```\n", ""),
    ],
)
def test_an_enclosing_fence_is_removed_and_nothing_else_is(reply: str, expected: str) -> None:
    assert _strip_code_fence(reply) == expected


@pytest.mark.parametrize(
    "reply",
    [
        # No fence at all: the overwhelmingly common answer, and it must come back identical.
        _CANNED_DIFF,
        # A diff whose own last line is three backticks. Every line inside a unified diff
        # carries a '+', '-' or space, which is exactly what stops this being read as a fence.
        _DIFF_CONTAINING_A_FENCE,
        # Half a pair is not a pair. An opener with no closer is a reply the endpoint cut off,
        # and a closer with no opener is not a fence anyone opened - guessing at either is the
        # repair overreaching, so both are left as the model sent them.
        f"```diff\n{_CANNED_DIFF}",
        f"{_CANNED_DIFF}```\n",
        # A closer shorter than its opener does not close it (CommonMark).
        f"````diff\n{_CANNED_DIFF}```\n",
        # Prose then a fenced block. This is not an extractor: a reply carrying commentary is a
        # reply that ignored the system prompt, and the report should record that it did.
        f"Here is the patch:\n\n```diff\n{_CANNED_DIFF}```\n",
        # One line cannot be both halves of the pair.
        "```\n",
        "```diff\n",
        # Under three markers is not a fence.
        f"``\n{_CANNED_DIFF}``\n",
        # A backtick fence's info string may not contain a backtick, so this opens nothing.
        f"```a`b\n{_CANNED_DIFF}```\n",
        # A closing marker carries no info string, so this closes nothing.
        f"```diff\n{_CANNED_DIFF}``` done\n",
        # Degenerate input reaches the adapter as readily as anything else.
        "",
        "\n\n",
    ],
)
def test_a_reply_that_is_not_a_fenced_block_comes_back_unchanged(reply: str) -> None:
    assert _strip_code_fence(reply) == reply


def test_a_fenced_answer_is_recorded_as_the_diff_inside_it(tmp_path: Path) -> None:
    # Through the adapter, because this is the failure the repair exists for: without it, a
    # model that fenced its answer scores FAILED for a formatting habit and M3's headline
    # finding about the naive baseline is an artefact of markdown.
    transport = _CannedTransport(_response(text=_FENCED_DIFF))

    attempt = _run(_adapter(transport), _workspace(tmp_path))

    assert attempt.diff == _CANNED_DIFF
    # A repair, not a rescue: the trial is scored on the diff like any other, and nothing about
    # the answer having been fenced is recorded as an error.
    assert attempt.error is None


def test_the_unfenced_diff_is_what_reaches_the_measured_workspace(tmp_path: Path) -> None:
    # The other end of the repair. The diff is applied in a second checkout (ADR-0038), so what
    # matters is which text got there - a strip that stopped at the attempt would prove nothing.
    history = _TrialHistory(tmp_path)

    result = run_trial(
        task=_task(),
        adapter=_adapter(_CannedTransport(_response(text=_FENCED_DIFF))),
        budget=_budget(),
        history=history,
        runner_for=_RecordingFactory(_ScriptedRunner(_green())),
        timeout_s=_TIMEOUT_S,
        trial_index=_TRIAL_INDEX,
    )

    assert result.outcome is Outcome.PASSED
    assert history.applied == [_TEST_PATCH, _TEST_PATCH, _CANNED_DIFF]
