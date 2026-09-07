"""Preserve full search evidence separately from bounded model summaries."""

import re


def sanitize_evidence(value):
    if isinstance(value, dict):
        return {
            str(k): sanitize_evidence(v)
            for k, v in value.items()
            if not re.search(
                r"authorization|api[_-]?key|password|secret|token|cookie|credential",
                str(k),
                re.I,
            )
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_evidence(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [redacted]", value)
        value = re.sub(
            r"(?i)([?&](?:api[_-]?key|token|secret|access_token)=)[^&\s\"']+",
            r"\1[redacted]",
            value,
        )
        value = re.sub(r"(?i)(https?://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", value)
    return value
