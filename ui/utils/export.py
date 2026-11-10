"""Export utilities for QC Studio.

This module provides functions for saving QC results to various formats.
"""

import pandas as pd
from pathlib import Path
from constants import QC_DEDUP_KEYS


def normalize_note_value(value):
    """Strip leading/trailing whitespace and line endings from note text."""
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    if text.lower() == "nan":
        return ""
    return text.strip()


def _normalize_screen_size_label(value):
    """Compatibility helper: convert range-based choices to the display labels used in exports."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    mapping = {
        "14 or less": "Laptop (13 inch)",
        "15-20": "Laptop (17 inch)",
        "21-25": "Monitor (24 inch)",
        "26-30": "Desktop (27 inch)",
        "31 or above": "Large desktop display (32 inch)",
        "Unknown": "Unknown",
    }
    return mapping.get(text, text)


def build_qc_results_dataframe(qc_records):
    """Build the canonical tabular QC export frame from in-memory QC records."""
    expected_columns = [
        "pipeline",
        "qc_task",
        "participant_id",
        "session_id",
        "task_id",
        "run_id",
        "timestamp",
        "rater_id",
        "rater_experience",
        "rater_fatigue",
        "rater_screen_size",
        "final_qc",
        "facet",
        "rating_value",
        "notes",
    ]

    rows = []

    for rec in qc_records:
        if hasattr(rec, "model_dump"):
            rec_dict = rec.model_dump()
        elif hasattr(rec, "dict"):
            rec_dict = rec.dict()
        elif isinstance(rec, dict):
            rec_dict = rec
        else:
            continue

        participant_id = rec_dict.get("participant_id") or ""
        session_id = rec_dict.get("session_id") or ""
        if session_id is not None:
            session_id = str(session_id)

        row = {
            "pipeline": rec_dict.get("pipeline"),
            "qc_task": rec_dict.get("qc_task"),
            "participant_id": participant_id,
            "session_id": session_id,
            "task_id": rec_dict.get("task_id"),
            "run_id": rec_dict.get("run_id"),
            "timestamp": rec_dict.get("timestamp"),
            "rater_id": rec_dict.get("rater_id"),
            "rater_experience": rec_dict.get("rater_experience"),
            "rater_fatigue": rec_dict.get("rater_fatigue"),
            "rater_screen_size": _normalize_screen_size_label(rec_dict.get("rater_screen_size")),
            "final_qc": rec_dict.get("final_qc"),
            "facet": "",
            "rating_value": "",
            "notes": normalize_note_value(rec_dict.get("notes")),
        }
        ratings = rec_dict.get("ratings")
        if isinstance(ratings, dict) and ratings:
            for facet, value in ratings.items():
                facet_row = row.copy()
                facet_row["facet"] = str(facet)
                facet_row["rating_value"] = value if value is not None and not pd.isna(value) else ""
                rows.append(facet_row)
        else:
            rows.append(row)

    if rows:
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(columns=expected_columns)

    for col in expected_columns:
        if col not in df.columns:
            df[col] = ""
    extra = [c for c in df.columns if c not in expected_columns]
    if extra:
        df = df.drop(columns=extra)
    df = df[expected_columns]
    df = df.fillna("")
    df = df.replace({pd.NA: ""})

    if not df.empty:
        sort_cols = [c for c in ("pipeline", "participant_id", "session_id", "qc_task", "facet") if c in df.columns]
        if sort_cols:
            df = df.sort_values(by=sort_cols, kind="mergesort").reset_index(drop=True)

    return df


def save_qc_results_to_csv(out_file, qc_records, drop_duplicates=True):
    """Save QC results from Streamlit session state to a CSV file.

        This function is resilient to both `QCRecord` model instances and plain
        dicts. It will extract canonical fields from `QCRecord` and supports:
        - single-scale ratings (`final_qc`)
        - multi-facet ratings (`ratings` dict), exported one row per facet

    If a record also contains a `metrics` list (items compatible with
    `MetricQC`), those metrics will be flattened into columns as
    `<metric_name>_value` and `<metric_name>` (for qc string), and
    `QC_notes` (if present) will be placed in a `notes` column.

    Parameters
    ----------
    out_file : str or Path
            Path where the CSV will be saved.
    qc_records : list
            List of `QCRecord` objects (or dicts) stored.
    """
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    df = build_qc_results_dataframe(qc_records)
    expected_columns = [
        "pipeline",
        "qc_task",
        "participant_id",
        "session_id",
        "task_id",
        "run_id",
        "timestamp",
        "rater_id",
        "rater_experience",
        "rater_fatigue",
        "rater_screen_size",
        "final_qc",
        "facet",
        "rating_value",
        "notes",
    ]

    if out_file.exists():
        df_existing = pd.read_csv(out_file, sep="\t")
        df = pd.concat([df_existing, df], ignore_index=True)

    # Align column order and fill missing cells (e.g. legacy files with different column order).
    for col in expected_columns:
        if col not in df.columns:
            df[col] = ""
    extra = [c for c in df.columns if c not in expected_columns]
    if extra:
        df = df.drop(columns=extra)
    df = df[expected_columns]
    df = df.fillna("")
    df = df.replace({pd.NA: ""})

    # Drop duplicates based on core identity columns
    dropped = 0
    dropped_details: list[str] = []
    if drop_duplicates:
        existing_keys = [k for k in QC_DEDUP_KEYS if k in df.columns]
        if "facet" in df.columns:
            existing_keys.append("facet")
        if existing_keys:
            # Normalise to string so int/str type mismatches (e.g. session_id 1 vs "1") don't prevent dedup
            for col in existing_keys:
                df[col] = df[col].astype(str)
            duped_mask = df.duplicated(subset=existing_keys, keep="last")
            dropped = duped_mask.sum()
            grouped: dict[tuple[str, str], list[str]] = {}
            for _, r in df.loc[duped_mask].iterrows():
                key = (r.get("participant_id", ""), r.get("session_id", ""))
                grouped.setdefault(key, [])
                task = r.get("qc_task", "")
                if task not in grouped[key]:
                    grouped[key].append(task)
            dropped_details = {k: v for k, v in grouped.items()}
            df = df[~duped_mask]

    # Cohort-style row order: all tasks for participant A session 1, then session 2, then next participant.
    if not df.empty:
        sort_cols = [c for c in ("pipeline", "participant_id", "session_id", "qc_task", "facet") if c in df.columns]
        if sort_cols:
            df = df.sort_values(by=sort_cols, kind="mergesort").reset_index(drop=True)

    df.to_csv(out_file, index=False, sep="\t")

    return out_file, dropped, dropped_details
