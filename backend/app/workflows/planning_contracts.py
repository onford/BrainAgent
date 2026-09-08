"""Model-facing operation contracts include the same bindings used by compilation."""

from typing import Annotated, Literal, Union

from pydantic import Field, create_model

from app.preprocessing.units import OPERATIONS
from .cognition_contracts import CandidateDesign, MethodDesign, PlannedStep


def design_contract(finding_ids, request):
    ids = tuple(finding_ids)
    variants = []
    for (unit, op), parameters in OPERATIONS.items():
        bindings = {}
        if "picks" in parameters.model_fields:
            bindings["picks"] = (Literal["$eeg_channels"], "$eeg_channels")
        if "picks_artifact" in parameters.model_fields:
            bindings["picks_artifact"] = (Literal["$eog_channels"], "$eog_channels")
        if op == "epoch":
            bindings.update(
                event_id=(Literal["$event_id"], "$event_id"),
                tmin=(Literal[request["tmin"]], request["tmin"]),
                tmax=(Literal[request["tmax"]], request["tmax"]),
            )
        params = create_model(f"{op}Parameters", __base__=parameters, **bindings)
        variants.append(
            create_model(
                f"{op}Step",
                __base__=PlannedStep,
                op=(Literal[op], ...),
                unit_id=(Literal[unit], unit),
                params=(params, ...),
                finding_ids=(list[Literal[ids]], ...),
            )
        )
    step = Annotated[Union[tuple(variants)], Field(discriminator="op")]
    candidate = create_model(
        "CandidateDesign",
        __base__=CandidateDesign,
        steps=(list[step], Field(min_length=1, max_length=12)),
    )
    return create_model(
        "MethodDesign",
        __base__=MethodDesign,
        candidates=(list[candidate], Field(min_length=2, max_length=3)),
    )
