"""Targeted views: extra images that a rule adds for a specific flag.

A flag rule fires when any metric it lists carries a flag. The mask overlay rule fires when the
QC task names an overlay image (``overlay_mri_image_path`` in ``qc.json``), so the mask or
segmentation the pipeline produced is audited as part of QC. Targeted views are drawn from the
same scene as the core views; no new volumes are computed.

In control mode, a scan with no flagged metric gets every flag rule's view, marked as a control,
to measure how often a model confirms a problem that a view merely suggests.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Optional, Sequence

from .constants import CORE_BBOX_FRACTIONS, CORE_MNI_COORDS, CORE_PLANES, CORE_WINDOW_PERCENTILES
from .models import MetricEvidence, Plane, ViewRef
from .render import Scene, load_overlay, render_view


@dataclass(frozen=True)
class ViewRule:
    """One row of the rule table: the metrics that trigger it and the view it adds."""

    name: str
    metrics: tuple[str, ...]
    """IQM names or globs; a flag on any of them fires the rule."""
    plane: Plane
    mni_coords: tuple[float, ...]
    bbox_fractions: tuple[float, ...]
    window_percentiles: tuple[float, float]


FLAG_RULES: tuple[ViewRule, ...] = (
    ViewRule(
        name="motion",
        # Framewise displacement (bold); CJV rises with head motion in T1w (MRIQC docs). MRIQC
        # has no direct motion IQM for anatomical scans.
        metrics=("fd_mean", "fd_num", "fd_perc", "cjv"),
        plane="sagittal",
        mni_coords=(-50.0, -40.0, 40.0, 50.0),
        bbox_fractions=(0.15, 0.25, 0.75, 0.85),
        window_percentiles=CORE_WINDOW_PERCENTILES,
    ),
    ViewRule(
        name="noise",
        # Noise and ghosting show in the background, so the window saturates the head.
        metrics=("snr_*", "efc", "fber", "qi_1", "gsr_*"),
        plane="axial",
        mni_coords=CORE_MNI_COORDS["axial"],
        bbox_fractions=CORE_BBOX_FRACTIONS,
        window_percentiles=(0.5, 50.0),
    ),
)
"""Flag rules, in the order their views are written."""

MASK_OVERLAY_RULE = "mask_overlay"
"""Rule name of the overlay views; one view per core plane."""


def is_flagged(metric: MetricEvidence) -> bool:
    return bool(metric.flags)


def rule_fires(rule: ViewRule, metrics: Sequence[MetricEvidence]) -> bool:
    """True when any flagged metric matches one of the rule's names or globs."""
    return any(is_flagged(m) and any(fnmatchcase(m.name, pattern) for pattern in rule.metrics) for m in metrics)


def fired_rules(metrics: Sequence[MetricEvidence], *, control: bool = False) -> list[tuple[ViewRule, bool]]:
    """Flag rules to render, each with whether its view is a control.

    In control mode a scan with no flagged metric gets every flag rule as a control.
    """
    if control and not any(is_flagged(m) for m in metrics):
        return [(rule, True) for rule in FLAG_RULES]
    return [(rule, False) for rule in FLAG_RULES if rule_fires(rule, metrics)]


def render_targeted_views(
    scene: Scene,
    bundle_dir: Path,
    metrics: Sequence[MetricEvidence],
    *,
    overlay_path: Optional[Path] = None,
    control: bool = False,
) -> list[ViewRef]:
    """Render the targeted views for one scan and return their references.

    ``overlay_path`` must be on the grid of the scene's volume; otherwise ``ValueError``.
    """
    views = [
        render_view(
            scene,
            bundle_dir,
            name=f"targeted_{rule.name}",
            kind="targeted",
            plane=rule.plane,
            mni_coords=rule.mni_coords,
            bbox_fractions=rule.bbox_fractions,
            window_percentiles=rule.window_percentiles,
            rule=rule.name,
            control=is_control,
        )
        for rule, is_control in fired_rules(metrics, control=control)
    ]
    if overlay_path is not None:
        overlay = load_overlay(overlay_path, scene)
        views.extend(
            render_view(
                scene,
                bundle_dir,
                name=f"targeted_{MASK_OVERLAY_RULE}_{plane}",
                kind="targeted",
                plane=plane,  # type: ignore[arg-type]
                mni_coords=CORE_MNI_COORDS[plane],
                bbox_fractions=CORE_BBOX_FRACTIONS,
                window_percentiles=CORE_WINDOW_PERCENTILES,
                rule=MASK_OVERLAY_RULE,
                overlay=overlay,
            )
            for plane in CORE_PLANES
        )
    return views
