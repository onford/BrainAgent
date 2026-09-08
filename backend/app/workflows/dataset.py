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
from .survey_contracts import LocalFact, LocalInspection
from .intake import Audit, table

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
    import numpy as np

    all_edf = sorted(root.glob("S[0-9][0-9][0-9]/S*R*.edf"))
    subjects = sorted({p.parent.name for p in all_edf})
    chosen = request.subjects or subjects[: request.max_subjects]
    if not chosen:
        raise ValueError("没有找到 EEGMMIDB EDF 记录")
    records, checks, channel_sets = [], [], {}
    local_facts = []

    def observe(field, scope, value, locator):
        local_facts.append(
            LocalFact(
                id=f"local-{len(local_facts) + 1}",
                field=field,
                scope=scope,
                value=str(value),
                locator=locator,
            )
        )

    all_files = sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())
    inventory = [
        {"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size}
        for p in all_files
    ]
    tree_paths = set()
    for p in all_files:
        relative = p.relative_to(root)
        tree_paths.add(relative)
        tree_paths.update(q for q in relative.parents if q != Path("."))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "directory-tree.txt").write_text(
        ".\n"
        + "\n".join(
            "  " * (len(p.parts) - 1) + p.name + ("/" if (root / p).is_dir() else "")
            for p in sorted(tree_paths, key=lambda p: p.as_posix())
        )
        + "\n",
        encoding="utf-8",
    )
    observe(
        "directory_structure",
        "source directory",
        f"{len(all_files)} files; extensions={dict(Counter(p.suffix for p in all_files))}",
        "survey/directory-tree.txt; survey/source-inventory.tsv",
    )
    observe(
        "subjects",
        "source directory and selected subset",
        f"available={len(subjects)}; selected={chosen}",
        "survey/survey.json#/selected_subjects",
    )
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
                original = root / relative
                if (
                    original.is_symlink()
                    or original.parent.is_symlink()
                    or getattr(original.parent, "is_junction", lambda: False)()
                ):
                    raise ValueError("源文件需要为实际文件")
                record["sha256"] = file_hash(path)
                with mne.io.read_raw_edf(path, preload=False, verbose="ERROR") as raw:
                    counts = dict(Counter(str(v) for v in raw.annotations.description))
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
                        task_trials=counts.get("T1", 0) + counts.get("T2", 0),
                        sha256=file_hash(path),
                        status="readable",
                    )
                    values = raw.get_data()
                    measurements = {
                        "file_format": "EDF decoded by MNE",
                        "file_header": f"nchan={raw.info['nchan']}; sfreq={raw.info['sfreq']}; samples={raw.n_times}",
                        "signal_arrays": f"shape={values.shape}; dtype={values.dtype}; unit=V (MNE); finite={bool(np.isfinite(values).all())}",
                        "channels": f"count={len(raw.ch_names)}; channel_set={channel_set}; names={raw.ch_names}",
                        "sampling_rate": f"{raw.info['sfreq']} Hz",
                        "events": json.dumps(counts, ensure_ascii=False),
                        "task_runs": f"path run={run}; decoded annotations={sorted(counts)}; task meaning needs external verification",
                        "recording_duration": f"{raw.n_times / raw.info['sfreq']} s",
                    }
                    for field, measurement in measurements.items():
                        observe(field, record["id"], measurement, relative)
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
        "available_recordings": len(all_edf),
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
    write_json(
        folder / "local-inspection.json",
        LocalInspection(
            scope="Directory inventory covers the source root; headers and arrays cover selected records only. Values are observations, not adapter assumptions.",
            facts=local_facts,
        ).model_dump(mode="json"),
    )
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
        "trials": sum(r["task_trials"] for r in readable)
        if all("task_trials" in r for r in readable)
        else None,
        "duration_s": sum(r["duration_s"] for r in readable)
        if all("duration_s" in r for r in readable)
        else None,
        "unknown_recordings": sum("samples" not in r for r in readable),
        "sessions": None,
        "runs": len({(r["subject"], r["run"]) for r in readable}),
        "channels": None,
        "channel_observations": None,
        "events": sum(sum(r.get("event_counts", {}).values()) for r in readable)
        if all("event_counts" in r for r in readable)
        else None,
        "rest_segments": sum(r.get("event_counts", {}).get("T0", 0) for r in readable)
        if all("event_counts" in r for r in readable)
        else None,
        "files": sum(bool(r.get("sha256")) for r in readable),
        "behavior_records": None,
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
    folder.mkdir(parents=True, exist_ok=True)
    audit = Audit(folder, survey)
    kept, excluded = audit.scan()
    post = screening_statistics(survey, kept, excluded, folder)
    table(folder, "exclusions.tsv", excluded)
    integrity = {
        r["source_path"]: r["sha256"] for r in survey["records"] if r.get("sha256")
    }
    write_json(
        folder / "source-integrity.json",
        {
            "scope": "所选记录中实际存在的源 EDF；读取前后按同一清单核验",
            "files": integrity,
            "checked_after": False,
            "unchanged": False,
        },
    )
    channel_mapping, event_mapping = [], []
    for item in kept:
        path = within(root, item["source_path"])
        # Only inspection failures are excluded. Conversion errors fail the stage,
        # rather than silently leaving partial BIDS file groups in the selection.
        raw = mne.io.read_raw_edf(path, preload=True, verbose="ERROR")
        source_names = list(raw.ch_names)
        original_annotations = raw.annotations.copy()
        mne.datasets.eegbci.standardize(raw)
        raw.set_montage("standard_1005", on_missing="raise", verbose="ERROR")
        event_names = {"T0": "rest", "T1": "left_hand", "T2": "right_hand"}
        standard_event_id = {**EVENT_ID, "rest": 3}
        raw.set_annotations(
            mne.Annotations(
                original_annotations.onset - raw.first_time,
                original_annotations.duration,
                [event_names[v] for v in original_annotations.description],
            )
        )
        channel_mapping.extend(
            {
                "object_key": item["id"],
                "source_index": i,
                "source_name": source_name,
                "target_name": raw.ch_names[i],
                "channel_type": raw.get_channel_types()[i],
                "decoded_unit": "V",
                "coordinate_source": "standard_1005 template; not individual digitization",
            }
            for i, source_name in enumerate(source_names)
        )
        event_mapping.extend(
            {
                "object_key": item["id"],
                "source_index": i,
                "source_label": str(label),
                "target_label": event_names[label],
                "target_code": standard_event_id[event_names[label]],
                "onset_s": float(onset - raw.first_time),
                "duration_s": float(duration),
                "source_sample": int(
                    round((onset - raw.first_time) * raw.info["sfreq"])
                ),
                "training_selected": label in {"T1", "T2"},
            }
            for i, (onset, duration, label) in enumerate(
                zip(
                    original_annotations.onset,
                    original_annotations.duration,
                    original_annotations.description,
                )
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
            event_id=standard_event_id,
            overwrite=True,
            verbose="ERROR",
        )
        vhdr = bids.copy().update(suffix="eeg", extension=".vhdr").fpath
        meta = json.loads(vhdr.with_suffix(".json").read_text(encoding="utf-8"))
        meta["EEGReference"] = "n/a"
        meta["Manufacturer"] = "n/a"
        meta["HardwareFilters"] = "n/a"
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
        mapping.append(
            {
                "object_key": item["id"],
                "source": item["source_path"],
                "source_sha256": item["sha256"],
                "target": vhdr.relative_to(bids_root).as_posix(),
                "roundtrip_max_error_V": error,
                "target_sha256": file_hash(vhdr),
            }
        )
        import csv

        event_path = vhdr.parent / vhdr.name.replace("eeg.vhdr", "events.tsv")
        with event_path.open(encoding="utf-8-sig", newline="") as stream:
            target_events = list(csv.DictReader(stream, delimiter="\t"))
        expected_events = [e for e in event_mapping if e["object_key"] == item["id"]]
        if len(target_events) != len(expected_events) or any(
            row["trial_type"] != expected["target_label"]
            or abs(float(row["onset"]) - expected["onset_s"]) > 1e-6
            or abs(float(row["duration"]) - expected["duration_s"]) > 1e-6
            or int(row["value"]) != expected["target_code"]
            for row, expected in zip(target_events, expected_events)
        ):
            raise ValueError("standardized events differ from source annotations")
        if (
            converted.ch_names != raw.ch_names
            or converted.n_times != raw.n_times
            or converted.info["sfreq"] != raw.info["sfreq"]
        ):
            raise ValueError("standardized channel/time identity differs from source")
        audit.add(
            "raw_processed",
            item["id"],
            "信号往返误差受限；通道、采样点、采样率和全部事件一致",
            f"max_error_V={error}; events={len(target_events)}; mapping.tsv, channel-mapping.tsv, event-mapping.tsv",
            action="建立工作副本",
        )
    if records:
        audit.checks = [
            c
            for c in audit.checks
            if not (
                c.check_category == "raw_processed"
                and c.object_key == "dataset/selection"
            )
        ]
    audit.save()
    table(folder, "channel-mapping.tsv", channel_mapping)
    table(folder, "event-mapping.tsv", event_mapping)
    if not records:
        raise ValueError("没有通过基础读取检查的记录")
    check_sources(survey)
    for path in bids_root.rglob("*coordsystem.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["EEGCoordinateSystemDescription"] = (
            "MNE standard_1005 template transformed to head coordinates; not individual digitization. "
            + metadata.get("EEGCoordinateSystemDescription", "")
        )
        write_json(path, metadata)
    description_path = bids_root / "dataset_description.json"
    description = json.loads(description_path.read_text(encoding="utf-8"))
    description["Name"] = survey["profile"]["name"]
    if survey["profile"]["license"] != "unknown":
        description["License"] = survey["profile"]["license"]
    write_json(description_path, description)
    write_json(
        folder / "source-integrity.json",
        {
            "scope": "所选记录中实际存在的源 EDF；读取前后按同一清单核验",
            "files": integrity,
            "checked_after": True,
            "unchanged": True,
        },
    )
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
            context_event_id={"rest": 3},
            processing_history=[
                "EDF to BrainVision; channel names standardized; all source annotations preserved; template electrode coordinates"
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
    table(folder, "mapping.tsv", mapping)
    write_json(
        folder / "standardization.json",
        {
            "standard": "BIDS-EEG",
            "version": description["BIDSVersion"],
            "writer": "mne-bids " + audit.provenance.versions["mne-bids"],
            "supported_scope": "EEGMMIDB EDF，所选左右手运动想象记录；BrainVision BIDS 工作副本",
            "unsupported_modalities": ["BIDS-iEEG (eCoG/sEEG)", "NWB"],
            "validation": "信号往返、通道/时间一致性、完整事件映射、文件组/根元数据及输入合同检查",
            "official_validator": "not_run",
            "coordinate_source": "standard_1005 template, not individual digitization",
            "source_events": len(event_mapping),
            "standardized_events": len(event_mapping),
            "training_events": sum(e["training_selected"] for e in event_mapping),
            "file_count": len(inventory),
        },
    )
    return {
        "input_ref": ref.model_dump(),
        "standardized_root": str(bids_root),
        "statistics": post,
        "excluded": excluded,
        "source_unchanged": True,
        "validation": "BrainVision roundtrip and bounded BIDS input contract; full official BIDS validation not run",
        "adaptations": [
            "Channel names standardized; standard_1005 template positions are not individual digitizations",
            "All T0/T1/T2 annotations preserved in BIDS; rest is explicit context outside training events",
            "Scientific artifact screening not applied",
        ],
    }


def screening_statistics(survey, kept, excluded, folder):
    pre, post = summarize(survey["records"], include_excluded=True), summarize(kept)
    for stats, items in ((pre, survey["records"]), (post, kept)):
        if all("channel_set" in r for r in items):
            stats["channels"] = len(
                {n for r in items for n in survey["channel_sets"][r["channel_set"]]}
            )
            stats["channel_observations"] = sum(
                len(survey["channel_sets"][r["channel_set"]]) for r in items
            )
    reason = (
        "; ".join(f"{r['object_key']}: {r['reason']}" for r in excluded)
        or "没有结构性排除；统计范围保持一致"
    )
    table(
        folder,
        "delta.tsv",
        [
            {
                "metric": k,
                "before": pre[k],
                "after": post[k],
                "change": post[k] - pre[k]
                if pre[k] is not None and post[k] is not None
                else None,
                "reason": "资料未提供或未解析，数量未知；" + reason
                if pre[k] is None or post[k] is None
                else reason,
            }
            for k in pre
        ],
    )
    write_json(folder / "pre-screen.json", pre)
    write_json(folder / "post-screen.json", post)
    return post
