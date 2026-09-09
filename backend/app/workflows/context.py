"""Lossless grouping for repeated measurements sent to the reasoning model."""

import json


def grouped_records(records, identity="id", omit=()):
    groups = {}
    for record in records:
        observed = {k: v for k, v in record.items() if k not in {identity, *omit}}
        key = json.dumps(observed, sort_keys=True, ensure_ascii=False)
        group = groups.setdefault(key, {"record_ids": [], "values": observed})
        group["record_ids"].append(record[identity])
    return list(groups.values())


def results_context(outputs):
    result = {}
    for stage, data in outputs.items():
        result[stage] = {
            k: v for k, v in data.items() if k not in {"records", "channel_sets"}
        }
        if "records" in data:
            if stage == "data_survey":
                result[stage]["record_groups"] = grouped_records(
                    data["records"], omit=("source_path", "sha256", "subject")
                )
            elif stage == "data_preprocessing":
                result[stage]["record_groups"] = grouped_records(
                    data["records"], "record_id", ("artifact_root",)
                )
            else:
                result[stage]["records"] = data["records"]
    return result
