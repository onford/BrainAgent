"""EEGMMIDB adapter: source inspection and conversion have separate outputs."""

import json
from collections import Counter
from pathlib import Path

from app.preprocessing.schemas import (
    CollectionSnapshot,
    Evidence,
    PreprocessInput,
    RecordSpec,
    SurveySnapshot,
)
from app.preprocessing.storage import file_hash, within
from .records import write_readable as write_json
from .formats import write_table as write_tsv
from .cognition_contracts import ResearchFindings, ResearchSources

SOURCE = "https://physionet.org/content/eegmmidb/1.0.0/"
EVENT_ID = {"left_hand": 1, "right_hand": 2}
PROFILE = {
    "dataset_id": "eegmmidb",
    "name": "EEG Motor Movement/Imagery Dataset",
    "version": "1.0.0",
    "doi": "10.13026/C28G6P",
    "publisher": "PhysioNet / Gerwin Schalk",
    "published": "2009-09-09",
    "license": "Open Data Commons Attribution License v1.0",
    "source_url": SOURCE,
    "profile_reviewed": "2026-09-08",
    "task": "left_right_motor_imagery",
    "expected_sfreq": 160,
    "expected_eeg_channels": 64,
    "trigger_map": {"T0": "rest", "T1": "left_hand", "T2": "right_hand"},
    "run_scope": [4, 8, 12],
    "references": [
        {"title": "EEG Motor Movement/Imagery Dataset", "url": SOURCE},
        {
            "title": "BCI2000: A General-Purpose Brain-Computer Interface (BCI) System",
            "doi": "10.1109/TBME.2004.827072",
            "url": "https://doi.org/10.1109/TBME.2004.827072",
        },
        {
            "title": "PhysioNet as a global platform for biomedical research",
            "doi": "10.1038/s44360-026-00096-z",
            "url": "https://doi.org/10.1038/s44360-026-00096-z",
        },
    ],
    "unknown_fields": [
        "age",
        "sex",
        "health_status",
        "acquisition_reference",
        "hardware_filter",
    ],
    "literature_status": "versioned dataset references; automatic full-text review not performed",
}


def allowed_source(request, allowed_roots, output_roots):
    root = Path(request.source_root).resolve(strict=True)
    if not root.is_dir() or not any(
        root.is_relative_to(p.resolve()) for p in allowed_roots
    ):
        raise ValueError("数据目录不在 WORKFLOW_INPUT_ROOTS 允许范围内")
    if any(
        root.is_relative_to(p.resolve()) or p.resolve().is_relative_to(root)
        for p in output_roots
    ):
        raise ValueError("源数据与输出目录必须分离")
    return root


def inspect(root, request, folder):
    import mne

    all_edf = sorted(root.glob("S[0-9][0-9][0-9]/S*R*.edf"))
    subjects = sorted({p.parent.name for p in all_edf})
    chosen = request.subjects or subjects[: request.max_subjects]
    if not chosen:
        raise ValueError("没有找到 EEGMMIDB EDF 记录")
    records, checks, channel_sets = [], [], {}
    inventory = [
        {"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size}
        for p in all_edf
    ]
    for subject in chosen:
        for run in request.runs:
            relative = f"{subject}/{subject}R{run:02}.edf"
            path = within(root, relative)
            record = {
                "id": f"{subject}R{run:02}",
                "subject": subject,
                "run": run,
                "source_path": relative,
            }
            try:
                if path.is_symlink():
                    raise ValueError("源文件需要为实际文件")
                with mne.io.read_raw_edf(path, preload=False, verbose="ERROR") as raw:
                    counts = dict(Counter(str(v) for v in raw.annotations.description))
                    if not {"T1", "T2"} <= counts.keys():
                        raise ValueError("记录缺少左右手类别标签")
                    if raw.info["sfreq"] != 160 or len(raw.ch_names) != 64:
                        raise ValueError("采样率或通道数与 EEGMMIDB 配置不一致")
                    channel_set = next(
                        (k for k, v in channel_sets.items() if v == raw.ch_names), None
                    )
                    if channel_set is None:
                        channel_set = f"channels_{len(channel_sets) + 1}"
                        channel_sets[channel_set] = list(raw.ch_names)
                    record.update(
                        sfreq=float(raw.info["sfreq"]),
                        samples=int(raw.n_times),
                        channel_set=channel_set,
                        duration_s=raw.n_times / raw.info["sfreq"],
                        event_counts=counts,
                        task_trials=counts["T1"] + counts["T2"],
                        sha256=file_hash(path),
                        status="readable",
                    )
            except (OSError, ValueError, RuntimeError) as exc:
                record.update(status="excluded", reason=str(exc))
                checks.append(
                    {
                        "object_key": record["id"],
                        "check_category": "format_readability",
                        "status": "不一致",
                        "severity": "structural-hard-fail",
                        "action": "排除",
                        "observed_evidence": str(exc),
                    }
                )
            records.append(record)
    result = {
        "profile": PROFILE,
        "source_root": str(root),
        "available_subjects": len(subjects),
        "available_recordings": len(inventory),
        "selected_subjects": chosen,
        "channel_sets": channel_sets,
        "records": records,
        "checks": checks,
        "statistics": summarize(records, include_excluded=True),
        "evidence": [
            {
                "source_url": SOURCE,
                "locator": "Methods / Data Description / Usage Notes",
                "type": "reviewed_profile",
            },
            {
                "source_url": "https://mne.tools/1.10/generated/mne.datasets.eegbci.load_data.html",
                "locator": "runs table: 4, 8, 12",
                "type": "run_mapping",
            },
        ],
        "scope": "selected subjects and imagery runs; unselected recordings are outside this workflow",
    }
    write_tsv(folder / "source-inventory.tsv", inventory, ["path", "bytes"])
    write_tsv(
        folder / "triggers.tsv",
        [{"trigger": k, "meaning": v} for k, v in PROFILE["trigger_map"].items()],
        ["trigger", "meaning"],
    )
    return result


def summarize(records, *, include_excluded=False):
    readable = [r for r in records if include_excluded or r.get("status") != "excluded"]
    return {
        "subjects": len({r["subject"] for r in readable}),
        "recordings": len(readable),
        "trials": sum(r.get("task_trials", 0) for r in readable),
        "duration_s": sum(r.get("duration_s", 0) for r in readable),
        "unknown_recordings": sum("samples" not in r for r in readable),
    }


def check_sources(survey):
    root = Path(survey["source_root"])
    for record in survey["records"]:
        if (
            record.get("sha256")
            and file_hash(within(root, record["source_path"])) != record["sha256"]
        ):
            raise ValueError(f"源文件已变化：{record['source_path']}")


def collect(survey, folder, workflow_id, service, owner):
    import mne
    import numpy as np
    from mne_bids import BIDSPath, write_raw_bids

    check_sources(survey)
    bids_root = folder / "bids"
    root = Path(survey["source_root"])
    records, mapping, excluded = [], [], []
    checks = list(survey["checks"])
    kept = []
    for item in survey["records"]:
        if item["status"] == "excluded":
            excluded.append({"object_key": item["id"], "reason": item["reason"]})
            continue
        path = within(root, item["source_path"])
        # Only inspection failures are excluded. Conversion errors fail the stage,
        # rather than silently leaving partial BIDS file groups in the selection.
        raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR")
        if not np.isfinite(raw.get_data()).all():
            excluded.append({"object_key": item["id"], "reason": "nonfinite signal"})
            checks.append(
                {
                    "object_key": item["id"],
                    "check_category": "dimensions_units_values",
                    "status": "不一致",
                    "severity": "structural-hard-fail",
                    "action": "排除",
                    "observed_evidence": "nonfinite signal",
                }
            )
            continue
        mne.datasets.eegbci.standardize(raw)
        raw.set_montage("standard_1005", on_missing="raise", verbose="ERROR")
        take = np.isin(raw.annotations.description, ["T1", "T2"])
        raw.set_annotations(
            mne.Annotations(
                raw.annotations.onset[take],
                raw.annotations.duration[take],
                [
                    "left_hand" if v == "T1" else "right_hand"
                    for v in raw.annotations.description[take]
                ],
            )
        )
        bids = BIDSPath(
            root=bids_root,
            subject=item["subject"][1:],
            task="leftrightmi",
            run=f"{item['run']:02}",
            datatype="eeg",
        )
        write_raw_bids(
            raw,
            bids,
            format="BrainVision",
            allow_preload=True,
            event_id=EVENT_ID,
            overwrite=True,
            verbose="ERROR",
        )
        vhdr = bids.copy().update(suffix="eeg", extension=".vhdr").fpath
        meta = json.loads(vhdr.with_suffix(".json").read_text(encoding="utf-8"))
        meta["EEGReference"] = "n/a"
        write_json(vhdr.with_suffix(".json"), meta)
        converted = mne.io.read_raw_brainvision(vhdr, preload=True, verbose="ERROR")
        error = float(np.max(np.abs(converted.get_data() - raw.get_data())))
        if not np.allclose(converted.get_data(), raw.get_data(), rtol=3e-7, atol=1e-12):
            raise ValueError("BrainVision conversion roundtrip exceeded tolerance")
        records.append(
            RecordSpec(
                id=item["id"],
                bids_path=vhdr.relative_to(bids_root).as_posix(),
                files={"pending": "0" * 64},
                sfreq=item["sfreq"],
                samples=item["samples"],
                channels=dict(zip(raw.ch_names, raw.get_channel_types())),
                channel_order=raw.ch_names,
                reference="n/a",
            )
        )
        kept.append(item)
        mapping.append(
            {
                "object_key": item["id"],
                "source": item["source_path"],
                "source_sha256": item["sha256"],
                "target": vhdr.relative_to(bids_root).as_posix(),
                "roundtrip_max_error_V": error,
            }
        )
        checks.append(
            {
                "object_key": item["id"],
                "check_category": "format_readability",
                "status": "一致",
                "severity": "information-only",
                "action": "建立工作副本",
                "observed_evidence": f"roundtrip max error {error} V",
            }
        )
    if not records:
        raise ValueError("没有通过基础读取检查的记录")
    check_sources(survey)
    inventory = {
        p.relative_to(bids_root).as_posix(): file_hash(p)
        for p in bids_root.rglob("*")
        if p.is_file()
    }
    for record in records:
        record.files = inventory.copy()
    evidence = Evidence(
        source_url="workflow:" + workflow_id,
        locator="collection/mapping.tsv and local EDF headers",
        text="Local EDF decoded, EEGMMIDB adapter applied, BrainVision roundtrip checked; source bytes unchanged.",
        source_version="1",
    )
    facts = [evidence]
    research_folder = (
        folder if (folder / "research.json").exists() else folder.parent / "survey"
    )
    research_path = research_folder / "research.json"
    if research_path.exists():
        research = ResearchFindings.model_validate_json(
            research_path.read_text(encoding="utf-8")
        )
        sources = ResearchSources.model_validate_json(
            (research_folder / "sources.json").read_text(encoding="utf-8")
        )
        documents = {d.id: d for d in sources.documents}
        for fact in research.facts:
            doc = documents[fact.source_id]
            ref = service.store.put(
                owner, "evidence", {"url": doc.url, "content": doc.text}
            )
            facts.append(
                Evidence(
                    source_url=doc.url,
                    locator=fact.topic,
                    text=fact.quote,
                    source_version=doc.sha256,
                    artifact_ref=ref,
                )
            )
    data = PreprocessInput(
        purpose="production",
        survey=SurveySnapshot(
            dataset_id="eegmmidb",
            dataset_version="1.0.0",
            survey_run_id=workflow_id,
            task="left_right_motor_imagery",
            event_id=EVENT_ID,
            processing_history=[
                "EDF to BrainVision; channel names standardized; task annotations selected; template electrode coordinates"
            ],
            facts=facts,
        ),
        collection=CollectionSnapshot(
            dataset_id="eegmmidb",
            dataset_version="1.0.0",
            root=str(bids_root),
            standard_version=json.loads(
                (bids_root / "dataset_description.json").read_text()
            )["BIDSVersion"],
            validation_evidence=evidence,
            selection_reason="explicit workflow subject/run selection; structural checks only",
            selected_record_ids=[r.id for r in records],
            records=records,
        ),
    )
    ref = service.register_input(owner, data)
    write_json(folder / "input.json", data.model_dump(mode="json"))
    pre, post = survey["statistics"], summarize(kept)
    write_json(folder / "pre-screen.json", pre)
    write_json(folder / "post-screen.json", post)
    write_tsv(
        folder / "delta.tsv",
        [
            {
                "metric": k,
                "before": pre[k],
                "after": post[k],
                "change": post[k] - pre[k],
            }
            for k in pre
        ],
        ["metric", "before", "after", "change"],
    )
    write_tsv(
        folder / "mapping.tsv",
        mapping,
        ["object_key", "source", "source_sha256", "target", "roundtrip_max_error_V"],
    )
    for check in checks:
        check.setdefault(
            "expected_statement",
            "EEGMMIDB profile: readable EDF, 64 EEG channels, 160 Hz, T1/T2 imagery events",
        )
        check["provenance"] = (
            f"workflow={workflow_id}; adapter=eegmmidb-v1; output={folder}"
        )
    write_tsv(
        folder / "anomalies.tsv",
        checks,
        [
            "check_category",
            "object_key",
            "expected_statement",
            "observed_evidence",
            "status",
            "severity",
            "action",
            "provenance",
        ],
    )
    write_tsv(folder / "exclusions.tsv", excluded, ["object_key", "reason"])
    return {
        "input_ref": ref.model_dump(),
        "standardized_root": str(bids_root),
        "statistics": post,
        "excluded": excluded,
        "source_unchanged": True,
        "validation": "BrainVision roundtrip and bounded BIDS input contract; full official BIDS validation not run",
        "adaptations": [
            "Channel names standardized; standard_1005 template positions are not individual digitizations",
            "T0 rest annotations excluded from training event table; source EDF retained",
            "Scientific artifact screening not applied",
        ],
    }
