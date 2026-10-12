"""Graph kernel: workflow model, types, validation, planning and serialisation.

The kernel has no dependency on the runtime, storage, server or Studio.
"""

from neuroweave.kernel.definitions import NodeDefinition, PortSpec
from neuroweave.kernel.diff import WorkflowDiff, diff_workflows
from neuroweave.kernel.model import Edge, NodeInstance, Position, Workflow
from neuroweave.kernel.planning import CycleError, downstream, topological_order, upstream
from neuroweave.kernel.serialization import dump_workflow, load_workflow, snapshot_hash
from neuroweave.kernel.types import TypeSpec
from neuroweave.kernel.validation import Issue, ValidationReport, validate_workflow

__all__ = [
    "CycleError",
    "Edge",
    "Issue",
    "NodeDefinition",
    "NodeInstance",
    "PortSpec",
    "Position",
    "TypeSpec",
    "ValidationReport",
    "Workflow",
    "WorkflowDiff",
    "diff_workflows",
    "downstream",
    "dump_workflow",
    "load_workflow",
    "snapshot_hash",
    "topological_order",
    "upstream",
    "validate_workflow",
]
