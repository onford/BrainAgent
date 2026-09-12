"""Method seeds, executable operators and evidence-bound pipeline edits."""

from typing import Any, Annotated, Literal

from pydantic import Field, model_validator

from app.preprocessing.schemas import Contract, Evidence, Scope, Step, EvaluationWindow


Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]


class ParameterDomain(Contract):
    kind: Literal["number", "integer", "choice"]
    minimum: float | None = Field(default=None, allow_inf_nan=False)
    maximum: float | None = Field(default=None, allow_inf_nan=False)
    choices: list[Any] = Field(default_factory=list)
    unit: str
    rationale: str = Field(min_length=1)
    origin: Literal["mathematical", "implementation", "literature", "engineering"]
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def domain(self):
        if self.kind == "choice":
            if not self.choices or self.minimum is not None or self.maximum is not None:
                raise ValueError("choice domain requires choices and no numeric bounds")
        elif (
            self.minimum is None
            or self.maximum is None
            or self.minimum > self.maximum
            or self.choices
        ):
            raise ValueError("numeric domain requires ordered finite bounds")
        if self.origin == "literature" and not self.evidence_ids:
            raise ValueError("literature parameter domains require evidence")
        return self


class ParameterSeparation(Contract):
    upper_parameter: str
    lower_parameter: str
    minimum: float = Field(gt=0, allow_inf_nan=False)
    rationale: str = Field(min_length=1)


class InputHighpassRequirement(Contract):
    minimum_hz: float = Field(gt=0, allow_inf_nan=False)
    window_parameter: str
    minimum_cycles: float = Field(gt=0, allow_inf_nan=False)
    rationale: str = Field(min_length=1)


class OperatorDefinition(Contract):
    id: Identifier
    title: str
    unit_id: str
    op: str
    implementation_version: Literal['1', '2'] = '1'
    profile: str = 'source'
    input_stage: Literal["continuous", "epochs", "either"]
    output_stage: Literal["continuous", "epochs", "same"]
    fit_scope: Literal["none", "record_unlabelled"]
    domains: dict[str, ParameterDomain]
    defaults: dict[str, Any]
    bindings: dict[str, Any] = Field(default_factory=dict)
    required: bool = False
    max_instances: int = Field(default=1, ge=1, le=4)
    requires: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    separations: list[ParameterSeparation] = Field(default_factory=list)
    input_highpass: InputHighpassRequirement | None = None
    emit_mark: bool = True

    @model_validator(mode="after")
    def valid_separations(self):
        if self.input_highpass is not None and self.input_highpass.window_parameter not in self.domains:
            raise ValueError("input highpass requirement must reference an operator window parameter")
        for rule in self.separations:
            if any(k not in self.domains or self.domains[k].kind == "choice"
                   for k in (rule.upper_parameter, rule.lower_parameter)):
                raise ValueError("parameter separation requires numeric domains")
        return self


class PipelineNode(Contract):
    id: Identifier
    operator: Identifier
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_from: str | None = None
    model_from: str | None = None
    decision_from: str | None = None
    fit_scope: Scope | None = None
    optional: bool = True
    trace: list[dict[str, Any]] = Field(default_factory=list)
    graph: Step | None = None


class PipelineRecipe(Contract):
    nodes: list[PipelineNode] = Field(min_length=1, max_length=24)
    output: str | None = None
    evaluation_window: EvaluationWindow | None = None
    output_roles: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def node_identity(self):
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("pipeline node identifiers must be unique")
        return self


class MethodSeed(Contract):
    id: Identifier
    title: str
    origin: Literal["basic", "literature", "literature_adaptation", "derived"]
    recipe: PipelineRecipe
    evidence_ids: list[str] = Field(default_factory=list)
    applicability: list[str] = Field(default_factory=list)
    deviations: list[str] = Field(default_factory=list)
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def source(self):
        if self.origin != "basic" and not self.evidence_ids:
            raise ValueError("literature method seeds require verified sources")
        return self


class PriorCondition(Contract):
    scope: Literal["context", "parameter"]
    key: str
    operator: str | None = None
    comparison: Literal["eq", "ne", "lt", "le", "gt", "ge", "in"]
    value: Any

    @model_validator(mode="after")
    def parameter_owner(self):
        if (self.scope == "parameter") != (self.operator is not None):
            raise ValueError("parameter predicates must name their operator")
        return self


class ScientificPrior(Contract):
    id: Identifier
    revision: int = Field(default=1, ge=1)
    status: Literal['active', 'revoked'] = 'active'
    change_reason: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    operator_match: Literal['registered_id', 'unit_operation'] = 'registered_id'
    implementation_versions: list[Literal['1', '2']] = Field(default_factory=lambda: ['1'])
    strength: Literal["hard", "soft"]
    relation: Literal["before", "requires", "incompatible", "parameter_condition"]
    operators: list[str] = Field(min_length=1)
    condition: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    origin: Literal["mathematical", "implementation", "literature", "engineering"]
    when: list[PriorCondition] = Field(default_factory=list)
    requirements: list[PriorCondition] = Field(default_factory=list)

    @model_validator(mode="after")
    def relation_shape(self):
        if (self.status == 'revoked' or self.revision > 1 or self.supersedes) and not (self.change_reason or '').strip():
            raise ValueError('rule revisions/revocations require a change reason')
        if not self.implementation_versions or len(set(self.implementation_versions)) != len(self.implementation_versions):
            raise ValueError('rule implementation versions must be nonempty and unique')
        if (
            self.relation in {"before", "requires", "incompatible"}
            and len(self.operators) < 2
        ):
            raise ValueError("operator relation requires at least two operators")
        if self.relation == "before" and len(self.operators) != 2:
            raise ValueError("before relation identifies an ordered pair")
        if self.relation == "parameter_condition" and not self.requirements:
            raise ValueError("parameter condition requires machine-readable predicates")
        if self.origin == "literature" and not self.evidence_ids:
            raise ValueError("literature priors require evidence")
        return self


class ParameterEdit(Contract):
    action: Literal["set_parameter"]
    node_id: Identifier
    parameter: str
    value: Any


class InsertEdit(Contract):
    action: Literal["insert_operator"]
    after_node_id: Identifier | None
    node: PipelineNode

    @model_validator(mode="after")
    def no_invented_provenance(self):
        if self.node.trace:
            raise ValueError("inserted operators cannot invent source traces; use a registered donor fragment")
        return self


class RemoveEdit(Contract):
    action: Literal["remove_operator"]
    node_id: Identifier


class SwapEdit(Contract):
    action: Literal["swap_adjacent"]
    first_node_id: Identifier
    second_node_id: Identifier




class CombineEdit(Contract):
    action: Literal["combine_fragment"]
    donor_id: Identifier
    node_ids: list[Identifier] = Field(min_length=1, max_length=16)
    after_node_id: Identifier | None


PipelineEdit = Annotated[
    ParameterEdit | InsertEdit | RemoveEdit | SwapEdit | CombineEdit,
    Field(discriminator="action"),
]


class PriorWarning(Contract):
    prior_id: str
    reason: str
    evidence_ids: list[str]


class PolicySummary(Contract):
    operators: list[str]


class CandidateRecipe(Contract):
    id: Identifier
    title: str
    recipe: PipelineRecipe
    recipe_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    origin: Literal["basic", "literature", "literature_adaptation", "derived"]
    seed_id: Identifier
    evidence_ids: list[str]
    deviations: list[str]
    prior_warnings: list[PriorWarning]
    prior_challenges: dict[str, str]
    parent_id: Identifier | None
    edits: list[PipelineEdit]
    parameters: PolicySummary
    operator_count: int = Field(ge=1)
    order: int = Field(ge=0)
    lineage: list[dict[str, Any]] = Field(default_factory=list)
    parent_ids: list[str] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)


class ExplorationSpace(Contract):
    version: Literal["1"] = "1"
    semantic_identity: Literal["operator_ids_v1", "operation_contracts_v1"] = "operator_ids_v1"
    operators: list[OperatorDefinition]
    methods: list[MethodSeed]
    priors: list[ScientificPrior]
    evidence: dict[str, Evidence]
    max_edits_per_proposal: int = Field(default=3, ge=1, le=8)

    @model_validator(mode="after")
    def references(self):
        for items in (self.operators, self.methods, self.priors):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError("space identifiers must be unique within their kind")
            for item in items:
                if not set(item.evidence_ids) <= self.evidence.keys():
                    raise ValueError("space evidence reference does not exist")
        for operator in self.operators:
            if set(operator.defaults) != set(operator.domains):
                raise ValueError(
                    "operator defaults must cover exactly its parameter domains"
                )
            for domain in operator.domains.values():
                if not set(domain.evidence_ids) <= self.evidence.keys():
                    raise ValueError("parameter evidence reference does not exist")
            if operator.bindings.keys() & operator.domains.keys():
                raise ValueError("fixed bindings cannot overlap editable parameters")
        operators = {o.id: o for o in self.operators}
        for method in self.methods:
            if any(n.operator not in operators for n in method.recipe.nodes):
                raise ValueError("method references an unknown operator")
        for prior in self.priors:
            prior_by_id = {p.id: p for p in self.priors}
            for old_id in prior.supersedes:
                old = prior_by_id.get(old_id)
                if old is None or old.status != 'revoked' or old.revision >= prior.revision:
                    raise ValueError('replacement must reference a retained revoked rule with lower revision')
            if not set(prior.operators) <= operators.keys():
                raise ValueError("prior references an unknown operator")
            for predicate in prior.when + prior.requirements:
                if predicate.scope == "parameter" and (
                    predicate.operator not in operators
                    or predicate.key not in operators[predicate.operator].domains
                ):
                    raise ValueError("prior references an unknown operator parameter")
        return self
