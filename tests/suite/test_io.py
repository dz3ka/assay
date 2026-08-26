"""A suite file is a provenance claim: these tests are what makes the claim checkable.

Reading one has to answer two questions before anything is trusted - "can this build read
this document at all" and "are these bytes the bytes that were hashed" - and it has to answer
them in that order, so an unreadable version fails with a sentence rather than a parser dump.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from assay.core import SUPPORTED, AssayError, JsonValue, UnsupportedSchemaVersionError
from assay.suite import SuiteBody, SuiteFile, SuiteHashMismatchError, load_suite, save_suite

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _minimal_body() -> SuiteBody:
    document = _read(FIXTURES / "suite_minimal.json")
    body = document["body"]
    assert isinstance(body, dict)
    return SuiteBody.model_validate(body)


def _read(path: Path) -> dict[str, JsonValue]:
    document: dict[str, JsonValue] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _write(path: Path, document: dict[str, JsonValue]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def test_a_hand_written_suite_file_verifies_against_its_recorded_hash() -> None:
    # The fixture is pretty-printed; the hash is over the canonical encoding of the *value*,
    # so a readable file and the bytes save_suite writes verify identically.
    suite = load_suite(FIXTURES / "suite_minimal.json")

    assert suite.body.suite_name == "fixture-repo"
    assert suite.suite_hash.startswith("sha256:")
    assert suite.generator == "assay/0.1.0"


def test_a_saved_suite_loads_back_with_the_same_hash_and_tasks(tmp_path: Path) -> None:
    body = _minimal_body()

    written = save_suite(tmp_path / "suite.json", body, generator="assay/0.1.0")
    loaded = load_suite(tmp_path / "suite.json")

    assert loaded == written
    assert loaded.body == body
    assert loaded.generator == "assay/0.1.0"


def test_a_saved_suite_is_canonical_bytes_on_every_platform(tmp_path: Path) -> None:
    # Windows dev host, Ubuntu CI runner: a \r or a trailing newline would change the file's
    # bytes without changing its content, which is exactly what content addressing forbids.
    path = tmp_path / "suite.json"

    save_suite(path, _minimal_body(), generator="assay/0.1.0")

    raw = path.read_bytes()
    assert b"\r" not in raw
    assert not raw.endswith(b"\n")
    assert raw.startswith(b'{"body":')


def test_saving_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    save_suite(tmp_path / "suite.json", _minimal_body(), generator="assay/0.1.0")

    assert [entry.name for entry in tmp_path.iterdir()] == ["suite.json"]


def test_saving_over_an_existing_suite_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text("not json at all", encoding="utf-8", newline="\n")

    written = save_suite(path, _minimal_body(), generator="assay/0.1.0")

    assert load_suite(path).suite_hash == written.suite_hash


def test_the_version_written_is_the_version_this_build_can_read(tmp_path: Path) -> None:
    written = save_suite(tmp_path / "suite.json", _minimal_body(), generator="assay/0.1.0")

    assert written.schema_version == SUPPORTED["suite"]
    assert written.body.schema_version == written.schema_version


def test_the_recorded_generator_is_the_one_the_caller_named(tmp_path: Path) -> None:
    written = save_suite(tmp_path / "suite.json", _minimal_body(), generator="assay/9.9.9")

    assert written.generator == "assay/9.9.9"


def test_generated_at_is_outside_the_hash(tmp_path: Path) -> None:
    # A digest covering the clock would make identical task sets hash differently and defeat
    # content addressing, so re-stamping a file must not invalidate it.
    path = tmp_path / "suite.json"
    written = save_suite(path, _minimal_body(), generator="assay/0.1.0")
    document = _read(path)
    document["generated_at"] = "1999-12-31T23:59:59+00:00"
    _write(path, document)

    restamped = load_suite(path)

    assert restamped.suite_hash == written.suite_hash
    assert restamped.generated_at != written.generated_at


def test_an_edited_body_is_refused_with_both_hashes(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    written = save_suite(path, _minimal_body(), generator="assay/0.1.0")
    document = _read(path)
    body = document["body"]
    assert isinstance(body, dict)
    body["suite_name"] = "tampered"
    _write(path, document)

    with pytest.raises(SuiteHashMismatchError) as caught:
        load_suite(path)

    assert caught.value.expected == written.suite_hash
    assert caught.value.actual != written.suite_hash
    assert written.suite_hash in str(caught.value)
    assert caught.value.actual in str(caught.value)


def test_a_hash_mismatch_is_catchable_as_an_assay_error() -> None:
    assert issubclass(SuiteHashMismatchError, AssayError)


def test_a_future_schema_version_is_refused_before_the_document_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    save_suite(path, _minimal_body(), generator="assay/0.1.0")
    document = _read(path)
    document["schema_version"] = 2
    # Also unreadable to this build's parser, which must not be what the user hears about.
    document["horizon"] = "a field from a later version"
    _write(path, document)

    with pytest.raises(UnsupportedSchemaVersionError) as caught:
        load_suite(path)

    message = str(caught.value)
    assert caught.value.kind == "suite"
    assert caught.value.found == 2
    assert "suite" in message
    assert "supported: 1" in message


def test_a_document_with_no_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    _write(path, {"suite_hash": "sha256:0", "body": {}})

    with pytest.raises(UnsupportedSchemaVersionError, match="absent"):
        load_suite(path)


def test_a_document_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text("[1, 2, 3]", encoding="utf-8", newline="\n")

    with pytest.raises(UnsupportedSchemaVersionError, match="absent"):
        load_suite(path)


def test_a_suite_file_carrying_an_unknown_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    save_suite(path, _minimal_body(), generator="assay/0.1.0")
    document = _read(path)
    document["signed_by"] = "someone"
    _write(path, document)

    with pytest.raises(ValidationError, match="signed_by"):
        load_suite(path)


def test_the_returned_suite_file_is_frozen(tmp_path: Path) -> None:
    written = save_suite(tmp_path / "suite.json", _minimal_body(), generator="assay/0.1.0")

    with pytest.raises(ValidationError, match="frozen"):
        written.generator = "assay/0.0.0"


def test_suite_file_is_the_type_both_directions_agree_on(tmp_path: Path) -> None:
    written = save_suite(tmp_path / "suite.json", _minimal_body(), generator="assay/0.1.0")

    assert isinstance(written, SuiteFile)
    assert isinstance(load_suite(tmp_path / "suite.json"), SuiteFile)
