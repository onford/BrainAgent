"""Freeze a score-blind finite control neighbourhood, without running candidates.

The registry starts with every original seed, followed by single-edit children.
It can be passed directly to method_space.verify_registry. All controls should
share this exact frozen object; this is not an exhaustive continuous search or
an equal-space comparator for unrestricted, multi-generation adaptive editing.
"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
import math

from app.preprocessing.storage import canonical, digest
from .exploration_coverage import EDIT_FAMILIES
from .method_space import edited_entry, seed_entries
from .pipeline_space import apply_edits, recipe_hash
from .space_contracts import ExplorationSpace


VERSION = "finite-control-v1"
QUANTILES = (0.25, 0.5, 0.75)
GATE_THRESHOLDS = (2.0, 5.0, 10.0, 20.0)


def _values(domain):
    if domain.kind == "choice":
        values = domain.choices
    elif domain.kind == "integer":
        lo, hi = math.ceil(domain.minimum), math.floor(domain.maximum)
        if lo > hi:
            return []
        values = [math.floor(lo * (1 - q) + hi * q + 0.5) for q in QUANTILES]
    else:
        # Convex interpolation also avoids overflow in maximum - minimum.
        values = [domain.minimum * (1 - q) + domain.maximum * q for q in QUANTILES]
    return list({digest(v): deepcopy(v) for v in values}.values())


def _variants(operator):
    """Default insertion plus one parameter changed, never a Cartesian product."""
    variants = [deepcopy(operator.defaults)]
    for name, domain in sorted(operator.domains.items()):
        variants.extend(
            {**deepcopy(operator.defaults), name: v} for v in _values(domain)
        )
    return list({digest(v): v for v in variants}.values())


def _edits(parent, space):
    nodes = parent["recipe"]["nodes"]
    operators = {o.id: o for o in space.operators}
    counts = Counter(n["operator"] for n in nodes)
    for node in nodes:
        spec = operators[node["operator"]]
        for parameter, domain in sorted(spec.domains.items()):
            for value in _values(domain):
                yield dict(
                    action="set_parameter",
                    node_id=node["id"],
                    parameter=parameter,
                    value=value,
                )
        if not spec.required:
            yield dict(action="remove_operator", node_id=node["id"])
    for first, second in zip(nodes, nodes[1:]):
        yield dict(
            action="swap_adjacent",
            first_node_id=first["id"],
            second_node_id=second["id"],
        )
    for spec in sorted(space.operators, key=lambda o: o.id):
        if spec.required or counts[spec.id] >= spec.max_instances:
            continue
        identity = "control-" + spec.id
        while identity in {n["id"] for n in nodes}:
            identity += "-x"
        for parameters in _variants(spec):
            for after in [None] + [n["id"] for n in nodes]:
                yield dict(
                    action="insert_operator",
                    after_node_id=after,
                    node=dict(id=identity, operator=spec.id, parameters=parameters),
                )
    for mode in (
        "none",
        "subject_scale",
        "euclidean_alignment",
        "conditional_alignment",
    ):
        thresholds = GATE_THRESHOLDS if mode == "conditional_alignment" else (10.0,)
        for threshold in thresholds:
            yield dict(
                action="set_adaptation",
                policy=dict(adaptation=mode, alignment_threshold=threshold),
            )


def _balanced(rows, seed):
    """Round robin edit types AND seed families; hashes break within-cell ties."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["action"], row["parent_id"]].append(row)
    queues = {
        key: deque(sorted(value, key=lambda r: digest([seed, r["proposal_id"]])))
        for key, value in groups.items()
    }
    actions = sorted(EDIT_FAMILIES, key=lambda a: digest([seed, "action", a]))
    parents = sorted(
        {r["parent_id"] for r in rows}, key=lambda p: digest([seed, "family", p])
    )
    while any(queues.values()):
        for action in actions:
            for parent in parents:
                queue = queues.get((action, parent))
                if queue:
                    yield queue.popleft()


def _challenges(parent, edit, warnings):
    """Predeclared, falsifiable engineering contrasts, never measured findings."""
    changed = canonical(edit)
    return {
        w["prior_id"]: (
            f"竞争假设：{w['reason']} 对当前冻结面板未必必要；本次仅编辑 {changed}。"
            f"以父方案 {parent['id']} 为配对参照，检验开发 assessment.selection_score "
            "是否不下降，并在相同冻结重建条件和相同被试分母上分别检验 "
            "artifact_residual_rms_ratio 与 clean_retention_nrmse 是否不增加。"
            "任一恶化即削弱该竞争假设；缺指标、失败或分母不齐不能支持挑战。"
            "若父方案已偏离同一先验，此对照只检验本次编辑，不能单独验证先验。"
            "这是开发压力测试，重建仅针对物理处理的cleanproxy，不能证明神经保真或独立泛化。"
        )
        for w in warnings
    }


def control_entries(space, context, seed, max_entries=256):
    """Return strict-JSON design/registry/coverage/ledger and their freeze hashes.

    ``context`` must be frozen, pre-evaluation acquisition/capability facts.
    Only keys named by operator requirements or prior predicates are read and
    hashed: unrelated scores, labels and result payloads cannot change selection.
    Missing referenced facts fail closed (explicit False is a valid fact).

    All legal adjacent seed swaps have selection priority, subject to the cap.
    Remaining capacity is shared across edit types and original seed families.
    Output order is balanced too, after the unmodified, original seed prefix.
    Each ledger row records its exact proposed edit and rejection or selected
    semantic alias, so an omitted alternative is distinguishable from a failure.
    This function validates recipes, not dataset execution or measured efficacy.
    """
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be an integer in [0, 2**32 - 1]")
    if type(max_entries) is not int or not 1 <= max_entries <= 256:
        raise ValueError("max_entries must be an integer in [1, 256]")
    space = ExplorationSpace.model_validate(space).model_copy(deep=True)
    needed = {key for o in space.operators for key in o.requires}
    needed.update(
        p.key
        for prior in space.priors
        for p in prior.when + prior.requirements
        if p.scope == "context"
    )
    if not isinstance(context, dict) or not needed <= context.keys():
        raise ValueError(
            f"context must explicitly supply frozen facts: {sorted(needed)}"
        )
    facts = {key: deepcopy(context[key]) for key in sorted(needed)}
    digest(facts)  # Reject non-JSON or non-finite facts before enumerating.
    seeds = seed_entries(space, facts)
    if not seeds or len(seeds) > max_entries:
        raise ValueError(
            "max_entries must accommodate every seed (at least one required)"
        )
    if len({s["recipe_hash"] for s in seeds}) != len(seeds):
        raise ValueError("duplicate seed semantics cannot form a verified registry")
    ledger, candidates = [], {}
    for parent in seeds:
        for edit in _edits(parent, space):
            row = dict(
                proposal_id=digest([parent["id"], edit]),
                parent_id=parent["id"],
                action=edit["action"],
                edit=deepcopy(edit),
            )
            try:
                recipe, warnings = apply_edits(parent["recipe"], [edit], space, facts)
            except ValueError as exc:
                row.update(
                    status="rejected",
                    reason=str(exc),
                    recipe_hash=None,
                    candidate_id=None,
                )
            else:
                row.update(
                    status="eligible",
                    reason=None,
                    recipe_hash=recipe_hash(recipe),
                    candidate_id=None,
                    prior_challenges=_challenges(parent, edit, warnings),
                )
                candidates[row["proposal_id"]] = parent
            ledger.append(row)

    eligible = [r for r in ledger if r["status"] == "eligible"]
    selected_hashes = {s["recipe_hash"] for s in seeds}
    chosen = []
    priority = [r for r in eligible if r["action"] == "swap_adjacent"]
    for rows in (priority, eligible):
        for row in _balanced(rows, seed):
            if len(seeds) + len(chosen) == max_entries:
                break
            if row["recipe_hash"] not in selected_hashes:
                chosen.append(row)
                selected_hashes.add(row["recipe_hash"])
    registry = deepcopy(seeds)
    for row in _balanced(chosen, seed):
        parent = candidates[row["proposal_id"]]
        entry = edited_entry(
            parent,
            [row["edit"]],
            space,
            title=f"{parent['title']} · {row['action']}",
            order=len(registry),
            context=facts,
            prior_challenges=row["prior_challenges"],
        )
        registry.append(entry)
        row["status"] = "selected"
    by_hash = {e["recipe_hash"]: e["id"] for e in registry}
    for row in eligible:
        row["candidate_id"] = by_hash.get(row["recipe_hash"])
        if row["status"] != "selected":
            row["status"] = "deduplicated" if row["candidate_id"] else "capped"

    def counts(rows):
        return dict(
            proposed=len(rows),
            rejected=sum(r["status"] == "rejected" for r in rows),
            selected=sum(r["status"] == "selected" for r in rows),
            deduplicated=sum(r["status"] == "deduplicated" for r in rows),
            capped=sum(r["status"] == "capped" for r in rows),
            legal_unique=len({r["recipe_hash"] for r in rows if r["recipe_hash"]}),
            represented_unique=len(
                {r["recipe_hash"] for r in rows if r["candidate_id"]}
            ),
        )

    total = counts(ledger)
    coverage = dict(
        **total,
        seed_count=len(seeds),
        entry_count=len(registry),
        finite_neighbourhood_unique=len(
            {s["recipe_hash"] for s in seeds} | {r["recipe_hash"] for r in eligible}
        ),
        truncated=any(r["status"] == "capped" for r in ledger),
        by_edit_type={
            a: counts([r for r in ledger if r["action"] == a]) for a in EDIT_FAMILIES
        },
        by_seed={
            s["id"]: counts([r for r in ledger if r["parent_id"] == s["id"]])
            for s in seeds
        },
        all_legal_adjacent_swaps_represented=all(r["candidate_id"] for r in priority),
        missing_edit_types=[
            a
            for a in EDIT_FAMILIES
            if not any(r["action"] == a and r["status"] == "selected" for r in ledger)
        ],
    )
    design = dict(
        schema_version=VERSION,
        seed=seed,
        max_entries=max_entries,
        depth=1,
        edits_per_child=1,
        quantiles=list(QUANTILES),
        numeric_grid="linear domain quartiles; integers rounded half-up within integer bounds",
        insertion_grid="default plus one parameter at a time; all legal insertion slots",
        adaptation_modes=[
            "none",
            "subject_scale",
            "euclidean_alignment",
            "conditional_alignment",
        ],
        conditional_thresholds=list(GATE_THRESHOLDS),
        conditional_threshold_provenance="finite engineering sensitivity grid; not physiological cutoffs",
        ordering="original seeds; edit-type/seed-family round robin; seeded hash ties",
        selection_priority="all legal adjacent seed swaps, then balanced other edits, within cap",
        context=facts,
        context_hash=digest(facts),
        space_hash=digest(space.model_dump(mode="json")),
        limitations=[
            "Finite single-edit seed neighbourhood; no recursive descendants or full parameter Cartesian product.",
            "Coverage counts structurally legal recipes, not executable successes or scientifically distinct effects.",
            "Deduplication uses canonical recipe hashes, not a proof of mathematical non-equivalence.",
            "Random/exhaustive/one_shot must share this frozen registry; exhaustive means this finite panel only.",
            "Unrestricted adaptive editing has a different space; isolate feedback effects with a separate same-panel adaptive comparator.",
            "Freeze space, context, design seed, data/probe panels and budgets before feedback; repeat controller seeds for order sensitivity.",
            "Subject fitting is label-free, offline whole-batch; development selection is not independent confirmation.",
            "Soft challenges are predeclared comparisons, not measured support; missing metrics cannot validate them.",
        ],
    )
    result = dict(
        design=design,
        seeds=deepcopy(seeds),
        edited_entries=deepcopy(registry[len(seeds) :]),
        registry=registry,
        registry_hash=digest(registry),
        coverage=coverage,
        proposals=ledger,
    )
    result["design_hash"] = digest(result)
    return result
