"""The adapter interface, the seams a real adapter is driven through, and the two oracles.

Import these names from ``assay.adapters`` rather than from the submodules; the split between
``protocol`` (the interface SPEC §6 fixes), one module per seam and one module per adapter is
an implementation detail, this surface is not.

The M0 pair are both oracles rather than tools: the ground-truth adapter scores everything and
the null adapter scores nothing, and a harness that cannot tell the two apart is not measuring
anything (SPEC §9). M3's real adapters are drivers over an injected seam - a
:class:`ModelTransport` for the naive baseline, a :class:`ToolProcess` for an agentic CLI -
declared here and bound in :mod:`assay.cli.main`. The seams are what keep ``adapters``, and
therefore ``score``, free of every process and every socket: the implementations live in
``host``, which nothing on this side of the line imports (ADR-0036).
"""

from assay.adapters.agentic import AgenticCliAdapter
from assay.adapters.ground_truth import GroundTruthAdapter
from assay.adapters.model import ModelResponse, ModelTransport, ModelTransportError
from assay.adapters.naive import NaiveBaselineAdapter
from assay.adapters.null import NullAdapter
from assay.adapters.process import ProcessOutput, ToolProcess
from assay.adapters.protocol import Adapter

__all__ = [
    "Adapter",
    "AgenticCliAdapter",
    "GroundTruthAdapter",
    "ModelResponse",
    "ModelTransport",
    "ModelTransportError",
    "NaiveBaselineAdapter",
    "NullAdapter",
    "ProcessOutput",
    "ToolProcess",
]
