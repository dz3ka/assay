"""The whole pipeline, in one command, against the repository Assay ships with.

    uv run --frozen python scripts/demo.py

Mine a suite, revalidate it, score it with the two oracles, render the report twice. Those are
SPEC §6's four commands in SPEC §6's order, and there is nothing to choose: no flags, no model,
no API key, no cost. Docker has to be running, because `assay run` puts every trial in a
container and the measurement phase in a second one with no network at all.

**What it runs against is a fixture, and :data:`FIXTURE_NOTICE` says so before anything else
happens.** The target is the synthetic repository in `tests/fixture_repo.py` - a history written
so that each of the gate's verdicts fires exactly once - and the two tasks it yields measure
this harness rather than any software. Mining a real repository is what
`docs/milestones/m1-yield-httpie.md` and `m2-yield-httpie-pinned.md` record: 743 commits of
httpie in M1, then in M2 a 40-commit pilot and the full 743 again under pinned images, zero
valid tasks every time. A demo that pointed at one of those would print an empty suite, which is
an honest finding about that repository and a useless first impression of this tool
([ADR-0050](../docs/adr/0050-the-demo-runs-against-the-fixture-and-says-so-first.md)). M5's
`m5-yield-public-repos.md` then mined three libraries selected in advance to fit what this miner
reaches and got 14 valid tasks out of 600 commits - a yield, but not one any tool has run, and
not a target whose numbers are known before the walk.

The notice states rather than asks. There is no prompt and no `--yes`, which is the choice
`HOST_EXECUTION_NOTICE` already made (ADR-0013): a confirmation nobody can answer breaks the
scripted use a demo is for, and what is being disclosed is a fact about the run rather than a
decision the reader is being asked to take.

It prints and it does not gate. `scripts/verify.py` is the single definition of green, and a
second script that could fail the build would be a second one. This returns the exit code of
whichever step stopped it, so a human can see what broke, and 0 when all five ran.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

from assay.cli.main import DEFAULT_TRIALS, ORACLE_ADAPTERS

ROOT = Path(__file__).resolve().parent.parent

# Where the two rendered documents land. Under `build/`, which `.gitignore` already covers, so
# a demo run leaves the working tree clean. Files are overwritten and nothing is deleted: the
# directory is the caller's once it exists, and a script that removed things under it would be
# reaching outside what it was asked to do.
ARTIFACTS = ROOT / "build" / "demo"
REPORT_TEXT = ARTIFACTS / "report.txt"
REPORT_HTML = ARTIFACTS / "report.html"

# Ceiling on one test run, well under `DEFAULT_TEST_TIMEOUT_S`, and the same number M3's oracle
# run used. The fixture's tests are assertions over a handful of pure functions and finish in
# well under a second, so anything past a minute here is a hang - and one commit *is* a hang on
# purpose: `slow_lookup`'s red test sleeps for an hour, so that `run_timed_out` has a witness.
# This constant is therefore most of the demo's mining time, and lowering it further would start
# discarding candidates the fixture expects to reach the gate.
DEMO_TEST_TIMEOUT_S = 120

# Printed to stderr before the first step, because a reader who sees the numbers first will
# read them as a measurement of something. Every claim in it is checkable from the tree: the
# yield is `tests.fixture_repo.EXPECTED_YIELD`, the three real-repository runs are the milestone
# documents named, and the adapters are the two `_adapter_refusal` exempts from the naive
# baseline requirement because neither is a tool.
FIXTURE_NOTICE = (
    "assay demo: this runs the whole pipeline against the synthetic fixture repository built "
    "by tests/fixture_repo.py - not against real software. Its history is written so that each "
    "of the miner's verdicts fires once: 11 commits examined, 2 valid tasks. Those two tasks "
    "measure this harness and say nothing about any tool. Mining a real repository is what "
    "docs/milestones/m1-yield-httpie.md and m2-yield-httpie-pinned.md record - 743 commits of "
    "httpie in M1, then a 40-commit pilot and the full 743 again in M2, and 0 valid tasks every "
    "time - and what m5-yield-public-repos.md records: 600 commits of three libraries picked in "
    "advance to fit this miner, 14 valid tasks, and none of them run by any tool since. Both "
    "adapters here are oracles - the recorded fix, and nothing at all - so no model is called, "
    "no key is read and nothing is spent. Docker must be running, and mining spends about two "
    "minutes on the one commit whose red test is written never to finish."
)


def demo_steps(*, repo: Path, suite: Path, results: Path) -> tuple[tuple[str, ...], ...]:
    """The five command lines the demo runs, in order, as data.

    Pure, and separated from :func:`main` so the argvs can be asserted against the parser that
    will receive them without building a fixture or starting a container
    (`tests/cli/test_demo_steps.py`). A flag renamed in `assay.cli.main` should fail a test
    rather than a demonstration.

    Every step is `<this interpreter> -m assay.cli.main`, the same resolution
    `scripts/verify.py` uses on its tools: it works from a plain `python scripts/demo.py` on
    both platforms without depending on PATH, on a shell, or on the console script having been
    installed.

    The adapter names are the two oracles' own and the trial count is the CLI's own default, so
    neither this file nor the report it produces can disagree with the module they come from -
    `--trials` in particular, because the n in every `pass^n` caption is read against it.
    """
    assay = (sys.executable, "-m", "assay.cli.main")
    adapters = tuple(word for name in sorted(ORACLE_ADAPTERS) for word in ("--adapter", name))
    return (
        (
            *assay,
            "mine",
            "--repo",
            str(repo),
            "--out",
            str(suite),
            "--test-timeout-s",
            str(DEMO_TEST_TIMEOUT_S),
        ),
        (*assay, "validate", "--suite", str(suite), "--repo", str(repo)),
        (
            *assay,
            "run",
            "--suite",
            str(suite),
            "--repo",
            str(repo),
            "--out",
            str(results),
            *adapters,
            "--trials",
            str(DEFAULT_TRIALS),
        ),
        (*assay, "report", "--results", str(results)),
        (*assay, "report", "--results", str(results), "--format", "html"),
    )


def run_step(argv: tuple[str, ...], destination: Path | None) -> int:
    """Run one step and return its exit code, saving its stdout when it has a destination.

    `assay report` writes its document to stdout and nothing else, so the document *is* that
    step's stdout and there is no `--out` flag to hand it a path (ADR-0049). The two report
    steps therefore have their stdout captured and written here, with `newline="\\n"` so the
    saved page is byte-identical on Windows and on Linux; the three steps that stream progress
    to stderr for minutes at a time inherit both streams instead, because a demo that showed
    nothing while it worked would be indistinguishable from a hung one.
    """
    if destination is None:
        return subprocess.run(argv, cwd=ROOT, check=False).returncode
    completed = subprocess.run(
        argv, cwd=ROOT, check=False, stdout=subprocess.PIPE, text=True, encoding="utf-8"
    )
    destination.write_text(completed.stdout, encoding="utf-8", newline="\n")
    return completed.returncode


def main() -> int:
    print(FIXTURE_NOTICE, file=sys.stderr, flush=True)

    # `tests/` is not an installed package and this file is not run through pytest, so the repo
    # root goes on the path rather than being assumed to be there. Imported inside the function
    # for the same reason: at module scope it would have to run before the path existed.
    sys.path.insert(0, str(ROOT))
    from tests.fixture_repo import build_fixture_repo

    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    # The fixture is built into a temporary directory and goes with the run: it is a git
    # repository with read-only objects, and `TemporaryDirectory` is the one cleanup in the
    # standard library that resets permissions rather than raising on them - the same reason
    # `run_mine` puts its worktrees here.
    with tempfile.TemporaryDirectory(prefix="assay-demo-") as scratch:
        workspace = Path(scratch)
        repo = build_fixture_repo(workspace)
        steps = demo_steps(
            repo=repo, suite=workspace / "suite.json", results=workspace / "results.json"
        )
        # Positional, and zipped strictly: a sixth step added without a decision about where
        # its output goes should stop the demo here rather than be run and discarded.
        destinations: tuple[Path | None, ...] = (None, None, None, REPORT_TEXT, REPORT_HTML)
        for argv, destination in zip(steps, destinations, strict=True):
            print(f"\n== {' '.join(argv)}", flush=True)
            code = run_step(argv, destination)
            if code != 0:
                print(
                    f"demo: FAILED at 'assay {argv[3]}' with exit code {code}",
                    file=sys.stderr,
                    flush=True,
                )
                return code

    print(f"\ndemo: wrote {REPORT_TEXT}", flush=True)
    print(f"demo: wrote {REPORT_HTML}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
