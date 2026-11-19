"""Draw a stratified, seeded sample of labelled scans for the evaluation.

Strata are the label and, by default, the BIDS ``acq`` entity (MR-ART's standard and two
head-motion acquisitions). Each stratum gives ``--n_per_stratum`` scans, or all it has. A
fraction of the sampled ``pass`` scans is marked as control scans: they are exported with
targeted views in control mode, to measure false confirmation.

Writes to ``--out_dir``:

- ``sample.tsv``: ``bids_name``, ``participant_id``, ``label``, ``original_label``,
  ``stratum``, ``control``. It is also the ``--labels`` file of ``run_eval.py``.
- ``sample.json``: seed, options, the hash of the labels file, and per stratum the scans
  available and sampled. The seed goes to ``report.py --seed``.

Usage (from the repo root)::

    .venv/bin/python sandbox/evaluation/sample.py labels.tsv --out_dir SAMPLE --n_per_stratum 20 --seed 20261119
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence

for _path in (Path(__file__).resolve().parents[1],):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from evaluation.labels import write_tsv  # noqa: E402

SAMPLE_FIELDS = ("bids_name", "participant_id", "label", "original_label", "stratum", "control")
SAMPLE_FILE = "sample.tsv"
MANIFEST_FILE = "sample.json"
LABELS = ("pass", "fail", "uncertain")


def bids_entity(bids_name: str, key: str) -> str:
    """The value of a BIDS entity in a name (``acq`` in ``sub-1_acq-standard_T1w``), or ``""``."""
    for part in bids_name.split("_"):
        if part.startswith(f"{key}-"):
            return part[len(key) + 1 :]
    return ""


def load_label_rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = {"bids_name", "label"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        rows = [dict(row) for row in reader if (row.get("bids_name") or "").strip()]
    for row in rows:
        if row["label"] not in LABELS:
            raise ValueError(f"{path}: label '{row['label']}' of {row['bids_name']} is not one of {LABELS}")
    return rows


def stratum_of(row: dict[str, str], strata: Sequence[str]) -> str:
    return "|".join(row["label"] if key == "label" else f"{key}-{bids_entity(row['bids_name'], key)}" for key in strata)


def draw(
    rows: Sequence[dict[str, str]], n_per_stratum: int, seed: int, strata: Sequence[str] = ("label", "acq"), control_fraction: float = 0.5
) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    """The sampled rows (sorted by BIDS name) and, per stratum, the scans available and sampled.

    The same rows, options and seed always give the same sample.
    """
    rng = random.Random(seed)
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["bids_name"]):
        groups[stratum_of(row, strata)].append(row)
    sampled, counts = [], {}
    for stratum in sorted(groups):
        members = groups[stratum]
        chosen = rng.sample(members, min(n_per_stratum, len(members)))
        counts[stratum] = {"available": len(members), "sampled": len(chosen)}
        sampled += [{**row, "participant_id": row.get("participant_id") or row["bids_name"].split("_", 1)[0], "stratum": stratum} for row in chosen]
    clean = sorted((r for r in sampled if r["label"] == "pass"), key=lambda r: r["bids_name"])
    controls = {r["bids_name"] for r in rng.sample(clean, round(control_fraction * len(clean)))}
    for row in sampled:
        row["control"] = "1" if row["bids_name"] in controls else "0"
    return sorted(sampled, key=lambda r: r["bids_name"]), counts


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Draw a stratified, seeded sample of labelled scans.")
    parser.add_argument("labels", type=Path, help="labels TSV (bids_name, label, original_label), e.g. from labels.py")
    parser.add_argument("--out_dir", type=Path, required=True)
    parser.add_argument("--n_per_stratum", type=int, required=True, help="scans per stratum; a smaller stratum gives all")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--strata", nargs="+", default=["label", "acq"], help="'label' and BIDS entities; default label acq")
    parser.add_argument("--control_fraction", type=float, default=0.5, help="share of sampled pass scans made control scans")
    args = parser.parse_args(argv)
    if args.n_per_stratum < 1 or not 0 <= args.control_fraction <= 1:
        parser.error("--n_per_stratum must be at least 1 and --control_fraction between 0 and 1")
    try:
        rows = load_label_rows(args.labels)
    except (OSError, ValueError) as err:
        print(err, file=sys.stderr)
        return 2
    sampled, counts = draw(rows, args.n_per_stratum, args.seed, args.strata, args.control_fraction)
    write_tsv(args.out_dir / SAMPLE_FILE, sampled, SAMPLE_FIELDS)
    manifest = {
        "seed": args.seed,
        "n_per_stratum": args.n_per_stratum,
        "strata": args.strata,
        "control_fraction": args.control_fraction,
        "labels_file": args.labels.name,
        "labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest(),
        "n": len(sampled),
        "n_control": sum(r["control"] == "1" for r in sampled),
        "per_stratum": counts,
    }
    (args.out_dir / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{len(sampled)} scans ({manifest['n_control']} control) written to {args.out_dir / SAMPLE_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
