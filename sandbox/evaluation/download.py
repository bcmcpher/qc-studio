"""Download the MR-ART dataset (OpenNeuro ds004173) to a folder outside the repository.

MR-ART has T1w scans of 148 adults, each acquired three times (``acq-standard``,
``acq-headmotion1``, ``acq-headmotion2``), a neuroradiologist's artefact score per scan
(``derivatives/scores.tsv``), and MRIQC 0.16.1 IQMs (``derivatives/mriqc-0.16.1/group_T1w.tsv``).
Licence CC0; see ``README.md`` for the citation.

Files are fetched from OpenNeuro's public S3 bucket and laid out for the export CLI::

    DATA_DIR/bids/                       dataset_description.json, participants.tsv, README,
                                         sub-*/anat/*_T1w.nii.gz and .json, sub-*/*_scans.tsv
    DATA_DIR/derivatives/scores.tsv      artefact scores (bids_name, score)
    DATA_DIR/derivatives/mriqc/          group_T1w.tsv, dataset_description.json
    DATA_DIR/download.json               dataset version and the files fetched

Without ``--subjects`` or ``--sample`` only the metadata is fetched (under 1 MB). The T1w images
are about 11 MB each, about 4.8 GB for all 436 scans. A file already present with the listed
size is not fetched again.

Usage (from the repo root)::

    .venv/bin/python sandbox/evaluation/download.py --data_dir ~/data/mrart
    .venv/bin/python sandbox/evaluation/download.py --data_dir ~/data/mrart --sample SAMPLE/sample.tsv
    .venv/bin/python sandbox/evaluation/download.py --data_dir ~/data/mrart --subjects all --dry_run
"""

import argparse
import csv
import json
import logging
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

LOG = logging.getLogger("download")

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = "ds004173"
DATASET_DOI = "doi:10.18112/openneuro.ds004173.v1.0.2"
BUCKET_URL = "https://s3.amazonaws.com/openneuro.org"
MRIQC_DIR = "derivatives/mriqc-0.16.1"
TOP_FILES = ("dataset_description.json", "participants.tsv", "participants.json", "README", "CHANGES")
MANIFEST_FILE = "download.json"
TIMEOUT_S = 60
CHUNK = 1 << 20
_S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_SUBJECT_FILE = re.compile(r"(sub-[A-Za-z0-9]+)/(?:anat/\1_.*_T1w\.(?:nii\.gz|json)|\1_scans\.(?:tsv|json))")


@dataclass(frozen=True)
class Remote:
    key: str
    size: int


def list_keys(prefix: str = f"{DATASET}/") -> list[Remote]:
    """Every object under ``prefix`` in the bucket, through the paged S3 ListObjectsV2 API."""
    remotes, token = [], None
    while True:
        query = {"list-type": "2", "prefix": prefix}
        if token:
            query["continuation-token"] = token
        with urllib.request.urlopen(f"{BUCKET_URL}?{urllib.parse.urlencode(query)}", timeout=TIMEOUT_S) as response:
            root = ET.fromstring(response.read())
        for item in root.iter(f"{_S3}Contents"):
            remotes.append(Remote(item.findtext(f"{_S3}Key", ""), int(item.findtext(f"{_S3}Size", "0"))))
        if root.findtext(f"{_S3}IsTruncated") != "true":
            return remotes
        token = root.findtext(f"{_S3}NextContinuationToken")


def local_path(key: str, subjects: Optional[set[str]]) -> Optional[Path]:
    """Where a bucket key goes under the data folder, or None when it is not needed.

    ``subjects`` None means every subject; an empty set means metadata only.
    """
    rel = key.removeprefix(f"{DATASET}/")
    if rel in TOP_FILES:
        return Path("bids") / rel
    if rel == "derivatives/scores.tsv":
        return Path("derivatives/scores.tsv")
    if rel in (f"{MRIQC_DIR}/group_T1w.tsv", f"{MRIQC_DIR}/dataset_description.json"):
        return Path("derivatives/mriqc") / Path(rel).name
    match = _SUBJECT_FILE.fullmatch(rel)
    if match and (subjects is None or match.group(1) in subjects):
        return Path("bids") / rel
    return None


def inside_repo(path: Path) -> bool:
    path = path.expanduser().resolve()
    return path == REPO_ROOT or REPO_ROOT in path.parents


def fetch(remote: Remote, target: Path) -> None:
    """Download one object to ``target`` through a partial file, so a cut download is never kept."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    with urllib.request.urlopen(f"{BUCKET_URL}/{urllib.parse.quote(remote.key)}", timeout=TIMEOUT_S) as response:
        with open(partial, "wb") as handle:
            while chunk := response.read(CHUNK):
                handle.write(chunk)
    if partial.stat().st_size != remote.size:
        partial.unlink()
        raise OSError(f"{remote.key}: got a different size than the listed {remote.size} bytes")
    partial.replace(target)


def subjects_from_sample(path: Path) -> set[str]:
    """The participant ids in a ``sample.py`` sample TSV."""
    with open(path, newline="", encoding="utf-8") as handle:
        return {row["participant_id"] for row in csv.DictReader(handle, delimiter="\t") if row.get("participant_id")}


def plan(remotes: Iterable[Remote], data_dir: Path, subjects: Optional[set[str]]) -> list[tuple[Remote, Path, bool]]:
    """(remote, local path, already present) for every needed object."""
    jobs = []
    for remote in remotes:
        rel = local_path(remote.key, subjects)
        if rel is None:
            continue
        target = data_dir / rel
        jobs.append((remote, target, target.is_file() and target.stat().st_size == remote.size))
    return jobs


def write_manifest(data_dir: Path, jobs: Sequence[tuple[Remote, Path, bool]]) -> Path:
    manifest = data_dir / MANIFEST_FILE
    previous = json.loads(manifest.read_text(encoding="utf-8")).get("files", {}) if manifest.is_file() else {}
    files = {**previous, **{target.relative_to(data_dir).as_posix(): remote.size for remote, target, _ in jobs if target.is_file()}}
    payload = {"dataset": DATASET, "doi": DATASET_DOI, "source": BUCKET_URL, "files": dict(sorted(files.items()))}
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download MR-ART (OpenNeuro ds004173) outside the repository.")
    parser.add_argument("--data_dir", type=Path, required=True, help="destination folder; must be outside the repository")
    images = parser.add_mutually_exclusive_group()
    images.add_argument("--subjects", nargs="+", help="subjects whose T1w images to fetch, or 'all'")
    images.add_argument("--sample", type=Path, help="sample TSV from sample.py; fetch its subjects' images")
    parser.add_argument("--dry_run", action="store_true", help="print the file count and size; fetch nothing")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    data_dir = args.data_dir.expanduser()
    if inside_repo(data_dir):
        LOG.error("--data_dir %s is inside the repository %s; choose a folder outside it", data_dir, REPO_ROOT)
        return 2
    if args.subjects == ["all"]:
        subjects: Optional[set[str]] = None
    elif args.subjects:
        subjects = set(args.subjects)
    elif args.sample:
        subjects = subjects_from_sample(args.sample)
    else:
        subjects = set()
    try:
        jobs = plan(list_keys(), data_dir, subjects)
    except OSError as err:
        LOG.error("cannot list %s/%s: %s", BUCKET_URL, DATASET, err)
        return 1
    todo = [(remote, target) for remote, target, present in jobs if not present]
    size = sum(remote.size for remote, _ in todo)
    print(f"files: {len(jobs)}; to fetch: {len(todo)} ({size / 1e6:.1f} MB)")
    if args.dry_run:
        return 0
    failed = 0
    for remote, target in todo:
        try:
            fetch(remote, target)
        except OSError as err:
            LOG.error("%s: %s", remote.key, err)
            failed += 1
    LOG.info("manifest written to %s", write_manifest(data_dir, jobs))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
