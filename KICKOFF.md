# Kickoff prompt for the Claude Code session

Paste this as the first message in a fresh Claude Code session, in an empty `assay/`
directory containing `SPEC.md` and `CLAUDE.md`.

---

Read `SPEC.md` and `CLAUDE.md` in full before writing anything.

Then implement **M0** only:

1. Scaffold a Python 3.12+ project managed with `uv`, `mypy --strict` and ruff wired into CI.
2. Define the task schema and the suite format (SPEC.md §3, §6). Suites are content-addressed
   and versioned from the start — a suite file carries its own hash and schema version.
3. Define the result and attempt schemas, including the cost and latency fields from
   SPEC.md §4.2. Version them too.
4. Implement the `Adapter` protocol exactly as narrow as SPEC.md §6 states, plus two adapters
   that need no model to run: a **ground-truth adapter** that replays the known-good diff, and
   a **null adapter** that returns an empty diff. Every later result is bracketed by these two.
5. Implement the CLI surface — `assay mine | validate | run | report` — with `mine`,
   `validate` and `run` stubbed to a clear "not implemented in M0" error, and `report`
   functional against a hand-written fixture result set.
6. Implement the three report renderers. The HTML renderer emits a single self-contained file:
   no external assets, no CDN. Include the "no winner when intervals overlap" code path now,
   with a test, even though no real statistics exist yet — stub the interval computation and
   assert the suppression behaviour.
7. Implement the redaction boundary (SPEC.md §5.4) with tests, before any real data path
   exists, so nothing downstream can bypass it.
8. Write ADRs 0001–0007 covering the seven decisions in SPEC.md §8.
9. README stating what Assay is, what it explicitly is not (not a leaderboard, not a
   SWE-bench competitor, numbers meaningful only for the repo they were mined from), and how
   it pairs with `dz3ka/portcall`.

**Exit criteria:** `assay report` renders a valid report in all three formats from a fixture
result set; the ground-truth and null adapters both satisfy the `Adapter` protocol and are
covered by tests; a hand-written task round-trips through the schema unchanged; the overlap
suppression path has a passing test; ADRs 0001–0007 are written; CI is green with
`mypy --strict`.

Do not implement mining, validation, the sandbox, or any real scoring in M0. Stop when the
exit criteria are met, summarise what landed, then wait.
