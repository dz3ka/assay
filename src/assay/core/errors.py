"""The project's exception base.

Placement rule for the whole package: an error lives in the module that raises it, and
everything in ``core`` is re-exported from :mod:`assay.core`. This module holds the base
alone - every error Assay raises is defined beside the code that raises it.
"""


class AssayError(Exception):
    """Base class for every error Assay raises deliberately.

    A caller that wants "anything Assay itself refused to do" catches this; anything else
    escaping the package is a bug and should surface as itself.
    """
