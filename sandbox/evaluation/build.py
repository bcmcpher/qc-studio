"""Export evidence bundles for an MR-ART sample with the export CLI.

Each MR-ART acquisition is its own QC task in ``mrart_qc.json`` (``anat_standard``,
``anat_headmotion1``, ``anat_headmotion2``), since the export writes one bundle per participant,
session and task. For each task this writes the sampled participants to
``OUT/participants_<task>.tsv`` and runs the export into ``OUT/<task>/``. Views are drawn from
the raw T1w, as MR-ART has no preprocessed images; IQMs come from MRIQC's ``group_T1w.tsv``.

Usage (from the repo root)::

    .venv/bin/python sandbox/evaluation/build.py --data_dir ~/data/mrart --sample SAMPLE/sample.tsv --out_dir BUNDLES
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence

for _path in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2] / "ui"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation.download import inside_repo  # noqa: E402
from evaluation.sample import bids_entity  # noqa: E402
from evidence_bundle import export  # noqa: E402

QC_JSON = Path(__file__).with_name("mrart_qc.json")
PIPELINE = "mriqc"


def task_of(bids_name: str) -> str:
    return f"anat_{bids_entity(bids_name, 'acq')}"


def participants_by_task(sample: Path) -> dict[str, list[str]]:
    """Sampled participants per QC task, sorted."""
    tasks: dict[str, set[str]] = defaultdict(set)
    with open(sample, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            tasks[task_of(row["bids_name"])].add(row["participant_id"])
    return {task: sorted(pids) for task, pids in sorted(tasks.items())}


def build(data_dir: Path, sample: Path, out_dir: Path, stats_config: Optional[str] = None) -> int:
    """Run the export once per task; return the number of tasks whose export wrote no bundle."""
    failed = 0
    known = set(export.list_qc_tasks_from_json(QC_JSON))
    for task, pids in participants_by_task(sample).items():
        if task not in known:
            print(f"{task}: not a task in {QC_JSON.name}; {len(pids)} participants skipped", file=sys.stderr)
            failed += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        participants = out_dir / f"participants_{task}.tsv"
        participants.write_text("participant_id\n" + "".join(f"{pid}\n" for pid in pids), encoding="utf-8")
        argv = [
            "--dataset_dir",
            str(data_dir),
            "--participant_list",
            str(participants),
            "--qc_json",
            str(QC_JSON),
            "--qc_task",
            task,
            "--qc_pipeline",
            PIPELINE,
            "--out_dir",
            str(out_dir / task),
        ]
        if stats_config:
            argv += ["--stats_config", stats_config]
        print(f"{task}: {len(pids)} participants")
        failed += export.main(argv) != 0
    return failed


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export evidence bundles for an MR-ART sample.")
    parser.add_argument("--data_dir", type=Path, required=True, help="folder download.py wrote")
    parser.add_argument("--sample", type=Path, required=True, help="sample TSV from sample.py")
    parser.add_argument("--out_dir", type=Path, required=True, help="bundle folder; must be outside the repository")
    parser.add_argument("--stats_config", help="StatsConfig JSON passed to the export")
    args = parser.parse_args(argv)
    if inside_repo(args.out_dir):
        print(f"--out_dir {args.out_dir} is inside the repository; bundles hold images, choose a folder outside it", file=sys.stderr)
        return 2
    return 1 if build(args.data_dir.expanduser(), args.sample, args.out_dir.expanduser(), args.stats_config) else 0


if __name__ == "__main__":
    sys.exit(main())
