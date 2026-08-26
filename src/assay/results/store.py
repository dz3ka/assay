"""Reading and writing result-set files - the only place in ``results`` that touches a disk.

Loading is two steps in a fixed order: probe the version, then parse. Probing first means a
document this build cannot read is reported as one sentence rather than as a parser's
field-by-field complaint about a version it was never able to read.

There is no third step. A suite verifies against its own hash; a result set carries the hash
of the suite it was run against instead, so what it claims is checked by loading that suite,
not by re-hashing this file.
"""

import json
import os
import tempfile
from pathlib import Path

from assay.core import JsonValue, canonical_json, require_supported_version
from assay.results.models import ResultSet


def read_result_set(path: Path) -> ResultSet:
    """Read the result-set file at ``path``.

    Raises:
        UnsupportedSchemaVersionError: if the document declares no readable schema version.
        ValidationError: if it declares a readable one but does not match the schema.
    """
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    # A document that is not a JSON object cannot declare a version at all, which is the same
    # thing the version probe already has wording for.
    raw: dict[str, object] = decoded if isinstance(decoded, dict) else {}
    require_supported_version("result_set", raw)

    return ResultSet.model_validate(raw)


def write_result_set(path: Path, result_set: ResultSet) -> None:
    """Write ``result_set`` to ``path`` as canonical bytes.

    The version written is the one the model declares - ``ResultSet.schema_version`` is
    ``Literal[1]``, so there is nothing else it can be; that it is also the version this
    build can read is asserted in tests rather than re-derived here.

    The write is atomic - a temporary file in the destination directory, then a replace - so
    a reader never sees a half-written result set, and an interrupted write leaves the
    previous file intact rather than a truncated one.
    """
    document: JsonValue = result_set.model_dump(mode="json")
    # Canonical bytes, written as bytes: no platform newline, no trailing newline, no BOM.
    _replace_atomically(path, canonical_json(document))


def _replace_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a sibling temporary file and an atomic replace.

    The twin of ``assay.suite.io``'s helper. It is copied rather than imported because
    ``results`` and ``suite`` are siblings and neither owns the other's internals; the third
    caller is the one that should move it into ``core``.
    """
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
