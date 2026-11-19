"""Evaluation runner: send every evidence bundle to one adapter under each view variant.

A cell is one adapter and model with one variant. A variant is a view set (IQMs only, core,
core + targeted) and, for targeted views, whether their reason is stated or hidden. Bundles
are exported once; each variant is derived here, so the export CLI needs no extra flags.

Each (bundle, cell) gets its own folder ``OUT/<model_key>/<variant>/<bundle path>/`` with the
variant's ``bundle.json``, ``PACKAGE.md``, ``views/``, a ``cell.json`` and the adapter's
``feedback.json``. The ``feedback.json`` beside the exported bundle is never touched. An
existing ``feedback.json`` in a cell folder is read, not resent, so runs made on another host
can be copied into ``OUT`` and collected. After each run every cell folder under ``OUT`` is
collected into one TSV, one row per (scan, cell).

Usage (from the repo root)::

    .venv/bin/python sandbox/evaluation/run_eval.py BUNDLE_ROOT --out_dir OUT --adapter claude --acknowledge_data_use --dry_run
    .venv/bin/python sandbox/evaluation/run_eval.py BUNDLE_ROOT --out_dir OUT --adapter openai_compat \\
        --base_url http://gpu-host:8000/v1 --model_id llava-onevision --acknowledge_data_use
    .venv/bin/python sandbox/evaluation/run_eval.py --collect_only --out_dir OUT --labels labels.tsv
"""

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import struct
import sys
from collections import Counter
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Sequence

# Make ``model_adapters`` (sandbox/) and ``evidence_bundle`` (ui/) importable when run as a script.
for _path in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2] / "ui"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from model_adapters.base import BUNDLE_FILE, PACKAGE_FILE, PROMPT_TEMPLATE, DataUseError, ModelAdapter, load_bundle  # noqa: E402
from model_adapters.run_feedback import add_adapter_args, find_bundles, make_adapter, resolve_model_id  # noqa: E402
from evidence_bundle.export import _cell, _deviation_lines, _distribution_text, package_context, render_markdown_template  # noqa: E402
from evidence_bundle.feedback import FEEDBACK_FILE, FeedbackResult, error_result, load_feedback, write_feedback  # noqa: E402
from evidence_bundle.models import AcquisitionMetadata, DistributionContext, EvidenceBundle, ScannerMetadata, ViewRef  # noqa: E402
from evidence_bundle.view_rules import FLAG_RULES  # noqa: E402

LOG = logging.getLogger("run_eval")

EVAL_PACKAGE_TEMPLATE = Path(__file__).with_name("PACKAGE_eval.md")
"""The export's ``PACKAGE.md`` template without the scan identifiers and the rater QC section."""
WITHHELD_FIELDS = frozenset({"site", "md5sum", *ScannerMetadata.model_fields})
"""Acquisition fields never shown to the model in the evaluation: each can identify a scan, a
site or a dataset, and so stand in for the label. They stay in ``bundle.json`` and the TSV."""

CELL_FILE = "cell.json"
RESULTS_FILE = "results.tsv"
LABELS = ("pass", "fail", "uncertain")

ViewSet = Literal["iqms", "core", "core_targeted"]
ReasonMode = Literal["none", "stated", "hidden"]


@dataclass(frozen=True)
class Variant:
    """One way of presenting a bundle: which views, and whether targeted-view reasons are shown."""

    name: str
    view_set: ViewSet
    reason: ReasonMode


VARIANTS: tuple[Variant, ...] = (
    Variant("iqms", "iqms", "none"),
    Variant("core", "core", "none"),
    Variant("core_targeted_stated", "core_targeted", "stated"),
    Variant("core_targeted_hidden", "core_targeted", "hidden"),
)
"""The reason mode only matters with targeted views, so the other view sets have one variant each."""
VARIANT_NAMES = tuple(v.name for v in VARIANTS)

TEXT_CHARS_PER_TOKEN = 4
IMAGE_PIXELS_PER_TOKEN = 750
IMAGE_TOKENS_FALLBACK = 1600
"""Token estimate for an image whose size cannot be read; about the cap of a large Claude image."""

ROW_FIELDS: tuple[str, ...] = (
    "participant_id",
    "session_id",
    "bids_name",
    "suffix",
    "support",
    "source_bundle",
    "cell_id",
    "adapter",
    "model_id",
    "variant",
    "view_set",
    "reason",
    "n_views",
    "control_scan",
    "control_rules",
    "targeted_rules",
    "prompt_hash",
    "status",
    "schema_valid",
    "consistency_valid",
    "decision",
    "confidence",
    "flagged_metrics",
    "control_confirmed",
    "label",
    "original_label",
    "agreement",
    "error",
)


# --- variants --------------------------------------------------------------------------------


def model_key(adapter: str, model_id: Optional[str]) -> str:
    """Folder name for one adapter and model: ``<adapter>__<model id>-<hash>``, filesystem-safe.

    The hash of the raw model id keeps ids that differ only in replaced characters apart.
    """
    raw = model_id or "default"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{adapter}__{re.sub(r'[^A-Za-z0-9._-]+', '-', raw)}-{digest}"


def variant_views(views: Sequence[ViewRef], view_set: ViewSet) -> list[ViewRef]:
    if view_set == "iqms":
        return []
    if view_set == "core":
        return [v for v in views if v.kind == "core"]
    return list(views)


def staged_views(bundle: EvidenceBundle, variant: Variant) -> list[tuple[str, ViewRef]]:
    """The variant's views as (source path, view renamed ``views/view_NN.png``).

    Export names a view after its kind and rule (``targeted_noise``); the neutral name keeps
    that out of the prompt, which lists each image's path.
    """
    return [
        (view.path, view.model_copy(update={"path": f"views/view_{index:02d}.png"}))
        for index, view in enumerate(variant_views(bundle.views, variant.view_set), start=1)
    ]


def variant_bundle(bundle: EvidenceBundle, variant: Variant) -> EvidenceBundle:
    """The bundle with only the variant's views, under neutral names."""
    return bundle.model_copy(update={"views": [view for _, view in staged_views(bundle, variant)]})


def views_text(views: Sequence[ViewRef], reason: ReasonMode) -> str:
    """The "Views" section of ``PACKAGE.md`` for a variant.

    No mode says which views are controls, so the model cannot tell a control from a real flag.
    A hidden reason drops both the rule and the core/targeted kind, since "targeted" alone
    suggests a problem.
    """
    if not views:
        return "No views."
    lines = []
    for view in views:
        if reason == "hidden":
            label = f"{view.plane} view"
        else:
            label = f"{view.kind} {view.plane}" + (f", rule {view.rule}" if view.rule else "")
        lines.append(f"![{label}]({view.path})")
    return "\n\n".join(lines)


def acquisition_table(acquisition: AcquisitionMetadata) -> str:
    """The acquisition table without ``WITHHELD_FIELDS``."""
    rows = []
    for group in ("sequence", "geometry", "provenance"):
        for name, value in getattr(acquisition, group).model_dump().items():
            if name not in WITHHELD_FIELDS:
                rows.append(f"| {group} | `{name}` | {_cell(value)} |")
    return "\n".join(rows)


def blind_distribution(context: Optional[DistributionContext]) -> Optional[DistributionContext]:
    """The distribution without the values of withheld filters (site, scanner); field names stay."""
    if context is None:
        return None
    return context.model_copy(update={"filters": {k: v for k, v in context.filters.items() if k not in WITHHELD_FIELDS}})


def package_text(bundle: EvidenceBundle, reason: ReasonMode) -> str:
    """The evaluation ``PACKAGE.md`` for a variant bundle.

    Rendered from the export's context with no scan identifiers, no rater QC, none of
    ``WITHHELD_FIELDS`` (acquisition rows, deviations or distribution filters), and the
    variant's view labels.
    """
    context = package_context(bundle)
    context["acquisition_table"] = acquisition_table(bundle.acquisition)
    context["deviations"] = _deviation_lines([d for d in bundle.acquisition_deviations if d.field not in WITHHELD_FIELDS])
    context["project"] = _distribution_text("Project", blind_distribution(bundle.project))
    context["reference"] = _distribution_text("MRIQC reference", blind_distribution(bundle.reference))
    context["views"] = views_text(bundle.views, reason)
    return render_markdown_template(EVAL_PACKAGE_TEMPLATE, context)


def _unique(items: Sequence[Optional[str]]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def cell_info(bundle: EvidenceBundle, staged: EvidenceBundle, variant: Variant, source_bundle: str) -> dict[str, Any]:
    """What ``cell.json`` records: the variant, whether the scan is a control scan, and the
    targeted and control rules of the views this variant shows (none for ``iqms`` and ``core``)."""
    return {
        "variant": variant.name,
        "view_set": variant.view_set,
        "reason": variant.reason,
        "source_bundle": source_bundle,
        "control_scan": any(v.control for v in bundle.views),
        "targeted_rules": _unique([v.rule for v in staged.views if v.kind == "targeted"]),
        "control_rules": _unique([v.rule for v in staged.views if v.control]),
    }


def stage(source_dir: Path, bundle: EvidenceBundle, variant: Variant, cell_dir: Path, source_bundle: str) -> EvidenceBundle:
    """Write the variant's ``cell.json``, ``bundle.json``, ``PACKAGE.md`` and ``views/`` to ``cell_dir``.

    The metadata is written first, so a view that fails to copy still leaves a cell the
    collector finds. An earlier ``views/`` folder is replaced; ``feedback.json`` is left for the caller.
    """
    pairs = staged_views(bundle, variant)
    staged = bundle.model_copy(update={"views": [view for _, view in pairs]})
    cell_dir.mkdir(parents=True, exist_ok=True)
    (cell_dir / CELL_FILE).write_text(json.dumps(cell_info(bundle, staged, variant, source_bundle), indent=2), encoding="utf-8")
    (cell_dir / BUNDLE_FILE).write_text(staged.model_dump_json(indent=2), encoding="utf-8")
    (cell_dir / PACKAGE_FILE).write_text(package_text(staged, variant.reason), encoding="utf-8")
    shutil.rmtree(cell_dir / "views", ignore_errors=True)
    (cell_dir / "views").mkdir()
    for source, view in pairs:
        shutil.copyfile(source_dir / source, cell_dir / view.path)
    return staged


# --- token estimate --------------------------------------------------------------------------


def png_size(path: Path) -> Optional[tuple[int, int]]:
    """Width and height from a PNG header, or None when the file is not a readable PNG."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or not head.startswith(b"\x89PNG\r\n\x1a\n") or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def image_tokens(path: Path) -> int:
    """Rough input tokens for one image: pixels / 750, as Claude counts them."""
    size = png_size(path)
    if size is None:
        return IMAGE_TOKENS_FALLBACK
    return max(1, size[0] * size[1] // IMAGE_PIXELS_PER_TOKEN)


def estimate_tokens(source_dir: Path, bundle: EvidenceBundle, variant: Variant, images: bool) -> int:
    """Rough input tokens for one request: prompt characters / 4 plus each attached image."""
    pairs = staged_views(bundle, variant)
    staged = bundle.model_copy(update={"views": [view for _, view in pairs]})
    text = len(PROMPT_TEMPLATE.read_text(encoding="utf-8")) + len(package_text(staged, variant.reason))
    tokens = text // TEXT_CHARS_PER_TOKEN
    if images:
        tokens += sum(image_tokens(source_dir / source) for source, _ in pairs)
    return tokens


# --- run -------------------------------------------------------------------------------------


@dataclass
class Job:
    source_dir: Path
    bundle: EvidenceBundle
    variant: Variant
    cell_dir: Path
    source_bundle: str
    action: Literal["send", "kept", "skip_unsupported"]


def variants_for(names: Optional[Sequence[str]], images: bool) -> list[Variant]:
    """The selected variants; only ``iqms`` when the adapter sends no images."""
    selected = [v for v in VARIANTS if names is None or v.name in names]
    if not images:
        dropped = [v.name for v in selected if v.view_set != "iqms"]
        if dropped:
            LOG.warning("the adapter sends no images; skipping variants %s", ", ".join(dropped))
        selected = [v for v in selected if v.view_set == "iqms"]
    return selected


def is_done(cell_dir: Path, bundle: EvidenceBundle) -> bool:
    """True when the cell already holds a final result: a schema-valid reply, or the skip of an
    unsupported bundle. An error, an invalid reply or an unreadable file is resent."""
    if not (cell_dir / FEEDBACK_FILE).exists():
        return False
    try:
        result = load_feedback(cell_dir)
    except (OSError, ValueError):
        return False
    if bundle.support == "unsupported":
        return result.status == "skipped_unsupported"
    return result.status == "ok" and result.schema_valid


def _inside(path: Path, folder: Path) -> bool:
    path, folder = path.resolve(), folder.resolve()
    return path == folder or folder in path.parents


def plan(root: Path, out_dir: Path, key: str, variants: Sequence[Variant], overwrite: bool = False) -> tuple[list[Job], list[Path]]:
    """Every (bundle, variant) job under ``root``, and the bundle folders whose ``bundle.json`` is unreadable.

    Bundles under ``out_dir`` are staged cells, not sources, and are skipped.
    """
    jobs, unreadable = [], []
    for source_dir in find_bundles(root):
        if _inside(source_dir, out_dir):
            continue
        try:
            bundle = load_bundle(source_dir)
        except Exception as err:  # noqa: BLE001 - one bad bundle must not stop the run
            LOG.error("%s: %s: %s", source_dir, type(err).__name__, err)
            unreadable.append(source_dir)
            continue
        source_bundle = source_dir.relative_to(root).as_posix()
        for variant in variants:
            cell_dir = out_dir / key / variant.name / source_bundle
            if not overwrite and is_done(cell_dir, bundle):
                action = "kept"
            elif bundle.support == "unsupported":
                action = "skip_unsupported"
            else:
                action = "send"
            jobs.append(Job(source_dir, bundle, variant, cell_dir, source_bundle, action))
    return jobs, unreadable


def dry_run_summary(jobs: Sequence[Job], images: bool) -> dict[str, int]:
    """Request count and input-token estimate for the jobs that would be sent."""
    counts = Counter(job.action for job in jobs)
    tokens = sum(estimate_tokens(j.source_dir, j.bundle, j.variant, images) for j in jobs if j.action == "send")
    return {
        "bundles": len({job.source_dir for job in jobs}),
        "variants": len({job.variant.name for job in jobs}),
        "requests": counts["send"],
        "kept": counts["kept"],
        "skipped_unsupported": counts["skip_unsupported"],
        "input_tokens_estimate": tokens,
    }


def run_job(job: Job, adapter: ModelAdapter) -> str:
    """Stage one cell folder and write its ``feedback.json``; return the result status.

    An earlier ``feedback.json`` is removed first, so a failed restage never leaves an old result
    beside new staging. A view that fails to copy is stored as an ``error`` result.
    """
    (job.cell_dir / FEEDBACK_FILE).unlink(missing_ok=True)
    try:
        stage(job.source_dir, job.bundle, job.variant, job.cell_dir, job.source_bundle)
    except OSError as err:
        result = error_result(
            job.bundle,
            f"staging failed: {type(err).__name__}: {err}",
            adapter=adapter.name,
            model_id=adapter.model_id,
            settings=adapter.settings,
            endpoint=adapter.endpoint,
        )
    else:
        result = adapter.send(job.cell_dir)
    write_feedback(job.cell_dir, result)
    return result.status


def run(jobs: Sequence[Job], adapter: ModelAdapter) -> Counter:
    """Run every job that is not kept; return a count of outcomes (``failed`` when staging or writing fails)."""
    counts: Counter = Counter()
    for job in jobs:
        if job.action == "kept":
            counts["kept"] += 1
            continue
        try:
            outcome = run_job(job, adapter)
        except Exception as err:  # noqa: BLE001 - one bad cell must not stop the run
            LOG.error("%s: %s: %s", job.cell_dir, type(err).__name__, err)
            outcome = "failed"
        LOG.info("%s: %s", job.cell_dir, outcome)
        counts[outcome] += 1
    return counts


# --- collect ---------------------------------------------------------------------------------


def load_labels(path: Path) -> dict[str, tuple[str, str]]:
    """``bids_name -> (label, original_label)`` from a TSV with columns ``bids_name``, ``label`` and
    optionally ``original_label``. Labels must be ``pass``, ``fail`` or ``uncertain``."""
    labels = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = {"bids_name", "label"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            name = (row.get("bids_name") or "").strip()
            label = (row.get("label") or "").strip()
            if not name and not label:
                continue  # a blank line or a line of tabs
            if not name:
                raise ValueError(f"{path}:{line}: empty bids_name")
            if label not in LABELS:
                raise ValueError(f"{path}:{line}: label '{label}' is not one of {LABELS}")
            if name in labels:
                raise ValueError(f"{path}:{line}: duplicate bids_name '{name}'")
            labels[name] = (label, (row.get("original_label") or "").strip())
    return labels


def _flag(value: Optional[bool]) -> str:
    return "" if value is None else str(int(value))


def control_confirmed(flagged: Sequence[str], control_rules: Sequence[str]) -> Optional[bool]:
    """True when the model flagged a metric that one of the control views' rules listens to.

    None when the scan has no control view. Rules without metrics (the mask overlay) never confirm.
    """
    if not control_rules:
        return None
    patterns = [p for rule in FLAG_RULES if rule.name in control_rules for p in rule.metrics]
    return any(fnmatchcase(name, pattern) for name in flagged for pattern in patterns)


def collect_row(cell_dir: Path, out_dir: Path, labels: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """One TSV row for a cell folder. A missing or unreadable ``feedback.json`` gives status ``missing``."""
    info = json.loads((cell_dir / CELL_FILE).read_text(encoding="utf-8"))
    bundle = load_bundle(cell_dir)
    key, variant = cell_dir.relative_to(out_dir).parts[:2]
    result: Optional[FeedbackResult] = None
    error = ""
    if (cell_dir / FEEDBACK_FILE).exists():
        try:
            result = load_feedback(cell_dir)
        except (OSError, ValueError) as err:
            error = f"unreadable {FEEDBACK_FILE}: {err}"
    feedback = result.feedback if result is not None else None
    label, original = labels.get(bundle.bids_name, ("", ""))
    control_rules = info.get("control_rules", [])
    row = {
        "participant_id": bundle.participant_id,
        "session_id": bundle.session_id,
        "bids_name": bundle.bids_name,
        "suffix": bundle.suffix,
        "support": bundle.support,
        "source_bundle": info["source_bundle"],
        "cell_id": f"{key}/{variant}",
        "adapter": result.adapter if result else "",
        "model_id": (result.model_id or "") if result else "",
        "variant": info["variant"],
        "view_set": info["view_set"],
        "reason": info["reason"],
        "n_views": str(len(bundle.views)),
        "control_scan": _flag(bool(info.get("control_scan"))),
        "control_rules": ",".join(control_rules),
        "targeted_rules": ",".join(info.get("targeted_rules", [])),
        "prompt_hash": (result.prompt_hash or "") if result else "",
        "status": result.status if result else "missing",
        "schema_valid": _flag(result.schema_valid) if result and result.status == "ok" else "",
        "consistency_valid": _flag(not result.consistency_errors) if result is not None and feedback is not None else "",
        "decision": feedback.decision if feedback else "",
        "confidence": feedback.confidence if feedback else "",
        "flagged_metrics": ",".join(feedback.flagged_metrics) if feedback else "",
        "control_confirmed": _flag(control_confirmed(feedback.flagged_metrics, control_rules)) if feedback else "",
        "label": label,
        "original_label": original,
        "agreement": _flag(feedback.decision == label) if feedback and label else "",
        "error": (result.error or "") if result else error,
    }
    return row


def collect(out_dir: Path, labels: Optional[Mapping[str, tuple[str, str]]] = None) -> list[dict[str, str]]:
    """One row per cell folder under ``out_dir``, sorted by source bundle and cell."""
    rows = []
    for cell_file in sorted(Path(out_dir).rglob(CELL_FILE)):
        try:
            rows.append(collect_row(cell_file.parent, out_dir, labels or {}))
        except Exception as err:  # noqa: BLE001 - a broken cell folder is reported, not fatal
            LOG.error("%s: %s: %s", cell_file.parent, type(err).__name__, err)
    return sorted(rows, key=lambda r: (r["source_bundle"], r["cell_id"]))


def write_results(path: Path, rows: Sequence[Mapping[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


# --- CLI -------------------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run model feedback over every bundle under each view variant.")
    parser.add_argument("bundle_root", type=Path, nargs="?", help="folder searched recursively for bundle.json files")
    parser.add_argument("--out_dir", type=Path, required=True, help="folder for cell folders and the results TSV")
    add_adapter_args(parser, required=False)
    parser.add_argument("--variants", nargs="+", choices=VARIANT_NAMES, help="variants to run; default all")
    parser.add_argument("--dry_run", action="store_true", help="print the request count and token estimate; send nothing")
    parser.add_argument("--overwrite", action="store_true", help="resend cells that already have feedback.json")
    parser.add_argument("--collect_only", action="store_true", help="only collect existing cell folders into the TSV")
    parser.add_argument("--labels", type=Path, help="TSV of bids_name, label (pass/fail/uncertain), original_label")
    parser.add_argument("--results", type=Path, help=f"results TSV; default OUT_DIR/{RESULTS_FILE}")
    args = parser.parse_args(argv)
    if not args.collect_only:
        if args.bundle_root is None:
            parser.error("bundle_root is required unless --collect_only is given")
        if args.adapter is None:
            parser.error("--adapter is required unless --collect_only is given")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        labels = load_labels(args.labels) if args.labels else {}
    except (OSError, ValueError) as err:
        LOG.error("%s", err)
        return 2
    unreadable: list[Path] = []
    if not args.collect_only:
        if not args.bundle_root.is_dir():
            LOG.error("not a folder: %s", args.bundle_root)
            return 2
        images = not args.iqms_only
        key = model_key(args.adapter, resolve_model_id(args))
        jobs, unreadable = plan(args.bundle_root, args.out_dir, key, variants_for(args.variants, images), overwrite=args.overwrite)
        if args.dry_run:
            summary = dry_run_summary(jobs, images)
            for name, value in summary.items():
                print(f"{name}: {value}")
            return 1 if unreadable else 0
        try:
            adapter = make_adapter(args)
        except (DataUseError, ValueError, ImportError) as err:
            LOG.error("%s", err)
            return 2
        counts = run(jobs, adapter)
        LOG.info("done: %s", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no jobs")
        if counts["failed"]:
            unreadable.append(args.out_dir)
    rows = collect(args.out_dir, labels)
    path = write_results(args.results or args.out_dir / RESULTS_FILE, rows)
    LOG.info("%d rows written to %s", len(rows), path)
    return 1 if unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
