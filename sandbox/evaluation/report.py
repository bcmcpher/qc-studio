"""Evaluation report: summarise a ``run_eval.py`` results TSV as Markdown.

The report reads only the results TSV and, optionally, a TSV of per-rater labels. It needs no
images, bundles or model access, so a TSV copied from another host gives the same report.

For each cell (adapter, model and variant) it reports schema validity, consistency validity,
agreement with the labels with and without ``uncertain`` (with Cohen's kappa), and the
false-confirmation rate on control views. The same numbers are broken down by support tier
(``supported`` / ``fallback``) and contrast. Unsupported scans are never sent and are only
counted.

Usage (from the repo root)::

    .venv/bin/python sandbox/evaluation/report.py OUT/results.tsv --seed 20261119 \\
        --rater_labels rater_labels.tsv --out OUT/report.md
"""

import argparse
import csv
import hashlib
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

LOG = logging.getLogger("report")

LABELS = ("pass", "fail", "uncertain")
REPORTED_SUPPORT = ("supported", "fallback")
SENT_STATUSES = ("ok", "error")
REQUIRED_COLUMNS = frozenset(
    {
        "bids_name",
        "suffix",
        "support",
        "cell_id",
        "adapter",
        "model_id",
        "variant",
        "control_scan",
        "prompt_hash",
        "status",
        "schema_valid",
        "consistency_valid",
        "decision",
        "control_confirmed",
        "label",
    }
)
REPORT_FILE = "report.md"

Row = Mapping[str, str]


# --- input -----------------------------------------------------------------------------------


def load_results(path: Path) -> list[dict[str, str]]:
    """Rows of a results TSV written by ``run_eval.py``."""
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        return list(reader)


def load_rater_labels(path: Path) -> dict[str, dict[str, str]]:
    """``bids_name -> {rater: label}`` from a TSV with columns ``bids_name``, ``rater``, ``label``.

    Labels must be ``pass``, ``fail`` or ``uncertain`` (the mapped labels of task 1.3)."""
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = {"bids_name", "rater", "label"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            name, rater, label = ((row.get(k) or "").strip() for k in ("bids_name", "rater", "label"))
            if not (name or rater or label):
                continue  # a blank line or a line of tabs
            if not name or not rater:
                raise ValueError(f"{path}:{line}: empty bids_name or rater")
            if label not in LABELS:
                raise ValueError(f"{path}:{line}: label '{label}' is not one of {LABELS}")
            if rater in labels[name]:
                raise ValueError(f"{path}:{line}: duplicate label by '{rater}' for '{name}'")
            labels[name][rater] = label
    return dict(labels)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- statistics ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    """``k`` of ``n``; ``n == 0`` means the rate is undefined."""

    k: int
    n: int

    @property
    def value(self) -> Optional[float]:
        return self.k / self.n if self.n else None

    def __str__(self) -> str:
        return f"{self.k}/{self.n} ({100 * self.k / self.n:.1f}%)" if self.n else "–"


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> Optional[float]:
    """Cohen's kappa of two label sequences; None when empty or when chance agreement is 1."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[c] * second[c] for c in first) / n**2
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def _kappa_text(value: Optional[float]) -> str:
    return "–" if value is None else f"{value:.2f}"


@dataclass(frozen=True)
class Summary:
    rows: int
    sent: int
    errors: int
    missing: int
    schema_valid: Rate
    consistency_valid: Rate
    agreement: Rate
    kappa: Optional[float]
    agreement_binary: Rate
    kappa_binary: Optional[float]
    false_confirmation: Rate


def summarize(rows: Sequence[Row]) -> Summary:
    """Metrics over the rows of one group. Each denominator is defined in ``DEFINITIONS``."""
    sent = [r for r in rows if r["status"] in SENT_STATUSES]
    parsed = [r for r in rows if r["consistency_valid"] in ("0", "1")]
    labelled = [r for r in rows if r["decision"] and r["label"]]
    binary = [r for r in labelled if "uncertain" not in (r["decision"], r["label"])]
    controls = [r for r in rows if r["control_confirmed"] in ("0", "1")]
    return Summary(
        rows=len(rows),
        sent=len(sent),
        errors=sum(r["status"] == "error" for r in rows),
        missing=sum(r["status"] == "missing" for r in rows),
        schema_valid=Rate(sum(r["schema_valid"] == "1" for r in sent), len(sent)),
        consistency_valid=Rate(sum(r["consistency_valid"] == "1" for r in parsed), len(parsed)),
        agreement=Rate(sum(r["decision"] == r["label"] for r in labelled), len(labelled)),
        kappa=cohen_kappa([(r["decision"], r["label"]) for r in labelled]),
        agreement_binary=Rate(sum(r["decision"] == r["label"] for r in binary), len(binary)),
        kappa_binary=cohen_kappa([(r["decision"], r["label"]) for r in binary]),
        false_confirmation=Rate(sum(r["control_confirmed"] == "1" for r in controls), len(controls)),
    )


@dataclass(frozen=True)
class RaterPair:
    first: str
    second: str
    agreement: Rate
    kappa: Optional[float]
    agreement_binary: Rate
    kappa_binary: Optional[float]


def rater_agreement(labels: Mapping[str, Mapping[str, str]], scans: Iterable[str]) -> list[RaterPair]:
    """Pairwise agreement between raters on the scans they both labelled, within ``scans``."""
    scans = set(scans)
    raters = sorted({rater for name, by_rater in labels.items() if name in scans for rater in by_rater})
    pairs = []
    for first, second in combinations(raters, 2):
        shared = [
            (by_rater[first], by_rater[second]) for name, by_rater in labels.items() if name in scans and first in by_rater and second in by_rater
        ]
        binary = [(a, b) for a, b in shared if "uncertain" not in (a, b)]
        pairs.append(
            RaterPair(
                first,
                second,
                Rate(sum(a == b for a, b in shared), len(shared)),
                cohen_kappa(shared),
                Rate(sum(a == b for a, b in binary), len(binary)),
                cohen_kappa(binary),
            )
        )
    return pairs


def prompt_digest(hashes: Iterable[str]) -> str:
    """One hash over a cell's sorted, distinct prompt hashes: equal digests mean equal prompts."""
    joined = "\n".join(sorted({h for h in hashes if h}))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16] if joined else "–"


# --- Markdown --------------------------------------------------------------------------------


DEFINITIONS = """\
- **Sent:** rows with a result, status `ok` or `error`. An `error` is a staging, transport or
  refusal failure. Rows `missing` a `feedback.json` and unsupported scans are not sent.
- **Schema valid:** sent rows with a reply that parsed against the feedback schema.
- **Consistency valid:** schema-valid rows whose reply passed the consistency checks.
- **Agreement (3-class):** rows with a label and a decision where the decision equals the
  label; `uncertain` is a class.
- **Agreement (pass/fail):** the same, leaving out rows where the label or the decision is
  `uncertain`.
- **κ:** Cohen's kappa over the same rows; `–` when undefined.
- **False confirmation:** rows that show a control view where the model flagged a metric of
  that view's rule. Only variants with targeted views can show a control view.
- **Prompt digest:** a hash over the cell's distinct prompt hashes; two cells with the same
  digest sent the same prompts.
"""

METRIC_HEADER = (
    "Rows",
    "Sent",
    "Errors",
    "Missing",
    "Schema valid",
    "Consistency valid",
    "Agreement (3-class)",
    "κ",
    "Agreement (pass/fail)",
    "κ (pass/fail)",
    "False confirmation",
)


def _metric_cells(s: Summary) -> list[str]:
    return [
        str(s.rows),
        str(s.sent),
        str(s.errors),
        str(s.missing),
        str(s.schema_valid),
        str(s.consistency_valid),
        str(s.agreement),
        _kappa_text(s.kappa),
        str(s.agreement_binary),
        _kappa_text(s.kappa_binary),
        str(s.false_confirmation),
    ]


def _table(header: Sequence[str], body: Iterable[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |" for row in body]
    return lines


def _group(rows: Iterable[Row], *keys: str) -> dict[tuple[str, ...], list[Row]]:
    groups: dict[tuple[str, ...], list[Row]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in keys)].append(row)
    return dict(sorted(groups.items()))


def render_report(
    rows: Sequence[Row],
    *,
    source_name: str,
    source_sha256: str,
    seed: Optional[str] = None,
    rater_labels: Optional[Mapping[str, Mapping[str, str]]] = None,
) -> str:
    """The Markdown report for a results TSV's rows."""
    reported = [r for r in rows if r["support"] in REPORTED_SUPPORT]
    unsupported = {r["bids_name"] for r in rows if r["support"] not in REPORTED_SUPPORT}
    scans = {r["bids_name"] for r in reported}
    labelled = {r["bids_name"] for r in reported if r["label"]}
    controls = {r["bids_name"] for r in reported if r["control_scan"] == "1"}
    cells = _group(rows, "cell_id")

    lines = [
        "# Feedback evaluation report",
        "",
        f"- **Results:** `{source_name}` (sha256 `{source_sha256[:16]}`)",
        f"- **Seed:** {seed if seed else 'not recorded'}",
        f"- **Sample:** {len(scans)} scans ({len(labelled)} labelled, {len(controls)} control scans)",
        f"- **Unsupported scans:** {len(unsupported)} (never sent; left out of every table)",
        f"- **Cells:** {len(cells)}",
        "",
        "## Cells",
        "",
    ]
    cell_rows = []
    for (cell_id,), group in cells.items():
        adapters = sorted({r["adapter"] for r in group if r["adapter"]})
        models = sorted({r["model_id"] for r in group if r["model_id"]})
        hashes = {r["prompt_hash"] for r in group if r["prompt_hash"]}
        cell_rows.append(
            [
                cell_id,
                ", ".join(adapters) or "–",
                ", ".join(models) or "–",
                group[0]["variant"],
                str(len(hashes)),
                prompt_digest(hashes),
            ]
        )
    lines += _table(("Cell", "Adapter", "Model id", "Variant", "Prompt hashes", "Prompt digest"), cell_rows)

    lines += ["", "## Results per cell", "", "Supported and fallback scans together.", ""]
    lines += _table(
        ("Cell", *METRIC_HEADER),
        ([cell_id, *_metric_cells(summarize(group))] for (cell_id,), group in _group(reported, "cell_id").items()),
    )

    lines += ["", "## Results by support and contrast", ""]
    lines += _table(
        ("Cell", "Support", "Contrast", *METRIC_HEADER),
        (
            [cell_id, support, suffix, *_metric_cells(summarize(group))]
            for (cell_id, support, suffix), group in _group(reported, "cell_id", "support", "suffix").items()
        ),
    )

    lines += ["", "## Rater agreement", ""]
    pairs = rater_agreement(rater_labels, scans) if rater_labels else []
    if pairs:
        lines += ["Pairwise, on the sampled scans both raters labelled. It is the ceiling for model agreement.", ""]
        lines += _table(
            ("Rater", "Rater", "Agreement (3-class)", "κ", "Agreement (pass/fail)", "κ (pass/fail)"),
            ([p.first, p.second, str(p.agreement), _kappa_text(p.kappa), str(p.agreement_binary), _kappa_text(p.kappa_binary)] for p in pairs),
        )
    elif rater_labels:
        lines.append("Fewer than two raters labelled the sampled scans.")
    else:
        lines.append("No rater labels given (`--rater_labels`).")

    lines += ["", "## Definitions", "", DEFINITIONS.rstrip()]
    return "\n".join(lines) + "\n"


# --- CLI -------------------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a Markdown report from a run_eval.py results TSV.")
    parser.add_argument("results", type=Path, help="results TSV written by run_eval.py")
    parser.add_argument("--out", type=Path, help=f"report path; default {REPORT_FILE} beside the results TSV")
    parser.add_argument("--seed", help="seed of the scan sample, recorded in the report")
    parser.add_argument("--rater_labels", type=Path, help="TSV of bids_name, rater, label (pass/fail/uncertain)")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        rows = load_results(args.results)
        rater_labels = load_rater_labels(args.rater_labels) if args.rater_labels else None
    except (OSError, ValueError) as err:
        LOG.error("%s", err)
        return 2
    text = render_report(
        rows,
        source_name=args.results.name,
        source_sha256=file_sha256(args.results),
        seed=args.seed,
        rater_labels=rater_labels,
    )
    out = args.out or args.results.with_name(REPORT_FILE)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    LOG.info("report written to %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
