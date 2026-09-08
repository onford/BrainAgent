from pydantic import BaseModel, Field
from typing import Literal


class LLMConfig(BaseModel):
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float = Field(default=180, gt=0, le=600, allow_inf_nan=False)
    reasoning_effort: Literal["low", "high", "max"] | None = None
