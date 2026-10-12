from typing import Dict

from src.sdk.python.metadata.model import NodeMetadata


class NodeRegistry:

    _functions: Dict[str, callable] = {}
    _metadata: Dict[str, NodeMetadata] = {}

    @classmethod
    def register(
        cls,
        func: callable,
        metadata: NodeMetadata
    ):
        cls._functions[metadata.name] = func
        cls._metadata[metadata.name] = metadata

    @classmethod
    def get_function(cls, name: str):
        return cls._functions.get(name)

    @classmethod
    def get_metadata(cls, name: str):
        return cls._metadata.get(name)

    @classmethod
    def all_nodes(cls):
        return cls._metadata

    @classmethod
    def clear(cls):
        cls._functions.clear()
        cls._metadata.clear()