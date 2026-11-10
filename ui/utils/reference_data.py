"""Reference IQM data: download, scanner-metadata normalization, and filtering.

Uncached by design; caching lives in ``iqm_viewer.load_reference_iqm_for_subject``.
"""

import os
from pathlib import Path
from typing import Optional

import requests

from utils.data_loaders import load_parquet_table

# Reference-data host is not committed to source; set REFERENCE_DATA_URL in
# the environment (or a .env file) before running the app. Resolved at call
# time (not import time) so it can't go stale relative to .env loading.
REFERENCE_CACHE_DIR = Path(".streamlit/reference_cache")

MAX_REFERENCE_ROWS = 50_000
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

UNKNOWN_LABELS = {"", "unknown", "nan", "none", "na", "n/a", "null"}

MANUFACTURER_ALIASES = {
    "siemens": "siemens",
    "siemens healthineers": "siemens",
    "siemens healthcare": "siemens",
    "ge": "ge",
    "general electric": "ge",
    "ge healthcare": "ge",
    "ge medical systems": "ge",
    "philips": "philips",
    "philips healthcare": "philips",
    "philips medical systems": "philips",
}

FIELD_STRENGTH_ALIASES = {
    "1": "1",
    "1.0": "1",
    "1t": "1",
    "1.0t": "1",
    "1.5": "1.5",
    "1.5t": "1.5",
    "3": "3",
    "3.0": "3",
    "3t": "3",
    "3.0t": "3",
    "7": "7",
    "7.0": "7",
    "7t": "7",
    "7.0t": "7",
}


def _download_reference_parquet_bytes(url: str) -> bytes:
    """Download reference Parquet content."""
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response.content


def _get_reference_cache_dir() -> Path:
    """Create and return the reference-data cache directory when needed."""
    REFERENCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return REFERENCE_CACHE_DIR


def _resolve_reference_data_url(url_parent: Optional[str] = None) -> str:
    """Return the active reference-data URL from runtime config."""
    resolved = url_parent or os.environ.get("REFERENCE_DATA_URL")
    if not resolved:
        raise RuntimeError("REFERENCE_DATA_URL is not set. Set it in the environment to enable " "downloading reference IQM data.")
    return resolved


def download_reference_parquet(modality: str, url_parent: Optional[str] = None) -> str:
    """Ensure a reference Parquet file exists locally and return its path."""
    cache_file_path = REFERENCE_CACHE_DIR / f"{modality}.parquet"

    if cache_file_path.exists():
        return str(cache_file_path)

    resolved_url_parent = _resolve_reference_data_url(url_parent)
    url = resolved_url_parent.rstrip("/") + f"/{modality}.parquet"
    cache_file_path = _get_reference_cache_dir() / f"{modality}.parquet"
    cache_file_path.write_bytes(_download_reference_parquet_bytes(url))

    return str(cache_file_path)


def normalize_manufacturer(value: object) -> str:
    normalized = str(value or "").strip().lower()

    if normalized in UNKNOWN_LABELS:
        return "unknown"

    return MANUFACTURER_ALIASES.get(normalized, normalized)


def normalize_field_strength(value: object) -> Optional[str]:
    normalized = str(value or "").strip().lower()

    if normalized in UNKNOWN_LABELS:
        return None

    if normalized in FIELD_STRENGTH_ALIASES:
        return FIELD_STRENGTH_ALIASES[normalized]

    if normalized.endswith("t"):
        normalized = normalized[:-1].strip()

    try:
        numeric_value = float(normalized)
    except (TypeError, ValueError):
        return normalized or None

    return f"{numeric_value:g}"


def _load_reference_parquet(modality: str):
    """Ensure the modality's Parquet file is downloaded, then read it."""
    local_parquet_path = REFERENCE_CACHE_DIR / f"{modality}.parquet"
    if not local_parquet_path.exists():
        download_reference_parquet(modality=modality)

    return load_parquet_table(local_parquet_path)


def filter_reference_iqm(
    modality: str,
    manufacturer_norm: str,
    field_strength_norm: Optional[str],
    max_rows: int,
):
    """Filter the reference table by already-normalized scanner values.

    Expects pre-normalized manufacturer/field-strength so equivalent raw
    spellings (e.g. "GE", "General Electric") share one cache entry upstream.
    """
    data = _load_reference_parquet(modality)

    # TODO: Add a dedicated reference-data cleaning step before filtering (#82).
    if manufacturer_norm != "unknown" and "Manufacturer" in data.columns:
        manufacturer_col_norm = data["Manufacturer"].map(normalize_manufacturer)
        data = data[manufacturer_col_norm == manufacturer_norm]

    if field_strength_norm is not None and "MagneticFieldStrength" in data.columns:
        field_strength_col_norm = data["MagneticFieldStrength"].map(normalize_field_strength)
        data = data[field_strength_col_norm == field_strength_norm]

    if len(data) > max_rows:
        data = data.sample(n=max_rows, random_state=42)

    return data
