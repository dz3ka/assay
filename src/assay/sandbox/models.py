"""What a trial is allowed to consume. One value, deliberately small.

A plain frozen dataclass rather than a :class:`assay.core.SchemaModel`: nothing here is
serialised, addressed or versioned. Limits are an argument to a container, decided by the caller
that starts it, and they never reach a suite file or a result set - so the validation, the
canonical encoding and the schema-version discipline a ``SchemaModel`` brings would all be
machinery for a value that only ever travels between two functions in this process.

There are no defaults on the fields, on purpose. A default here would be a policy this module
has no standing to set, quietly applying to every trial in every report; the shipped numbers
live at the call site that starts containers, where they can be read next to the flags they
become.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerLimits:
    """The resource ceiling a single trial runs under.

    SPEC §9 requires a test proving a trial is *killed at its resource limit*, and that test has
    to drive the limits far below anything shipped - a container allowed a sensible amount of
    memory takes a long time to be refused it. Passing this value in is what makes that possible
    without a second, test-only path into the sandbox.

    Attributes:
        memory_mb: The memory ceiling in mebibytes. Also spelled as the swap ceiling, so a host
            with swap available kills the container instead of letting it page (measured in
            :mod:`assay.sandbox.image`).
        cpus: Fractional CPUs, as docker's own decimal string - ``"0.5"``, ``"2"``. A string
            rather than a float because a float is not canonicalisable anywhere in this
            codebase, and because the value is handed to ``--cpus`` unchanged; parsing it into a
            number here would only be a chance to render it back differently.
        pids: The process-count ceiling. A fork bomb in a mined test is a plausible accident
            rather than an attack, and it is the one runaway a memory limit does not catch.
    """

    memory_mb: int
    cpus: str
    pids: int
