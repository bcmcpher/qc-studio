"""Shared helpers for building MRI QC experiment packages.

This module owns reusable data loading, IQM enrichment, and Markdown rendering
helpers. Individual experiments should keep their own templates and small
rendering scripts, then import these helpers instead of duplicating the data
preparation logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_UI_DIR = Path(__file__).resolve().parents[1] / "ui"
if str(_UI_DIR) not in sys.path:
    sys.path.insert(0, str(_UI_DIR))

from utils.reference_data import (  # noqa: E402
    filter_reference_frame,
    normalize_field_strength,
    normalize_manufacturer,
)


BIDS_METADATA_FIELDS = [
    "Manufacturer",
    "ManufacturersModelName",
    "MagneticFieldStrength",
    "ScanningSequence",
    "SequenceVariant",
    "MRAcquisitionType",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "ReceiveCoilName",
    "PhaseEncodingDirection",
    "SliceEncodingDirection",
]


ALWAYS_HIGHLIGHT_T1W = {
    "snr_total",
    "snr_gm",
    "snr_wm",
    "cjv",
    "cnr",
    "efc",
    "fber",
    "fwhm_avg",
    "qi_1",
    "qi_2",
    "wm2max",
    "inu_range",
}




def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}, got {type(data)}")

    return data


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def numeric_values(data: dict[str, Any]) -> dict[str, float]:
    values = {}

    for key, value in data.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue

        if np.isfinite(number):
            values[key] = number

    return values


def read_table(path: Path) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    return pd.read_csv(path, sep=sep, low_memory=False)


def select_metadata(sidecar: dict[str, Any]) -> dict[str, Any]:
    return {
        key: sidecar[key]
        for key in BIDS_METADATA_FIELDS
        if key in sidecar and sidecar[key] not in (None, "")
    }


def load_subject_iqms(iqm_path: Path) -> dict[str, float]:
    """Load subject-level MRIQC IQMs from JSON or one-row TSV/CSV."""
    if iqm_path.suffix.lower() == ".json":
        return numeric_values(load_json(iqm_path))

    df = read_table(iqm_path)

    if df.empty:
        return {}

    return numeric_values(df.iloc[0].to_dict())


def load_reference_iqms(reference_path: Path) -> pd.DataFrame:
    return read_table(reference_path)


def compute_reference_stats(
    metric_name: str,
    value: float,
    reference_df: pd.DataFrame,
) -> dict[str, float | None]:
    """Compute percentile and z-score for one IQM."""
    if metric_name not in reference_df.columns:
        return {"percentile": None, "z_score": None}

    ref = pd.to_numeric(reference_df[metric_name], errors="coerce").dropna().to_numpy()

    if ref.size == 0:
        return {"percentile": None, "z_score": None}

    ref_mean = float(np.mean(ref))
    ref_std = float(np.std(ref, ddof=0))

    percentile = float(100 * np.mean(ref <= value))
    z_score = None if ref_std == 0 else float((value - ref_mean) / ref_std)

    return {
        "percentile": round(percentile, 3),
        "z_score": None if z_score is None else round(z_score, 3),
    }


def load_semantics(semantics_path: Path | None) -> dict[str, Any]:
    if semantics_path is None:
        return {"metrics": {}, "metric_patterns": {}}

    data = load_json(semantics_path)

    return {
        "metrics": data.get("metrics", {}),
        "metric_patterns": data.get("metric_patterns", {}),
    }


def lookup_semantics(metric_name: str, catalog: dict[str, Any]) -> dict[str, Any] | None:
    """Find exact or pattern-based semantic context for one metric."""
    if metric_name in catalog["metrics"]:
        return catalog["metrics"][metric_name]

    for pattern, entry in catalog["metric_patterns"].items():
        if pattern.endswith("*") and metric_name.startswith(pattern[:-1]):
            return entry

    return None


def enrich_iqms(
    subject_iqms: dict[str, float],
    reference_df: pd.DataFrame,
    semantics_catalog: dict[str, Any],
    subject_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Attach reference stats and optional semantic context to every IQM."""
    # Shared filter from ui/utils/reference_data.py: Manufacturer and field strength only
    # (the old sandbox filter also matched ManufacturersModelName). No row cap, and the full
    # population is kept when the subject's scanner has no reference rows.
    metadata = subject_metadata or {}
    filtered_ref = filter_reference_frame(
        reference_df,
        normalize_manufacturer(metadata.get("Manufacturer")),
        normalize_field_strength(metadata.get("MagneticFieldStrength")),
        max(len(reference_df), 1),
    )
    if filtered_ref.empty:
        filtered_ref = reference_df
    enriched = []

    for metric_name, value in sorted(subject_iqms.items()):
        item: dict[str, Any] = {
            "name": metric_name,
            "value": value,
            "reference_stats": compute_reference_stats(
                metric_name=metric_name,
                value=value,
                reference_df=filtered_ref,
            ),
        }

        semantics = lookup_semantics(metric_name, semantics_catalog)
        if semantics is not None:
            item["semantic_context"] = {k: v for k, v in semantics.items() if k != "matches"}

        enriched.append(item)

    return enriched


def prepare_qc_data(
    *,
    bids_json: Path,
    iqm_file: Path,
    reference_tsv: Path,
    semantics_json: Path | None,
    match_reference_metadata: bool = False,
) -> dict[str, Any]:
    """Load raw inputs and return the shared data needed by renderers."""
    sidecar = load_json(bids_json)
    selected_metadata = select_metadata(sidecar)
    raw_iqm_data = load_json(iqm_file)
    provenance_warnings = extract_provenance_warnings(raw_iqm_data)
    raw_iqms = numeric_values(raw_iqm_data)
    reference_columns = load_reference_iqms(reference_tsv)
    semantics_catalog = load_semantics(semantics_json)
    enriched_iqms = enrich_iqms(
        raw_iqms,
        reference_columns,
        semantics_catalog,
        selected_metadata if match_reference_metadata else None,
    )

    return {
        "sidecar": sidecar,
        "selected_metadata": selected_metadata,
        "raw_iqm_data": raw_iqm_data,
        "provenance_warnings": provenance_warnings,
        "raw_iqms": raw_iqms,
        "enriched_iqms": enriched_iqms,
    }


def write_shared_qc_data(shared_data_dir: Path, qc_data: dict[str, Any]) -> None:
    """Write experiment-independent processed metadata and IQM data.

    Only the selected sequence and scanner fields are written. The full sidecar holds
    identifying fields (DeviceSerialNumber, InstitutionName, ...) and is never written.
    """
    shared_data_dir.mkdir(parents=True, exist_ok=True)
    write_json(shared_data_dir / "metadata.json", {"selected": qc_data["selected_metadata"]})
    write_json(shared_data_dir / "iqms.json", {"iqms": qc_data["enriched_iqms"]})


def should_highlight_iqm(iqm: dict[str, Any], modality: str) -> bool:
    name = iqm["name"]
    percentile = iqm["reference_stats"].get("percentile")
    z_score = iqm["reference_stats"].get("z_score")

    if modality.lower() == "t1w" and name in ALWAYS_HIGHLIGHT_T1W:
        return True

    if percentile is not None and (percentile <= 10 or percentile >= 90):
        return True

    if z_score is not None and abs(z_score) >= 1.5:
        return True

    return False


def format_optional(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def render_metadata_table(selected_metadata: dict[str, Any]) -> str:
    if not selected_metadata:
        return "| n/a | n/a |"

    return "\n".join(
        f"| `{key}` | `{value}` |"
        for key, value in selected_metadata.items()
    )


def render_iqm_table(iqms: list[dict[str, Any]], modality: str) -> str:
    highlighted = [
        iqm for iqm in iqms
        if should_highlight_iqm(iqm, modality)
    ]

    if not highlighted:
        return "| n/a | n/a | n/a | n/a | n/a | No highlighted IQMs. |"

    rows = []

    for iqm in highlighted:
        stats = iqm["reference_stats"]
        semantics = iqm.get("semantic_context", {})
        if semantics.get("evidence_strength") == "none":
            continue

        rows.append(
            "| `{name}` | {value} | {percentile} | {z_score} | {direction} | {interpretation} | {caveats} | {evidence_strength} |".format(
                name=iqm["name"],
                value=round(iqm["value"], 6),
                percentile=format_optional(stats.get("percentile")),
                z_score=format_optional(stats.get("z_score")),
                direction=semantics.get("direction_of_concern", ""),
                interpretation=semantics.get("qc_interpretation", ""),
                caveats="; ".join(semantics.get("caveats", [])) or "None",
                evidence_strength=semantics.get("evidence_strength", "unknown"),
            )
        )

    return "\n".join(rows)


def extract_provenance_warnings(raw_iqm_data: dict[str, Any]) -> dict[str, bool]:
    provenance = raw_iqm_data.get("provenance", {})
    if not isinstance(provenance, dict):
        return {}
    warnings = provenance.get("warnings", {})
    return {k: v for k, v in warnings.items() if isinstance(v, bool)}


def render_warnings_section(warnings: dict[str, bool]) -> str:
    if not warnings:
        return "No provenance warnings."
    return "\n".join(
        f"- `{key}`: {'**true**' if value else 'false'}"
        for key, value in sorted(warnings.items())
    )


def build_template_context(
    *,
    scan_id: str,
    participant_id: str,
    session_id: str | None,
    modality: str,
    acquisition: str | None,
    qc_data: dict[str, Any],
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the default placeholder values used by Markdown templates."""
    context = {
        "scan_id": scan_id or "n/a",
        "participant_id": participant_id,
        "session_id": session_id or "n/a",
        "modality": modality,
        "acquisition": acquisition or "n/a",
        "metadata_table": render_metadata_table(qc_data["selected_metadata"]),
        "iqm_table": render_iqm_table(qc_data["enriched_iqms"], modality),
        "warnings_section": render_warnings_section(qc_data["provenance_warnings"]),
    }

    if extra_context:
        context.update(extra_context)

    return context


def render_markdown_template(template_path: Path, context: dict[str, Any]) -> str:
    """Render a Markdown template using Python format placeholders."""
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)
