"""Reading and writing suite files - the only place in ``suite`` that touches a filesystem.

Loading is deliberately three steps in a fixed order: probe the version, then parse, then
verify the hash. Probing first means an unreadable version is reported as one sentence rather
than as a parser's field-by-field complaint about a document it was never able to read.
Verifying last means the digest is recomputed from the parsed value, so a file that was
edited after it was written is refused rather than trusted.
"""

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from assay.core import (
    AssayError,
    JsonValue,
    canonical_json,
    content_hash,
    require_supported_version,
)
from assay.suite.models import SuiteBody, SuiteFile


class SuiteHashMismatchError(AssayError):
    """A suite file's recorded hash does not describe its own body.

    Either the file was edited after it was written or it was truncated in transit. Both make
    every result that cites this suite unattributable (SPEC §5.5), so the file is refused
    rather than loaded with a warning.
    """

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"suite hash mismatch: file records {expected}, body hashes to {actual}")


def load_suite(path: Path) -> SuiteFile:
    """Read and verify the suite file at ``path``.

    Raises:
        UnsupportedSchemaVersionError: if the document declares no readable schema version.
        ValidationError: if it declares a readable one but does not match the schema.
        SuiteHashMismatchError: if the body does not hash to the recorded ``suite_hash``.
    """
    decoded: object = json.loads(path.read_text(encoding="utf-8"))
    # A document that is not a JSON object cannot declare a version at all, which is the same
    # thing the version probe already has wording for.
    raw: dict[str, object] = decoded if isinstance(decoded, dict) else {}
    require_supported_version("suite", raw)

    suite = SuiteFile.model_validate(raw)
    actual = _body_hash(suite.body)
    if actual != suite.suite_hash:
        raise SuiteHashMismatchError(suite.suite_hash, actual)
    return suite


def save_suite(path: Path, body: SuiteBody, *, generator: str) -> SuiteFile:
    """Write ``body`` to ``path`` as a hashed suite file and return what was written.

    The write is atomic - a temporary file in the destination directory, then a replace - so
    a reader never sees a half-written suite, and an interrupted write leaves the previous
    file intact rather than a truncated one.
    """
    # The version written is the one the model declares; that it is also the version this
    # build can read is asserted in tests, not re-derived here.
    suite = SuiteFile(
        schema_version=1,
        suite_hash=_body_hash(body),
        generated_at=datetime.now(UTC).isoformat(),
        generator=generator,
        body=body,
    )
    document: JsonValue = suite.model_dump(mode="json")
    # Canonical bytes, written as bytes: no platform newline, no trailing newline, no BOM.
    _replace_atomically(path, canonical_json(document))
    return suite


def _body_hash(body: SuiteBody) -> str:
    """Hash the body's JSON value, which is what ``suite_hash`` addresses."""
    payload: JsonValue = body.model_dump(mode="json")
    return content_hash(payload)


def _replace_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a sibling temporary file and an atomic replace."""
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
