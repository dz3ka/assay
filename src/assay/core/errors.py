"""The project's exception base, plus errors that are raised outside ``core``.

Placement rule for the whole package: an error lives in the module that raises it, and
everything in ``core`` is re-exported from :mod:`assay.core`. ``NotImplementedInMilestone``
is the exception to the first half - it is raised by the CLI, but it is not CLI-specific
enough to make the CLI a dependency of anything that wants to catch it.
"""


class AssayError(Exception):
    """Base class for every error Assay raises deliberately.

    A caller that wants "anything Assay itself refused to do" catches this; anything else
    escaping the package is a bug and should surface as itself.
    """


class NotImplementedInMilestone(AssayError):
    """A CLI command that exists in the surface but is not built yet.

    Milestones land one at a time (CLAUDE.md), so a command can be reachable and honest
    about being unbuilt. The message names where the work is planned, so the user reads a
    schedule rather than a failure.
    """

    def __init__(self, command: str, milestone: str, planned: str) -> None:
        self.command = command
        self.milestone = milestone
        self.planned = planned
        super().__init__(
            f"assay {command} is not implemented in {milestone} "
            f"(planned: {planned}, SPEC section 7)"
        )
