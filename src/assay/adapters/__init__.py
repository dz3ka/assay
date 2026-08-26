"""The adapter interface, and the two adapters that bracket every result run against it.

Import these names from ``assay.adapters`` rather than from the submodules; the split between
``protocol`` (the interface SPEC §6 fixes) and one module per adapter is an implementation
detail, this surface is not.

The M0 pair are both oracles rather than tools: the ground-truth adapter scores everything and
the null adapter scores nothing, and a harness that cannot tell the two apart is not measuring
anything (SPEC §9). Real adapters land in M3.
"""

from assay.adapters.ground_truth import GroundTruthAdapter
from assay.adapters.null import NullAdapter
from assay.adapters.protocol import Adapter

__all__ = [
    "Adapter",
    "GroundTruthAdapter",
    "NullAdapter",
]
