"""The active research objective, shared by discovery and method extraction."""

INSTRUCTION = (
    'The active objective is one shared preprocessing recipe across records. '
    'Subject-specific preprocessing, subject-pooled fitting/normalization, per-subject '
    'unlabeled adaptation and subject-specific recipe selection are withdrawn objectives. '
    'Do not search for, implement or repair these as capabilities. A source branch that '
    'requires them is outside the active method objective; retain its scope reason rather '
    'than silently omit required stages to make it executable. An independently supported '
    'shared branch in the same source may still be considered. Record-local native '
    'ICA/ASR/PREP/RELAX fitting remains allowed only with explicit shared record_unlabeled '
    'permission. Subject IDs, grouped validation and subject-macro reporting are retained '
    'for leakage control and statistics. Near-SOTA performance chasing is withdrawn; '
    'measure actual outcomes without imposing a frontier-performance target. '
)
