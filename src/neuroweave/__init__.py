"""NeuroWeave: a graph-native platform for reproducible computational research.

Public SDK surface for researchers::

    from neuroweave import node, log_metric, Table, Figure, Markdown
"""

from pathlib import Path as File

from neuroweave.datatypes import Figure, Markdown, Table
from neuroweave.sdk import (
    Node,
    NodeRegistry,
    WorkflowBuilder,
    current_context,
    default_registry,
    log_metric,
    node,
)

__version__ = "0.2.0"

__all__ = [
    "File",
    "Figure",
    "Markdown",
    "Node",
    "NodeRegistry",
    "Table",
    "WorkflowBuilder",
    "__version__",
    "current_context",
    "default_registry",
    "log_metric",
    "node",
]
