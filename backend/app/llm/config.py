from pydantic import BaseModel


class LLMConfig(BaseModel):
    api_key: str | None
    base_url: str
    model: str
