from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.workflows.planning_contracts import collection_review_contract


def test_model_contract_separates_research_facts_from_paper_exclusion_quotes():
    schema = collection_review_contract(("run-fact",), (4,), [
        {"id": "paper-discussion", "findings": [{"id": "paper-quote"}]},
        {"id": "other-discussion", "findings": [{"id": "other-quote"}]},
    ])
    value = {"compatible": True, "rationale": "Fixture", "supporting_facts": ["run-fact"],
        "conflicts": [], "limitations": [],
        "task_mappings": [{"run": 4, "status": "verified", "finding_ids": ["run-fact"]}],
        "literature_exclusions": [{"entry_id": "paper-discussion", "object_type": "unspecified", "reported_ids": [],
            "finding_ids": ["paper-quote"], "claim_type": "unspecified", "object_quote": "excluded objects", "reason": "The source does not identify the excluded objects"}]}
    assert schema.model_validate(value).literature_exclusions[0].finding_ids == ["paper-quote"]
    for incorrect in ("run-fact", "other-quote", "invented"):
        wrong = deepcopy(value)
        wrong["literature_exclusions"][0]["finding_ids"] = [incorrect]
        with pytest.raises(ValidationError):
            schema.model_validate(wrong)


def test_no_discussion_evidence_cannot_generate_exclusion_claims():
    schema = collection_review_contract(("fact",), (4,), [])
    assert schema.model_json_schema()["properties"]["literature_exclusions"]["maxItems"] == 0
