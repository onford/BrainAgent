"""Fixed contracts for workflow-owned supporting files and training exports."""

import csv
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from app.file_publish import replace_file
from app.preprocessing.schemas import (
    Contract,
    ExecutionPlan,
    MethodSpec,
    PreprocessInput,
    Ref,
    RunResult,
)
from .contracts import (
    Count,
    DatasetProfile,
    EvaluationOutput,
    ReportData,
    Statistics,
)

from .cognition_contracts import (
    CollectionReview,
    DecisionLog,
    ReportNarrative,
    ResearchFindings,
    ResearchSources,
)

from .survey_contracts import (
    DatasetVerification,
    LiteratureReview,
    SurveyPlan,
)

from .collection_contracts import (
    IntakeAudit,
    IntakeCheck,
    LiteratureExclusions,
    SourceIntegrity,
    Standardization,
)

from .local_contracts import LocalObservation, LocalEvent

FORMAT_VERSION = "9"
ARRAY_FORMATS = {
    "X.npy": {
        "dtype": "float32",
        "axes": ["trial", "channel", "sample"],
        "unit": "channels.json:unit",
    },
    "y.npy": {
        "dtype": "int64",
        "axes": ["trial"],
        "labels": {"0": "left_hand", "1": "right_hand"},
    },
    "subjects.npy": {"dtype": "<U4", "axes": ["trial"]},
    "split.npy": {
        "dtype": "<U10",
        "axes": ["trial"],
        "values": ["train", "validation", "test"],
    },
}


class InventoryRow(Contract):
    path: str
    bytes: Count


class TriggerRow(Contract):
    trigger: str
    meaning: str


class DeltaRow(Contract):
    metric: str
    before: float | None
    after: float | None
    change: float | None
    reason: str

    @model_validator(mode="before")
    @classmethod
    def nullable_tsv_numbers(cls, value):
        return {
            k: None if k in {"before", "after", "change"} and v == "" else v
            for k, v in value.items()
        }


class MappingRow(Contract):
    object_key: str
    source: str
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target: str
    roundtrip_max_error_V: float = Field(ge=0)
    target_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


AnomalyRow = IntakeCheck


class ChannelMappingRow(Contract):
    object_key: str
    source_index: Count
    source_name: str
    target_name: str
    channel_type: str
    decoded_unit: str
    coordinate_source: str


class EventMappingRow(Contract):
    object_key: str
    source_index: Count
    source_label: str
    target_label: str
    target_code: int
    onset_s: float
    duration_s: float
    source_sample: Count
    training_selected: bool


class ExclusionRow(Contract):
    object_key: str
    reason: str


class TrialRow(Contract):
    index: Count
    record_id: str
    subject: str = Field(pattern=r"^S\d{3}$")
    label: Literal["left_hand", "right_hand"]
    source_event: str
    source_sample: Count
    epoch_index: Count
    split: Literal["train", "validation", "test"]


TABLE_MODELS = {
    "local-events.tsv": LocalEvent,
    "source-inventory.tsv": InventoryRow,
    "triggers.tsv": TriggerRow,
    "delta.tsv": DeltaRow,
    "mapping.tsv": MappingRow,
    "anomalies.tsv": AnomalyRow,
    "exclusions.tsv": ExclusionRow,
    "trial-index.tsv": TrialRow,
    "channel-mapping.tsv": ChannelMappingRow,
    "event-mapping.tsv": EventMappingRow,
}


class TrainingLabels(Contract):
    left: Literal["left_hand"] = Field(alias="0")
    right: Literal["right_hand"] = Field(alias="1")


class ChannelInfo(Contract):
    names: list[str] = Field(min_length=1)
    sfreq: float = Field(gt=0)
    unit: Literal["V", "dimensionless"]
    spatial_semantics: str
    representation: dict | None = None
    dtype: Literal["float32"]
    layout: tuple[Literal["epochs"], Literal["channels"], Literal["samples"]]
    tmin_s: float
    tmax_s: float
    time_endpoint: Literal["inclusive"]


class SourceFile(Contract):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SourceManifest(Contract):
    profile: DatasetProfile
    files: list[SourceFile]


class ManifestFile(Contract):
    name: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: Count


class DeliveryManifest(Contract):
    workflow_id: str
    shape: list[Count] = Field(min_length=3, max_length=3)
    classes: dict[Literal["0", "1"], Count]
    split_counts: dict[Literal["train", "validation", "test"], Count]
    subject_split: dict[str, Literal["train", "validation", "test"]]
    unit: Literal["V", "dimensionless"]
    selection_policy: Literal["development_score"]
    quality_evaluated: Literal[True]
    evaluation_scope: Literal["development"] = "development"
    independent_confirmation: Literal[False] = False
    search_id: str
    selected_candidate_id: str
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    representation: dict | None = None
    selected_method_ref: Ref
    files: list[ManifestFile]
    limitations: list[str]

    @model_validator(mode="after")
    def fixed_count_keys(self):
        if set(self.classes) != {"0", "1"} or set(self.split_counts) != {
            "train",
            "validation",
            "test",
        }:
            raise ValueError(
                "all label and split counts must be present, including zeros"
            )
        return self


from .research_audit_contracts import EvidenceGrades, RetrievalProgress
from .collection_contracts import SourceClaimReview

JSON_MODELS = {
    'survey/evidence-grades.json': EvidenceGrades,
    'survey/dataset_verification-progress.json': RetrievalProgress,
    'survey/literature_review-progress.json': RetrievalProgress,
    'collection/source-claim-review.json': SourceClaimReview,
    "survey/research-plan.json": SurveyPlan,
    "survey/local-inspection.json": LocalObservation,
    "survey/verification.json": DatasetVerification,
    "survey/literature.json": LiteratureReview,
    "survey/research.json": ResearchFindings,
    "survey/sources.json": ResearchSources,
    "collection/review.json": CollectionReview,
    "collection/audit.json": IntakeAudit,
    "collection/literature-exclusions.json": LiteratureExclusions,
    "collection/source-integrity.json": SourceIntegrity,
    "collection/standardization.json": Standardization,
    "collection/research.json": ResearchFindings,
    "collection/sources.json": ResearchSources,
    "preprocessing/research.json": ResearchFindings,
    "preprocessing/sources.json": ResearchSources,
    "report/narrative.json": ReportNarrative,
    **{
        f"{stage}/decisions.json": DecisionLog
        for stage in ("survey", "collection", "preprocessing", "report")
    },
    "collection/input.json": PreprocessInput,
    "collection/pre-screen.json": Statistics,
    "collection/post-screen.json": Statistics,
    "preprocessing/plan.json": ExecutionPlan,
    "preprocessing/result.json": RunResult,
    "report/report.json": ReportData,
    "delivery/labels.json": TrainingLabels,
    "delivery/channels.json": ChannelInfo,
    "delivery/method.json": MethodSpec,
    "delivery/selection.json": EvaluationOutput,
    "delivery/sources.json": SourceManifest,
    "delivery/manifest.json": DeliveryManifest,
}

# Module receipts and temporary/leftover files never become archive members.
DELIVERY_FILES = (
    *ARRAY_FORMATS,
    "labels.json",
    "channels.json",
    "trial-index.tsv",
    "method.json",
    "selection.json",
    "sources.json",
    "report.html",
    "train_example.py",
    "README.md",
    "evaluation/protocol.json",
    "evaluation/panel.json",
    "evaluation/originalpredictions.tsv",
    "evaluation/folds.json",
    "evaluation/receipt.json",
    "evaluation/artifact-map.json",
)
PROVENANCE_FILES = ("provenance.json", "events.json", "delta.json")


def validate_json(path, value):
    key = f"{path.parent.name}/{path.name}"
    model = JSON_MODELS.get(key)
    if model is None:
        return value  # BIDS files follow the external writer's standard.
    return model.model_validate(value).model_dump(mode="json", by_alias=True)


def write_table(path, rows, fields):
    model = TABLE_MODELS[path.name]
    expected = list(model.model_fields)
    if fields != expected:
        raise ValueError(f"{path.name}: columns must be {expected}")
    # Validate before opening the destination; do not silently drop extra columns
    # or write blanks for missing values. Empty tables still get the same header.
    records = [model.model_validate(row).model_dump(mode="json") for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=expected, delimiter="\t", lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(records)
        replace_file(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def delivery_members(folder, record_ids, representation_files=()):
    paths = [folder / name for name in DELIVERY_FILES]
    paths += [
        folder / "provenance" / record / name
        for record in sorted(record_ids)
        for name in PROVENANCE_FILES
    ]
    paths += list(representation_files)
    for path in paths:
        if not path.is_file():
            raise ValueError(
                f"missing required delivery file: {path.relative_to(folder)}"
            )
    return paths
