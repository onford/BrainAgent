"""Model-facing operation contracts include the same bindings used by compilation."""

from typing import Annotated, Literal, Union

from pydantic import Field, create_model

from app.preprocessing.schemas import Contract
from .cognition_contracts import (
    CollectionReview,
)
from .survey_contracts import SearchGoal, SurveyPlan, LITERATURE_TARGETS


def verification_contract(local):
    from .survey_contracts import Comparison, DatasetVerification, FIELDS, SourceStatement

    # Prompt guidance belongs to the model-facing contract. Keep the stored
    # artifact schema stable when only instructions (not data fields) change.
    statement = create_model('CitedSourceStatement', __base__=SourceStatement,
        statement=(str | None, Field(min_length=1, description=(
            'A factual source statement supported by finding_ids. For missing evidence return JSON null; '
            'put absence explanations in the row conclusion/gaps, never here.'))),
        finding_ids=(list[str], Field(description=(
            'Nonempty exact finding IDs for a non-null statement; [] if and only if statement is null.'))))

    rows = []
    for field in FIELDS:
        rows.append(
            create_model(
                "Compare_" + field,
                __base__=Comparison,
                field=(Literal[field], ...),
                official_sources=(statement, ...),
                official_paper=(statement, ...),
                local_fact_ids=(
                    list[str],
                    Field(
                        max_length=0,
                        description="Return []; measured local references are attached deterministically after validation.",
                    ),
                ),
            )
        )
    return create_model(
        "DatasetVerification",
        __base__=DatasetVerification,
        comparisons=(
            list[Annotated[Union[tuple(rows)], Field(discriminator="field")]],
            Field(min_length=len(FIELDS), max_length=len(FIELDS)),
        ),
    )


def survey_plan_contract():
    def goal(target, medium):
        return create_model(
            f"{target}_{medium}",
            __base__=SearchGoal,
            target=(Literal[target], target),
            medium=(Literal[medium], medium),
        )

    verification = tuple[
        goal("official_sources", "official"), goal("official_publication", "paper")
    ]
    literature = tuple[
        tuple(goal(t, m) for t in LITERATURE_TARGETS for m in ("paper", "repository"))
    ]
    return create_model(
        "SurveyPlan",
        __base__=SurveyPlan,
        verification=(verification, ...),
        literature=(literature, ...),
    )


def collection_review_contract(finding_ids, runs, discussion=None):
    ids = tuple(finding_ids)
    mapping_models = tuple(
        create_model(
            f"Run{run}Mapping",
            __base__=Contract,
            run=(Literal[run], run),
            status=(Literal["verified", "unresolved", "contradictory"], ...),
            finding_ids=(
                list[Literal[ids]],
                Field(
                    description="Exact quoted evidence linking this run number to left/right motor imagery; acquisition or generic trigger evidence alone is insufficient."
                ),
            ),
        )
        for run in sorted(set(runs))
    )
    fields = {}
    if discussion is not None:
        from .collection_contracts import ReportedExclusion
        variants = tuple(create_model(f"Exclusions_{i}", __base__=ReportedExclusion,
            entry_id=(Literal[e["id"]], ...),
            finding_ids=(list[Literal[tuple(f["id"] for f in e["findings"])]], Field(min_length=1,
                description="Exact IDs from this literature entry; these are not source IDs or research-summary fact IDs.")))
            for i, e in enumerate(discussion) if e["findings"])
        if variants:
            item = variants[0] if len(variants) == 1 else Annotated[Union[variants], Field(discriminator="entry_id")]
            fields["literature_exclusions"] = (list[item], Field(default_factory=list))
        else:
            fields["literature_exclusions"] = (list[ReportedExclusion], Field(default_factory=list, max_length=0))
    return create_model(
        "CollectionReview",
        __base__=CollectionReview,
        supporting_facts=(list[Literal[ids]], Field(min_length=1)),
        task_mappings=(tuple[mapping_models], ...),
        **fields,
    )


def validate_task_mappings(value, findings):
    facts = {f.id: f for f in findings.facts}
    import re

    for mapping in value.task_mappings:
        if mapping.status == "verified":
            quotes = " ".join(facts[i].quote for i in mapping.finding_ids)
            if not re.search(rf"(?<!\d)0*{mapping.run}(?!\d)", quotes):
                raise ValueError(
                    "verified task mapping needs quoted evidence naming the run number"
                )
            if not set(mapping.finding_ids) <= set(value.supporting_facts):
                raise ValueError(
                    "task mapping findings must also be retained in supporting_facts"
                )
    if value.compatible and any(m.status != "verified" for m in value.task_mappings):
        raise ValueError(
            "unresolved or contradictory run/task mapping cannot be a nonblocking limitation; set compatible=false and obtain mapping evidence"
        )
