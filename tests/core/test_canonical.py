"""Canonicalisation is the base of content addressing: same value, same bytes, same hash."""

import hashlib
import math
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from assay.core import CanonicalizationError, JsonValue, canonical_json, content_hash


class GateModel(BaseModel):
    """The shape M0 schemas are built from: frozen, closed, money as Decimal.

    This model exists so the type-checked round trip pydantic -> JSON -> hash is
    exercised by the test suite rather than assumed (ADR-0008 risk gate).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_usd: Decimal
    max_seconds: int


class LossyGateModel(BaseModel):
    """A model that serialises a float, to prove the hash boundary rejects it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_usd: float


def test_canonical_json_sorts_keys_and_omits_whitespace() -> None:
    assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json_preserves_non_ascii_characters_unescaped() -> None:
    assert canonical_json({"author": "Džekić"}) == '{"author":"Džekić"}'.encode()


def test_canonical_json_emits_no_trailing_newline() -> None:
    encoded = canonical_json({"a": 1})
    assert not encoded.endswith(b"\n")
    assert b"\r" not in encoded


def test_canonical_json_encodes_booleans_as_json_literals_not_numbers() -> None:
    assert canonical_json({"ok": True, "bad": False}) == b'{"bad":false,"ok":true}'


def test_content_hash_is_independent_of_key_insertion_order() -> None:
    first: JsonValue = {"task_id": "t1", "schema_version": 1, "tests": ["a", "b"]}
    second: JsonValue = {"tests": ["a", "b"], "schema_version": 1, "task_id": "t1"}

    assert content_hash(first) == content_hash(second)


def test_content_hash_depends_on_list_order() -> None:
    assert content_hash(["a", "b"]) != content_hash(["b", "a"])


def test_content_hash_is_prefixed_sha256_of_the_canonical_bytes() -> None:
    value: JsonValue = {"a": 1}
    expected = hashlib.sha256(canonical_json(value)).hexdigest()

    digest = content_hash(value)

    assert digest == f"sha256:{expected}"
    assert digest.islower()
    assert len(digest) == len("sha256:") + 64


@pytest.mark.parametrize(
    "value",
    [
        0.1,
        [0.1],
        {"cost": 0.1},
        {"trials": [{"cost_usd": 0.1}]},
        math.nan,
        math.inf,
    ],
    ids=["top-level", "in-list", "in-dict", "nested", "nan", "inf"],
)
def test_canonical_json_rejects_a_float_anywhere_in_the_structure(value: JsonValue) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json(value)


def test_float_rejection_names_the_path_to_the_offending_value() -> None:
    # Typed as Any because JsonValue statically excludes float - a payload with a float in
    # it can only reach this boundary from a dynamically typed source, e.g. model_dump().
    nested: Any = {"trials": [{"cost_usd": 0.1}]}

    with pytest.raises(CanonicalizationError, match=r"\$\.trials\[0\]\.cost_usd"):
        canonical_json(nested)


def test_content_hash_rejects_a_float_anywhere_in_the_structure() -> None:
    lossy: Any = {"cost": 1.5}

    with pytest.raises(CanonicalizationError):
        content_hash(lossy)


def test_canonical_json_reports_unserialisable_values_as_canonicalization_errors() -> None:
    unsupported: Any = {"when": object()}

    with pytest.raises(CanonicalizationError):
        canonical_json(unsupported)


def test_pydantic_json_dump_hashes_with_money_as_a_string() -> None:
    gate = GateModel(max_usd=Decimal("1.50"), max_seconds=600)

    payload: JsonValue = gate.model_dump(mode="json")

    assert payload == {"max_usd": "1.50", "max_seconds": 600}
    assert content_hash(payload).startswith("sha256:")


def test_pydantic_model_is_frozen_and_closed() -> None:
    gate = GateModel(max_usd=Decimal("1.50"), max_seconds=600)

    with pytest.raises(ValidationError):
        gate.max_seconds = 1
    with pytest.raises(ValidationError):
        GateModel.model_validate({"max_usd": "1.50", "max_seconds": 600, "surprise": True})


def test_a_model_that_serialises_a_float_cannot_be_content_addressed() -> None:
    payload: JsonValue = LossyGateModel(max_usd=1.5).model_dump(mode="json")

    with pytest.raises(CanonicalizationError):
        content_hash(payload)
