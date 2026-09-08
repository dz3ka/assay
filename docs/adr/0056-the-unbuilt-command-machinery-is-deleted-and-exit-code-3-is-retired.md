# ADR-0056: The unbuilt-command machinery is deleted and exit code 3 is retired at the freeze

- **Status:** Accepted
- **Date:** 2026-09-07
- **Deciders:** Bogdan Dzekic

## Context
M5 publishes the surface. Everything the CLI advertises — the four commands, their flags, the
`--version` line ([ADR-0047](0047-the-version-line-names-the-milestone.md)) and the exit-code
table in the README — stops being an internal convention and becomes what a caller is entitled to
rely on. That is the moment to check that each published thing is true, because after it, removing
one costs a compatibility story rather than a paragraph.

**One of them is not true.** Exit code 3, `EXIT_NOT_IMPLEMENTED`, has been published since M0 and
no path in the tree can return it. The machinery behind it is `PLANNED` and `_UNBUILT_HELP` in
`cli/main.py`, both empty since M3 built `run`; a `for command in _UNBUILT_HELP` loop that
registers no subparser because it iterates an empty dict; a `raise NotImplementedInMilestone` after
the four command branches in `main()`, unreachable because argparse enforces a required subcommand
drawn from exactly the four names registered above it; the `except` that turns it into the exit
code; and `NotImplementedInMilestone` itself (`core/errors.py`), exported from `assay.core`,
carrying five tests and a ruff `N818` exemption written for its name.

**The README says so in the row that publishes it.** The table's row for `3` reads "The command
exists in the surface but is not implemented in this milestone. No command reaches it now: all four
are built", and a paragraph below explains what the code is for. A reference table that documents a
code and withdraws it in the same sentence is not a reference; it is a note about the project's
history sitting in the document a reader consults to write a script.

**[ADR-0047](0047-the-version-line-names-the-milestone.md) diagnosed all of this and deferred it
here on purpose.** It named the deletion as an alternative and rejected it *on scope* — "the honest
end state and the one this record expects M5 to reach" — because it retired a published exit code
and stranded an error class with live tests on a tree with one gate left before M4 closed. It set a
trigger in the Decision: "**Trigger: M5's public-release surface freeze**, at which point the branch
either gains a consumer or is deleted along with the exit code and the error class", and listed the
surviving dead code in its own Consequences as "a withdrawn promise waiting for the milestone that
can retire it properly". This is that milestone, and the branch gained no consumer.

**It could not have gained one.** SPEC §6 publishes four commands and §7's M5 adds none, and the
one candidate for a fifth was ruled out by a later record for this exact reason:
[ADR-0050](0050-the-demo-runs-against-the-fixture-and-says-so-first.md) put the demo in
`scripts/demo.py` rather than in the surface, citing that "0047 has just decided M5 freezes the
surface rather than growing it". The two live routes to a consumer are therefore both closed by
decisions already accepted.

## Decision
**The unbuilt-command machinery is deleted and exit code 3 is retired. `assay` returns 0, 1 or 2
and nothing else, and the README's exit-code table has three rows.**

What goes: `PLANNED`, `_UNBUILT_HELP`, the subparser loop over the empty dict, the unreachable
`raise` and the `except` that caught it, `EXIT_NOT_IMPLEMENTED`, `NotImplementedInMilestone` with
its `assay.core` export and its five tests, the `[tool.ruff.lint.per-file-ignores]` entry that
existed only for its name, the `[project.scripts]` comment claiming three of the four commands exit
3, and the README's row for `3` together with the paragraph explaining it. The module docstrings
that justified keeping the machinery are rewritten to describe the surface as it now is.

**Retiring 3 cannot break a caller, and that is why it is a deletion rather than a deprecation.**
No release exists, and no build since M3 has been able to return the code. A script that branches
on `== 3` therefore has a branch that has not fired in three milestones and will not start firing;
it stops matching a value it never saw. Nothing that used to exit 3 now exits something else — the
commands that once did are built, and they exit 0 or 1 on their own terms.

**The exit-code table says nothing about 3 at all — not "reserved", not "retired".** A code marked
reserved is a promise to a caller who has no way to test it, and it would silently constrain the
next command that ever needs a status of its own. The history of the code lives in this record and
in 0047, which is where a reader looking for history goes.

**`main()`'s last branch is `report` as a fall-through, not a fourth `if`.** With the unreachable
raise gone, a fourth `if` needs something after it, and everything that could go there — an `else`
that cannot run, an `assert`, a re-raise — is the dead branch this record is deleting, re-created
one line lower. argparse rejects any name not registered as a subparser and requires one, so a
command that reaches the end of the chain is `report`. The constraint is stated in a comment where
the fall-through happens.

**`NotImplementedInMilestone` goes rather than surviving as an unused export.** `assay.core.__all__`
is a public surface and this removes a name from it. CLAUDE.md's rule about treating something as
API once it is public is scoped to the task and result schemas, which are versioned documents other
builds read; an exception class nobody can raise is not one of those, and keeping it would preserve
0047's diagnosis — code alive only because deleting it would remove something published — one module
over from where it was diagnosed.

**`MILESTONE` stays.** It is the second token of the `--version` line and 0047 made that public; the
comment above it loses the clause about being quoted into every "not implemented" message, because
after this record `--version` is its only reader.

## Alternatives considered
- **Give the machinery a consumer instead — declare a fifth command.** The other half of 0047's
  trigger. Rejected on the facts rather than on taste: SPEC §6 publishes four commands, §7's M5 adds
  none, and 0050 already put the only candidate in `scripts/` expressly because 0047 froze the
  surface. Declaring one to justify the code that would declare it is the tail wagging the dog.
- **Keep `3` in the table marked "reserved, never returned".** Rejected. It reads as a promise a
  caller cannot exercise, it is indistinguishable to a reader from "not currently produced", and it
  quietly reserves the next free status code for a use case nobody has. The table is a reference for
  writing a script, and [ADR-0055](0055-the-readme-is-a-release-document-not-a-changelog.md) is the
  standing rule that the README is not where the project's history is kept.
- **Delete the CLI half and keep `NotImplementedInMilestone` for a future milestone.** Rejected as
  the worst of the three: the class is the half carrying the tests, so the tree would keep five
  green tests over code with no caller, which reads to a reviewer as live wiring. YAGNI aside, an
  exception is four lines to rewrite when something actually needs it.
- **Defer again, past the freeze.** Rejected because the freeze is the thing that changes the cost.
  Before it, exit 3 is a convention this repository can retire in a paragraph; after it, it is a
  published code, and every later removal has to argue about callers that may exist. 0047 deferred
  once, deliberately and with a named trigger; deferring on the trigger is how a named deferral
  becomes a permanent one.
- **Do it in M3, when `run` landed.** Not available now, and named because it is where the argument
  was first true. 0047 records why it was not taken then, and the answer — one verification gate
  left before a milestone closed — is exactly the answer that is not available at a freeze.

## Consequences
**The published exit codes are 0, 1 and 2, and every one of them has a live producer.** 0047's
standing consequence — "the exit-code table keeps a code nothing can currently produce" — is
discharged, and this record is the reason the code is gone rather than a compatibility break.

**The suite loses five tests and gains two.** Five covered `NotImplementedInMilestone`'s message and
its place in the hierarchy; two are the parametrised ADR-index cases every record adds. The net −3
is written down here because a suite that shrinks without an account cannot be told apart from tests
deleted to make a gate pass.

**`core/errors.py` is under the same lint rules as the rest of `src/`.** The `N818` exemption existed
for one name and leaves with it, so a future error class in that module gets the "Error" suffix the
rule asks for rather than inheriting a per-file pass it had no part in earning.

**A fifth subcommand, if one is ever registered, silently inherits `report`'s handler.** That is the
cost of the fall-through and it is named rather than guarded, because the guard is the dead branch
this record removes. What protects it is not a runtime check but a test: registering a subparser
and forgetting its branch is a change to `build_parser` and `main` in one file but about 640 lines
apart — `build_parser` returns at `src/assay/cli/main.py:600` and the dispatch begins at `:1244`,
in 1293 lines — which is far too far for the eye to hold, so
`tests/cli/test_main.py::test_the_parser_registers_exactly_the_four_commands_the_surface_declares`
pins the registered set to `{"mine", "validate", "run", "report"}` by equality. A fifth subcommand
fails that test on the commit that registers it, which is where its handler is owed.

**Nothing a user can observe changes except the vanished code.** The four commands take the same
flags, print the same output on the same streams, and return the same 0 or 1; `--help` is
byte-identical to before this record. `--version` differs by one token and not because of this
record: the same change set moves `MILESTONE` from `"M4"` to `"M5"` at `src/assay/cli/main.py:109`,
and the version line is built from it, so the line now reads `(milestone M5)` where it read
`(milestone M4)`. Nothing else about it changed.
