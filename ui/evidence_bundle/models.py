"""Pydantic models for the evidence bundle.

An evidence bundle is the model-independent export of the QC information for one scan:
metrics with statistical context, a multivariate outlier score, rendered views and the
rater's QC. See ``docs/source/development/evidence_bundle_design.md``.
"""

from typing import Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"

DirectionOfConcern = Literal[
    "higher_worse",
    "lower_worse",
    "outside_range",
    "context_dependent",
    "not_quality_metric",
]
"""Whether high values, low values, or values outside a range indicate poor quality."""

DIRECTIONAL = ("higher_worse", "lower_worse", "outside_range")
"""Directions for which flags and a context category are defined."""

EvidenceStrength = Literal["high", "medium", "low", "none"]

MetricFlag = Literal["project_outlier", "reference_outlier"]

ContextCategory = Literal["scan", "protocol", "project", "normal"]

ViewKind = Literal["core", "targeted"]

Plane = Literal["axial", "coronal", "sagittal"]

PlacementMethod = Literal["mni", "bbox_fraction"]
"""How slice positions were chosen: fixed MNI coordinates, or brain-mask bounding-box fractions."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def context_category_for(flags: Sequence[str]) -> ContextCategory:
    """Return the context category implied by a metric's flags."""
    project = "project_outlier" in flags
    reference = "reference_outlier" in flags
    if project and reference:
        return "scan"
    if reference:
        return "protocol"
    if project:
        return "project"
    return "normal"


class MetricContext(_Strict):
    """Interpretation of one IQM or IQM pattern, from ``iqms/<modality>.json``."""

    display_name: str
    category: str
    direction_of_concern: DirectionOfConcern
    qc_interpretation: str
    evidence_strength: EvidenceStrength
    caveats: list[str] = Field(default_factory=list)
    expected_range: Optional[tuple[Optional[float], Optional[float]]] = None
    matches: list[str] = Field(default_factory=list)


class MetricContextFile(_Strict):
    """One ``iqms/<modality>.json`` file."""

    schema_version: str
    modality: str
    source_documents: list[dict[str, str]] = Field(default_factory=list)
    metrics: dict[str, MetricContext]
    metric_patterns: dict[str, MetricContext] = Field(default_factory=dict)


class DistributionContext(_Strict):
    """A distribution a scan is compared against, and how it was selected."""

    filters: dict[str, str] = Field(default_factory=dict)
    n: int = Field(ge=0)


class MetricEvidence(_Strict):
    """One IQM with its statistical context."""

    name: str
    value: float
    display_name: str
    category: str
    direction_of_concern: DirectionOfConcern
    evidence_strength: EvidenceStrength
    project_percentile: Optional[float] = Field(default=None, ge=0, le=100)
    reference_percentile: Optional[float] = Field(default=None, ge=0, le=100)
    flags: list[MetricFlag] = Field(default_factory=list)
    context_category: Optional[ContextCategory] = None

    @model_validator(mode="after")
    def _check_flags_and_category(self):
        if self.direction_of_concern not in DIRECTIONAL:
            if self.flags or self.context_category is not None:
                raise ValueError(f"{self.name}: a '{self.direction_of_concern}' metric has no flags or context category")
            return self
        if self.context_category is None:
            raise ValueError(f"{self.name}: a directional metric needs a context category")
        expected = context_category_for(self.flags)
        if self.context_category != expected:
            raise ValueError(f"{self.name}: flags {self.flags} imply category '{expected}', not '{self.context_category}'")
        return self


class OutlierContributor(_Strict):
    metric: str
    contribution: float


class OutlierScore(_Strict):
    """Multivariate outlier score over the scan's standardized IQMs."""

    method: Literal["robust_mahalanobis"] = "robust_mahalanobis"
    score: float = Field(ge=0)
    percentile: Optional[float] = Field(default=None, ge=0, le=100)
    metrics_used: list[str]
    top_contributors: list[OutlierContributor] = Field(default_factory=list)


class ViewRef(_Strict):
    """One rendered 2D view in the bundle's ``views/`` directory."""

    path: str
    kind: ViewKind
    plane: Plane
    slice_positions: list[float] = Field(min_length=1)
    placement: PlacementMethod
    window_percentiles: tuple[float, float]
    rule: Optional[str] = None
    control: bool = False

    @model_validator(mode="after")
    def _check_kind(self):
        if self.kind == "targeted" and not self.rule:
            raise ValueError(f"{self.path}: a targeted view needs the rule that added it")
        if self.kind == "core" and (self.rule or self.control):
            raise ValueError(f"{self.path}: a core view has no rule and is never a control")
        return self


class AcquisitionMetadata(_Strict):
    """Selected fields from the BIDS sidecar."""

    manufacturer: Optional[str] = None
    manufacturers_model_name: Optional[str] = None
    magnetic_field_strength: Optional[float] = None
    site: Optional[str] = None


class RaterQC(_Strict):
    """The rater's QC for this scan, from a ``*_qc_status.tsv``."""

    rater_id: Optional[str] = None
    final_qc: Optional[str] = None
    facets: dict[str, str] = Field(default_factory=dict)
    notes: Optional[str] = None
    timestamp: Optional[str] = None


class EvidenceBundle(_Strict):
    """The evidence for one scan, written as ``bundle.json``."""

    schema_version: str = SCHEMA_VERSION
    qcstudio_version: Optional[str] = None
    mriqc_version: Optional[str] = None
    participant_id: str
    session_id: str
    pipeline: str
    qc_task: str
    modality: str
    acquisition: AcquisitionMetadata = Field(default_factory=AcquisitionMetadata)
    project: DistributionContext
    reference: Optional[DistributionContext] = None
    metrics: list[MetricEvidence]
    outlier: Optional[OutlierScore] = None
    views: list[ViewRef] = Field(default_factory=list)
    rater_qc: Optional[RaterQC] = None

    @model_validator(mode="after")
    def _check_names(self):
        names = [m.name for m in self.metrics]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"duplicate metrics: {duplicates}")
        if self.outlier is not None:
            unknown = sorted(set(self.outlier.metrics_used) - set(names))
            if unknown:
                raise ValueError(f"outlier score uses metrics not in the bundle: {unknown}")
        if self.reference is None and any("reference_outlier" in m.flags for m in self.metrics):
            raise ValueError("reference_outlier flags need a reference distribution")
        return self

    def flagged_metrics(self) -> list[str]:
        """Names of metrics with at least one flag."""
        return [m.name for m in self.metrics if m.flags]
