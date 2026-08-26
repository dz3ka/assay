"""The repository's single verify target.

CI runs exactly this, and so does a developer:

    uv run --frozen python scripts/verify.py

Keeping it one script is what stops local checks and CI checks from drifting apart.
Steps run in order and the first failure stops the run. Every step is invoked as
``<this interpreter> -m <tool>`` so it resolves inside the active environment on both
Windows and Linux without depending on PATH or on a shell.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lint", ("ruff", "check", ".")),
    ("format", ("ruff", "format", "--check", ".")),
    ("typecheck", ("mypy", "--strict", "src", "tests")),
    ("tests", ("pytest", "-q")),
)


def main() -> int:
    for name, argv in STEPS:
        command = (sys.executable, "-m", *argv)
        print(f"== {name}: {' '.join(argv)}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            print(
                f"verify: FAILED at step '{name}' ({' '.join(argv)}) "
                f"with exit code {completed.returncode}",
                file=sys.stderr,
                flush=True,
            )
            return completed.returncode
    print("verify: all steps passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
