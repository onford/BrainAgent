"""Citable research catalog; contextual claims are not automatically executable edges."""

from typing import Any, Literal
from pydantic import model_validator
from app.preprocessing.schemas import Contract


class ResearchSource(Contract):
    id: str
    title: str
    url: str
    kind: str
    locator: str
    version: str | None
    accessed_at: str
    evidence_scope: str
    limitations: str


class ResearchOperator(Contract):
    id: str
    name: str
    scope: str
    stage: str


class ResearchRelation(Contract):
    a: str
    b: str
    relation: str


class ResearchRule(Contract):
    id: str
    strength: Literal[
        "hard_math",
        "hard_contract",
        "conditional_empirical",
        "engineering",
        "conflict",
        "unknown",
    ]
    pairs: list[ResearchRelation]
    claim: str
    condition: str
    implication: str
    source_ids: list[str]
    derivation: str | None
    scope: str


class ResearchParameter(Contract):
    id: str
    operator: str
    parameter: str
    source_anchors: list[Any]
    exploration_space: dict[str, Any] | list[Any] | str
    exploration_status: str
    conditions: str
    validity_gates: str
    source_ids: list[str]


class PairCoverage(Contract):
    a: str
    b: str
    rule_ids: list[str]
    gap: str | None


class ScientificKnowledge(Contract):
    schema_version: Literal["1"] = "1"
    domain: str
    interpretation: str
    sources: list[ResearchSource]
    operators: list[ResearchOperator]
    rules: list[ResearchRule]
    parameters: list[ResearchParameter]
    pair_coverage: list[PairCoverage]

    @model_validator(mode="after")
    def complete_references(self):
        sources = {s.id for s in self.sources}
        operators = {o.id for o in self.operators}
        rules = {r.id for r in self.rules}
        for values in (self.sources, self.operators, self.rules, self.parameters):
            if len({v.id for v in values}) != len(values):
                raise ValueError("knowledge identifiers must be unique")
        for rule in self.rules:
            if not set(rule.source_ids) <= sources:
                raise ValueError("unknown rule source")
            if any(p.a not in operators or p.b not in operators for p in rule.pairs):
                raise ValueError("unknown operator in scientific relation")
        for parameter in self.parameters:
            if (
                parameter.operator not in operators
                or not set(parameter.source_ids) <= sources
            ):
                raise ValueError("unknown parameter operator/source")
        pairs = set()
        for pair in self.pair_coverage:
            key = tuple(sorted((pair.a, pair.b)))
            if (
                key in pairs
                or pair.a == pair.b
                or not set(key) <= operators
                or not set(pair.rule_ids) <= rules
            ):
                raise ValueError("invalid or duplicate pair coverage")
            pairs.add(key)
        if len(pairs) != len(operators) * (len(operators) - 1) // 2:
            raise ValueError(
                "every declared operator pair must have an explicit coverage entry"
            )
        return self
