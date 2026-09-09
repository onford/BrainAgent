from typing import Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract
from app.search.contracts import SearchBudget

STAGES = (
    "data_survey",
    "data_collection",
    "data_preprocessing",
    "data_evaluation",
    "data_report",
    "data_delivery",
)
STAGE_LABELS = (
    "数据调研",
    "数据接入",
    "数据预处理",
    "结果选择",
    "数据报告",
    "数据交付",
)


class WorkflowRequest(Contract):
    source_root: str
    adapter: Literal["eegmmidb"] = "eegmmidb"
    subjects: list[str] = Field(default_factory=list)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    tmin: float = 0
    tmax: float = 2
    search_budget: SearchBudget = Field(default_factory=SearchBudget)

    @model_validator(mode="after")
    def valid(self):
        import re

        if self.tmin >= self.tmax:
            raise ValueError("tmin must precede tmax")
        if len(set(self.subjects)) != len(self.subjects) or any(
            not re.fullmatch(r"S\d{3}", s) for s in self.subjects
        ):
            raise ValueError("subjects must be unique EEGMMIDB IDs such as S001")
        return self
