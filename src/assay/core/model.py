"""The pydantic base every Assay schema derives from.

The two settings below are load-bearing rather than stylistic, and putting them in one place
makes them structural instead of repeated-by-discipline on every model:

``extra="forbid"`` - a suite written by a *future* Assay version must fail loudly rather than
load with the fields this build does not know about silently dropped. A dropped field changes
the content hash, and a changed hash with no error is a result attributed to the wrong task
set (SPEC §8.7).

``frozen=True`` - a document that has been hashed must not be edited afterwards, or the hash
stops describing the object that is in memory.
"""

from pydantic import BaseModel, ConfigDict


class SchemaModel(BaseModel):
    """Base for every versioned, content-addressed document Assay reads or writes."""

    model_config = ConfigDict(frozen=True, extra="forbid")
