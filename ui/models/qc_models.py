"""QC-Studio data models.

Defines all Pydantic models used throughout QC-Studio.
"""

from datetime import date
from typing import List, Optional, Dict
from pathlib import Path

try:
    from typing import Annotated, Literal
except ImportError:
    from typing_extensions import Annotated, Literal

from pydantic import BaseModel, Field, RootModel, field_validator

from constants import MAX_MONTAGE_GRID_SIZE, MIN_MONTAGE_GRID_SIZE, QC_RATINGS


# Future plans:
# To be used if we want to provide configurable QC scoring options
class MetricQC(BaseModel):
    name: Annotated[str, Field(description="Name of the metric, e.g., Euler, segmentation")]
    value: Annotated[Optional[float], Field(description="Numeric value if applicable")] = None
    qc: Annotated[Optional[str], Field(description="QC decision: PASS, FAIL, UNCERTAIN")] = None
    notes: Annotated[Optional[str], Field(description="Additional comment")] = None


class QCRecord(BaseModel):
    qc_task: Annotated[str, Field(description="QC task identifier, e.g., sdc-wf")]
    participant_id: Annotated[str, Field(description="BIDS subject ID")]
    session_id: Annotated[str, Field(description="Session ID, e.g., ses-01")]
    task_id: Optional[str] = None
    run_id: Optional[str] = None
    pipeline: Annotated[str, Field(description="Pipeline name and version, e.g., freesurfer")]
    timestamp: Annotated[Optional[str], Field(description="Completion date")] = None
    rater_id: Annotated[str, Field(description="Name of the rater")]
    rater_experience: Annotated[Optional[str], Field(description="Rater experience level")] = None
    rater_fatigue: Annotated[Optional[str], Field(description="Rater fatigue level")] = None
    rater_screen_size: Annotated[Optional[str], Field(description="Rater monitor screen size")] = None
    final_qc: Optional[str] = None
    ratings: Optional[Dict[str, Optional[str]]] = None
    notes: Annotated[Optional[str], Field(description="Additional comment")] = None


class RatingConfig(BaseModel):
    """Task-level rating schema for single or multi-facet QC."""

    type: Annotated[
        Literal["single", "multi"],
        Field(description="Rating mode: one value for the task or one value per facet"),
    ] = "single"
    scale: Annotated[
        List[str],
        Field(description="Shared rating options used by the task (and by all facets when type=multi)"),
    ] = Field(default_factory=lambda: list(QC_RATINGS))
    facets: Annotated[
        List[str],
        Field(description="Facet names for type=multi; empty for type=single"),
    ] = Field(default_factory=list)

    @field_validator("scale", mode="before")
    @classmethod
    def _coerce_scale(cls, v):
        if v is None:
            return list(QC_RATINGS)
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        s = str(v).strip()
        return [s] if s else list(QC_RATINGS)

    @field_validator("facets", mode="before")
    @classmethod
    def _coerce_facets(cls, v):
        if v is None:
            return []
        if isinstance(v, (list, tuple)):
            return [str(x).strip() for x in v if str(x).strip()]
        s = str(v).strip()
        return [s] if s else []


class QCTask(BaseModel):
    """Represents one QC entry in <pipeline>_qc.json (i.e. single QC task)."""

    display_name: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional human-readable label for the UI (export keys stay the task id)",
        ),
    ] = None

    # Single file paths for mri and overlay images
    base_mri_image_path: Annotated[Optional[Path], Field(description="Path to base MRI image")] = None
    overlay_mri_image_path: Annotated[Optional[Path], Field(description="Path to overlay MRI image (mask etc.)")] = None

    # List of paths for montages
    montage_path: Annotated[Optional[List[Path]], Field(description="List of paths to 2D montage images for visual QC (SVG, PNG, JPG/JPEG)")] = None

    # Path for IQMs or other QC files (e.g. CSV, JSON)

    iqm_path: Annotated[
        Optional[List[Path]], Field(description="List of paths to IQM sources (TSV/CSV distribution tables or JSON metrics), one per pipeline source")
    ] = None

    # Optional grid constraints for multi-image SVG/raster montage (see utils.data_loaders.load_montage_data)
    montage_max_rows: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=MIN_MONTAGE_GRID_SIZE,
            le=MAX_MONTAGE_GRID_SIZE,
            description="Default max rows for montage grid; omit for auto layout",
        ),
    ] = None
    montage_max_cols: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=MIN_MONTAGE_GRID_SIZE,
            le=MAX_MONTAGE_GRID_SIZE,
            description="Default max columns for montage grid; omit for auto layout",
        ),
    ] = None

    rating: Annotated[
        Optional[RatingConfig],
        Field(
            default=None,
            description="Optional task-level rating schema. If omitted, defaults to legacy single PASS/FAIL/UNCERTAIN.",
        ),
    ] = None

    @field_validator("montage_path", mode="before")
    @classmethod
    def _coerce_montage_path(cls, v):
        """Accept a single path/string from JSON or a list of paths."""
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return [str(Path(x)) for x in v]
        return [str(Path(v))]

    @field_validator("iqm_path", mode="before")
    @classmethod
    def _coerce_iqm_path(cls, v):
        """Accept a single path/string from JSON or a list of paths."""
        if v is None:
            return None
        if isinstance(v, (list, tuple)):
            return [str(Path(x)) for x in v]
        return [str(Path(v))]


class QCConfig(RootModel[Dict[str, QCTask]]):
    """Top-level model for `qc.json`.

    The JSON is expected to be a mapping from QC-task keys (strings) to
    `QCTask` objects. Example:

    {
        "anat_wf_qc": {
            "base_mri_image_path": "...",
            "overlay_mri_image_path": "...",
            "montage_path": "...",
            "iqm_path": "...",
            "montage_max_rows": 2,
            "montage_max_cols": 2
        }
    }
    """

    # RootModel holds the mapping as `.root` (dict[str, QCTask])
    pass


QCDecision = Literal["pass", "fail", "uncertain"]


class QCStatusRow(BaseModel):
    participant_id: Annotated[str, Field(description="BIDS subject ID, e.g., sub-CMH0001")]
    session: Optional[str] = None
    acq: Optional[str] = None
    run: Optional[int] = None
    qc_task: Annotated[str, Field(description="QC task identifier, e.g., anat_wf_qc")]
    rater_id: Annotated[str, Field(description="Rater identifier")]
    score: Optional[QCDecision] = None
    notes: Optional[str] = None
    timestamp: Optional[date] = None
