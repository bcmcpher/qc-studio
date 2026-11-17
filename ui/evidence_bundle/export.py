"""Export evidence bundles for one QC task.

Run as ``python ui/evidence_bundle/export.py --dataset_dir ... --qc_task ...``. For each
participant and session of the cohort, the scan is the one ``base_mri_image_path`` names; its
IQMs come from the ``iqm_path`` group TSVs, which are also the project distribution. Output:

- ``<out_dir>/<participant_id>/<session_id>/<pipeline>/<qc_task>/`` with ``bundle.json``,
  ``PACKAGE.md`` and ``views/``;
- ``<out_dir>/acquisition_summary.tsv``, one row per cohort scan, with its export status.

A scan whose image cannot be drawn still gets a bundle, without views (status ``partial``). A
scan without IQMs gets no bundle (status ``error``). The CLI exits non-zero only when no
bundle was written.
"""

import argparse
import json
import numbers
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

_HERE = Path(__file__).resolve().parent
if __name__ == "__main__":
    # As a script, sys.path[0] is this directory, whose constants.py and models.py would
    # shadow ui/constants.py and ui/models.py, which ui/utils imports.
    sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

import pandas as pd  # noqa: E402

from evidence_bundle.acquisition import acquisition_deviations, extract_acquisition, nifti_geometry, protocol_signature  # noqa: E402
from evidence_bundle.constants import BASE_CATALOG_SUFFIX, DERIVED_ENTITIES, TEMPLATE_SPACE  # noqa: E402
from evidence_bundle.context import ResolvedContext, load_metric_context, resolve_context  # noqa: E402
from evidence_bundle.models import (  # noqa: E402
    AcquisitionDeviation,
    AcquisitionMetadata,
    DistributionContext,
    EvidenceBundle,
    MetricContextFile,
    ProtocolSignature,
    RaterQC,
    StatsConfig,
    ViewRef,
)
from evidence_bundle.render import prepare_scene, render_core_views  # noqa: E402
from evidence_bundle.stats import OutlierCache, ReferenceTable, ScanInput, scan_statistics  # noqa: E402
from evidence_bundle.view_rules import fired_rules, render_overlay_views, render_targeted_views  # noqa: E402
from utils import reference_data  # noqa: E402
from utils.cohort import build_qc_cohort, normalize_participant_id_bids, normalize_session_id_bids, parse_session_list  # noqa: E402
from utils.config import build_substitution_values, list_qc_tasks_from_json, parse_qc_config  # noqa: E402
from utils.data_loaders import _resolve_all_under_dataset, load_iqm_distribution_table, resolve_iqm_data_path  # noqa: E402

PACKAGE_TEMPLATE = _HERE / "templates" / "PACKAGE.md"

NIFTI_EXTENSIONS = (".nii.gz", ".nii")

SUMMARY_SIGNATURE_FIELDS = (
    "MRAcquisitionType",
    "MagneticFieldStrength",
    "Manufacturer",
    "RepetitionTime",
    "EchoTime",
    "InversionTime",
    "FlipAngle",
    "VoxelSize",
)


# --- BIDS names ----------------------------------------------------------------------------


def _strip_extension(name: str) -> str:
    for extension in (*NIFTI_EXTENSIONS, ".json"):
        if name.endswith(extension):
            return name[: -len(extension)]
    return name


def _entity(part: str) -> Optional[str]:
    return part.split("-", 1)[0] if "-" in part else None


def scan_bids_name(path: Path) -> str:
    """The name MRIQC gives the scan an image shows: derived entities and extension removed.

    ``sub-01_ses-01_run-1_space-MNI152NLin2009cAsym_res-2_desc-preproc_T1w.nii.gz`` gives
    ``sub-01_ses-01_run-1_T1w``.
    """
    parts = _strip_extension(Path(path).name).split("_")
    return "_".join(p for p in parts if _entity(p) not in DERIVED_ENTITIES)


def bids_suffix(bids_name: str) -> str:
    return bids_name.rsplit("_", 1)[-1]


def _template_candidates(path: Path) -> list[Path]:
    """Template-space files of the same scan and kind as ``path``, in the same directory.

    A candidate has the same entities as ``path`` plus ``space-<TEMPLATE_SPACE>`` and at most a
    ``res-`` entity, so ``sub-01_dseg`` does not match ``sub-01_space-..._desc-aparcaseg_dseg``.
    """
    parts = _strip_extension(path.name).split("_")
    head = [p for p in parts if _entity(p) not in ("space", "res", "desc") and p != parts[-1]]
    tail = [p for p in parts if _entity(p) == "desc"] + [parts[-1]]
    name = re.compile(re.escape("_".join([*head, f"space-{TEMPLATE_SPACE}"])) + r"(_res-[^_]+)?_" + re.escape("_".join(tail)) + r"\.nii(\.gz)?")
    return sorted(p for p in path.parent.iterdir() if p.is_file() and name.fullmatch(p.name))


def _res(path: Path) -> Optional[str]:
    return next((p for p in _strip_extension(path.name).split("_") if _entity(p) == "res"), None)


def is_template_space(path: Path) -> bool:
    return f"space-{TEMPLATE_SPACE}" in _strip_extension(path.name).split("_")


def template_counterpart(path: Path, like: Optional[Path] = None) -> Optional[Path]:
    """The ``TEMPLATE_SPACE`` counterpart of a native pipeline file, or None.

    With ``like``, only a counterpart at the same ``res-`` as ``like`` is returned, so a mask
    is on the grid of the template image it outlines.
    """
    candidates = _template_candidates(path)
    if like is not None:
        candidates = [c for c in candidates if _res(c) == _res(like)]
    return candidates[0] if candidates else None


# --- project distribution ------------------------------------------------------------------


@dataclass
class ProjectScan:
    """One row of the group TSVs, with its signature."""

    bids_name: str
    suffix: str
    datatype: Optional[str]
    iqms: dict[str, float]
    mriqc: dict[str, Any]
    """Per-scan MRIQC JSON (empty when there is none), with ``bids_meta`` and ``provenance``."""
    signature: ProtocolSignature


@dataclass
class Project:
    """All scans of the group TSVs, the statistics inputs and the acquisition deviations."""

    scans: list[ProjectScan]
    index: dict[str, int]
    inputs: list[ScanInput]
    deviations: list[list[AcquisitionDeviation]]
    outlier_cache: OutlierCache = field(default_factory=dict)
    """Stratum outlier scores, so each stratum of the project is scored once."""


def _row_iqms(row: Mapping[str, Any]) -> dict[str, float]:
    """Numeric cells of a group TSV row; an empty cell is NaN, which the statistics skip."""
    return {k: float(v) for k, v in row.items() if k != "bids_name" and isinstance(v, numbers.Real) and not isinstance(v, bool)}


def _mriqc_jsons(root: Path) -> dict[str, Path]:
    """Per-scan MRIQC JSONs under a group TSV's directory, by BIDS name."""
    return {p.name[: -len(".json")]: p for p in sorted(root.glob("sub-*/**/*.json"))}


def load_project(tsv_paths: Sequence[Path]) -> Project:
    """Read the group TSVs and the per-scan MRIQC JSON beside them.

    The project includes every row, not only the cohort. Each scan's signature uses the
    ``bids_meta`` of its MRIQC JSON and the MRIQC ``size_*``/``spacing_*`` geometry, so all
    scans of a stratum are described the same way.
    """
    scans: list[ProjectScan] = []
    index: dict[str, int] = {}
    for tsv in tsv_paths:
        jsons = _mriqc_jsons(tsv.parent)
        table = load_iqm_distribution_table(tsv)
        if "bids_name" not in table.columns:
            raise ValueError(f"{tsv}: no bids_name column")
        for row in table.to_dict(orient="records"):
            bids_name = str(row["bids_name"])
            if bids_name in index:
                continue
            json_path = jsons.get(bids_name)
            mriqc = json.loads(json_path.read_text()) if json_path is not None else {}
            iqms = _row_iqms(row)
            suffix = bids_suffix(bids_name)
            acquisition = extract_acquisition({**iqms, **mriqc})
            index[bids_name] = len(scans)
            scans.append(
                ProjectScan(
                    bids_name=bids_name,
                    suffix=suffix,
                    datatype=json_path.parent.name if json_path is not None else None,
                    iqms=iqms,
                    mriqc=mriqc,
                    signature=protocol_signature(suffix, acquisition),
                )
            )
    inputs = [ScanInput(suffix=s.suffix, signature=s.signature, iqms=s.iqms) for s in scans]
    deviations = acquisition_deviations([s.signature for s in scans])
    return Project(scans=scans, index=index, inputs=inputs, deviations=deviations)


# --- reference data ------------------------------------------------------------------------


class ReferenceTables:
    """MRIQC reference tables, loaded once per suffix through ``reference_data``."""

    def __init__(self):
        self._tables: dict[str, tuple[Optional[ReferenceTable], Optional[str]]] = {}

    def get(self, suffix: str) -> tuple[Optional[ReferenceTable], Optional[str]]:
        """The table for a suffix, or None with the reason it is unavailable.

        The host and the cache name files by the lower-case suffix (``t1w.parquet``), as the
        QC Metrics panel does.
        """
        modality = suffix.lower()
        if modality not in self._tables:
            try:
                self._tables[modality] = (ReferenceTable(reference_data.load_reference_parquet(modality)), None)
            except Exception as exc:  # no URL, no network, no table for the suffix
                self._tables[modality] = (None, f"no {modality} reference data: {exc}")
        return self._tables[modality]


# --- rater QC ------------------------------------------------------------------------------


def _session(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return normalize_session_id_bids(text) if text else "ses-01"


def load_rater_qc(path: Path) -> dict[tuple[str, str, str, str], RaterQC]:
    """The latest rating per (pipeline, qc_task, participant, session) in a ``*_qc_status.tsv``.

    Multi-facet ratings have one row per facet; they become ``RaterQC.facets``.
    """
    table = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    result: dict[tuple[str, str, str, str], RaterQC] = {}
    for (pipeline, qc_task, pid, sid), rows in table.groupby(["pipeline", "qc_task", "participant_id", "session_id"], sort=False):
        latest = rows[rows["timestamp"] == rows["timestamp"].max()]
        last = latest.iloc[-1]
        facets = {str(r["facet"]): str(r["rating_value"]) for _, r in latest.iterrows() if str(r.get("facet", "")).strip()}
        key = (str(pipeline), str(qc_task), normalize_participant_id_bids(pid), _session(sid))
        result[key] = RaterQC(
            rater_id=str(last.get("rater_id") or "") or None,
            final_qc=str(last.get("final_qc") or "") or None,
            facets=facets,
            notes=str(last.get("notes") or "") or None,
            timestamp=str(last.get("timestamp") or "") or None,
        )
    return result


# --- views ---------------------------------------------------------------------------------


def render_views(bundle_dir: Path, image: Path, overlay: Optional[Path], metrics, notes: list[str]) -> list[ViewRef]:
    """Render core and targeted views from existing pipeline files.

    A native image with a template-space counterpart is drawn in template space, with the
    template-space overlay and a native background scene. A template-space image is drawn as
    is; its overlay must be template-space too.

    The core views must succeed (their error propagates). Flag-rule views and mask overlay
    views are separate steps: a failure there is added to ``notes`` and the other views stay.
    """
    background_overlay = None
    if is_template_space(image):
        scene = prepare_scene(image, template_image_path=image)
        overlay_path = overlay
    elif (template := template_counterpart(image)) is not None:
        scene = prepare_scene(image, template_image_path=template)
        overlay_path, background_overlay = None, overlay
        if overlay is not None:
            overlay_path = overlay if is_template_space(overlay) else template_counterpart(overlay, like=template)
            if overlay_path is None:
                notes.append(f"no {TEMPLATE_SPACE} counterpart of {overlay.name}; no mask overlay views")
    else:
        try:
            scene = prepare_scene(image, mask_path=overlay)
        except ValueError as exc:  # the overlay is not on the image grid
            notes.append(f"slices placed by a threshold head mask: {exc}")
            scene = prepare_scene(image)
        overlay_path = overlay
    views = render_core_views(scene, bundle_dir)

    background = None
    if scene.placement == "mni" and not is_template_space(image) and any(rule.needs_background for rule, _ in fired_rules(metrics)):
        try:
            background = prepare_scene(image, mask_path=background_overlay)
        except Exception as exc:
            notes.append(f"no native background scene, background views drawn from the template image: {exc}")
    try:
        views += render_targeted_views(scene, bundle_dir, metrics, background_scene=background)
    except Exception as exc:
        notes.append(f"no flag-rule views: {exc}")
    if overlay_path is not None:
        try:
            views += render_overlay_views(scene, bundle_dir, overlay_path)
        except Exception as exc:
            notes.append(f"no mask overlay views: {exc}")
    return views


def _remove_unreferenced_views(bundle_dir: Path, views: Sequence[ViewRef]) -> None:
    """Delete PNGs a failed step wrote but the bundle does not reference."""
    keep = {bundle_dir / v.path for v in views}
    for path in (bundle_dir / "views").glob("*.png"):
        if path not in keep:
            path.unlink()


# --- PACKAGE.md ----------------------------------------------------------------------------


def render_markdown_template(template_path: Path, context: dict[str, Any]) -> str:
    """Render a Markdown template using Python format placeholders."""
    template = template_path.read_text(encoding="utf-8")
    return template.format(**context)


def _cell(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, (list, tuple)):
        return " x ".join(_cell(v) for v in value) if all(isinstance(v, (int, float)) for v in value) else ", ".join(map(str, value))
    return str(value).replace("|", "\\|").replace("\n", " ")


def _support_text(bundle: EvidenceBundle) -> str:
    if bundle.support == "supported":
        return f"Interpreted using {bundle.suffix} metric context."
    if bundle.support == "fallback":
        return (
            f"Interpreted using {bundle.context_suffix} metric context: {bundle.suffix} has no context of its own. "
            "Metrics that depend on tissue contrast are context_dependent, and there are no reference percentiles."
        )
    return f"No metric context for {bundle.suffix}: metrics are listed without a direction of concern, and none is flagged."


def _acquisition_table(acquisition: AcquisitionMetadata) -> str:
    rows = []
    for group in ("scanner", "sequence", "geometry", "provenance"):
        for name, value in getattr(acquisition, group).model_dump().items():
            rows.append(f"| {group} | `{name}` | {_cell(value)} |")
    if acquisition.site is not None:
        rows.insert(0, f"| site | `site` | {_cell(acquisition.site)} |")
    return "\n".join(rows)


def _deviation_lines(deviations: Sequence[AcquisitionDeviation]) -> str:
    if not deviations:
        return "No acquisition deviations from the project's usual protocol for this suffix."
    return "\n".join(f"- `{d.field}`: {_cell(d.value)}; expected {_cell(d.expected)} ({d.share:.0%} of {d.n} scans)" for d in deviations)


def _distribution_text(name: str, context: Optional[DistributionContext]) -> str:
    if context is None:
        return f"- {name}: none"
    filters = ", ".join(f"{k}={v}" for k, v in context.filters.items()) or "none"
    fields = ", ".join(context.signature_fields) or "none"
    text = f"- {name}: n={context.n}; signature fields {fields}; filters {filters}"
    return text + (f". {context.note}" if context.note else "")


def _metric_rows(bundle: EvidenceBundle) -> str:
    metrics = sorted(bundle.metrics, key=lambda m: (not m.is_flagged, m.name))
    return "\n".join(
        f"| `{m.name}` | {_cell(m.value)} | {m.direction_of_concern} | {m.evidence_strength} | {_cell(m.project_percentile)} | "
        f"{_cell(m.reference_percentile)} | {', '.join(m.flags) or '-'} | {m.context_category or '-'} |"
        for m in metrics
    )


def _outlier_text(bundle: EvidenceBundle) -> str:
    outlier = bundle.outlier
    if outlier is None:
        return "Not computed: the project stratum is too small or has no interpretable metrics."
    top = ", ".join(f"`{c.metric}` ({c.contribution:.3g})" for c in outlier.top_contributors) or "none"
    return f"Robust Mahalanobis score {outlier.score:.3g} (percentile {_cell(outlier.percentile)}); main contributors: {top}."


def _views_text(bundle: EvidenceBundle) -> str:
    if not bundle.views:
        return "No views."
    lines = []
    for view in bundle.views:
        label = f"{view.kind} {view.plane}" + (f", rule {view.rule}" if view.rule else "") + (", control" if view.control else "")
        lines.append(f"![{label}]({view.path})")
    return "\n\n".join(lines)


def _rater_text(rater: Optional[RaterQC]) -> str:
    if rater is None:
        return "No rater QC."
    lines = [f"- Final QC: {rater.final_qc or 'n/a'} (rater {rater.rater_id or 'n/a'}, {rater.timestamp or 'no timestamp'})"]
    lines += [f"- {facet}: {value}" for facet, value in rater.facets.items()]
    if rater.notes:
        lines.append(f"- Notes: {_cell(rater.notes)}")
    return "\n".join(lines)


def package_context(bundle: EvidenceBundle) -> dict[str, Any]:
    return {
        "participant_id": bundle.participant_id,
        "session_id": bundle.session_id,
        "pipeline": bundle.pipeline,
        "qc_task": bundle.qc_task,
        "bids_name": bundle.bids_name,
        "suffix": bundle.suffix,
        "support": bundle.support,
        "support_text": _support_text(bundle),
        "acquisition_table": _acquisition_table(bundle.acquisition),
        "deviations": _deviation_lines(bundle.acquisition_deviations),
        "project": _distribution_text("Project", bundle.project),
        "reference": _distribution_text("MRIQC reference", bundle.reference),
        "flagged": ", ".join(f"`{n}`" for n in bundle.flagged_metrics()) or "none",
        "metric_rows": _metric_rows(bundle),
        "outlier": _outlier_text(bundle),
        "views": _views_text(bundle),
        "rater_qc": _rater_text(bundle.rater_qc),
    }


# --- export --------------------------------------------------------------------------------


@dataclass
class ExportOptions:
    dataset_dir: Path
    qc_json: Path
    qc_task: str
    pipeline: str
    out_dir: Path
    stats_config: StatsConfig = field(default_factory=StatsConfig)
    contrast_map: Optional[dict[str, str]] = None
    rater_qc: dict[tuple[str, str, str, str], RaterQC] = field(default_factory=dict)


def _summary_row(pid: str, sid: str, options: ExportOptions) -> dict[str, Any]:
    row: dict[str, Any] = {"participant_id": pid, "session_id": sid, "pipeline": options.pipeline, "qc_task": options.qc_task}
    row.update({k: "" for k in ("bids_name", "suffix", "support", "context_suffix", *SUMMARY_SIGNATURE_FIELDS, "deviations")})
    row.update({"flagged_metrics": "", "n_views": 0, "status": "error", "error": "", "notes": "", "bundle_dir": ""})
    return row


def _resolve_image(dataset_dir: Path, spec: Path) -> Path:
    """The one image a ``base_mri_image_path`` names. A missing file is returned as is."""
    matches = _resolve_all_under_dataset(dataset_dir, spec)
    if len(matches) > 1:
        raise ValueError(f"base_mri_image_path matches {len(matches)} files; a bundle needs one scan: {spec}")
    if matches:
        return matches[0]
    if "*" in str(spec):
        raise ValueError(f"base_mri_image_path matches no file: {spec}")
    return dataset_dir / spec


def _raw_scan_files(dataset_dir: Path, pid: str, sid: str, datatype: Optional[str], bids_name: str) -> tuple[Optional[Path], Optional[Path]]:
    """The raw BIDS image and sidecar of a scan, when they exist.

    Looks in ``bids/<sub>/<ses>/<datatype>`` and, for datasets without a session level,
    ``bids/<sub>/<datatype>``.
    """
    if datatype is None:
        return None, None
    for folder in (dataset_dir / "bids" / pid / sid / datatype, dataset_dir / "bids" / pid / datatype):
        image = next((folder / f"{bids_name}{ext}" for ext in NIFTI_EXTENSIONS if (folder / f"{bids_name}{ext}").is_file()), None)
        sidecar = folder / f"{bids_name}.json"
        if image is not None or sidecar.is_file():
            return image, sidecar if sidecar.is_file() else None
    return None, None


def _catalog(resolved: ResolvedContext, datatype: Optional[str]) -> Optional[MetricContextFile]:
    if resolved.support != "unsupported":
        return None
    base = BASE_CATALOG_SUFFIX.get(datatype or "")
    return load_metric_context(base) if base else None


def export_scan(
    pid: str,
    sid: str,
    options: ExportOptions,
    projects: dict[tuple[Path, ...], Project],
    references: ReferenceTables,
) -> dict[str, Any]:
    """Export one participant and session; return its ``acquisition_summary.tsv`` row."""
    row = _summary_row(pid, sid, options)
    notes: list[str] = []
    config = parse_qc_config(options.qc_json, options.qc_task, build_substitution_values(pid, sid))
    if config["base_mri_image_path"] is None:
        row["error"] = "the QC task sets no base_mri_image_path"
        return row
    try:
        image = _resolve_image(options.dataset_dir, Path(config["base_mri_image_path"]))
    except ValueError as exc:
        row["error"] = str(exc)
        return row
    bids_name = scan_bids_name(image)
    row.update(bids_name=bids_name, suffix=bids_suffix(bids_name))

    tsvs = tuple(
        resolve_iqm_data_path(str(p), str(options.qc_json), str(options.dataset_dir))
        for p in (config["iqm_path"] or [])
        if Path(p).suffix.lower() in (".tsv", ".csv")
    )
    tsvs = tuple(p for p in tsvs if p.is_file())
    if not tsvs:
        row["error"] = "the QC task's iqm_path names no readable group TSV"
        return row
    if tsvs not in projects:
        projects[tsvs] = load_project(tsvs)
    project = projects[tsvs]
    if bids_name not in project.index:
        row["error"] = f"no IQMs for {bids_name} in {', '.join(p.name for p in tsvs)}"
        return row
    i = project.index[bids_name]
    scan = project.scans[i]
    # The MRIQC JSON's folder names the datatype; without one, the image's folder does.
    datatype = scan.datatype or (image.parent.name if image.parent.name in BASE_CATALOG_SUFFIX else None)

    resolved = resolve_context(scan.suffix, options.contrast_map)
    reference, unavailable = references.get(resolved.context_suffix or scan.suffix) if resolved.support == "supported" else (None, None)
    stats = scan_statistics(
        i, project.inputs, resolved, options.stats_config, reference, _catalog(resolved, datatype), unavailable, project.outlier_cache
    )
    if stats.skipped:
        notes.append(f"IQMs without a finite value: {', '.join(stats.skipped)}")

    raw_image, sidecar_path = _raw_scan_files(options.dataset_dir, pid, sid, datatype, bids_name)
    sidecar = json.loads(sidecar_path.read_text()) if sidecar_path is not None else None
    if raw_image is None and sidecar_path is None:
        notes.append(f"no raw BIDS files for {bids_name}; acquisition from MRIQC bids_meta and geometry from MRIQC")
    geometry_source = None
    if raw_image is not None:
        try:
            nifti_geometry(raw_image)
            geometry_source = raw_image
        except Exception as exc:
            notes.append(f"geometry from MRIQC: cannot read {raw_image.name}: {exc}")
    acquisition = extract_acquisition({**scan.iqms, **scan.mriqc}, sidecar, nifti_path=geometry_source)

    bundle_dir = options.out_dir / pid / sid / options.pipeline / options.qc_task
    bundle_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(bundle_dir / "views", ignore_errors=True)
    overlay_spec = config["overlay_mri_image_path"]
    overlay = None
    if overlay_spec is not None:
        overlay_matches = _resolve_all_under_dataset(options.dataset_dir, Path(overlay_spec))
        overlay = overlay_matches[0] if overlay_matches else None
        if overlay is None:
            notes.append(f"overlay not found: {overlay_spec}")
    views: list[ViewRef] = []
    error = ""
    try:
        if not image.is_file():
            raise FileNotFoundError(f"image not found: {image}")
        views = render_views(bundle_dir, image, overlay, stats.metrics, notes)
    except Exception as exc:
        error = f"no views: {exc}"
        views = []
    _remove_unreferenced_views(bundle_dir, views)

    bundle = EvidenceBundle(
        participant_id=pid,
        session_id=sid,
        pipeline=options.pipeline,
        qc_task=options.qc_task,
        bids_name=bids_name,
        suffix=scan.suffix,
        support=resolved.support,
        context_suffix=resolved.context_suffix,
        acquisition=acquisition,
        protocol_signature=scan.signature,
        acquisition_deviations=project.deviations[i],
        stats_config=options.stats_config,
        project=stats.project,
        reference=stats.reference,
        metrics=stats.metrics,
        outlier=stats.outlier,
        views=views,
        rater_qc=options.rater_qc.get((options.pipeline, options.qc_task, pid, sid)),
    )
    (bundle_dir / "bundle.json").write_text(bundle.model_dump_json(indent=2) + "\n")
    (bundle_dir / "PACKAGE.md").write_text(render_markdown_template(PACKAGE_TEMPLATE, package_context(bundle)))

    signature = scan.signature.model_dump()
    row.update({k: _cell(signature[k]) if signature[k] is not None else "" for k in SUMMARY_SIGNATURE_FIELDS})
    row.update(
        support=bundle.support,
        context_suffix=bundle.context_suffix or "",
        deviations="; ".join(f"{d.field}={_cell(d.value)} (expected {_cell(d.expected)})" for d in bundle.acquisition_deviations),
        flagged_metrics=",".join(bundle.flagged_metrics()),
        n_views=len(views),
        status="partial" if error else "ok",
        error=error,
        notes="; ".join(notes),
        bundle_dir=str(bundle_dir.relative_to(options.out_dir)),
    )
    return row


def export_bundles(cohort: Sequence[Mapping[str, Any]], options: ExportOptions) -> pd.DataFrame:
    """Export every cohort row; write and return ``acquisition_summary.tsv``.

    An unexpected error in one scan is recorded in its row and the export goes on.
    """
    options.out_dir.mkdir(parents=True, exist_ok=True)
    projects: dict[tuple[Path, ...], Project] = {}
    references = ReferenceTables()
    rows = []
    for entry in cohort:
        pid = entry["participant_id"]
        sid = _session(entry.get("session_id"))
        try:
            row = export_scan(pid, sid, options, projects, references)
        except Exception as exc:
            row = _summary_row(pid, sid, options)
            row["error"] = f"{type(exc).__name__}: {exc}"
        if row["status"] == "error":
            # A bundle from an earlier run would read as current evidence.
            shutil.rmtree(options.out_dir / pid / sid / options.pipeline / options.qc_task, ignore_errors=True)
        rows.append(row)
    summary = pd.DataFrame(rows, columns=list(_summary_row("", "", options)))
    summary.to_csv(options.out_dir / "acquisition_summary.tsv", sep="\t", index=False)
    return summary


# --- CLI -----------------------------------------------------------------------------------


def parse_args(args=None):
    parser = argparse.ArgumentParser("qc-studio-evidence-bundle", description="Export model-independent evidence bundles for one QC task.")
    parser.add_argument("--dataset_dir", dest="dataset_dir", required=True, help="Path to the dataset dir (the qc.json paths are relative to it)")
    parser.add_argument(
        "--participant_list", dest="participant_list", required=True, help="TSV with a participant_id (and optional session_id) column"
    )
    parser.add_argument(
        "--session_list",
        dest="session_list",
        default=None,
        help="Comma-separated BIDS sessions (e.g. ses-01,ses-02); ignored when the participant TSV has a session_id column",
    )
    parser.add_argument("--qc_json", dest="qc_json", required=True, help="Path to the pipeline's qc.json")
    parser.add_argument("--qc_task", dest="qc_task", required=True, help="QC task key from qc.json")
    parser.add_argument("--qc_pipeline", dest="qc_pipeline", required=True, help="Pipeline name recorded in the bundles")
    parser.add_argument("--out_dir", dest="out_dir", required=True, help="Directory for the bundles and acquisition_summary.tsv")
    parser.add_argument("--qc_status", dest="qc_status", default=None, help="Optional *_qc_status.tsv whose ratings go into the bundles")
    parser.add_argument(
        "--contrast_map",
        dest="contrast_map",
        default=None,
        help='JSON object (or path to one) mapping a suffix to the suffix whose context it uses; replaces the default {"FLAIR": "T2w", "T2starw": "T2w"}',
    )
    parser.add_argument(
        "--stats_config",
        dest="stats_config",
        default=None,
        help="JSON object (or path to one) with StatsConfig cutoffs: min_stratum_size, project_z_threshold, reference_percentile_low/high",
    )
    return parser.parse_args(args)


def _json_option(value: Optional[str]) -> Optional[Any]:
    if value is None:
        return None
    path = Path(value)
    return json.loads(path.read_text() if path.is_file() else value)


def main(args=None) -> int:
    ns = parse_args(args)
    qc_json = Path(ns.qc_json)
    if ns.qc_task not in list_qc_tasks_from_json(qc_json):
        print(f"QC task '{ns.qc_task}' not found in {qc_json}", file=sys.stderr)
        return 2
    contrast_map = _json_option(ns.contrast_map)
    if contrast_map is not None and not (isinstance(contrast_map, dict) and all(isinstance(v, str) for v in contrast_map.values())):
        print("--contrast_map must be a JSON object of suffix to suffix", file=sys.stderr)
        return 2
    options = ExportOptions(
        dataset_dir=Path(ns.dataset_dir),
        qc_json=qc_json,
        qc_task=ns.qc_task,
        pipeline=ns.qc_pipeline,
        out_dir=Path(ns.out_dir),
        stats_config=StatsConfig.model_validate(_json_option(ns.stats_config) or {}),
        contrast_map=contrast_map,
        rater_qc=load_rater_qc(Path(ns.qc_status)) if ns.qc_status else {},
    )
    participants = pd.read_csv(ns.participant_list, sep="\t", dtype=str)
    summary = export_bundles(build_qc_cohort(participants, parse_session_list(ns.session_list)), options)
    for _, row in summary[summary["status"] != "ok"].iterrows():
        print(f"{row['participant_id']} {row['session_id']}: {row['status']}: {row['error']}", file=sys.stderr)
    written = int((summary["status"] != "error").sum())
    print(f"{written} of {len(summary)} bundles written to {options.out_dir}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
