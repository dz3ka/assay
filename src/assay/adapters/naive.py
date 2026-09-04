"""The naive baseline: one raw model call, no agent loop - the floor of every report.

CLAUDE.md requires this adapter in every report, and the reason is that most benchmark
write-ups omit the baseline that would embarrass the sophisticated tools. One call with the
task's own prompt and the text of the failing tests is the cheapest thing that could possibly
work; if an agentic tool cannot beat it, that is the finding, and a report without this row
cannot state that finding at all.

It is the first adapter that reaches off this machine, and it does so through an injected
:class:`assay.adapters.model.ModelTransport` and nothing else. Nothing here opens a socket -
``host/model_api.py`` is the only module in ``src/assay`` that may (ADR-0036), and it is bound
to this adapter in :mod:`assay.cli.main` - so every branch below, including the refusal an
unfunded account gives, is reachable on a fake in CI.

It repairs exactly one thing, named and bounded: a markdown code fence wrapped around the whole
reply is removed before the text becomes ``Attempt.diff`` (ADR-0040). That is a repair of the
tool's output by the harness, so it is spelled in one pure function, tested on its own, and
recorded in a decision record rather than left as a convenience nobody reads.

Three things it deliberately does not do. It does not retry: n trials per task is how this
harness measures variance (SPEC §4), and a hidden retry inside one of them would flatter the
tool under test. It does not tidy, reformat or otherwise improve the answer: apart from the one
fence above, what came back is what is recorded, because an adapter that repaired the output
would be measuring the repair. And it does not judge the answer - a reply that is not a diff at
all is recorded as the diff it is not, fails to apply, and scores ``FAILED`` on the evidence
like any other wrong answer.
"""

from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from time import monotonic_ns

from assay.adapters.model import ModelTransport, ModelTransportError
from assay.results import Attempt, Budget
from assay.suite import Task

_NS_PER_MS = 1_000_000

# The twin of the constants in the M0 oracles, copied rather than shared for the reason
# :mod:`assay.adapters.null` gives: no adapter owns another's internals.
_NO_COST = Decimal("0.000000")
_NO_DIFF = ""

# The harness's own version, because the code in this file is half of what is being measured.
_HARNESS_VERSION = "0.1.0"

# The most prompt this adapter will send. The prompt is the one thing that leaves this machine
# (SPEC §5.1) - it carries the private repository's own test source - so its size is a decision
# taken here rather than whatever the repository happens to contain: a single generated fixture
# file would otherwise ship a megabyte of somebody's source to an endpoint. 64 KiB is several
# times the largest hand-written test file in a normal repository and roughly 20k tokens, well
# inside any current model's context, so the cap binds on the pathological case and on nothing
# else. A file that does not fit is named in the prompt rather than truncated into it: half a
# test file is a worse question than a stated absence, and a model that answered without seeing
# a file should be able to say so.
_MAX_PROMPT_BYTES = 64 * 1024

# The most answer this adapter will record as a diff. The text becomes ``Attempt.diff``, which
# is written into a result set and rendered into a report, so an endpoint that ignored
# ``max_tokens`` must not be able to put a megabyte of prose in a document somebody reads. Four
# times the prompt cap: an answer larger than the entire question is not a patch, and refusing
# it is a recorded ``Attempt.error`` rather than a crash.
_MAX_DIFF_BYTES = 256 * 1024

# The ceiling used when the trial's budget declines to set one. The transport refuses to choose
# a number of its own (:class:`assay.adapters.model.ModelTransport`) because an uncapped call to
# a metered endpoint is not a measurement anyone can repeat, so a ``None`` here has to become a
# number somewhere, and it becomes one at the adapter that knows what it is asking for: a
# unified diff, which is thousands of tokens and not tens of thousands.
_DEFAULT_MAX_OUTPUT_TOKENS = 4096

# What the model is asked to be. It is told about the test-path rule (ADR-0037) rather than
# silently refused by it: a harness that scores a tool ``FAILED`` for breaking a rule it never
# stated is measuring the harness's own reticence.
_SYSTEM_PROMPT = (
    "You are fixing a failing test in a software repository. Reply with a single unified diff "
    "and nothing else: no explanation, no commentary, no markdown code fence. The diff is "
    "applied at the repository root with 'git apply', so give every file an a/ and b/ path "
    "prefix. Change source files only - a diff that touches a test file is refused, because "
    "the tests are the measurement."
)

_FILES_HEADER = "The failing test files, as they stand in the repository:"

# What counts as a code fence, kept to the part of CommonMark a model actually emits: a run of
# at least three backticks or tildes. The pair is the shape - an opener alone is a truncated
# reply and not a fence this adapter will take apart (ADR-0040).
_FENCE_MARKERS = ("`", "~")
_MIN_FENCE_RUN = 3


class NaiveBaselineAdapter:
    """One model call per trial: the task's prompt, the failing tests, and whatever comes back."""

    name: str = "naive"
    # The model *is* this tool. A report that could not say which one answered could not say
    # which tool it measured, and nothing else in an attempt records the model - so it is
    # written into the version, beside the version of the harness code that framed the call.
    version: str

    def __init__(self, *, transport: ModelTransport, model: str) -> None:
        self._transport = transport
        self._model = model
        self.version = f"{_HARNESS_VERSION}+{model}"

    def run(self, task: Task, workspace: Path, budget: Budget, *, trial_index: int) -> Attempt:
        """Workspace is a repo checked out at the task's base state, tests already
        failing. Return the diff produced, plus token and latency accounting.

        ``workspace`` is read and never written: the diff this returns is applied by the trial,
        in a second checkout the tool never touched (ADR-0038). ``budget`` supplies both
        ceilings the transport requires - its output-token cap, and its wall clock as the
        socket timeout - so a trial cannot outlive the limit it was given.

        Every failure of the seam lands in ``error``: the endpoint refusing an unfunded account
        (ruling 6), a timeout, a payload that is not the declared shape, an answer too large to
        record, or a workspace whose test files cannot be read. All of them are a trial that
        ``ERRORED`` rather than a tool that failed, and :func:`assay.score.run_trial` starts no
        container for one. Nothing else is caught, and nothing raises past here.
        """
        started_ns = monotonic_ns()
        try:
            user = _prompt(task, workspace)
        except OSError as error:
            # The prepared workspace should hold every file the task declares, so this is a
            # broken suite or a broken checkout - the harness failing, which is why it is
            # recorded rather than raised: one trial errors and the run carries on.
            return self._attempt(
                task,
                trial_index=trial_index,
                started_ns=started_ns,
                diff=_NO_DIFF,
                input_tokens=0,
                output_tokens=0,
                error=f"the task's test files could not be read from the workspace: {error}",
            )

        max_output_tokens = (
            _DEFAULT_MAX_OUTPUT_TOKENS
            if budget.max_output_tokens is None
            else budget.max_output_tokens
        )
        try:
            response = self._transport.send(
                model=self._model,
                system=_SYSTEM_PROMPT,
                user=user,
                max_output_tokens=max_output_tokens,
                timeout_s=budget.max_wall_clock_s,
            )
        except ModelTransportError as error:
            # Recorded exactly as the transport worded it, which never carries the API key
            # (:class:`assay.adapters.model.ModelTransportError`). No tokens: nothing arrived.
            return self._attempt(
                task,
                trial_index=trial_index,
                started_ns=started_ns,
                diff=_NO_DIFF,
                input_tokens=0,
                output_tokens=0,
                error=str(error),
            )

        # The call happened and was billed, so its tokens are recorded whichever way this ends.
        if len(response.text.encode("utf-8")) > _MAX_DIFF_BYTES:
            return self._attempt(
                task,
                trial_index=trial_index,
                started_ns=started_ns,
                diff=_NO_DIFF,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                error=(
                    f"the model's answer is too large to record as a diff: over "
                    f"{_MAX_DIFF_BYTES} bytes"
                ),
            )
        # The size is read off what the endpoint sent, before the one repair below: the cap is
        # a ceiling on what is recorded, and the fence can only make the text shorter.
        return self._attempt(
            task,
            trial_index=trial_index,
            started_ns=started_ns,
            diff=_strip_code_fence(response.text),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            error=None,
        )

    def _attempt(
        self,
        task: Task,
        *,
        trial_index: int,
        started_ns: int,
        diff: str,
        input_tokens: int,
        output_tokens: int,
        error: str | None,
    ) -> Attempt:
        """The one place this adapter builds an attempt, so every exit records the same fields."""
        return Attempt(
            schema_version=1,
            adapter_name=self.name,
            adapter_version=self.version,
            task_id=task.task_id,
            trial_index=trial_index,
            diff=diff,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # Measured around the call, so a report's latency column is a latency something
            # timed. Floor division: sub-millisecond work reports the 0 ms it took.
            wall_clock_ms=(monotonic_ns() - started_ns) // _NS_PER_MS,
            # One raw model call, no agent loop and no retry - so both of these are zero by
            # construction rather than by omission, and a non-zero one would be a bug.
            tool_calls=0,
            retries=0,
            # M3 records tokens and not money. SPEC §7 puts cost accounting in M4, and pricing
            # tokens here would mean this harness inventing a rate card and presenting the
            # product as a measurement; ADR-0010's trigger for that work has not fired.
            cost_usd=_NO_COST,
            error=error,
        )


def _prompt(task: Task, workspace: Path) -> str:
    """The task's own prompt, then as much of the failing test text as the cap allows.

    Assembled file by file against the real encoded length, so the cap is a property of the
    string that is sent rather than of an estimate of it. A file that does not fit is left out
    and named, and the note that names the omissions is reserved for at its worst case - every
    declared file missing - so appending it can never be the thing that breaks the cap.

    Raises:
        OSError: if a declared test file cannot be read out of the prepared workspace.
    """
    prompt = f"{task.prompt}\n\n{_FILES_HEADER}"
    # Reserved up front. ``task.test_files`` is the worst case: the note can name no more.
    reserved = len(f"\n\n{_omission_note(task.test_files)}".encode())
    omitted: list[str] = []
    for path in task.test_files:
        # Repo-relative and free of '..' by the suite schema's own validator, so this joins to
        # somewhere inside the workspace and the adapter needs no rule of its own about it.
        candidate = f"{prompt}\n\n{_file_section(path, workspace)}"
        if len(candidate.encode()) + reserved > _MAX_PROMPT_BYTES:
            omitted.append(path)
            continue
        prompt = candidate
    if omitted:
        prompt = f"{prompt}\n\n{_omission_note(omitted)}"
    return prompt


def _file_section(path: str, workspace: Path) -> str:
    """One test file, labelled with the repo-relative path a diff would have to name.

    Decoded with replacement rather than strictly: a test file that is not valid UTF-8 is a
    strange thing to send a model and a stranger thing to fail a trial over, and the
    replacement characters are visible in the prompt for what they are.
    """
    text = (workspace / path).read_bytes().decode("utf-8", errors="replace")
    return f"===== {path} =====\n{text}"


def _omission_note(paths: Sequence[str]) -> str:
    """What the model is told about the files it is not being shown."""
    return (
        "These failing test files are not shown, because the prompt is size-capped: "
        f"{', '.join(paths)}. Answer from what is above."
    )


def _strip_code_fence(reply: str) -> str:
    """The reply with one enclosing markdown code fence removed, or the reply unchanged.

    The one repair this harness performs on a tool's output (ADR-0040). The system prompt asks
    for a bare unified diff and says so twice; a model that wraps the answer in ``` anyway has
    answered the question, and scoring that ``FAILED`` would report a formatting habit as a
    capability. The fence is removed and nothing else is: no whitespace normalisation, no line
    endings rewritten, no prose discarded. The kept text is sliced out of the reply's own lines
    rather than rebuilt from them, so what a diff carried through is byte-for-byte what it
    carried in.

    The shape is a *pair*: the first non-blank line opens a fence and the last non-blank line
    closes it with the same character, at least as long, and nothing else on it. An opener with
    no closer is a reply that was cut off rather than a fence, and is left alone; so is prose
    followed by a fenced block, because this is not an extractor - a reply that says anything
    besides the diff is a reply the model got wrong, and the report should say so. A reply that
    is nothing but an empty fence pair strips to the empty diff it always was: it applies
    cleanly, changes nothing, and the tests stay red.
    """
    lines = reply.splitlines(keepends=True)
    bounds = _content_bounds(lines)
    if bounds is None:
        return reply
    opening, closing = bounds
    if opening == closing:
        # One line cannot be both halves of a pair, whatever it says.
        return reply
    fence = _fence_opened_by(lines[opening])
    if fence is None or not _closes(lines[closing], fence):
        return reply
    return "".join(lines[opening + 1 : closing])


def _content_bounds(lines: Sequence[str]) -> tuple[int, int] | None:
    """The first and last lines that are not blank, or ``None`` when every line is.

    Blank lines around a fence are the model's formatting, not part of the answer, so the pair
    is looked for outside them - a trailing newline after the closing fence is the common case
    and must not be the reason a fenced diff is left fenced.
    """
    filled = [index for index, line in enumerate(lines) if line.strip()]
    if not filled:
        return None
    return filled[0], filled[-1]


def _fence_opened_by(line: str) -> str | None:
    """The fence run this line opens, or ``None`` if it opens none.

    The run must start the line: an indented or prefixed one is a diff's own content - every
    line inside a unified diff carries a ``+``, ``-`` or space - and this function saying no to
    it is what keeps a patch that adds a fenced block to a markdown file intact. What follows
    the run is CommonMark's info string (``diff``, ``patch``, nothing), which for a backtick
    fence may not itself contain a backtick.
    """
    text = line.rstrip()
    marker = text[:1]
    if marker not in _FENCE_MARKERS:
        return None
    run = len(text) - len(text.lstrip(marker))
    if run < _MIN_FENCE_RUN:
        return None
    if marker == "`" and "`" in text[run:]:
        return None
    return marker * run


def _closes(line: str, fence: str) -> bool:
    """Whether this line closes ``fence``: the same marker, no shorter, and nothing else on it.

    CommonMark's rule, and it is the strict half of the pair on purpose. A closing fence carries
    no info string, so a line with anything else on it is text that happens to begin with
    backticks rather than the end of the block.
    """
    text = line.rstrip()
    return text.startswith(fence) and text.lstrip(fence[0]) == ""
