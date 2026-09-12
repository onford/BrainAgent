"""Two purposes share retrieval tools, but not completion or acceptance criteria."""

from types import SimpleNamespace
from typing import Literal

from pydantic import Field, create_model
from .source_reader import abstract_only
from .planning_contracts import survey_plan_contract
from .screening import ScreeningSelection, urls

from .cognition_contracts import (
    ResearchAction,
    ResearchBatch,
    ResearchFindings,
    ResearchSources,
)
from .survey_contracts import (
    DatasetVerification,
    DESTINATIONS,
    LITERATURE_TARGETS,
    LiteratureCoverage,
    LiteratureReview,
    LocalInspection,
    SELECTION_CRITERIA,
    SurveyPlan,
)

SCREENING_OPERATION = "筛选方法文献与仓库，注明下游用途"


def available_tools(catalog, medium):
    categories = {'code', 'literature'} if medium == 'official' else {'code' if medium == 'repository' else 'literature'}
    return {
        t["name"] for t in catalog if t["available"] and t.get("category") in categories
    }


def missing_tasks(sources, goals, catalog, purpose, *, actionable_only=False):
    """Keep evidence gaps distinct from the bounded attempts required before finish."""
    missing = []
    documents = {d.id: d for d in sources.documents}
    for goal in goals:
        observations = [
            o
            for o in sources.observations
            if o.action.purpose == purpose
            and o.action.target == goal.target
            and o.action.medium == goal.medium
        ]
        if goal.medium == "official":
            if not any(o.success and o.action.action == "read" for o in observations):
                missing.append(f"{goal.target}: read the official dataset source")
            continue
        tools = available_tools(catalog, goal.medium)
        if not tools:
            if not actionable_only:
                missing.append(
                    f"{goal.target}/{goal.medium}: no available search provider"
                )
            continue
        searches = [o for o in observations if o.action.action == "search"]
        hits = [o for o in searches if o.success and o.output and o.output.get("items")]
        if not searches:
            missing.append(f"{goal.target}/{goal.medium}: search")
        elif not hits:
            attempts = {
                (o.action.tool, " ".join((o.action.query or "").lower().split()))
                for o in searches
            }
            # Try each configured provider, and at least two distinct queries if
            # only one is available. Repeating the same request is not a fallback.
            retry = bool(tools - {tool for tool, _ in attempts}) or len(attempts) < 2
            if not actionable_only or retry:
                reason = (
                    "no results"
                    if any(o.success for o in searches)
                    else "all searches failed"
                )
                missing.append(
                    f"{goal.target}/{goal.medium}: {reason}; try another provider or broader alias query; retain gap if exhausted"
                )
        else:
            reads = [o for o in observations if o.action.action == "read"]
            usable = any(
                o.success
                and (doc := documents.get((o.output or {}).get("source_id")))
                is not None
                and (goal.medium != "paper" or not abstract_only(doc))
                for o in reads
            )
            if usable:
                continue
            read_urls = {o.action.url for o in reads}
            candidates = urls([o.output for o in hits])
            candidates.update(
                link
                for o in reads
                if (doc := documents.get((o.output or {}).get("source_id"))) is not None
                for link in doc.links
            )
            retry = not reads or (len(read_urls) < 2 and bool(candidates - read_urls))
            if actionable_only and not retry:
                continue
            missing.append(
                f"{goal.target}/{goal.medium}: read a relevant returned source; no substantive text read yet; try full text or another candidate, retain access gaps"
            )
    return missing


async def retrieve(agent, plan, inputs, sources, catalog, purpose, budget):
    from .research_journal import ResearchJournal
    from .research_progress import progress
    from app.preprocessing.storage import write_json

    goals = plan.verification if purpose == "dataset_verification" else plan.literature
    valid_pairs = {(g.target, g.medium) for g in goals}
    journal = ResearchJournal(agent.folder / agent.prefix / "research-journal.json", sources)
    journal.bind_budget(purpose, budget, {"inputs": inputs, "goals": [g.model_dump() for g in goals]}, budget * 90)
    journal.restore(sources, include_uncertain=True)
    agent.save(agent.prefix + "/sources.json", sources)
    available = {
        t["name"]
        for t in catalog
        if t["available"] and t.get("category") in {"literature", "code"}
    }
    stop_reason, rationale = None, None
    while (remaining := journal.remaining(purpose)):
        missing = missing_tasks(sources, goals, catalog, purpose)
        measured_progress = progress(journal, purpose, missing)
        write_json(agent.folder / agent.prefix / f'{purpose}-progress.json', measured_progress)
        pending = missing_tasks(sources, goals, catalog, purpose, actionable_only=True)
        action_schema = create_model(
            "SurveyAction",
            __base__=ResearchAction,
            purpose=(Literal[purpose], purpose),
            target=(Literal[tuple(sorted({g.target for g in goals}))], ...),
            medium=(Literal[tuple(sorted({g.medium for g in goals}))], ...),
        )
        batch_schema = create_model(
            "ResearchBatch",
            __base__=ResearchBatch,
            actions=(
                list[action_schema],
                Field(min_length=1, max_length=min(4, remaining)),
            ),
        )

        def validate(batch):
            for a in batch.actions:
                if a.action == "finish":
                    if pending:
                        raise ValueError(
                            "Required research tasks remain: " + "; ".join(pending)
                        )
                    continue
                if (a.target, a.medium) not in valid_pairs:
                    raise ValueError(
                        "target/medium must match a goal for this research purpose"
                    )
                if a.action == "search" and a.tool not in available_tools(
                    catalog, a.medium
                ):
                    raise ValueError(
                        f"Search medium={a.medium} must use one of {sorted(available_tools(catalog, a.medium))}; received {a.tool}. "
                        "Paper searches use literature providers; repository searches use code providers; official-source discovery allows both."
                    )
                if a.action == "read" and (
                    (a.medium == "repository" and a.kind != "code")
                    or (a.medium == "paper" and a.kind != "paper")
                ):
                    raise ValueError(
                        "repository reads require kind=code; paper reads require kind=paper"
                    )

        batch = await agent.ask(
            "核对数据来源：安排阅读"
            if purpose == "dataset_verification"
            else "方法文献调研：安排阅读",
            batch_schema,
            {
                **inputs,
                "purpose": purpose,
                "goals": [g.model_dump() for g in goals],
                "tool_catalog": catalog,
                "sources": agent.source_context(sources),
                "observations": [o.model_dump() for o in sources.observations],
                "missing_requirements": missing,
                "required_next_attempts": pending,
                "remaining_actions": remaining,
                "measured_retrieval_progress": {**measured_progress, 'actions': measured_progress['actions'][-8:]},
                "selection_criteria": SELECTION_CRITERIA,
            },
            "Choose 1-4 independent search/read actions, or finish alone. Each action declares its goal target and medium. "
            "Batch independent sources; follow newly discovered links only in later batches. Search broadly by dataset aliases and task, not subject IDs. "
            "For dataset_verification, read the official website/repository and identify/read the OFFICIAL DATASET publication using its citation trail. "
            "An acquisition-system paper (e.g. BCI2000) or a paper merely using the dataset is not automatically its dataset paper; retain unconfirmed identity as a gap. "
            "For literature_review, cover analysis AND algorithm uses, dataset issues/discussion, and preprocessing of this data type; search papers AND repositories for each. "
            "Prefer reputable venues, high citations and high-star repos where observed; no invented metrics or arbitrary hard cutoff. "
            "Read useful fulltext/PDF and repository README/code, not just search titles. Discover associated PDF/repo links. "
            "For preprocessing, a data-loader API page, repository directory listing, or README linking an unread implementation does not establish a method. "
            "Follow discovered implementation/configuration dependencies until the whole preprocessing sequence and its parameter evidence are readable, "
            "or explicitly retain that gap. Select sources for scientific relevance and evidence completeness, without a fixed paper quota or preferred recipe. "
            "GitHub repository roots and blob file URLs are read through the public file API; retry failed HTML reads using these URLs and follow README links to substantive code. "
            "Usage literature must itself use the target dataset; a related-work citation alone is insufficient. Follow the cited primary work. "
            "Use read.query for excerpts beyond source previews. Failed/empty searches do not establish absence: satisfy required_next_attempts by changing provider or broadening the query with dataset aliases and English topic keywords. "
            "Read failures and abstract-only reads leave evidence gaps; try a returned full-text link or another candidate. After bounded attempts, retain missing_requirements as gaps even when finishing. Do not repeat successful actions. "
            "Use measured content/URL/excerpt novelty to avoid duplicate work; these counts alone do not establish scientific sufficiency. Finish once required searches/reading attempts are done and sufficient evidence exists, or retain explicit gaps if no useful source remains. State the concrete stopping reason; never claim exhaustive coverage from this bounded search.",
            validate,
        )
        if batch.actions[0].action == "finish":
            stop_reason, rationale = 'model_finished', batch.actions[0].rationale
            break
        await agent.research_batch(batch.actions, sources, available)
    missing = missing_tasks(sources, goals, catalog, purpose)
    if stop_reason is None:
        from time import time
        stop_reason = 'deadline_expired' if time() >= journal.read()['budgets'][purpose]['expires_at'] else 'action_budget_exhausted'
    write_json(agent.folder / agent.prefix / f'{purpose}-progress.json',
        progress(journal, purpose, missing, stop_reason=stop_reason, rationale=rationale))
    return missing


def validate_verification(agent, value, sources, local):
    agent.validate_findings(SimpleNamespace(facts=value.facts, literature=[]), sources)
    facts = {f.id: f for f in value.facts}
    docs = {d.id: d for d in sources.documents}
    local_facts = {f.id: f for f in local.facts}
    publication = value.official_publication
    if publication.role != "not_identified":
        if (
            publication.source_id not in docs
            or docs[publication.source_id].kind != "paper"
        ):
            raise ValueError(
                "identified official publication must be an actually read paper"
            )
        if (
            not publication.basis_finding_ids
            or not set(publication.basis_finding_ids) <= facts.keys()
        ):
            raise ValueError(
                "official publication identity requires cited verification findings"
            )
        if publication.role == "dataset_paper" and not (
            any(
                docs[facts[i].source_id].kind == "official"
                for i in publication.basis_finding_ids
            )
            and any(
                facts[i].source_id == publication.source_id
                for i in publication.basis_finding_ids
            )
        ):
            raise ValueError(
                "dataset_paper identity needs evidence from both an official source and the paper itself"
            )
    elif publication.source_id is not None:
        raise ValueError("not_identified publication must have source_id=null")
    problems = []
    for row in value.comparisons:
        try:
            if not set(row.local_fact_ids) <= local_facts.keys() or any(
                local_facts[i].field != row.field for i in row.local_fact_ids
            ):
                raise ValueError(
                    f"{row.field}: local IDs must refer to observed facts for that exact field"
                )
            # The model cannot hide observed records by omitting their local IDs.
            row.local_fact_ids = [
                f.id for f in local_facts.values() if f.field == row.field
            ]
            for side, kinds in (
                (row.official_sources, {"official", "documentation", "code"}),
                (row.official_paper, {"paper"}),
            ):
                if not set(side.finding_ids) <= facts.keys():
                    raise ValueError(f"{row.field}: unknown finding IDs")
                if side.statement is not None and not side.finding_ids:
                    raise ValueError(
                        f"{row.field}: source statement requires evidence, otherwise use null"
                    )
                if any(
                    docs[facts[i].source_id].kind not in kinds for i in side.finding_ids
                ):
                    raise ValueError(
                        f"{row.field}: evidence assigned to the wrong comparison column"
                    )
            if row.official_paper.finding_ids and (
                publication.role != "dataset_paper"
                or any(
                    facts[i].source_id != publication.source_id
                    for i in row.official_paper.finding_ids
                )
            ):
                raise ValueError(
                    "official-paper comparison cannot use a methods/acquisition-system paper as dataset authority"
                )
            if row.status == "consistent" and not (
                row.local_fact_ids
                and row.official_sources.finding_ids
                and row.official_paper.finding_ids
            ):
                raise ValueError(
                    f"{row.field}: consistent requires all three sides; use partial/unverifiable for missing evidence"
                )
        except ValueError as exc:
            problems.append(str(exc))
    if problems:
        raise ValueError("; ".join(problems))


def validate_screening(agent, value, sources, reserved_finding_ids=()):
    docs = {d.id: d for d in sources.documents}
    observations = {o.sequence: o for o in sources.observations}
    ids, problems = set(), []
    finding_ids = set(reserved_finding_ids)
    for entry in value.entries:
        if entry.id in ids:
            problems.append(f"{entry.id}: literature entry IDs must be unique")
        ids.add(entry.id)
        for fact in entry.findings:
            if fact.id in finding_ids:
                problems.append(
                    f"{entry.id}: finding ID {fact.id} must be unique across entries and verification"
                )
            finding_ids.add(fact.id)
        try:
            validate_entry(agent, entry, sources, docs, observations)
        except ValueError as exc:
            problems.append(f"{entry.id}: {exc}")
    if problems:
        raise ValueError("; ".join(problems))


def validate_entry(agent, entry, sources, docs, observations):
    if entry.source_id not in docs:
        raise ValueError(
            "screened entries must reference read sources; unread search hits remain coverage gaps"
        )
    doc = docs[entry.source_id]
    if doc.kind != ("paper" if entry.medium == "paper" else "code"):
        raise ValueError("paper/repository classification must match the read source")
    source_origins = {doc.url} | {
        o.action.url
        for o in sources.observations
        if o.output and o.output.get("source_id") == doc.id
    }
    associated_items = [
        item
        for o in sources.observations
        for item in (o.output or {}).get("items", [])
        if urls(item) & source_origins
    ]
    allowed_links = set(doc.links) | source_origins | urls(associated_items)
    if not set(entry.related_urls) <= allowed_links:
        raise ValueError(
            "PDF/repository links must belong to this source's links or its associated search result; "
            f"remove unverified links: {sorted(set(entry.related_urls) - allowed_links)}"
        )
    agent.validate_findings(
        SimpleNamespace(facts=entry.findings, literature=[]), sources
    )
    if any(f.source_id != entry.source_id for f in entry.findings):
        raise ValueError("entry findings must quote this entry's source")
    if entry.reading_scope == "full_text" and (
        doc.truncated or len(doc.text) > 24000 or abstract_only(doc)
    ):
        raise ValueError(
            "a preview, truncated text or abstract cannot be marked full_text"
        )
    if entry.medium == "paper" and entry.reading_scope in {
        "repository_docs",
        "code",
    }:
        raise ValueError("paper reading_scope cannot be repository_docs or code")
    if entry.decision == "included" and (
        not entry.findings or entry.reading_scope == "abstract" or abstract_only(doc)
    ):
        raise ValueError(
            "included literature needs substantive quoted evidence; abstract-only entries are deferred"
        )
    if entry.exclusions and (
        entry.target != "dataset_discussion" or not entry.findings
    ):
        raise ValueError("reported exclusions need dataset-discussion evidence")
    q = entry.quality
    if not set(q.observation_ids) <= observations.keys():
        raise ValueError("unknown quality-metric observation")
    source_urls = {doc.url, *entry.related_urls} | {
        o.action.url
        for o in sources.observations
        if o.output and o.output.get("source_id") == doc.id
    }
    matched = [
        item
        for i in q.observation_ids
        for item in (observations[i].output or {}).get("items", [])
        if urls(item) & source_urls
    ]
    for name in ("venue", "citations", "stars"):
        metric = getattr(q, name)
        if metric is not None and not any(item.get(name) == metric for item in matched):
            raise ValueError(
                f"{name} must match an associated search result; use null if unknown"
            )


def coverage_table(screening, sources, catalog):
    rows = []
    for target in LITERATURE_TARGETS:
        for medium in ("paper", "repository"):
            searches = [
                o.sequence
                for o in sources.observations
                if o.action.purpose == "literature_review"
                and o.action.target == target
                and o.action.medium == medium
                and o.action.action == "search"
            ]
            included = [
                e.id
                for e in screening.entries
                if e.target == target
                and e.medium == medium
                and e.decision == "included"
            ]
            explanation = (
                "有已读取并通过筛选的资料"
                if included
                else (
                    "该类检索工具不可用"
                    if not available_tools(catalog, medium)
                    else "尚无已读取且通过筛选的资料；见检索记录及候选筛选理由"
                )
            )
            rows.append(
                LiteratureCoverage(
                    target=target,
                    medium=medium,
                    destinations=DESTINATIONS[target],
                    status="covered" if included else "gap",
                    search_observation_ids=searches,
                    included_entry_ids=included,
                    explanation=explanation,
                )
            )
    return rows


async def research(agent, survey):
    local = agent.load("survey/local-inspection.json", LocalInspection)
    from .local_contracts import LocalObservation

    inputs = {
        "request": agent.state["request"],
        "adapter_profile_to_verify": survey["profile"],
        "local_inspection": local.research_context()
        if isinstance(local, LocalObservation)
        else local.model_dump(),
        "local_reference_policy": "Output local_fact_ids=[]; code attaches all measured references for each comparison field. Record groups enumerate all members and distinct measured values, not a sample.",
        "verification_source_candidates": survey["evidence"],
    }
    plan = (
        agent.load("survey/research-plan.json", SurveyPlan)
        if (agent.folder / "survey/research-plan.json").exists()
        else await agent.ask(
            "分别规划数据核对和方法文献调研",
            survey_plan_contract(),
            inputs,
            "Create two distinct research tracks. Verification compares actual local files, official website/repository and OFFICIAL DATASET publication. "
            "Literature has eight goals: analysis uses, algorithm uses, discussion of the dataset itself, preprocessing of this data type, each for paper AND repository. "
            "Use target/medium identifiers from the schema. Questions and queries should enable later selection and evidence extraction.",
        )
    )
    agent.save("survey/research-plan.json", plan)
    sources = (
        agent.load("survey/sources.json", ResearchSources)
        if (agent.folder / "survey/sources.json").exists()
        else ResearchSources(documents=[], observations=[])
    )
    catalog = await agent.tools.catalog(agent.context) if agent.tools else []
    if not any(t["available"] and t.get("category") == "literature" for t in catalog):
        raise ValueError("没有可用论文检索工具，请启用一个文献集成后重试")
    if (agent.folder / "survey/verification.json").exists():
        verification = agent.load("survey/verification.json", DatasetVerification)
        validate_verification(agent, verification, sources, local)
    else:
        missing = await retrieve(
            agent, plan, inputs, sources, catalog, "dataset_verification", 12
        )
        from .planning_contracts import verification_contract

        verification = await agent.ask(
            "逐项对比本地、官网仓库与官方论文",
            verification_contract(local),
            {
                **inputs,
                "sources": agent.source_context(sources),
                "observations": [o.model_dump() for o in sources.observations],
                "retrieval_gaps": missing,
            },
            "Produce every fixed comparison row. Local observations group identical measured values and retain every record ID. Return local_fact_ids=[]; code attaches all measured references. Compare all groups, including minority values. Do not rewrite measurements, manufacture pointers, infer task identity from file names, or treat unperformed checks as absence. "
            "Each official-site/repository or official-paper statement requires cited exact quotes. Missing statements are null with no findings. "
            "Identify the official DATASET paper via official citation evidence. A related acquisition-system paper is role=acquisition_system and cannot fill the official dataset-paper column. "
            "When identity cannot be confirmed use not_identified; do not substitute a usage/method paper. "
            'If official_publication.role is not dataset_paper, EVERY official_paper cell must be '
            '{"statement":null,"finding_ids":[]}. Do not write an absence explanation in statement, '
            'nor fill it with website, API documentation or third-party paper findings. Put missing-source '
            'explanations in conclusion/gaps. A row with this missing side cannot be consistent. '
            "consistent means all three sides were actually verified; partial/unverifiable retain absent sides or scope mismatches. Cite version and subset differences explicitly. "
            "Metadata values need cited facts, or null. Facts use unique IDs and exact contiguous source quotes.",
            lambda value: validate_verification(agent, value, sources, local),
        )
        agent.save("survey/verification.json", verification)
    if (agent.folder / "survey/literature.json").exists():
        literature = agent.load("survey/literature.json", LiteratureReview)
        validate_screening(agent, literature, sources)
    else:
        if any(r.operation == SCREENING_OPERATION for r in agent.log.records):
            # Reaching screening means retrieval already finished (or exhausted
            # its budget). Resume the failed decision using its saved sources.
            missing = missing_tasks(
                sources, plan.literature, catalog, "literature_review"
            )
        else:
            missing = await retrieve(
                agent, plan, inputs, sources, catalog, "literature_review", 32
            )
        selection = ScreeningSelection(sources)
        selected_passages = await agent.ask(
            SCREENING_OPERATION,
            selection.model,
            {
                "request": agent.state["request"],
                "verification": verification.model_dump(
                    exclude={"comparisons": {"__all__": {"local_fact_ids"}}}
                ),
                "criteria": SELECTION_CRITERIA,
                "destinations": DESTINATIONS,
                "source_passages": selection.context,
                "retrieval_gaps": missing,
            },
            "Screen the actual read sources separately as usage_analysis, usage_algorithm, dataset_discussion and preprocessing_methods, for papers and repositories. "
            "Include/exclude/defer each relevant candidate with a concrete reason. Every entry must select its source_id. Findings select passage_id from that source's schema enum; choose substantive passages supporting the statement. Finding source IDs, verbatim quotations and observed metrics are filled by code. Do not output quote, finding.source_id or quality fields. Abstract-only material is deferred. "
            "For usage_analysis and usage_algorithm, the work itself must actually use the target dataset: citing another work in related work is not sufficient; defer it and follow the primary work. "
            "Analysis means substantive analysis of data or signals, not merely a comparison of classifier accuracies. "
            "Keep coverage gaps explicit, never relabel unrelated papers to fill a category. A source may support multiple goals with distinct reasons/evidence. "
            "Extract explicit dataset-discussion subject/run exclusions as reported claims, not execution commands. Included subsets and held-out groups are study-scope findings, not exclusions. Never take a subset's complement to invent excluded subjects. related_urls may only copy URLs in that source links, its original read URL or its associated search result; omit inferred DOI URLs. "
            "Use the supplied observed_quality as context for screening; missing metrics remain unknown, and code preserves their provenance. "
            "Full_text requires full document access within the provided context; previews, abstracts and truncation are partial. Finding IDs must be unique across all entries and distinct from verification facts.",
            lambda value: validate_screening(
                agent,
                selection.project(value),
                sources,
                [f.id for f in verification.facts],
            ),
        )
        screening = selection.project(selected_passages)
        literature = LiteratureReview(
            **screening.model_dump(),
            criteria=SELECTION_CRITERIA,
            coverage=coverage_table(screening, sources, catalog),
            sources=[
                {"id": d.id, "title": d.title, "url": d.url}
                for d in sources.documents
                if d.id in {e.source_id for e in screening.entries}
            ],
        )
        agent.save("survey/literature.json", literature)
    from .evidence_grades import grade_review
    from app.preprocessing.storage import write_json
    write_json(agent.folder / 'survey/evidence-grades.json', grade_review(literature, sources))
    # Compatibility projection for the numeric pipeline; the authoritative two products remain separate.
    selected = [e for e in literature.entries if e.decision == "included"]
    facts = {f.id: f for f in verification.facts}
    for entry in selected:
        for fact in entry.findings:
            if fact.id in facts and facts[fact.id] != fact:
                raise ValueError("conflicting finding IDs across research products")
            facts[fact.id] = fact
    combined = ResearchFindings(
        summary=verification.summary,
        facts=list(facts.values()),
        metadata=verification.metadata,
        literature=[
            {
                "source_id": e.source_id,
                "category": "papers_discussing_dataset"
                if e.target == "dataset_discussion"
                else "preprocessing_papers"
                if e.target == "preprocessing_methods"
                else "papers_using_dataset",
                "relevance": e.reason,
                "reading_scope": e.reading_scope
                if e.reading_scope in {"abstract", "partial_text", "full_text"}
                else "partial_text",
            }
            for e in selected
            if e.medium == "paper"
        ],
        gaps=verification.gaps
        + literature.gaps
        + [
            f"{c.target}/{c.medium}: {c.explanation}"
            for c in literature.coverage
            if c.status == "gap"
        ],
        conflicts=verification.conflicts,
    )
    agent.save("survey/research.json", combined)
    return combined
