"""Registry of node implementations available in the current process."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import traceback
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from neuroweave.kernel.definitions import NodeDefinition
from neuroweave.sdk.introspection import RegisteredNode


class UnknownNodeError(KeyError):
    pass


class NodeRegistry:
    """Maps node definition ids (``module:qualname``) to implementations.

    Ids include the module, so equally named functions in different modules never collide.
    Re-registering the same id (e.g. after a module reload) replaces the previous entry.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, RegisteredNode] = {}

    def register(self, node: RegisteredNode) -> None:
        self._nodes[node.definition.id] = node

    def get(self, node_id: str) -> RegisteredNode:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise UnknownNodeError(f"No node registered with id '{node_id}'.") from None

    def resolve(self, reference: str) -> RegisteredNode:
        """Look up by full id, or by bare function name when it is unambiguous."""
        if reference in self._nodes:
            return self._nodes[reference]
        matches = [n for n in self._nodes.values() if n.definition.name == reference]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise UnknownNodeError(f"No node named '{reference}' is registered.")
        ids = ", ".join(sorted(n.definition.id for n in matches))
        raise UnknownNodeError(f"Node name '{reference}' is ambiguous: {ids}.")

    def definitions(self) -> list[NodeDefinition]:
        return [self._nodes[k].definition for k in sorted(self._nodes)]

    def catalog(self) -> dict[str, NodeDefinition]:
        return {k: n.definition for k, n in self._nodes.items()}

    def clear(self) -> None:
        self._nodes.clear()

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)


default_registry = NodeRegistry()


class ModuleLoadError(BaseModel):
    module: str
    error: str
    traceback: str


def load_node_modules(
    modules: Iterable[str], project_root: Path
) -> list[ModuleLoadError]:
    """Import (or reload) the project's node modules so their ``@node`` functions register.

    Packages are walked so every submodule is imported. Failures are collected and returned
    rather than raised, so one broken module does not hide the rest of the catalogue.
    """
    root = str(project_root.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    errors: list[ModuleLoadError] = []
    for name in modules:
        for module_name in _expand(name, errors):
            try:
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)
            except BaseException as exc:  # user code may raise anything, including SystemExit
                if isinstance(exc, KeyboardInterrupt):
                    raise
                errors.append(ModuleLoadError(module=module_name, error=f"{type(exc).__name__}: "
                                              f"{exc}", traceback=traceback.format_exc()))
    return errors


def _expand(name: str, errors: list[ModuleLoadError]) -> list[str]:
    try:
        module = sys.modules.get(name) or importlib.import_module(name)
    except BaseException as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        errors.append(ModuleLoadError(module=name, error=f"{type(exc).__name__}: {exc}",
                                      traceback=traceback.format_exc()))
        return []
    names = [name]
    if hasattr(module, "__path__"):
        names += [info.name for info in pkgutil.walk_packages(module.__path__, prefix=name + ".")]
    return names
