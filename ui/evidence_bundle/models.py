"""Pydantic models for the evidence bundle.

An evidence bundle is the model-independent export of the QC information for one scan:
metrics with statistical context, a multivariate outlier score, rendered views and the
rater's QC. See ``docs/source/development/evidence_bundle_design.md``.
"""

from typing import Any, Literal, Mapping, Optional, Sequence, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constants import (
    DEFAULT_MIN_STRATUM_SIZE,
    DEFAULT_PROJECT_Z_THRESHOLD,
    DEFAULT_REFERENCE_PERCENTILE_HIGH,
    DEFAULT_REFERENCE_PERCENTILE_LOW,
)

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

SupportTier = Literal["supported", "fallback", "unsupported"]
"""Whether the scan's suffix has its own metric context, uses a mapped one, or has none."""

SignatureField = Literal[
    "suffix",
    "MRAcquisitionType",
    "MagneticFieldStrength",
    "Manufacturer",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "VoxelSize",
]
"""Fields of the protocol signature, named as in the BIDS sidecar."""

SignatureValue = Union[str, float, tuple[float, float, float], None]


class _Strict(BaseModel):
    # NaN and inf serialize to JSON null, which then fails to load; reject them on input.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


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
    """Interpretation of one IQM or IQM pattern, from an ``iqms/`` file."""

    display_name: str
    category: str
    direction_of_concern: DirectionOfConcern
    qc_interpretation: str
    evidence_strength: EvidenceStrength
    caveats: list[str] = Field(default_factory=list)
    expected_range: Optional[tuple[Optional[float], Optional[float]]] = None
    matches: list[str] = Field(default_factory=list)


class MetricContextFile(_Strict):
    """One base ``iqms/<name>.json`` file, or the result of merging overrides into one."""

    schema_version: str
    modality: str
    source_documents: list[dict[str, str]] = Field(default_factory=list)
    metrics: dict[str, MetricContext]
    metric_patterns: dict[str, MetricContext] = Field(default_factory=dict)


class MetricContextOverride(_Strict):
    """Changes to one base entry. Only fields that are set replace the base value."""

    direction_of_concern: Optional[DirectionOfConcern] = None
    expected_range: Optional[tuple[Optional[float], Optional[float]]] = None
    evidence_strength: Optional[EvidenceStrength] = None
    qc_interpretation: Optional[str] = None
    add_caveats: list[str] = Field(default_factory=list)

    def apply(self, base: MetricContext) -> MetricContext:
        update = self.model_dump(exclude_unset=True, exclude={"add_caveats"})
        update["caveats"] = [*base.caveats, *self.add_caveats]
        return MetricContext.model_validate({**base.model_dump(), **update})


class MetricContextOverrideFile(_Strict):
    """An ``iqms/<suffix>.json`` file that changes entries of a base file."""

    schema_version: str
    modality: str
    base: str
    metrics: dict[str, MetricContextOverride] = Field(default_factory=dict)
    metric_patterns: dict[str, MetricContextOverride] = Field(default_factory=dict)


class DistributionContext(_Strict):
    """A distribution a scan is compared against, and how it was selected."""

    filters: dict[str, str] = Field(default_factory=dict)
    signature_fields: list[SignatureField] = Field(default_factory=list)
    n: int = Field(ge=0)
    note: Optional[str] = None
    """Why the distribution is reduced or unused, for example a stratum below the minimum size."""


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

    @model_validator(mode="before")
    @classmethod
    def _check_direction_named(cls, data: Any) -> Any:
        # The Literal error gives only the list index; name the metric instead.
        if isinstance(data, Mapping):
            direction = data.get("direction_of_concern")
            if isinstance(direction, str) and direction not in get_args(DirectionOfConcern):
                raise ValueError(f"{data.get('name')}: direction_of_concern '{direction}' is not one of {get_args(DirectionOfConcern)}")
        return data

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


class ScannerMetadata(_Strict):
    """Allowlisted scanner fields from the BIDS sidecar."""

    Manufacturer: Optional[str] = None
    ManufacturersModelName: Optional[str] = None
    MagneticFieldStrength: Optional[float] = None
    SoftwareVersions: Optional[str] = None
    ReceiveCoilName: Optional[str] = None
    """``ReceiveCoilName``, or ``CoilString`` when the sidecar has only that."""


class SequenceMetadata(_Strict):
    """Allowlisted sequence fields from the BIDS sidecar. Times in seconds, angles in degrees."""

    MRAcquisitionType: Optional[str] = None
    ScanningSequence: Union[str, list[str], None] = None
    SequenceVariant: Union[str, list[str], None] = None
    RepetitionTime: Optional[float] = None
    EchoTime: Optional[float] = None
    InversionTime: Optional[float] = None
    FlipAngle: Optional[float] = None
    PixelBandwidth: Optional[float] = None
    ParallelReductionFactorInPlane: Optional[float] = None
    PartialFourier: Optional[float] = None


class GeometryMetadata(_Strict):
    """Image geometry, from the NIfTI header except where noted."""

    shape: Optional[tuple[int, ...]] = None
    voxel_size: Optional[tuple[float, float, float]] = None
    """Spatial voxel size in mm."""
    orientation: Optional[tuple[str, str, str]] = None
    """Axis codes, for example ``("R", "A", "S")``."""
    field_of_view: Optional[tuple[float, float, float]] = None
    """Spatial extent in mm."""
    SliceThickness: Optional[float] = None
    """From the sidecar."""
    SpacingBetweenSlices: Optional[float] = None
    """From the sidecar."""


class ProvenanceMetadata(_Strict):
    """Where the IQMs came from, from the MRIQC JSON ``provenance``."""

    mriqc_version: Optional[str] = None
    md5sum: Optional[str] = None


class AcquisitionMetadata(_Strict):
    """Allowlisted acquisition metadata. Only the fields of these models are ever exported."""

    site: Optional[str] = None
    """From the participant list or configuration, never from ``InstitutionName``."""
    scanner: ScannerMetadata = Field(default_factory=ScannerMetadata)
    sequence: SequenceMetadata = Field(default_factory=SequenceMetadata)
    geometry: GeometryMetadata = Field(default_factory=GeometryMetadata)
    provenance: ProvenanceMetadata = Field(default_factory=ProvenanceMetadata)

    @classmethod
    def from_sidecar(cls, sidecar: Mapping[str, Any], **groups: Any) -> "AcquisitionMetadata":
        """Build the scanner and sequence groups from a sidecar, keeping only allowlisted keys.

        ``groups`` passes ``site``, ``geometry`` or ``provenance``. ``SliceThickness`` and
        ``SpacingBetweenSlices`` are taken from the sidecar unless ``geometry`` sets them.
        """
        scanner = {k: sidecar[k] for k in ScannerMetadata.model_fields if k in sidecar}
        if "ReceiveCoilName" not in scanner and "CoilString" in sidecar:
            scanner["ReceiveCoilName"] = sidecar["CoilString"]
        sequence = {k: sidecar[k] for k in SequenceMetadata.model_fields if k in sidecar}
        geometry = groups.pop("geometry", GeometryMetadata())
        if not isinstance(geometry, GeometryMetadata):
            geometry = GeometryMetadata.model_validate(geometry)
        from_sidecar = {k: sidecar[k] for k in ("SliceThickness", "SpacingBetweenSlices") if k in sidecar}
        geometry = geometry.model_copy(update={k: v for k, v in from_sidecar.items() if getattr(geometry, k) is None})
        return cls(scanner=ScannerMetadata(**scanner), sequence=SequenceMetadata(**sequence), geometry=geometry, **groups)


class ProtocolSignature(_Strict):
    """Rounded acquisition parameters that define which scans are comparable.

    Units as in the sidecar (seconds, degrees); voxel size in mm. A missing field is null and
    is part of the signature.
    """

    suffix: str
    MRAcquisitionType: Optional[str] = None
    MagneticFieldStrength: Optional[float] = None
    Manufacturer: Optional[str] = None
    RepetitionTime: Optional[float] = None
    EchoTime: Optional[float] = None
    InversionTime: Optional[float] = None
    FlipAngle: Optional[float] = None
    VoxelSize: Optional[tuple[float, float, float]] = None


class AcquisitionDeviation(_Strict):
    """A signature field whose value differs from the project's modal value for the suffix."""

    field: SignatureField
    value: SignatureValue
    expected: SignatureValue
    share: float = Field(ge=0, le=1)
    """Share of compared scans that have the expected value."""
    n: int = Field(ge=1)
    """Number of scans compared."""


class StatsConfig(_Strict):
    """Statistical cutoffs for one export. Projects may set them; each bundle records them."""

    min_stratum_size: int = Field(default=DEFAULT_MIN_STRATUM_SIZE, ge=2)
    """Fewest other scans a project stratum (or reference rows a reference subset) must hold."""
    project_z_threshold: float = Field(default=DEFAULT_PROJECT_Z_THRESHOLD, gt=0)
    """Robust z beyond which a metric is a project outlier in its direction of concern."""
    reference_percentile_low: float = Field(default=DEFAULT_REFERENCE_PERCENTILE_LOW, ge=0, le=100)
    reference_percentile_high: float = Field(default=DEFAULT_REFERENCE_PERCENTILE_HIGH, ge=0, le=100)

    @model_validator(mode="after")
    def _check_order(self):
        if self.reference_percentile_low >= self.reference_percentile_high:
            raise ValueError("reference_percentile_low must be below reference_percentile_high")
        return self


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
    participant_id: str
    session_id: str
    pipeline: str
    qc_task: str
    suffix: str
    """BIDS suffix of the scan (``T1w``, ``T2w``, ``FLAIR``, ``bold``, ...)."""
    support: SupportTier
    context_suffix: Optional[str]
    """Suffix whose metric context is used; null when ``unsupported``."""
    acquisition: AcquisitionMetadata = Field(default_factory=AcquisitionMetadata)
    protocol_signature: Optional[ProtocolSignature] = None
    acquisition_deviations: list[AcquisitionDeviation] = Field(default_factory=list)
    stats_config: StatsConfig = Field(default_factory=StatsConfig)
    """The cutoffs that produced the percentiles, flags and strata in this bundle."""
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

    @model_validator(mode="after")
    def _check_support(self):
        if self.protocol_signature is not None and self.protocol_signature.suffix.lower() != self.suffix.lower():
            raise ValueError(f"protocol signature suffix '{self.protocol_signature.suffix}' is not the bundle suffix '{self.suffix}'")
        # Suffixes compare case-insensitively, as in context.resolve_context.
        own = self.context_suffix is not None and self.context_suffix.lower() == self.suffix.lower()
        if self.support == "supported" and not own:
            raise ValueError(f"a supported bundle uses its own context, not '{self.context_suffix}'")
        if self.support == "fallback":
            if self.context_suffix is None or own:
                raise ValueError("a fallback bundle needs a context suffix other than its own")
            with_reference = [m.name for m in self.metrics if m.reference_percentile is not None or "reference_outlier" in m.flags]
            if with_reference:
                raise ValueError(f"a fallback bundle has no reference percentiles: {with_reference}")
        if self.support == "unsupported":
            if self.context_suffix is not None:
                raise ValueError("an unsupported bundle has no context suffix")
            interpreted = [m.name for m in self.metrics if m.direction_of_concern != "context_dependent"]
            if interpreted:
                raise ValueError(f"every metric of an unsupported bundle is context_dependent: {interpreted}")
            weighted = [m.name for m in self.metrics if m.evidence_strength != "none"]
            if weighted:
                raise ValueError(f"every metric of an unsupported bundle has evidence_strength 'none': {weighted}")
        return self

    def flagged_metrics(self) -> list[str]:
        """Names of metrics with at least one flag."""
        return [m.name for m in self.metrics if m.flags]
