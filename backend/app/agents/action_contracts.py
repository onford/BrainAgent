from typing import Any

from pydantic import BaseModel, ValidationError

from app.preprocessing.invasive.schemas import (
    InvasivePlanRequest,
    InvasiveRunRequest,
    NWBInspectRequest,
)


class ActionInputError(ValueError):
    """A routed action does not satisfy its registered execution contract."""


_REQUEST_MODELS: dict[str, type[BaseModel]] = {
    "invasive_inspect": NWBInspectRequest,
    "invasive_plan": InvasivePlanRequest,
    "invasive_run": InvasiveRunRequest,
}


def normalize_action_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate known action payloads before they reach an executing Agent."""

    action = inputs.get("action")
    model = _REQUEST_MODELS.get(action) if isinstance(action, str) else None
    if model is None:
        return inputs
    try:
        request = model.model_validate(inputs.get("request"))
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_input=False)
        raise ActionInputError(f"invalid {action} request: {errors}") from exc
    return {**inputs, "request": request.model_dump(mode="json")}
