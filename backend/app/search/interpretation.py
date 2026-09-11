"""Reviewed observations and counter-hypotheses, never scoring rules.

The catalog is frozen with each new search and made available to the existing
budgeted request_evidence mechanism. Reading historical runs never migrates it.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    url: str
    locator: str
    evidence: str
    accessed_at: str


class Card(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    metrics: list[str] = Field(min_length=1)
    evidence_level: str
    conditions: list[str] = Field(min_length=1)
    reading: str
    alternatives: list[str] = Field(min_length=1)
    checks: list[str] = Field(min_length=1)
    forbidden_inference: str
    parameters: dict[str, str]
    source_ids: list[str] = Field(min_length=1)


class Guide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    reviewed_at: str
    scope: str
    sources: list[Source]
    cards: list[Card]
    research_gaps: list[dict[str, str]]

    @model_validator(mode="after")
    def references(self):
        ids = {s.id for s in self.sources}
        if len(ids) != len(self.sources) or len({c.id for c in self.cards}) != len(self.cards):
            raise ValueError("duplicate interpretation source/card")
        if any(not set(c.source_ids) <= ids for c in self.cards):
            raise ValueError("unknown interpretation source")
        if any(not s.url.startswith("https://") for s in self.sources):
            raise ValueError("external sources must use HTTPS")
        return self


def interpretation_guide():
    path = Path(__file__).parent / "resources/interpretation-guide.json"
    return Guide.model_validate_json(path.read_text(encoding="utf-8")).model_dump(mode="json")


def evidence_document(guide):
    from app.preprocessing.storage import digest

    text = json.dumps(guide, ensure_ascii=False, indent=2)
    return {"id": "interpretation-guide", "title": "图表与指标解读：条件、竞争解释、参数和来源",
            "url": "brainagent:interpretation-guide:" + guide["schema_version"],
            "text": text, "sha256": digest(text)}


def interpretation_context(documents):
    """Use the run's saved document only, including for old/offline runs."""
    document = next((s for s in documents if s["id"] == "interpretation-guide"), None)
    if document is None:
        return {"status": "not_frozen_in_this_run", "cards": []}
    guide = Guide.model_validate_json(document["text"])
    return {"status": "frozen", "schema_version": guide.schema_version,
            "source_id": "interpretation-guide",
            "workflow": ["核对阶段、单位、分母、频带和适用状态", "引用实测数值路径",
                         "列出机制及竞争解释", "选择能区分解释的合法诊断",
                         "通过 request_evidence 阅读完整知识卡和来源定位", "登记预测并用实测反例更新解释"],
            "cards": [{"id": c.id, "metrics": c.metrics, "reading": c.reading,
                       "alternatives": c.alternatives, "checks": c.checks,
                       "conditions": c.conditions, "forbidden_inference": c.forbidden_inference}
                      for c in guide.cards]}
