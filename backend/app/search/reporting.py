"""Deterministic report projection from search records; no generated conclusions."""

from html import escape
from pathlib import Path

from .io import write
from .catalog import BASELINE_ID
from app.preprocessing.storage import file_hash


def score(value):
    return "—" if value is None else f"{value * 100:.2f}%"


def delta(value):
    return "—" if value is None else f"{value * 100:+.2f} 个百分点"


def render(root: Path, state):
    statuses = {
        "evaluated": "已评价",
        "completed": "已完成",
        "failed": "失败",
        "running": "执行中",
        "reserved": "待执行",
        "rejected": "已拒绝",
        "candidate_invalid": "候选无效",
        "execution_failure": "执行失败",
        "resource_failure": "资源不足",
        "data_unevaluable": "数据不可评价",
        "invalidated": "已失效",
        "interrupted": "已中断",
    }
    reasons = {
        "candidate_budget_exhausted": "候选预算耗尽",
        "proposal_budget_exhausted": "提案预算耗尽",
        "time_budget_exhausted": "时间预算耗尽",
        "memory_budget_exhausted": "内存预算耗尽",
        "disk_budget_exhausted": "磁盘预算耗尽",
        "resource_unavailable": "资源不足",
        "catalog_exhausted": "目录已遍历",
        "schedule_exhausted": "计划已执行完毕",
        "model_finished": "模型决定结束",
        "reference_failed": "固定参考失败",
        "integrity_failure": "冻结内容校验失败",
        "execution_conditions_unavailable": "执行条件不可用",
    }
    selected = next(
        (c for c in state["candidates"] if c["id"] == state["selected_candidate_id"]),
        None,
    )
    selection = {
        "schema_version": "1",
        "search_id": state["id"],
        "selected_candidate_id": state["selected_candidate_id"],
        "selection_policy": "highest_development_subject_macro_ba",
        "tie_break": ["reference", "fewer_operators", "catalog_order"],
        "panel_hash": state["panel"].get("panel_hash") if state["panel"] else None,
        "reference_candidate_id": BASELINE_ID,
        "stop_reason": state["stop_reason"],
        "development_evaluated": selected is not None,
        "independent_confirmation": False,
        "scientific_quality_certified": False,
        "job_id": selected.get("job_id") if selected else None,
        "plan_ref": selected.get("plan_ref") if selected else None,
        "limitations": [
            "反复使用开发面板进行选择，分数不是独立泛化改善的证据。",
            "仅比较固定目录、固定学习器和离线处理；没有确认神经信号保真或实时部署能力。",
        ],
    }
    write(root / "selection.json", selection)
    rows = []
    for c in state["candidates"]:
        receipt = c.get("receipt") or {}
        rows.append(
            "<tr>"
            + "".join(
                f"<td>{escape(str(v))}</td>"
                for v in (
                    c["title"]
                    + (" · 暂选" if c["id"] == state["selected_candidate_id"] else ""),
                    statuses.get(c["status"], c["status"]),
                    score(receipt.get("macro_ba")),
                    delta(receipt.get("mean_delta")),
                    f"{c['cost_seconds']:.1f} 秒",
                    c.get("error") or "",
                )
            )
            + "</tr>"
        )
    actions = []
    labels = {
        "propose_candidate": "候选提案",
        "request_evidence": "定向阅读",
        "finish": "结束搜索",
        "enumerate_remaining": "枚举剩余候选",
        "initial_schedule": "冻结一次性提案",
        "invalid_proposal": "提案校验未通过",
        "model_decision": "模型调用",
    }
    for a in state["actions"]:
        if a["action"] == "model_decision" and a["status"] == "completed":
            continue
        branches = a.get("decision_branches") or {}
        request, result = a.get("request") or {}, a.get("result") or {}
        details = [
            ("候选", a.get("candidate_id")),
            ("依据候选", a.get("base_candidate_id")),
            ("理由", a["reason"] or result.get("reason")),
            ("预期", a.get("expected_result")),
            ("若改善", branches.get("improvement")),
            ("若未改善", branches.get("no_improvement")),
            ("阅读问题", request.get("question")),
            ("影响的选择", request.get("affects_choice")),
            ("来源", result.get("url")),
            ("摘录", "\n".join(result.get("excerpts", []))),
            ("候选顺序", ", ".join(result.get("candidate_ids", []))),
            ("未解决问题", "；".join(request.get("unresolved", []))),
            ("失败原因", a.get("error")),
        ]
        actions.append(
            f"<details><summary>{a['index']} · {escape(labels.get(a['action'], a['action']))} · {escape(statuses.get(a['status'], a['status']))}</summary>"
            + "".join(
                f"<p><strong>{label}：</strong>{escape(str(value))}</p>"
                for label, value in details
                if value
            )
            + "</details>"
        )
    per_subject = []
    if selected:
        for subject, row in (selected.get("receipt") or {}).get("subjects", {}).items():
            per_subject.append(
                f"<tr><td>{escape(subject)}</td><td>{score(row.get('ba'))}</td><td>{delta(row.get('delta'))}</td></tr>"
            )
    content = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>开发面板下的预处理搜索</title><style>
body{{font:16px/1.7 system-ui,sans-serif;color:#20343a;background:#f5f7f8;margin:0;padding:36px}}
main{{max-width:1100px;margin:auto;background:white;padding:36px;border-radius:16px}}h1{{font-size:28px}}h2{{font-size:20px;margin-top:32px}}
.muted{{color:#62757c}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{text-align:left;border-bottom:1px solid #e0e8e9;padding:12px 8px}}
details{{border-bottom:1px solid #e0e8e9;padding:12px 0}}summary{{cursor:pointer}}.scroll{{overflow:auto}}a{{color:#127e79}}
</style><main><p class="muted">离线预处理搜索 · 开发评价</p><h1>在指定学习器和开发面板下选出的候选方案</h1>
<p>暂选：<strong>{escape(selected["title"] if selected else "未得到可评价候选")}</strong></p>
<p class="muted">{escape(reasons.get(state["stop_reason"], state["stop_reason"] or ""))} · 累计 {state["usage"]["elapsed_seconds"]:.1f} 秒 ·
候选 {state["usage"]["candidates"]}/{state["budget"]["max_candidates"]} · 提案 {state["usage"]["proposals"]}/{state["budget"]["max_proposals"]} · 阅读 {state["usage"]["evidence_reads"]}/{state["budget"]["max_evidence_reads"]}</p>
<p>本结果用于当前开发条件下的流程选择。开发集被反复查看，没有进行独立确认，也不证明神经信号质量。</p>
<h2>候选比较</h2><div class="scroll"><table><thead><tr><th>候选</th><th>状态</th><th>被试宏平均 BA</th><th>相对参考差值</th><th>实际耗时</th><th>原因</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<h2>逐轮决定</h2>{"".join(actions)}<h2>暂选候选的开发被试明细</h2><table><tr><th>被试</th><th>BA</th><th>相对参考</th></tr>{"".join(per_subject)}</table>
<h2>数据与评价协议</h2><p>完整原始 trial 清单见 panel.json；训练和开发被试互不重叠。特征为逐 trial、逐通道对数方差，StandardScaler 与逻辑回归只在训练组拟合。</p>
<p>只有完整覆盖同一开发清单的候选可被选择；分数精确相同时优先参考，再按算子数和目录顺序决定。无效候选、执行故障和资源不足分别记录。</p>
</main></html>"""
    (root / "report.html").write_text(content, encoding="utf-8")
    files = []
    for p in sorted(root.rglob("*")):
        if (
            not p.is_file()
            or p.name
            in {"files.json", "search.json", "search.lock", "preprocessing.db"}
            or p.name.endswith((".tmp", "-wal", "-shm", ".lock"))
        ):
            continue
        name = p.relative_to(root).as_posix()
        files.append(
            {
                "name": name,
                "bytes": p.stat().st_size,
                "sha256": file_hash(p),
                "url": f"/api/searches/{state['id']}/artifacts/{name}?download=true",
            }
        )
    write(root / "files.json", {"schema_version": "1", "files": files})
