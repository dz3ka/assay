"""The one gate between a repository's text and a report anybody else may read (SPEC §5.4).

Assay runs inside a customer's environment on a customer's private repository, and the report
is the single artefact that leaves it. So paths, identifiers and commit subjects are hashed
rather than printed, and :func:`redact` is total: it takes a whole :class:`~assay.report.Report`
and returns a whole one, with no per-field opt-out and no ``--no-redact`` flag in M0. An
opt-out would make redaction a habit callers remember instead of a property the pipeline has,
and the first renderer written in a hurry is where a private path would escape.

Four kinds of field are deliberately *not* hashed, because hashing them would destroy the
document rather than protect the repository. ``suite_hash`` is a digest of the task set, not
of the code, and it is what makes a result reproducible and attributable (SPEC §5.5). The tool
names are the finding itself: a report shared with a vendor has to say which tool is theirs.
The enum members are Assay's own vocabulary. And ``prices_source``, with the rates and dollars
beside it, is the reader's own text and the reader's own arithmetic - it never came from the
repository under evaluation, and a hashed provenance would leave the report's money
unattributable, which is the one thing SPEC §5.5 asks of it. Everything else in a report comes
from the repository and gets a token. The totality test in ``tests/report/test_redaction.py``
walks the serialised document instead of a field list, so a provenance field added by M1's
miner fails the suite until it is classified here.

The salt lives in a :class:`RedactionPolicy` and never enters a report. Without it a recipient
who guessed a path could confirm the guess by recomputing the hash, and two reports from the
same repository could be cross-referenced line by line.

Dependency direction (KICKOFF item 7): renderers depend on this module, this module depends on
:mod:`assay.report.model`, and never the other way round - which is why :data:`Redacted` is
declared next to the fields that hold one and merely re-exported from here.

Pure: hashing and model construction only. No I/O, no git, no clock - apart from
:meth:`RedactionPolicy.from_random`, which draws from the OS entropy source.
"""

import hmac
import secrets
from hashlib import sha256
from typing import Annotated, Literal, Self

from pydantic import Field

from assay.core import SchemaModel
from assay.report.model import Redacted, Report, TaskLine

# What a token is about. The kind is both the visible prefix on a token and part of the hashed
# message, so the same text filed under two kinds cannot produce one shared token.
type TokenKind = Literal["path", "ident", "message"]

# Full SHA-256 output width. A short salt would put the HMAC key inside the reach of a search
# over plausible salts, which is the one thing standing between a token and its plaintext.
SALT_BYTES = 32

# Hex characters kept from each digest. Enough that a collision across a suite of a few
# thousand tasks is not a practical concern, short enough that a report stays readable.
TOKEN_HEX_CHARS = 12

# Separates the kind from the raw text inside the hashed message. A NUL cannot occur in a path,
# an identifier or a commit subject, so no two (kind, raw) pairs can spell the same message -
# a property that would otherwise depend on no kind ever being a prefix of another.
_DOMAIN_SEPARATOR = "\0"

type Salt = Annotated[bytes, Field(min_length=SALT_BYTES, max_length=SALT_BYTES)]


class RedactionPolicy(SchemaModel):
    """The salt every token in one report is derived from.

    One policy per report: tokens are comparable within a document and meaningless across two,
    which is what stops a recipient joining two reports on a shared path.

    The salt has no default. A policy that fell back to a constant would still produce
    plausible-looking tokens while being reversible by anyone holding the same build, and the
    absence of a default is what makes that failure impossible rather than unlikely.
    """

    salt: Salt

    @classmethod
    def from_random(cls) -> Self:
        """Draw a fresh salt from the OS entropy source - the normal way to get a policy."""
        return cls(salt=secrets.token_bytes(SALT_BYTES))


def hash_token(policy: RedactionPolicy, kind: TokenKind, raw: str) -> Redacted:
    """Hash one piece of repo-derived text into the token a report may print for it.

    ``raw`` is typed ``str`` on purpose: this is the raw side of the boundary, the only place
    in the report layer that is allowed to see unredacted text. Everything downstream takes
    :data:`Redacted`, so the type checker refuses the path that skips this function.
    """
    message = f"{kind}{_DOMAIN_SEPARATOR}{raw}".encode()
    digest = hmac.new(policy.salt, message, sha256).hexdigest()
    return Redacted(f"{kind[0]}:{digest[:TOKEN_HEX_CHARS]}")


def _redact_task_line(line: TaskLine, policy: RedactionPolicy) -> TaskLine:
    """Hash a task line's three repo-derived fields, leaving an absent one absent.

    ``None`` passes through untouched. Hashing it would invent evidence - a token reads as
    "this task came from a path we are not showing you", when in fact no path was recorded
    (a M0 result set carries none at all).
    """
    return TaskLine(
        task_id=hash_token(policy, "ident", line.task_id),
        repo_path=None if line.repo_path is None else hash_token(policy, "path", line.repo_path),
        commit_subject=(
            None
            if line.commit_subject is None
            else hash_token(policy, "message", line.commit_subject)
        ),
        outcome=line.outcome,
    )


def redact(report: Report, policy: RedactionPolicy) -> Report:
    """Return the report again with every repo-derived string replaced by a token.

    Total by construction: the fields are named out rather than copied wholesale, so a field
    added to :class:`~assay.report.Report` in a later milestone does not silently pass through
    unredacted - it fails to compile here first.

    ``tools``, ``comparisons``, ``costs`` and ``prices_source`` are carried across unchanged:
    they hold tool names, scores, intervals, and the money the reader priced the run with,
    which are what the report is for. See this module's docstring for why that is a decision
    rather than an omission.
    """
    return Report(
        suite_hash=report.suite_hash,
        tools=report.tools,
        comparisons=report.comparisons,
        costs=report.costs,
        prices_source=report.prices_source,
        tasks=tuple(_redact_task_line(line, policy) for line in report.tasks),
    )
