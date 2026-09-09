"""Model/source doubles for numeric integration tests; application never imports them."""

from app.llm.client import LLMClient
from app.preprocessing.methods import baseline_methods
from app.tools.base import ToolResult
from app.workflows.cognition_contracts import SourceDocument

TEXT = "This dataset records 64 EEG channels at 160 Hz. Runs 4, 8 and 12 are left/right motor imagery. T1 means left hand and T2 means right hand. Bandpass filtering and average referencing are engineering candidate choices."


class ResearchTools:
    async def catalog(self, context):
        return [
            {"name": "europe_pmc", "category": "literature", "available": True},
            {"name": "github", "category": "code", "available": True},
        ]

    async def execute(self, name, context, **kwargs):
        return ToolResult(
            success=True,
            output={
                "items": [
                    {
                        "title": "Test paper",
                        "url": "https://example.org/repo"
                        if name == "github"
                        else "https://example.org/paper",
                    }
                ]
            },
        )


class Reader:
    async def read(self, url, kind):
        return SourceDocument(
            id="official"
            if kind == "official"
            else "repo"
            if kind == "code"
            else "paper",
            url=url,
            kind=kind,
            title="Test source",
            retrieved_at="2026-09-08T00:00:00+00:00",
            sha256="1" * 64,
            text=TEXT,
            links=[],
            truncated=False,
        )


class WorkflowLLM(LLMClient):
    def __init__(self, invalid_design=False):
        self.calls = []
        self.invalid_design = invalid_design

    async def chat(self, messages):
        raise AssertionError("structured interface expected")

    async def structured_output(self, messages, model):
        import json

        self.calls.append(model.__name__)
        data = json.loads(messages[1]["content"])
        categories = [
            "dataset",
            "papers_using_dataset",
            "papers_discussing_dataset",
            "preprocessing_papers",
        ]
        if model.__name__ == "SurveyPlan":
            from app.workflows.survey_contracts import LITERATURE_TARGETS

            return model(
                objective="区分数据核对与文献用途",
                verification=[
                    {
                        "target": "official_sources",
                        "medium": "official",
                        "question": "核对官网",
                        "query": "EEGMMIDB official",
                    },
                    {
                        "target": "official_publication",
                        "medium": "paper",
                        "question": "查官方论文",
                        "query": "EEGMMIDB official paper",
                    },
                ],
                literature=[
                    {
                        "target": t,
                        "medium": m,
                        "question": t,
                        "query": f"EEGMMIDB {t} {m}",
                    }
                    for t in LITERATURE_TARGETS
                    for m in ("paper", "repository")
                ],
            )
        if model.__name__ == "ResearchBatch" and "purpose" in data:
            actions = []
            for goal in data["goals"]:
                target, medium = goal["target"], goal["medium"]
                seen = [
                    o
                    for o in data["observations"]
                    if o["action"].get("purpose") == data["purpose"]
                    and o["action"].get("target") == target
                    and o["action"].get("medium") == medium
                ]
                action = {
                    "purpose": data["purpose"],
                    "target": target,
                    "medium": medium,
                    "rationale": "按用途查证",
                }
                if medium == "official" and not seen:
                    action.update(
                        action="read",
                        kind="official",
                        url="https://physionet.org/content/eegmmidb/1.0.0/",
                    )
                elif medium != "official" and not any(
                    o["action"]["action"] == "search" for o in seen
                ):
                    action.update(
                        action="search",
                        tool="github" if medium == "repository" else "europe_pmc",
                        query=goal["query"],
                    )
                elif medium != "official" and not any(
                    o["action"]["action"] == "read" for o in seen
                ):
                    action.update(
                        action="read",
                        kind="code" if medium == "repository" else "paper",
                        url="https://example.org/repo"
                        if medium == "repository"
                        else "https://example.org/paper",
                        query=target,
                    )
                else:
                    continue
                actions.append(action)
            if not actions:
                actions = [
                    {
                        "action": "finish",
                        "rationale": "该用途检索完成",
                        "purpose": data["purpose"],
                        "target": data["goals"][0]["target"],
                        "medium": data["goals"][0]["medium"],
                    }
                ]
            return model(actions=actions[: min(4, data["remaining_actions"])])
        if model.__name__ in {"DatasetVerification", "LiteratureScreening"}:
            from app.workflows.cognition_contracts import ResearchFindings
            from app.workflows.survey_contracts import FIELDS

            base = await WorkflowLLM().structured_output(
                [{}, {"content": "{}"}], ResearchFindings
            )
            if model.__name__ == "DatasetVerification":
                return model(
                    summary="三方核对，官方论文身份待确认",
                    facts=base.facts,
                    metadata=base.metadata,
                    official_publication={
                        "source_id": None,
                        "role": "not_identified",
                        "basis_finding_ids": [],
                        "explanation": "未确认官方数据集论文",
                    },
                    comparisons=[
                        {
                            "field": f,
                            "local_fact_ids": data.get(
                                "local_reference_catalog", {}
                            ).get(f, [])
                            if "local_reference_catalog" in data
                            else [
                                v["id"]
                                for v in data["local_inspection"]["facts"]
                                if v["field"] == f
                            ],
                            "official_sources": {"statement": None, "finding_ids": []},
                            "official_paper": {"statement": None, "finding_ids": []},
                            "status": "unverifiable",
                            "conclusion": "保留缺口",
                        }
                        for f in FIELDS
                    ],
                    gaps=["官方论文待确认"],
                    conflicts=[],
                )
            finding = base.facts[2].model_dump()
            if "source_passages" in data:
                source = next(
                    s for s in data["source_passages"] if s["source_id"] == "paper"
                )
                passage = next(
                    p for p in source["passages"] if finding["quote"] in p["text"]
                )
                finding = {
                    k: v for k, v in finding.items() if k not in {"quote", "source_id"}
                }
                finding.update(id="literature-f3", passage_id=passage["id"])
            return model(
                summary="筛选方法资料",
                entries=[
                    {
                        "id": "entry-method",
                        "source_id": "paper",
                        "target": "preprocessing_methods",
                        "medium": "paper",
                        "decision": "included",
                        "reason": "有可核验的方法内容",
                        "reading_scope": "partial_text",
                        "findings": [finding],
                        "related_urls": ["https://example.org/paper"],
                        **({} if "source_passages" in data else {"quality": {}}),
                    }
                ],
                gaps=["其他分类未找到通过筛选的资料"],
            )
        if model.__name__ == "ResearchPlan":
            value = {
                "objective": "核对模型训练数据",
                "questions": [
                    {"category": c, "question": c, "query": "EEGMMIDB " + c}
                    for c in categories
                ],
            }
        elif model.__name__ == "ResearchBatch":
            seen = {
                o["action"]["category"]
                for o in data["observations"]
                if o["action"]["action"] == "search"
            }
            kinds = {d["kind"] for d in data["sources"]}
            actions = []
            if "official" not in kinds:
                actions.append(
                    {
                        "action": "read",
                        "rationale": "核对官网",
                        "url": "https://physionet.org/content/eegmmidb/1.0.0/",
                        "kind": "official",
                    }
                )
            actions.extend(
                {
                    "action": "search",
                    "rationale": "分头检索",
                    "tool": "europe_pmc",
                    "query": "EEGMMIDB " + c,
                    "category": c,
                }
                for c in categories[1:]
                if c not in seen
            )
            if "paper" not in kinds:
                actions.append(
                    {
                        "action": "read",
                        "rationale": "阅读论文",
                        "url": "https://example.org/paper",
                        "kind": "paper",
                    }
                )
            value = {
                "actions": actions[: min(4, data["remaining_actions"])]
                or [{"action": "finish", "rationale": "最低覆盖完成"}]
            }
        elif model.__name__ == "ResearchAction":
            observations = data["observations"]
            seen = {
                o["action"]["category"]
                for o in observations
                if o["action"]["action"] == "search"
            }
            kinds = {d["kind"] for d in data["sources"]}
            value = {"action": "finish", "rationale": "最低覆盖完成"}
            if "official" not in kinds:
                value.update(
                    action="read",
                    url="https://physionet.org/content/eegmmidb/1.0.0/",
                    kind="official",
                )
            elif any(c not in seen for c in categories[1:]):
                value.update(
                    action="search",
                    tool="europe_pmc",
                    query="EEGMMIDB",
                    category=next(c for c in categories[1:] if c not in seen),
                )
            elif "paper" not in kinds:
                value.update(
                    action="read", url="https://example.org/paper", kind="paper"
                )
        elif model.__name__ == "ResearchFindings":
            value = {
                "summary": "官网与论文已核对，保留工程候选。",
                "facts": [
                    {
                        "id": "f1",
                        "topic": "acquisition",
                        "statement": "64 通道 160 Hz",
                        "source_id": "official",
                        "quote": "This dataset records 64 EEG channels at 160 Hz.",
                    },
                    {
                        "id": "f2",
                        "topic": "task",
                        "statement": "左右手想象",
                        "source_id": "official",
                        "quote": "Runs 4, 8 and 12 are left/right motor imagery.",
                    },
                    {
                        "id": "f3",
                        "topic": "methods",
                        "statement": "工程滤波候选",
                        "source_id": "paper",
                        "quote": "Bandpass filtering and average referencing are engineering candidate choices.",
                    },
                ],
                "literature": [
                    {
                        "source_id": "paper",
                        "category": "preprocessing_papers",
                        "relevance": "方法",
                        "reading_scope": "partial_text",
                    }
                ],
                "gaps": ["未完成全文调研"],
                "conflicts": [],
            }
        elif model.__name__ == "CollectionReview":
            value = {
                "compatible": True,
                "rationale": "任务与标签一致",
                "supporting_facts": ["f1", "f2"],
                "conflicts": [],
                "limitations": [],
                "task_mappings": [
                    {"run": run, "status": "verified", "finding_ids": ["f2"]}
                    for run in data["training_runs"]
                ],
            }
        elif model.__name__ == "MethodDesign":
            candidates = []
            for label, lo, hi in [("wide", 1, 40), ("narrow", 8, 30)]:
                recipe = baseline_methods()[0].recipe[:-1]
                recipe[0].params.update(
                    l_freq=lo,
                    h_freq=500
                    if self.invalid_design and not data["compiler_feedback"]
                    else hi,
                )
                recipe[-1].params.update(
                    tmin=data["request"]["tmin"],
                    tmax=data["request"]["tmax"],
                    picks="$eeg_channels",
                )
                candidates.append(
                    {
                        "id": "test-" + label,
                        "title": label,
                        "mechanism": label,
                        "rationale": "测试工程方案",
                        "output": recipe[-1].id,
                        "adaptations": [],
                        "steps": [
                            {
                                **s.model_dump(
                                    exclude={
                                        "evidence_indices",
                                        "profile",
                                        "implementation_version",
                                    }
                                ),
                                "basis": "engineering",
                                "finding_ids": ["f3"],
                                "rationale": "参数为工程设定",
                            }
                            for s in recipe
                        ],
                    }
                )
            value = {
                "objective": "训练数据",
                "candidates": candidates,
                "limitations": ["未评价质量"],
            }
        elif model.__name__ == "ReportNarrative":
            value = {
                "overview": "完成资料调研与真实数据处理。",
                "data_interpretation": "统计来自执行记录。",
                "method_reasoning": "随机选取工程方案。",
                "limitations": ["未进行质量排名"],
                "finding_ids": ["f3"],
            }
        else:
            raise AssertionError(model.__name__)
        if model.__name__ == "ResearchFindings":
            value["metadata"] = [
                {"field": field, "value": None, "finding_ids": []}
                for field in (
                    "name",
                    "version",
                    "doi",
                    "publisher",
                    "published",
                    "license",
                )
            ]
        return model.model_validate(value)


def workflow_service(root, input_roots, preprocessing, **kwargs):
    from app.workflows.service import WorkflowService

    return WorkflowService(
        root,
        input_roots,
        preprocessing,
        llm=kwargs.pop("llm", WorkflowLLM()),
        tools=ResearchTools(),
        source_reader=Reader(),
        **kwargs,
    )
