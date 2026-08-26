"""Schema version probing.

Task, suite and result-set documents are versioned from M0 and treated as API once public
(CLAUDE.md). A document of an unknown version must fail with one sentence naming what was
found and what is supported - not with a field-by-field parser dump - so the version is
probed before anything is parsed.
"""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final, Literal

from assay.core.errors import AssayError

type SchemaKind = Literal["task", "suite", "result_set"]

VERSION_KEY = "schema_version"

SUPPORTED: Final[Mapping[SchemaKind, int]] = MappingProxyType(
    {"task": 1, "suite": 1, "result_set": 1}
)


class UnsupportedSchemaVersionError(AssayError):
    """A document declares a schema version this build cannot read - or declares none."""

    def __init__(self, kind: SchemaKind, found: object, supported: Sequence[int]) -> None:
        self.kind = kind
        self.found = found
        self.supported = tuple(supported)
        # ``found is None`` also covers an explicit null, which is as unreadable as an
        # absent key and needs no separate wording.
        found_text = "absent" if found is None else f"found {found!r}"
        supported_text = ", ".join(str(version) for version in self.supported)
        super().__init__(
            f"unsupported {VERSION_KEY} for {kind}: {found_text} (supported: {supported_text})"
        )


def require_supported_version(kind: SchemaKind, raw: Mapping[str, object]) -> int:
    """Return the declared schema version of ``raw``, or refuse the document.

    Raises:
        UnsupportedSchemaVersionError: if the version key is absent, is not an integer, or
            names a version this build does not support.
    """
    supported = (SUPPORTED[kind],)
    found = raw.get(VERSION_KEY)
    # bool is an int subclass; ``schema_version: true`` is a malformed document, not v1.
    if not isinstance(found, int) or isinstance(found, bool) or found not in supported:
        raise UnsupportedSchemaVersionError(kind, found, supported)
    return found
