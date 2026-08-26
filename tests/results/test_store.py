"""A result-set file is what a report is rendered from: these tests are what makes it readable.

Reading one has to answer "can this build read this document at all" before it parses a field,
so an unreadable version fails with a sentence rather than a parser dump. Writing one has to
produce the same bytes on the Windows dev host and the Linux runner, and has to leave either
the old file or the new one behind - never half of either.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.core import SUPPORTED, JsonValue, UnsupportedSchemaVersionError
from assay.results import ResultSet, read_result_set, write_result_set

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _minimal_result_set() -> ResultSet:
    return ResultSet.model_validate(_read(FIXTURES / "result_set_minimal.json"))


def _read(path: Path) -> dict[str, JsonValue]:
    document: dict[str, JsonValue] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _write(path: Path, document: dict[str, JsonValue]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def test_a_hand_written_result_set_file_loads() -> None:
    result_set = read_result_set(FIXTURES / "result_set_minimal.json")

    assert result_set.suite_hash.startswith("sha256:")
    assert [result.adapter_name for result in result_set.results] == ["null", "ground-truth"]


def test_a_written_result_set_loads_back_unchanged(tmp_path: Path) -> None:
    written = _minimal_result_set()

    write_result_set(tmp_path / "results.json", written)

    assert read_result_set(tmp_path / "results.json") == written


def test_a_round_trip_preserves_money_to_the_last_microdollar(tmp_path: Path) -> None:
    # A cost that survived as a float would come back as 1.0000000000000001e-06 or as 0.0;
    # money is a Decimal serialised as a string precisely so the digits are the digits.
    path = tmp_path / "results.json"

    write_result_set(path, _minimal_result_set())
    cost = read_result_set(path).results[1].attempt.cost_usd

    assert isinstance(cost, Decimal)
    assert cost == Decimal("0.000001")
    assert str(cost) == "0.000001"
    assert b'"cost_usd":"0.000001"' in path.read_bytes()


def test_a_written_result_set_is_canonical_bytes_on_every_platform(tmp_path: Path) -> None:
    # Windows dev host, Ubuntu CI runner: a \r or a trailing newline would change the file's
    # bytes without changing its content, which is exactly what content addressing forbids.
    path = tmp_path / "results.json"

    write_result_set(path, _minimal_result_set())

    raw = path.read_bytes()
    assert b"\r" not in raw
    assert not raw.endswith(b"\n")
    assert raw.startswith(b'{"results":')


def test_writing_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    write_result_set(tmp_path / "results.json", _minimal_result_set())

    assert [entry.name for entry in tmp_path.iterdir()] == ["results.json"]


def test_writing_over_an_existing_result_set_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text("not json at all", encoding="utf-8", newline="\n")

    write_result_set(path, _minimal_result_set())

    assert read_result_set(path) == _minimal_result_set()


def test_the_version_written_is_the_version_this_build_can_read(tmp_path: Path) -> None:
    path = tmp_path / "results.json"

    write_result_set(path, _minimal_result_set())

    assert _read(path)["schema_version"] == SUPPORTED["result_set"]
    assert read_result_set(path).schema_version == SUPPORTED["result_set"]


def test_a_future_schema_version_is_refused_before_the_document_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    write_result_set(path, _minimal_result_set())
    document = _read(path)
    document["schema_version"] = 2
    # Also unreadable to this build's parser, which must not be what the user hears about.
    document["scoring_profile"] = "a field from a later version"
    _write(path, document)

    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        read_result_set(path)

    message = str(caught.value)
    assert caught.value.kind == "result_set"
    assert caught.value.found == 2
    assert "result_set" in message
    assert "supported: 1" in message


def test_a_document_with_no_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    document = _read(FIXTURES / "result_set_minimal.json")
    del document["schema_version"]
    _write(path, document)

    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        read_result_set(path)

    assert caught.value.kind == "result_set"
    assert caught.value.found is None
    assert "absent" in str(caught.value)


def test_a_document_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text("[1, 2, 3]", encoding="utf-8", newline="\n")

    with pytest.raises(UnsupportedSchemaVersionError, match="absent"):
        read_result_set(path)


def test_a_result_set_file_carrying_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    document = _read(FIXTURES / "result_set_minimal.json")
    document["signed_by"] = "someone"
    _write(path, document)

    with pytest.raises(ValidationError, match="signed_by"):
        read_result_set(path)


def test_result_set_is_the_type_both_directions_agree_on(tmp_path: Path) -> None:
    path = tmp_path / "results.json"

    write_result_set(path, _minimal_result_set())

    assert isinstance(read_result_set(path), ResultSet)
