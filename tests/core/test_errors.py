"""The exception base is a contract about what a caller may catch, so it is asserted."""

from assay.core import AssayError, CanonicalizationError


def test_canonicalization_error_is_an_assay_error() -> None:
    assert issubclass(CanonicalizationError, AssayError)
