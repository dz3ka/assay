# M5 public release: one command, a redacted report, and the oracles' bracket

**Run date:** 2026-09-07 · **Assay at:** M5 working tree (on `98e6ea8`) · **Milestone:** M5, SPEC
§7's public-release exit criteria

This record answers one question: **does a stranger with a clone and a running Docker daemon get
from nothing to a rendered, redacted report with one command, no API key, no network call and no
decision to make?** It answers yes, and it publishes the report that came out.

**Before any number appears below: no real tool has been scored, here or anywhere else in this
repository.** The two adapters that ran are the two oracles — `ground-truth`, which replays the
recorded fix, and `null`, which does nothing — and they bracket every real result precisely by not
being one. No model was called, no API key was read and nothing was spent. Read §2 before quoting
anything from §3; the ordering of those two sections is a decision with a record behind it
([ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md)), not a stylistic choice.

## 1. What was built, and what was run

Six decisions landed, each with its record — ADR-0052 because a defect surfaced while the release
was being written up, and §3 has it:

| | |
|---|---|
| [ADR-0049](../adr/0049-the-report-states-its-redaction-and-carries-no-clock.md) | The published report states its redaction, and carries no timestamp, generator string or schema field |
| [ADR-0050](../adr/0050-the-demo-runs-against-the-fixture-and-says-so-first.md) | The one-command demo runs against the synthetic fixture repository, and says so before the first step |
| [ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md) | M5's published results are the two oracles, and the record says what produced them before it prints them |
| [ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md) | A repository with no remote names itself by its root commit, so the suite hash stops moving with the directory it was mined in |
| [ADR-0053](../adr/0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md) | The public-repo yield is measured with the shipped `assay mine` on the host path, and the pinned-image miner stays unwired |
| [ADR-0054](../adr/0054-a-premise-of-adr-0050-is-overtaken-and-the-decision-stands.md) | A premise of ADR-0050 is overtaken by that yield, and the demo stays on the fixture |

What was run is the demo, end to end, three times — one warm-up, one recorded below, and one
re-run to check that the recorded figures reproduce:

```
uv run --frozen python scripts/demo.py
```

That is one command with no flags, and it expands to SPEC §6's four commands in SPEC §6's order —
`mine`, `validate`, `run`, then `report` twice, once as text and once as HTML. The five argv lines
it builds are a pure function (`scripts/demo.py::demo_steps`) so that `tests/cli/test_demo_steps.py`
can put every one of them through the real parser without Docker; the adapter names come from
`ORACLE_ADAPTERS` and the trial count from `DEFAULT_TRIALS`, so neither this document nor the demo
can disagree with the module they are read against.

The demo was run three further times after the suite-hash fix recorded in §3, from three different
parent directories; that is where the suite hash below comes from. Every other figure in this
document is the recorded run's.

| | |
|---|---|
| Target | SPEC §9's fixture repository, built by `tests/fixture_repo.py::build_fixture_repo` into a temporary directory |
| Suite hash | `sha256:bfa6e5bc2efe5d2966a937eabe5d51ee8999fefc0b4445aa1184375efd011344` — **it reproduces across runs, and the earlier hash that did not is in §3** |
| Docker | server 29.7.2, one image per task, measurement phase `--network none` |
| Adapters | `ground-truth` and `null`, both oracles; no model, no key, no spend |
| Trials | 2 tasks × 2 adapters × 5 trials = **20**, all recorded, exit `0` |
| Wall clock | **206 s**, on a **warm** daemon (see below) |
| Artefacts | `build/demo/report.txt` (2223 bytes) and `build/demo/report.html` (5301 bytes), both gitignored |

### The wall clock is a warm number, and no cold number was measured

206 seconds is a **warm** run and must not be quoted as a first-run figure. Two things establish
that, and both are checkable with `docker images assay-task` taken either side of the run:

- The two task images the run needs were already in the local cache before it started, carrying
  build timestamps of `2026-09-03 11:10:51` and `2026-09-03 11:11:02`. No new tag appeared. The
  two tags' image IDs did change across the run — the build ran and was served from the layer
  cache rather than resolving and installing a toolchain from scratch.
- An immediately preceding identical run of the same script took **213 s**, within seven seconds
  of the recorded one, which is what a cache that is already hot looks like.

**A cold run — no `assay-task` images, no layer cache, and a daemon that has to pull a base image
— was not measured in this milestone, and no number for it is published here.** It is materially
slower, and how much slower is unknown rather than estimated.

Most of the 206 s is one commit. `slow_lookup`'s red test sleeps for an hour so that
`run_timed_out` has a witness in the fixture, and `--test-timeout-s 120` is therefore paid in full
on every mine.

### The yield, stated as a yield

**11 single-parent commits examined → 2 valid tasks.** 7 candidates reached the gate, 0
unprovisioned; merges and the root commit are not examined at all. Rejected: `no_test_changes` 1,
`no_source_changes` 2, `patch_did_not_apply` 1, `already_green` 1, `still_red` 1,
`no_tests_executed` 1, `unstable_green` 1, `run_timed_out` 1. Then `2 of 2 tasks revalidate`.

That reproduces `tests/fixture_repo.EXPECTED_YIELD` exactly, which is the whole point of the
fixture: every rejection reason fires once, and the red→green gate is demonstrated on both sides.
It is also, precisely, a statement about this harness — see §2.

## 2. What this milestone does NOT establish

**No model was called during M5. Not once, on any path, by any adapter, on any machine. No API key
was set. No token was bought. Nothing here establishes anything at all about any tool.** M3 said
this, M4 said it and changed not one word of M3's version, and M5 is the third consecutive
milestone to say it. Saying it a third time is the point rather than a repetition to be trimmed.

**SPEC §7 grades M5 on "published results for two tools with intervals", and the two adapters that
ran are not tools.** `ground-truth` replays the recorded fix and cannot fail; `null` does nothing
and cannot pass. CLAUDE.md's own words for the pair are that they "bracket every real result" — and
a bracket is defined by not being a member of the set it bounds. Two adapters that between them can
only produce 1.000 and 0.000 are not a comparison, however many confidence intervals are printed
beside them. The criterion is met in letter and short in substance, and
[ADR-0051](../adr/0051-m5s-two-tools-are-two-oracles.md) records both halves and why the shortfall
is written down instead of being allowed to tick quietly.

**The demo's target is synthetic.** It mines a repository that `tests/fixture_repo.py` writes on
the spot, whose history is authored so each of the miner's verdicts fires exactly once. The yield
in §1 is therefore a *specification* being confirmed, not an observation about software.
[ADR-0050](../adr/0050-the-demo-runs-against-the-fixture-and-says-so-first.md) records why, and one
of its premises has since been overtaken by this same milestone. When it was written, every attempt
against real software was on the record at zero
([`m1-yield-httpie.md`](m1-yield-httpie.md): 743 commits → 0 valid tasks;
[`m2-yield-httpie-pinned.md`](m2-yield-httpie-pinned.md): a 40-commit pilot and then the full 743
again under pinned images, still 0). M5 then mined three public repositories with the shipped
command, and **that third answer is not zero: 600 commits examined → 14 valid tasks** ([`m5-yield-public-repos.md`](m5-yield-public-repos.md)).

**That is a reach limit sidestepped by advance selection, not a reach limit lifted.** The three
repositories were chosen under a rule — small single-package pytest-based libraries with pinned dev
dependencies and no service dependencies — that was written down, with the repositories and the
`--limit 200`, before the first clone existed, and the rule selects for the narrow shape this miner
could already reach. ADR-0019's limit is unrepealed: a repository whose test dependencies are
unpinned still cannot be mined this way, and nothing in M5 was measured that bears on it. Nor does
the result move what the demo points at. Those 14 tasks passed the red→green gate once, at mining
time, and have been neither re-validated nor scored by anything, while the fixture remains the only
target in the project whose yield is a specification rather than an observation.

Specifically, nothing in this repository yet demonstrates:

- that the naive baseline (`src/assay/adapters/naive.py`) can solve any task, on any repository;
- that the agentic Claude Code adapter (`src/assay/adapters/agentic.py`) can solve any task;
- that either beats the other, or that the agentic tool beats one raw model call;
- that the in-container `api.anthropic.com` allowlist works against the real endpoint;
- what a trial costs in tokens or dollars — every adapter that ran records zero of both;
- that a suite mined out of a real repository has ever been *run* — M5's 14 tasks
  ([`m5-yield-public-repos.md`](m5-yield-public-repos.md)) passed the gate at mining time and have
  not been re-validated or scored since;
- that Assay can mine a repository outside that document's stated selection rule, which was fixed
  in advance to sit inside the reach ADR-0019 measured.

The two real adapters remain built, unit-tested against fakes, container-tested, and **never once
measured live**. [ADR-0042](../adr/0042-the-readme-withdraws-the-promise-of-a-live-run.md) still
holds: **no milestone owns the live run**, and this document supplies no date for one.

## 3. The result

Everything below was produced by the two oracles. No tool has been scored. With that said, this is
the first three of the five sections of the report the demo wrote to `build/demo/report.txt` — the
header, Tools and Comparisons — with two lines the renderer emits unbroken, the Tools caption and
the comparison's second sentence, wrapped here to fit this page and nothing else altered:

```
Assay report
Suite: sha256:110fffd99365935935077673dab2d1bb864c290c2f2173f7333c3bde05aa3221
Redaction: every task identifier and path here is an HMAC-SHA-256 token under a salt drawn for this render and never stored, so two reports on one suite share no token, and there is no flag that turns it off

Tools (two bands by two methods, both 95%: pass^n is a Wilson score interval over tasks; pass@1
is a mean of per-task rates rather than a proportion, so its band is a seeded percentile bootstrap
over tasks (2000 resamples, seed 20260904))
  ground-truth  trials=10  pass@1=1.000  pass@1 interval=[1.000, 1.000]  pass^n=1.000  pass^n interval=[0.342, 1.000]
  null          trials=10  pass@1=0.000  pass@1 interval=[0.000, 0.000]  pass^n=0.000  pass^n interval=[0.000, 0.658]

Comparisons
  ground-truth vs null: No winner: the pass^n confidence intervals overlap.
    ground-truth solved 2 tasks null did not, and null solved 0 ground-truth did not (exact
    McNemar p = 0.5000). This measures whether they differ, not which ranks higher - ranking is
    the pass^n intervals' decision alone.
```

**The two sections left out are Costs and Trials, and between them they are the longer part of the
file.** Costs is described line by line a few paragraphs below rather than quoted here. Trials is
the raw material the bands above are computed from: one line for each of the 20 recorded trials —
two tasks by two adapters, five trials each — carrying the task's per-render redaction token and
whether that trial passed. Neither section is omitted because it is inconvenient; they are omitted
because the header, Tools and Comparisons are what the rest of this section argues about, and a
reader who wants the file itself can produce it with §5's recipe.

That transcript's `Suite:` line is the pre-fix run's address and is left exactly as it was written;
it is not the digest §1 quotes, and the difference is the subject of the second subsection below.

**pass^n leads, and it is the number the ranking reads.** `ground-truth` is 1.000 and `null` is
0.000 on pass^n over 2 tasks; pass@1 is 1.000 and 0.000 over 10 trials each, reported for
comparability and banded by a different procedure, which is what the caption exists to say.

### The renderer still refuses to declare a winner, and it is still right to

`[0.342, 1.000]` overlaps `[0.000, 0.658]`, so `decide_verdict` prints **"No winner"** on the most
lopsided input this harness will ever be handed: an adapter that cannot fail against one that
cannot pass. Two tasks is not enough for the Wilson bands to separate, and Assay says so out loud
instead of printing a ranking it cannot support. A harness that would announce a winner here would
announce one anywhere.

The paired test agrees about the size of the suite rather than about the tools: 2 discordant tasks
give an exact two-sided McNemar p of **0.5000**, and with 2 discordant tasks the smallest p
attainable is 2 × 0.5² = 0.5. **A suite this small cannot produce a significant paired result at
all**, however lopsided the adapters. That is a fact about the suite, not about the test, and
neither statistic was allowed to move the other: the p is printed beside the verdict and the bands
alone decided it ([ADR-0044](../adr/0044-the-paired-test-is-exact-mcnemar-on-pass-caret-n.md)).

The costs section prints in full with `no price was supplied` on every line, because no `--price`
was passed and Assay stores no prices
([ADR-0046](../adr/0046-a-cost-line-carries-the-reason-it-has-no-dollars.md)). Both adapters
recorded `input=0 output=0`; `ground-truth` shows `solved=2` and `null` `solved=0`, which is the
bracket again, in the one section where dollars would go.

### The suite hash did not reproduce across demo runs, and M5 stopped to fix it

**Two demo runs minutes apart produced two different suite hashes** —
`sha256:110fffd9…` and `sha256:a7b887df…` — while every other figure above was byte-identical,
including both task IDs, the yield, both pass^n Wilson bands, both pass@1 bootstrap bands, the
McNemar p and the verdict.

The cause was not the fixture, which is deterministic: `build_fixture_repo` drops the ambient
`GIT_*` environment and asserts its history built to pinned object names, and both runs mined the
same two task IDs. The cause was the **path**. The fixture has no `origin` remote, so
`GitHistory.repo_url` (then at `src/assay/host/git.py:137`) fell back to `str(self._repo)`; that
absolute path became `Task.repo_url`, and `Task` sits inside `SuiteBody`, which is what
`suite_hash` is computed over. The demo builds its fixture inside a fresh
`tempfile.TemporaryDirectory`, so the path — and therefore the address — was new on every run.

**This is published rather than smoothed over, because it was a real limit on
[ADR-0007](../adr/0007-suites-are-content-addressed-and-versioned.md)'s promise.** A content
address is supposed to make two identical task sets the same suite; there, two identical task sets
mined from two directories were two suites. It never affected a run against a *fixed* checkout,
which is every real use of `assay mine`, and it made no figure above wrong. What it did make wrong
was the one figure the release exists to hand out: the hash pinned the directory that produced it
rather than the demo, so the §5 recipe could not deliver what its name promises.

**It was fixed inside M5 rather than carried out of it.** A repository with no `origin` now names
itself by its root commit — `root-commit:<sha>`, derived from the history rather than from where
the history is sitting — so the same fixture built into any directory answers with the same name
and the suite keeps one address
([ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md)). The §5
recipe has since been run end to end from three different parent directories and produced one
digest each time,
`sha256:bfa6e5bc2efe5d2966a937eabe5d51ee8999fefc0b4445aa1184375efd011344`, which is the hash quoted
in §1 and the one a reader following §5 should see.

**A narrower defect of the same shape is still open, and ADR-0052 records it as deliberately not
fixed:** `origin` URL spellings are not normalised, so one repository declared as
`git@example.invalid:me/repo.git` and as `https://example.invalid/me/repo.git` still hashes to two
different suites. That is a human's spelling rather than a directory's accident, and it is carried
into §4.

### The HTML artefact, and what it does not contain

`build/demo/report.html` is 5301 bytes and stands alone:

- **No external reference of any kind.** Not a script, a stylesheet, a font or an image — grepping
  the file for `http` returns nothing — and `<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'">` is in the head to enforce it. A page
  about a private repository that fetched anything would be a beacon.
- **`<meta name="viewport" content="width=device-width, initial-scale=1">`**, so the 60rem layout
  is readable on a phone rather than shrunk to fit a 980px assumption.
- **No timestamp and no generator string**, in either format. The suite hash is the provenance that
  matters, and a clock would make two renders of one result set differ
  ([ADR-0049](../adr/0049-the-report-states-its-redaction-and-carries-no-clock.md)).
- **Its redaction tokens are not the text report's.** The same run produced `i:fed35ad93de5` in
  `report.txt` and `i:0b97975edd1b` in `report.html` for the same task, because the salt is drawn
  per render and never stored ([ADR-0009](../adr/0009-redaction-is-hmac-with-a-per-render-salt.md)).
  That is the redaction statement in the header being literally true, checkable from the two files
  the one command wrote, and there is no flag that turns it off.

## 4. Open flags carried past M5

M3's and M4's flags are all still open and M5 touched none of them: `model_api.py` never reading
the served snapshot back off the response, `--network bridge` on the adapter phase not being a
hostname allowlist, `AGENT_TOOL_VERSION` being `None`, the unverified `TRIAL_LIMITS` /
`IMAGE_BUILD_TIMEOUT_S` / `DEFAULT_TRIAL_TIMEOUT_S` guesses, the absence of resume on a run that
fails late, the degenerate bootstrap band on oracle data, and `BOOTSTRAP_SEED` /
`BOOTSTRAP_RESAMPLES` as unre-examined constants. New, or newly sharpened by the release:

- **`run_mine` still hardcodes `host_runner_for`, so M2's pinned-image widening lives only in
  `assay run`'s images and not in `mine`'s.** That is why M5's public-repo yield — 600 commits
  examined → 14 valid tasks, from three repositories chosen in advance to fit the host path
  ([`m5-yield-public-repos.md`](m5-yield-public-repos.md),
  [ADR-0053](../adr/0053-the-public-repo-yield-uses-the-shipped-command-on-the-host-path.md)) — is a
  floor on that path rather than a measurement of Assay's reach. **No mined real-repository suite
  has been run by any tool**, and ADR-0019's limit outside the selection rule is unrepealed.
- **`origin` URL spellings are not normalised, so one repository can still have two addresses.**
  A remote declared as `git@example.invalid:me/repo.git` and as `https://example.invalid/me/repo.git`
  is the same repository and hashes to two suites. This is the residual left by
  [ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md), which
  records it as open on purpose: normalisation is a URL-parsing rule with its own judgement calls,
  and it was not going to be decided in a paragraph.
- **No cold-daemon wall clock exists.** §1's 206 s is warm. A first-run figure is the one a
  stranger actually experiences, and this milestone did not measure it.
- **`build/demo/` is overwritten and never cleaned.** A failed run leaves the previous run's
  `report.html` in place. The demo prints each command and stops at the first failure, so a reader
  can tell — but nothing enforces it, and a stale artefact is indistinguishable from a fresh one
  by inspection of the file alone.
- **The demo needs Docker and takes minutes.** There is no fast path, and there deliberately is no
  `--trials 1` shortcut: weakening the headline statistic to save two minutes would teach the wrong
  lesson about the tool.
- **The fixture notice carries numbers, and numbers rot.** 11, 2, 743, 40, 600 and 14 are pinned to
  `tests.fixture_repo.EXPECTED_YIELD` and to three completed milestone records, but nothing tests
  the sentence against them.

**One flag this section carried before the fix landed is closed.** The suite hash was
path-dependent, so the demo's address moved with the temporary directory it was built in; a
repository with no `origin` now names itself by its root commit and the address holds
([ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md), measured
in §3). The normalisation bullet above is the narrower part of it that is still open.

## 5. Reproducing this

1. Start Docker. Nothing else is needed: no API key, no network access beyond the image cache, no
   configuration.
2. `uv run --frozen python scripts/demo.py`
3. Read `build/demo/report.txt` and open `build/demo/report.html`.

That single command regenerates every figure in §3 and the yield in §1, and this document was
written against a run of it that was then repeated to check. **On the repeat: the two task IDs,
the yield line, the rejection counts, both pass^n Wilson intervals, both pass@1 bootstrap bands,
the exact McNemar p and the "No winner" verdict were all identical, character for character.**
Since the fix in §3, the suite hash is identical across runs as well, and two `report.txt` files
from runs in different parent directories were then diffed to check. **On that diff: 20 of the 39
lines differed and every one of them was a trial row, which is where the redaction tokens are; the
other 19 lines, the suite hash among them, were identical character for character.** That leaves
exactly one kind of difference:

- **The redaction tokens differ, and that is the one thing that is supposed to.** Every render
  draws a fresh salt, so `i:fed35ad93de5` above will be some other token in your copy — and the
  same run's HTML already disagrees with its own text report for the same reason.
- **The suite hash no longer differs**, which used to be the second kind. Three runs from three
  different parent directories printed `sha256:bfa6e5bc…`, the digest §1 quotes; §3 has the defect
  it replaced and [ADR-0052](../adr/0052-a-repository-with-no-remote-names-itself-by-its-root-commit.md)
  has the decision.

Anything else that differs is a change an ADR should have recorded — and the address is now one of
the things to compare, not just the figures, which is the guarantee
[ADR-0007](../adr/0007-suites-are-content-addressed-and-versioned.md) was written to give. It holds
for this demo and for any repository mined twice from two directories. It does not yet hold for one
repository whose `origin` is spelled two ways; §4 keeps that open.

The wall clock will not reproduce on a cold daemon. See §1: 206 s is warm. The three runs behind
this document took 213 s, 206 s and 203 s.
