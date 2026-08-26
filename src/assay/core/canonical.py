"""Canonical JSON encoding and content addressing.

Suites are content-addressed (SPEC §5.5), so two structurally equal values must produce
byte-identical output on every platform and every run. That rules out insertion order,
incidental whitespace and - see :class:`CanonicalizationError` - floats.

Pure: no I/O, no clock, no environment.
"""

import hashlib
import json

from assay.core.errors import AssayError

type JsonValue = str | int | bool | list[JsonValue] | dict[str, JsonValue] | None

HASH_PREFIX = "sha256:"


class CanonicalizationError(AssayError):
    """A value cannot be turned into stable canonical bytes."""


def canonical_json(value: JsonValue) -> bytes:
    """Encode ``value`` as canonical UTF-8 JSON: keys sorted, no whitespace, no newline.

    Raises:
        CanonicalizationError: if the structure contains a float, or a type JSON cannot
            represent.
    """
    _reject_floats(value, "$")
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(f"value is not JSON-serialisable: {exc}") from exc
    # str.encode() is UTF-8; canonical bytes are UTF-8 by contract.
    return text.encode()


def content_hash(value: JsonValue) -> str:
    """Return ``sha256:<64 lowercase hex>`` over the canonical encoding of ``value``."""
    return HASH_PREFIX + hashlib.sha256(canonical_json(value)).hexdigest()


def _reject_floats(value: JsonValue, path: str) -> None:
    """Refuse floats anywhere in ``value``, naming the JSON path to the offender.

    A float's repr is not a stable hash input across platforms, and NaN/Inf are not JSON
    at all. Money is a ``Decimal`` serialised as a string by ``model_dump(mode="json")``,
    so nothing legitimate in a suite or result set arrives here as a float.

    ``bool`` is a subclass of ``int``, not of ``float``, so ``True``/``False`` pass this
    check untouched - which is what we want; they encode as ``true``/``false``.
    """
    if isinstance(value, float):
        raise CanonicalizationError(
            f"float at {path}: {value!r} - floats are not canonicalisable "
            f"(use Decimal, serialised as a string)"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_floats(item, f"{path}[{index}]")
