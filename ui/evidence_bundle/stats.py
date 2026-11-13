"""Project and reference statistics, flags, context categories and the outlier score.

All cutoffs come from a ``models.StatsConfig``. Project statistics compare a scan with the
other scans of its signature stratum (the scan itself is left out). Everything is numpy; there
is no scikit-learn.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, get_args

import numpy as np
import pandas as pd

from utils.reference_data import MAX_REFERENCE_ROWS, VOXEL_SIZE_COLUMNS, filter_reference_frame, normalize_field_strength

from .constants import (
    MAD_SCALE,
    OUTLIER_TOP_CONTRIBUTORS,
    OUTLIER_WINSOR_Z,
    REFERENCE_SIGNATURE_FIELDS,
    SIGNATURE_FALLBACK_ORDER,
    SIGNATURE_FIXED,
    SIGNATURE_ROUNDING,
)
from .context import ResolvedContext, lookup_metric
from .models import (
    DIRECTIONAL,
    DirectionOfConcern,
    DistributionContext,
    EvidenceStrength,
    MetricContextFile,
    MetricEvidence,
    MetricFlag,
    OutlierContributor,
    OutlierScore,
    ProtocolSignature,
    SignatureField,
    StatsConfig,
    context_category_for,
)

MEAN_ABSOLUTE_DEVIATION_SCALE = math.sqrt(math.pi / 2)
"""Scales the mean absolute deviation to the standard deviation; used when the MAD is 0."""


@dataclass(frozen=True)
class ScanInput:
    """What the statistics need from one scan of the project."""

    suffix: str
    signature: ProtocolSignature
    iqms: Mapping[str, float]
    site: Optional[str] = None


@dataclass
class ScanStatistics:
    """Statistics for one scan, ready to go into an ``EvidenceBundle``."""

    metrics: list[MetricEvidence]
    project: DistributionContext
    reference: DistributionContext
    outlier: Optional[OutlierScore]
    skipped: list[str] = field(default_factory=list)
    """IQMs left out because their value is not finite."""


def numeric_iqms(mriqc: Mapping[str, Any]) -> dict[str, float]:
    """Top-level numeric fields of an MRIQC JSON (the IQMs); booleans and nested groups are skipped."""
    return {k: float(v) for k, v in mriqc.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


# --- robust statistics -------------------------------------------------------------------


def robust_z(value: float, sample: np.ndarray) -> float:
    """Robust z-score of ``value`` against ``sample``: (value - median) / (1.4826 * MAD).

    When the MAD is 0 the scaled mean absolute deviation is used. When that is 0 too, the
    result is 0 for the median value and +/-inf otherwise.
    """
    median = float(np.median(sample))
    deviation = np.abs(sample - median)
    scale = MAD_SCALE * float(np.median(deviation))
    if scale == 0:
        scale = MEAN_ABSOLUTE_DEVIATION_SCALE * float(np.mean(deviation))
    if scale == 0:
        return 0.0 if value == median else math.copysign(math.inf, value - median)
    return (value - median) / scale


def empirical_percentile(value: float, sample: np.ndarray) -> float:
    """Percentage of ``sample`` below ``value``, counting ties as half."""
    below = int(np.sum(sample < value))
    ties = int(np.sum(sample == value))
    return 100.0 * (below + 0.5 * ties) / sample.size


# --- strata ------------------------------------------------------------------------------


def _signature_value(signature: ProtocolSignature, name: str) -> Any:
    value = getattr(signature, name)
    return value.lower() if name == "suffix" and value is not None else value


def select_stratum(index: int, scans: Sequence[ScanInput], config: StatsConfig) -> tuple[list[int], DistributionContext]:
    """Return the other scans comparable with ``scans[index]``, and how they were chosen.

    The stratum starts with the full signature (and the same site when the scan's site is
    known). Below ``config.min_stratum_size``, fields are dropped in
    ``SIGNATURE_FALLBACK_ORDER``. If the stratum is still too small, no members are returned
    and the context says why.
    """
    target = scans[index]
    candidates = [j for j, scan in enumerate(scans) if j != index and (target.site is None or scan.site == target.site)]
    filters = {} if target.site is None else {"site": target.site}
    fields: list[SignatureField] = list(get_args(SignatureField))
    drops = [f for f in SIGNATURE_FALLBACK_ORDER if f not in SIGNATURE_FIXED]
    while True:
        members = [j for j in candidates if all(_signature_value(scans[j].signature, f) == _signature_value(target.signature, f) for f in fields)]
        if len(members) >= config.min_stratum_size:
            return members, DistributionContext(filters=filters, signature_fields=fields, n=len(members))
        if not drops:
            break
        fields.remove(drops.pop(0))  # type: ignore[arg-type]
    note = (
        f"stratum of {len(members)} other scans is below the minimum of {config.min_stratum_size} "
        f"with only {', '.join(fields)} left; project percentiles not computed"
    )
    return [], DistributionContext(filters=filters, signature_fields=fields, n=len(members), note=note)


def reference_subset(
    resolved: ResolvedContext,
    signature: ProtocolSignature,
    reference: Optional[pd.DataFrame],
    config: StatsConfig,
    unavailable_reason: Optional[str] = None,
) -> tuple[Optional[pd.DataFrame], DistributionContext]:
    """Select reference rows matching the signature fields the reference data holds.

    ``reference`` is the loaded reference table for the scan's suffix, or None when there is
    none. Fallback and unsupported scans get no reference. Below ``config.min_stratum_size``,
    ``VoxelSize`` and then ``Manufacturer`` are dropped; ``MagneticFieldStrength`` is kept.
    """
    if resolved.support != "supported":
        note = f"no reference for {resolved.support} bundles: the MRIQC reference has no {signature.suffix} scans"
        return None, DistributionContext(n=0, note=note)
    if reference is None:
        return None, DistributionContext(n=0, note=unavailable_reason or f"no reference data for {signature.suffix}")

    field_strength = normalize_field_strength(signature.MagneticFieldStrength)
    fields = list(REFERENCE_SIGNATURE_FIELDS)
    drops = [f for f in SIGNATURE_FALLBACK_ORDER if f in fields]
    while True:
        applied: dict[str, str] = {}
        if field_strength is not None and "MagneticFieldStrength" in reference.columns:
            applied["MagneticFieldStrength"] = field_strength
        manufacturer = signature.Manufacturer if "Manufacturer" in fields and signature.Manufacturer else "unknown"
        if manufacturer != "unknown" and "Manufacturer" in reference.columns:
            applied["Manufacturer"] = manufacturer
        voxel = signature.VoxelSize if "VoxelSize" in fields else None
        data = filter_reference_frame(reference, manufacturer, field_strength, MAX_REFERENCE_ROWS, voxel, SIGNATURE_ROUNDING["VoxelSize"])
        if voxel is not None and all(c in reference.columns for c in VOXEL_SIZE_COLUMNS):
            applied["VoxelSize"] = "x".join(f"{v:g}" for v in voxel)
        if len(data) >= config.min_stratum_size or not drops:
            break
        fields.remove(drops.pop(0))
    used: list[SignatureField] = [f for f in REFERENCE_SIGNATURE_FIELDS if f in applied]  # type: ignore[misc]
    if len(data) < config.min_stratum_size:
        note = f"reference subset of {len(data)} rows is below the minimum of {config.min_stratum_size}; reference percentiles not computed"
        return None, DistributionContext(filters=applied, signature_fields=used, n=len(data), note=note)
    return data, DistributionContext(filters=applied, signature_fields=used, n=len(data))


# --- metrics -----------------------------------------------------------------------------


def describe_metric(
    name: str, resolved: ResolvedContext, catalog: Optional[MetricContextFile] = None
) -> tuple[str, str, DirectionOfConcern, EvidenceStrength]:
    """Return display name, category, direction of concern and evidence strength for an IQM.

    Unsupported scans take the name and category from ``catalog`` (the modality's base
    catalog), with ``context_dependent`` and ``none``. An IQM the context does not describe is
    ``context_dependent`` with ``none`` too, named by itself and ``uncategorized``.
    """
    if resolved.support == "unsupported":
        entry = lookup_metric(catalog, name) if catalog is not None else None
        if entry is None:
            return name, "uncategorized", "context_dependent", "none"
        return entry.display_name, entry.category, "context_dependent", "none"
    entry = lookup_metric(resolved.context, name) if resolved.context is not None else None
    if entry is None:
        return name, "uncategorized", "context_dependent", "none"
    return entry.display_name, entry.category, entry.direction_of_concern, entry.evidence_strength


def metric_flags(
    direction: DirectionOfConcern,
    project_z: Optional[float],
    reference_percentile: Optional[float],
    config: StatsConfig,
) -> list[MetricFlag]:
    """Flags for one metric in its direction of concern; ``outside_range`` is two-sided."""
    if direction not in DIRECTIONAL:
        return []
    flags: list[MetricFlag] = []
    if project_z is not None:
        high = project_z >= config.project_z_threshold
        low = project_z <= -config.project_z_threshold
        if (direction == "higher_worse" and high) or (direction == "lower_worse" and low) or (direction == "outside_range" and (high or low)):
            flags.append("project_outlier")
    if reference_percentile is not None:
        high = reference_percentile >= config.reference_percentile_high
        low = reference_percentile <= config.reference_percentile_low
        if (direction == "higher_worse" and high) or (direction == "lower_worse" and low) or (direction == "outside_range" and (high or low)):
            flags.append("reference_outlier")
    return flags


def _finite(values: Sequence[Optional[float]]) -> np.ndarray:
    array = np.asarray([v for v in values if v is not None], dtype=float)
    return array[np.isfinite(array)]


# --- outlier score -----------------------------------------------------------------------


def shrinkage_covariance(x: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf covariance of rows ``x`` (already centred), shrunk toward a scaled identity."""
    n, p = x.shape
    sample = x.T @ x / n
    target = np.trace(sample) / p * np.eye(p)
    d2 = float(np.sum((sample - target) ** 2))
    if d2 == 0:
        return target
    b2 = (float(np.sum(np.sum(x**2, axis=1) ** 2)) - n * float(np.sum(sample**2))) / n**2
    shrink = min(max(b2, 0.0), d2) / d2
    return shrink * target + (1 - shrink) * sample


def _distance(target: np.ndarray, members: np.ndarray, keep: np.ndarray) -> tuple[float, np.ndarray]:
    """Squared-distance terms of ``target`` against ``members`` over the ``keep`` columns."""
    median = np.median(members[:, keep], axis=0)
    mad = MAD_SCALE * np.median(np.abs(members[:, keep] - median), axis=0)
    mad = np.where(mad > 0, mad, np.inf)  # a metric constant in this subset contributes nothing
    z_members = np.clip((members[:, keep] - median) / mad, -OUTLIER_WINSOR_Z, OUTLIER_WINSOR_Z)
    z_target = (target[keep] - median) / mad
    precision = np.linalg.pinv(shrinkage_covariance(z_members - z_members.mean(axis=0)))
    contributions = z_target * (precision @ z_target)
    return math.sqrt(max(float(contributions.sum()), 0.0)), contributions


def outlier_score(target: np.ndarray, members: np.ndarray, names: Sequence[str]) -> Optional[OutlierScore]:
    """Robust Mahalanobis distance of ``target`` from the stratum ``members`` (rows).

    Each metric is standardized by the members' median and MAD; metrics with a MAD of 0 are
    left out. Member z-scores are clipped to ``OUTLIER_WINSOR_Z`` before the shrinkage
    covariance, so one extreme member does not hide others. A metric's contribution is its
    term ``z_i * (inverse covariance @ z)_i``; contributions sum to the squared distance.

    The percentile compares the score with each member's score against the other members
    (leave-one-out), so the target and the members are scored the same way.
    """
    mad = MAD_SCALE * np.median(np.abs(members - np.median(members, axis=0)), axis=0)
    keep = mad > 0
    if not keep.any() or len(members) < 3:
        return None
    used = [n for n, k in zip(names, keep) if k]
    score, contributions = _distance(target, members, keep)
    member_scores = np.array([_distance(members[k], np.delete(members, k, axis=0), keep)[0] for k in range(len(members))])
    order = [i for i in np.argsort(-contributions, kind="stable") if contributions[i] > 0][:OUTLIER_TOP_CONTRIBUTORS]
    return OutlierScore(
        score=score,
        percentile=empirical_percentile(score, member_scores),
        metrics_used=used,
        top_contributors=[OutlierContributor(metric=used[i], contribution=float(contributions[i])) for i in order],
    )


# --- one scan ----------------------------------------------------------------------------


def scan_statistics(
    index: int,
    scans: Sequence[ScanInput],
    resolved: ResolvedContext,
    config: StatsConfig,
    reference: Optional[pd.DataFrame] = None,
    catalog: Optional[MetricContextFile] = None,
    reference_unavailable: Optional[str] = None,
) -> ScanStatistics:
    """Compute metrics, distributions and the outlier score for ``scans[index]``.

    ``reference`` is the loaded reference table for the scan's suffix; ``catalog`` is the base
    catalog used to name the metrics of an unsupported scan.
    """
    scan = scans[index]
    members, project = select_stratum(index, scans, config)
    ref_data, ref_context = reference_subset(resolved, scan.signature, reference, config, reference_unavailable)

    metrics: list[MetricEvidence] = []
    skipped: list[str] = []
    for name in sorted(scan.iqms):
        value = scan.iqms[name]
        if not math.isfinite(value):
            skipped.append(name)
            continue
        display_name, category, direction, strength = describe_metric(name, resolved, catalog)
        project_sample = _finite([scans[j].iqms.get(name) for j in members])
        project_percentile = project_z = None
        if project_sample.size >= config.min_stratum_size:
            project_percentile = empirical_percentile(value, project_sample)
            project_z = robust_z(value, project_sample)
        reference_percentile = None
        if ref_data is not None and name in ref_data.columns:
            ref_sample = np.asarray(pd.to_numeric(ref_data[name], errors="coerce"), dtype=float)
            ref_sample = ref_sample[np.isfinite(ref_sample)]
            if ref_sample.size >= config.min_stratum_size:
                reference_percentile = empirical_percentile(value, ref_sample)
        flags = metric_flags(direction, project_z, reference_percentile, config)
        metrics.append(
            MetricEvidence(
                name=name,
                value=value,
                display_name=display_name,
                category=category,
                direction_of_concern=direction,
                evidence_strength=strength,
                project_percentile=project_percentile,
                reference_percentile=reference_percentile,
                flags=flags,
                context_category=context_category_for(flags) if direction in DIRECTIONAL else None,
            )
        )

    outlier = None
    scored = [m.name for m in metrics if m.direction_of_concern in DIRECTIONAL and m.evidence_strength != "none"]
    scored = [n for n in scored if all(math.isfinite(scans[j].iqms.get(n, math.nan)) for j in members)]
    if members and scored:
        target = np.array([scan.iqms[n] for n in scored])
        matrix = np.array([[scans[j].iqms[n] for n in scored] for j in members])
        outlier = outlier_score(target, matrix, scored)
    return ScanStatistics(metrics=metrics, project=project, reference=ref_context, outlier=outlier, skipped=skipped)
