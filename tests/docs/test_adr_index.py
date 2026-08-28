"""The decision record is a document set with a shape, so the shape is asserted, not trusted.

Three properties carry this module, and each one fails a different way in practice.

The first is that the set is *closed*: ADRs are numbered sequentially from 0001 and none of
the numbers is missing, so a file added out of band - or a number quietly skipped - shows up
here rather than in a reader's head.

The second is that every ADR answers the four questions the template asks (`docs/adr/README.md`).
An ADR that records a decision without the alternatives that lost is the failure mode CLAUDE.md
names: a record written retroactively, which reads as a rationalisation.

The third is that the index and the directory agree *in both directions*. An ADR missing from
the index is invisible; a row pointing at a file that does not exist is a dead link in the one
document whose job is navigation. Neither half implies the other, so both are asserted.

The files are discovered by glob rather than listed: a test that hardcodes ten paths passes for
as long as somebody remembers to edit it, which is precisely the discipline these tests replace.
The one exception is the count, because there the number *is* the assertion.
"""

import re
from pathlib import Path

import pytest

ADR_DIR = Path(__file__).parent.parent.parent / "docs" / "adr"
INDEX = ADR_DIR / "README.md"

# Sequentially numbered ADRs only; `README.md` is the index, not a decision.
ADRS = sorted(ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md"))
ADR_IDS = [path.name for path in ADRS]

# The four headings `docs/adr/README.md` templates, verbatim and in the order it lists them.
REQUIRED_HEADINGS = (
    "## Context",
    "## Decision",
    "## Alternatives considered",
    "## Consequences",
)

# SPEC section 8 names seven decisions; M0's implementation forced five more and M1's forced
# seven. Nineteen is the number a reviewer should find, so a missing or unnumbered twentieth
# fails here.
EXPECTED_NUMBERS = {f"{number:04d}" for number in range(1, 20)}

# A markdown link target that names an ADR file: `[0005](0005-no-winner-....md)`.
_ADR_LINK = re.compile(r"\]\((\d{4}-[a-z0-9-]+\.md)\)")


def indexed_filenames() -> set[str]:
    """The ADR filenames the index's `## Index` table links to.

    Only that section counts. ADRs cross-reference each other by the same link form, and the
    index's own template block shows the file-naming rule, so reading the whole document would
    let a link from anywhere stand in for a row in the table.
    """
    text = INDEX.read_text(encoding="utf-8")
    _, separator, table = text.partition("\n## Index\n")
    assert separator, "docs/adr/README.md has no '## Index' section"
    return set(_ADR_LINK.findall(table))


def test_the_decision_record_is_exactly_adrs_0001_through_0019() -> None:
    assert {path.name[:4] for path in ADRS} == EXPECTED_NUMBERS


@pytest.mark.parametrize("adr", ADRS, ids=ADR_IDS)
def test_every_adr_answers_the_four_questions_the_template_asks(adr: Path) -> None:
    lines = adr.read_text(encoding="utf-8").splitlines()
    headings = [line for line in lines if line.startswith("## ")]

    assert headings == list(REQUIRED_HEADINGS)


@pytest.mark.parametrize("adr", ADRS, ids=ADR_IDS)
def test_every_adr_has_a_row_in_the_index(adr: Path) -> None:
    assert adr.name in indexed_filenames()


def test_the_index_lists_no_adr_that_does_not_exist() -> None:
    # The cheap half of the same agreement, and the one a rename breaks: moving a file updates
    # the glob above silently while the index keeps pointing at the old name.
    missing = {name for name in indexed_filenames() if not (ADR_DIR / name).is_file()}

    assert missing == set()
