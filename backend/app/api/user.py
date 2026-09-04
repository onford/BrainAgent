from pydantic import BaseModel


class CurrentUser(BaseModel):
    owner_id: str
