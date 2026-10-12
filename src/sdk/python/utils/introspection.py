import inspect
from typing import get_type_hints

from src.sdk.python.metadata.model import (
    ParameterMetadata,
)


def extract_parameters(func):

    signature = inspect.signature(func)

    hints = get_type_hints(func)

    parameters = []

    for name, parameter in signature.parameters.items():

        annotation = hints.get(name)

        parameters.append(
            ParameterMetadata(
                name=name,
                type=(
                    annotation.__name__
                    if annotation
                    else "Any"
                ),
                default=(
                    None
                    if parameter.default
                    is inspect._empty
                    else parameter.default
                ),
                required=(
                    parameter.default
                    is inspect._empty
                )
            )
        )

    return parameters


def extract_input_types(func):

    hints = get_type_hints(func)

    result = {}

    for key, value in hints.items():

        if key == "return":
            continue

        result[key] = value.__name__

    return result


def extract_output_type(func):

    hints = get_type_hints(func)

    return_type = hints.get("return")

    if return_type:
        return return_type.__name__

    return None