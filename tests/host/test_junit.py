"""What one junit report is allowed to say, read as text rather than as a file on disk.

:mod:`assay.host.pytest_runner` proves this reading against a real pytest 9.1.1 subprocess.
What is pinned here is the other half of the same question: given the XML that run wrote,
which node ids get a status, which files are named as uncollectable, and what a report that
is missing or truncated is allowed to imply. M2's sandbox scorer reads a junit report it did
not run itself, so the shapes below are the contract between the two callers - one gate, one
scorer, one verdict on the same bytes.

``TestStatus`` is imported under an alias: pytest collects any module-level ``Test*`` class,
and importing it under its own name would warn on every run of this file.
"""

from assay.host.junit import build_test_report
from assay.mine.models import TestStatus as Status

# The shape pytest writes, declaration and all - the declaration is load-bearing, because a
# parser handed the *string* rather than its bytes refuses an encoding declaration outright.
_REPORT = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="1" skipped="1" tests="5" time="0.05">\
<testcase classname="pkg.sub.test_deep" name="test_plain" time="0.001" />\
<testcase classname="pkg.sub.test_deep" name="test_fails" time="0.001">\
<failure message="assert 1 == 2">E    assert 1 == 2</failure></testcase>\
<testcase classname="pkg.sub.test_deep" name="test_errors_in_setup" time="0.001">\
<error message="test setup failure">E    RuntimeError: boom in setup</error></testcase>\
<testcase classname="pkg.sub.test_deep" name="test_skipped" time="0.001">\
<skipped type="pytest.skip" message="no reason">skipped</skipped></testcase>\
<testcase classname="pkg.sub.test_deep.TestThing" name="test_p[1]" time="0.001" />\
</testsuite></testsuites>
"""

# One unimportable module, which is a whole-run verdict rather than a per-test one: the empty
# classname is the discriminator and the name is the dotted module path, not a file name.
_COLLECT_ERROR = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="0" skipped="0" tests="1" time="0.01">\
<testcase classname="" name="pkg.sub.test_bad" time="0.001">\
<error message="collection failure">ImportError: this module refuses to import</error>\
</testcase></testsuite></testsuites>
"""

_COLLECTED = """\
pkg/sub/test_deep.py::test_plain
pkg/sub/test_deep.py::test_fails
pkg/sub/test_deep.py::test_errors_in_setup
pkg/sub/test_deep.py::test_skipped
pkg/sub/test_deep.py::TestThing::test_p[1]

5 tests collected in 0.03s
"""


def test_every_collected_id_carries_the_status_the_report_gave_it() -> None:
    # The four shapes the gate acts on, keyed by node id rather than by junit's own
    # (classname, name): a plain pass, a failure, an error raised outside the test body, and
    # a parametrised method on a class - which junit spells as a nested classname. The
    # skipped case is absent on purpose: a test that did not run is evidence of nothing.
    report = build_test_report(
        collected_stdout=_COLLECTED,
        junit_xml=_REPORT,
        selectors=["pkg/sub/test_deep.py"],
        exit_code=1,
    )

    assert dict(report.statuses) == {
        "pkg/sub/test_deep.py::TestThing::test_p[1]": Status.PASSED,
        "pkg/sub/test_deep.py::test_errors_in_setup": Status.ERRORED,
        "pkg/sub/test_deep.py::test_fails": Status.FAILED,
        "pkg/sub/test_deep.py::test_plain": Status.PASSED,
    }
    assert report.uncollectable == ()
    assert report.exit_code == 1
    assert not report.timed_out


def test_a_selected_node_id_is_known_even_when_collection_printed_nothing() -> None:
    # A run that refused its selection prints no ids, and the ids Assay itself asked for are
    # still the ones a task names. The union is what makes a status findable at all.
    report = build_test_report(
        collected_stdout="",
        junit_xml=_REPORT,
        selectors=["pkg/sub/test_deep.py::test_fails", "pkg/sub"],
        exit_code=1,
    )

    assert dict(report.statuses) == {"pkg/sub/test_deep.py::test_fails": Status.FAILED}


def test_an_empty_classname_names_an_uncollectable_file_and_not_a_test() -> None:
    # The ordinary shape of red at a parent commit: a new test importing something the fix
    # has not added yet. The file is named repo-relative and POSIX, and the id selected from
    # it gets a status of its own - "did not run because its module would not import".
    report = build_test_report(
        collected_stdout="",
        junit_xml=_COLLECT_ERROR,
        selectors=["pkg/sub/test_bad.py::test_never"],
        exit_code=2,
    )

    assert report.uncollectable == ("pkg/sub/test_bad.py",)
    assert dict(report.statuses) == {"pkg/sub/test_bad.py::test_never": Status.COLLECT_ERROR}


def test_an_id_the_report_says_nothing_about_is_absent_rather_than_guessed_at() -> None:
    # Silence is not a pass. An id that collection resolved but the report never mentions -
    # the run aborted before reaching it - has no status at all.
    report = build_test_report(
        collected_stdout="pkg/sub/test_deep.py::test_never_reached\n",
        junit_xml=_REPORT,
        selectors=["pkg/sub"],
        exit_code=1,
    )

    assert "pkg/sub/test_deep.py::test_never_reached" not in report.statuses


def test_no_report_at_all_is_no_evidence_rather_than_an_empty_green() -> None:
    # pytest writes the XML as it exits, so a mined test that takes the process down with it
    # (``os._exit``, a segfault) leaves nothing to read. The report is empty and the exit code
    # travels raw, which is the shape every rule in ``assay.mine.gate`` discards.
    report = build_test_report(
        collected_stdout=_COLLECTED, junit_xml=None, selectors=["pkg/sub"], exit_code=-9
    )

    assert dict(report.statuses) == {}
    assert report.uncollectable == ()
    assert report.exit_code == -9
    assert not report.timed_out


def test_a_truncated_report_is_read_the_same_way_as_a_missing_one() -> None:
    # The same run, killed one write earlier. Unparsable XML may not be allowed to look like
    # a run in which nothing failed.
    truncated = _REPORT[: _REPORT.index("<testcase")]

    report = build_test_report(
        collected_stdout=_COLLECTED, junit_xml=truncated, selectors=["pkg/sub"], exit_code=1
    )

    assert dict(report.statuses) == {}
    assert report.uncollectable == ()


def test_a_run_that_collected_nothing_reports_nothing_and_says_so_with_its_exit_code() -> None:
    # pytest's empty testsuite, which arrives with exit 4 (a node id that did not resolve) or
    # exit 5 (a selection with nothing collectable in it). Telling the two apart is the gate's
    # business, so the code travels untouched and the statuses stay empty.
    empty = '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite name="pytest" \
errors="0" failures="0" skipped="0" tests="0" time="0.01" /></testsuites>\n'

    report = build_test_report(
        collected_stdout="",
        junit_xml=empty,
        selectors=["pkg/sub/test_deep.py::test_absent"],
        exit_code=4,
    )

    assert dict(report.statuses) == {}
    assert report.uncollectable == ()
    assert report.exit_code == 4
