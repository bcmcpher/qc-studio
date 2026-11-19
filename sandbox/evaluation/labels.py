"""Map MR-ART artefact scores to the evaluation labels ``pass``, ``fail`` and ``uncertain``.

MR-ART (``derivatives/scores.tsv``, columns ``bids_name`` and ``score``) gives each scan one
neuroradiologist's score of its use for clinical diagnosis:

=====  ===============================================  ============
Score  MR-ART meaning                                   Label
=====  ===============================================  ============
1      Good quality image                               ``pass``
2      Medium quality image                             ``uncertain``
3      Bad quality image (unusable for diagnostic use)  ``fail``
=====  ===============================================  ============

Score 2 is ``uncertain``, not ``pass`` or ``fail``: the evaluation reports agreement both with
``uncertain`` as a class and without it, so the mapping does not decide where medium scans go.
The original score is kept as ``original_label``.

Usage (from the repo root)::

    .venv/bin/python sandbox/evaluation/labels.py DATA_DIR/derivatives/scores.tsv --out labels.tsv
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Optional, Sequence

MRART_LABELS = {"1": "pass", "2": "uncertain", "3": "fail"}
LABEL_FIELDS = ("bids_name", "participant_id", "label", "original_label")


def participant_of(bids_name: str) -> str:
    return bids_name.split("_", 1)[0]


def map_scores(path: Path) -> list[dict[str, str]]:
    """One label row per scored scan, sorted by BIDS name. An unknown score is an error."""
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = {"bids_name", "score"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            name, score = (row.get("bids_name") or "").strip(), (row.get("score") or "").strip()
            if not (name or score):
                continue
            if score not in MRART_LABELS:
                raise ValueError(f"{path}:{line}: score '{score}' is not one of {sorted(MRART_LABELS)}")
            rows.append({"bids_name": name, "participant_id": participant_of(name), "label": MRART_LABELS[score], "original_label": score})
    names = [r["bids_name"] for r in rows]
    if len(set(names)) != len(names):
        raise ValueError(f"{path}: duplicate bids_name")
    return sorted(rows, key=lambda r: r["bids_name"])


def write_tsv(path: Path, rows: Sequence[dict[str, str]], fields: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Map MR-ART scores to pass / uncertain / fail.")
    parser.add_argument("scores", type=Path, help="MR-ART derivatives/scores.tsv")
    parser.add_argument("--out", type=Path, required=True, help="labels TSV to write")
    args = parser.parse_args(argv)
    try:
        rows = map_scores(args.scores)
    except (OSError, ValueError) as err:
        print(err, file=sys.stderr)
        return 2
    write_tsv(args.out, rows, LABEL_FIELDS)
    print(f"{len(rows)} labels written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
