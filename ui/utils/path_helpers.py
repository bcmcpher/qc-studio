"""Shared filename/path normalization helpers for QC-Studio."""

import re


def sanitize_qc_task_slug(qc_task: str | None) -> str:
    """Return a canonical QC task slug for file names.

    Rules:
    - blank -> ``unknown_task``
    - ``all`` (case-insensitive) -> ``all_tasks``
    - otherwise: replace non filename-safe chars with ``_`` and lowercase.
    """
    task = str(qc_task or "").strip()
    if not task:
        return "unknown_task"
    if task.lower() == "all":
        return "all_tasks"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", task).strip("_").lower() or "unknown_task"
