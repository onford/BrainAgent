from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float = Field(default=180, gt=0, le=600, allow_inf_nan=False)
