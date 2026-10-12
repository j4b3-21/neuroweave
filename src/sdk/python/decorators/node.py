from functools import wraps

from src.sdk.python.metadata.model import (
    NodeMetadata
)

from src.sdk.python.registry.registry import (
    NodeRegistry
)

from ..utils.introspection import (
    extract_parameters,
    extract_input_types,
    extract_output_type
)


def Node(
    category: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    cache: bool = True,
    version: bool = True,
):

    def decorator(func):

        metadata = NodeMetadata(
            name=func.__name__,
            qualified_name=(
                f"{func.__module__}"
                f".{func.__name__}"
            ),
            category=category,
            description=description,
            parameters=extract_parameters(func),
            input_types=extract_input_types(func),
            output_type=extract_output_type(func),
            cache_enabled=cache,
            version_enabled=version,
            tags=tags or []
        )

        NodeRegistry.register(
            func=func,
            metadata=metadata
        )

        @wraps(func)
        def wrapper(*args, **kwargs):

            result = func(
                *args,
                **kwargs
            )

            return result

        wrapper._metadata = metadata

        return wrapper

    return decorator