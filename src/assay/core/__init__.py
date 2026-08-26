"""Primitives shared by every other package: canonical bytes, versions, errors.

``core`` depends on nothing else in Assay and performs no I/O. Import the names below from
``assay.core`` rather than from the submodules; the submodule layout is an implementation
detail, this surface is not.
"""

from assay.core.canonical import (
    HASH_PREFIX,
    CanonicalizationError,
    JsonValue,
    canonical_json,
    content_hash,
)
from assay.core.errors import AssayError, NotImplementedInMilestone
from assay.core.model import SchemaModel
from assay.core.versioning import (
    SUPPORTED,
    VERSION_KEY,
    SchemaKind,
    UnsupportedSchemaVersionError,
    require_supported_version,
)

__all__ = [
    "HASH_PREFIX",
    "SUPPORTED",
    "VERSION_KEY",
    "AssayError",
    "CanonicalizationError",
    "JsonValue",
    "NotImplementedInMilestone",
    "SchemaKind",
    "SchemaModel",
    "UnsupportedSchemaVersionError",
    "canonical_json",
    "content_hash",
    "require_supported_version",
]
