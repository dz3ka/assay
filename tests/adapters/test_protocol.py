"""SPEC §6 titles the adapter interface "keep it this small", and this is where that is kept.

Every method on the protocol is a method each future adapter - an agentic CLI, an editor in
batch mode, a raw model call - has to implement, so widening it here is a cost paid once per
tool that is ever added. A test is a cheaper place to notice that than a code review is.
"""

from assay.adapters import Adapter


def test_the_interface_is_two_attributes_and_one_method() -> None:
    annotated = set(Adapter.__annotations__)
    methods = {name for name in vars(Adapter) if not name.startswith("_")} - annotated

    assert annotated == {"name", "version"}
    assert methods == {"run"}


def test_the_protocol_is_not_runtime_checkable() -> None:
    # Conformance is a static claim, checked by ``mypy --strict`` at each adapter's module
    # level. ``isinstance`` against a runtime-checkable protocol only asks whether the names
    # exist, so offering it here would advertise a proof it cannot give.
    assert not getattr(Adapter, "_is_runtime_protocol", False)
