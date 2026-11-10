"""QC configuration parsing utilities."""

import json
from pathlib import Path
from models import QCConfig
from constants import SUBSTITUTIONS_DICT


def list_qc_tasks_from_json(qc_json) -> list[str]:
    """Return top-level QC task keys from a ``qc.json`` file (JSON object keys, file order)."""
    qc_json_path = Path(qc_json) if qc_json else None
    if not qc_json_path or not qc_json_path.is_file():
        return []
    try:
        data = json.loads(qc_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    return list(data.keys())


def build_substitution_values(participant_id: str, session_id: str) -> dict:
    """Template values for ``qc.json`` path placeholders."""
    sid = str(session_id or "ses-01").strip()
    return {
        "participant_id": participant_id,
        "session_id": sid,
        "session_slug": sid.replace("-", "_"),
    }


def parse_qc_config(qc_json, qc_task, substitution_values=None) -> dict:
    """Parse a QC JSON file using the QCConfig Pydantic model.

    Returns a dict with keys:
      - 'base_mri_image_path': Path | None
      - 'overlay_mri_image_path': Path | None
      - 'montage_path': list[Path] | None
      - 'iqm_path': list[Path] | None
      - 'montage_max_rows': int | None
      - 'montage_max_cols': int | None

    If the file is missing, invalid, or the requested qc_task is not present,
    path values will be None and montage limits will be None. Uses `QCConfig`
    from `models` for validation.
    """

    qc_json_path = Path(qc_json) if qc_json else None

    try:
        # Pydantic v2 deprecates `parse_file`; read file and validate JSON string.
        raw_text = qc_json_path.read_text()

        # Make all the substitutions in the raw text before parsing with Pydantic
        sub_vals = substitution_values or {}
        for key, substitution in SUBSTITUTIONS_DICT.items():
            if substitution in raw_text:
                val = sub_vals.get(key)
                if val is not None:
                    raw_text = raw_text.replace(substitution, str(val))

        qcconf = QCConfig.model_validate_json(raw_text)
    except Exception:
        # validation/parsing failed
        return {
            "base_mri_image_path": None,
            "overlay_mri_image_path": None,
            "montage_path": None,
            "iqm_path": None,
            "montage_max_rows": None,
            "montage_max_cols": None,
            "display_name": None,
            "rating": None,
        }

    # qcconf.root is a dict: qc_task -> QCTask (RootModel)
    qctask = qcconf.root.get(qc_task)
    if not qctask:
        return {
            "base_mri_image_path": None,
            "overlay_mri_image_path": None,
            "montage_path": None,
            "iqm_path": None,
            "montage_max_rows": None,
            "montage_max_cols": None,
            "display_name": None,
            "rating": None,
        }

    # qctask is a QCTask model; its fields are Path or None already
    display = qctask.display_name
    display_label = str(display).strip() if display is not None and str(display).strip() else qc_task

    return {
        "base_mri_image_path": qctask.base_mri_image_path,
        "overlay_mri_image_path": qctask.overlay_mri_image_path,
        "montage_path": qctask.montage_path,
        "iqm_path": qctask.iqm_path,
        "montage_max_rows": qctask.montage_max_rows,
        "montage_max_cols": qctask.montage_max_cols,
        "display_name": display_label,
        "rating": qctask.rating.model_dump() if qctask.rating is not None else None,
    }
