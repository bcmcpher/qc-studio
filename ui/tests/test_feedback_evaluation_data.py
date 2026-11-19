"""Tests for the evaluation's data steps (download, labels, sample, build) and an end-to-end smoke
test on the repository's ``sample_data/``."""

import csv
import io
import json
import sys
from pathlib import Path

import pytest

SANDBOX_DIR = Path(__file__).resolve().parents[2] / "sandbox"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from model_adapters.base import ModelAdapter  # noqa: E402
from evaluation import build, download, labels, report, run_eval, sample  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SCORES = "bids_name\tscore\nsub-01_acq-standard_T1w\t1\nsub-01_acq-headmotion1_T1w\t2\nsub-01_acq-headmotion2_T1w\t3\n"


def _rows(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _labels(n_subjects: int) -> list[dict[str, str]]:
    """Three scans per subject: standard pass, headmotion1 uncertain, headmotion2 fail."""
    rows = []
    for i in range(n_subjects):
        for acq, label in (("standard", "pass"), ("headmotion1", "uncertain"), ("headmotion2", "fail")):
            rows.append({"bids_name": f"sub-{i:02d}_acq-{acq}_T1w", "label": label, "original_label": ""})
    return rows


class TestLabels:
    def test_mapping_keeps_score(self, tmp_path):
        path = tmp_path / "scores.tsv"
        path.write_text(SCORES + "\t\n")
        rows = {r["bids_name"]: r for r in labels.map_scores(path)}
        assert [rows[f"sub-01_acq-{a}_T1w"]["label"] for a in ("standard", "headmotion1", "headmotion2")] == ["pass", "uncertain", "fail"]
        assert rows["sub-01_acq-headmotion2_T1w"]["original_label"] == "3"
        assert rows["sub-01_acq-standard_T1w"]["participant_id"] == "sub-01"

    def test_labels_file_reads_in_run_eval(self, tmp_path):
        path = tmp_path / "scores.tsv"
        path.write_text(SCORES)
        assert labels.main([str(path), "--out", str(tmp_path / "labels.tsv")]) == 0
        assert run_eval.load_labels(tmp_path / "labels.tsv")["sub-01_acq-headmotion1_T1w"] == ("uncertain", "2")

    @pytest.mark.parametrize("bad", ["sub-01_acq-standard_T1w\t4\n", "sub-01_acq-standard_T1w\t1\n"])
    def test_bad_score_or_duplicate(self, tmp_path, bad):
        path = tmp_path / "scores.tsv"
        path.write_text(SCORES + bad)
        with pytest.raises(ValueError):
            labels.map_scores(path)


class TestSample:
    def test_strata_and_seed(self):
        rows = _labels(10)
        drawn, counts = sample.draw(rows, n_per_stratum=4, seed=3)
        assert counts == {s: {"available": 10, "sampled": 4} for s in ("fail|acq-headmotion2", "pass|acq-standard", "uncertain|acq-headmotion1")}
        assert drawn == sample.draw(rows, n_per_stratum=4, seed=3)[0]
        assert drawn != sample.draw(rows, n_per_stratum=4, seed=4)[0]
        assert {r["participant_id"] for r in drawn} <= {f"sub-{i:02d}" for i in range(10)}

    def test_small_stratum_gives_all(self):
        _, counts = sample.draw(_labels(2), n_per_stratum=5, seed=1)
        assert all(c == {"available": 2, "sampled": 2} for c in counts.values())

    def test_controls_are_pass_scans(self):
        drawn, _ = sample.draw(_labels(10), n_per_stratum=4, seed=3, control_fraction=0.5)
        controls = [r for r in drawn if r["control"] == "1"]
        assert len(controls) == 2 and {r["label"] for r in controls} == {"pass"}

    def test_cli_writes_sample_and_manifest(self, tmp_path):
        path = tmp_path / "labels.tsv"
        labels.write_tsv(path, _labels(6), ("bids_name", "label", "original_label"))
        assert sample.main([str(path), "--out_dir", str(tmp_path / "s"), "--n_per_stratum", "3", "--seed", "9"]) == 0
        manifest = json.loads((tmp_path / "s" / "sample.json").read_text())
        assert manifest["seed"] == 9 and manifest["n"] == 9 and len(manifest["labels_sha256"]) == 64
        assert list(_rows(tmp_path / "s" / "sample.tsv")[0]) == list(sample.SAMPLE_FIELDS)
        assert len(run_eval.load_labels(tmp_path / "s" / "sample.tsv")) == 9


LISTING = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{items}<IsTruncated>{truncated}</IsTruncated>{token}</ListBucketResult>"""


def _listing(keys, truncated=False, token=None):
    items = "".join(f"<Contents><Key>{k}</Key><Size>{s}</Size></Contents>" for k, s in keys)
    return LISTING.format(
        items=items, truncated=str(truncated).lower(), token=f"<NextContinuationToken>{token}</NextContinuationToken>" if token else ""
    )


class TestDownload:
    @pytest.mark.parametrize(
        "key, subjects, expected",
        [
            ("ds004173/participants.tsv", set(), "bids/participants.tsv"),
            ("ds004173/derivatives/scores.tsv", set(), "derivatives/scores.tsv"),
            ("ds004173/derivatives/mriqc-0.16.1/group_T1w.tsv", set(), "derivatives/mriqc/group_T1w.tsv"),
            ("ds004173/derivatives/mriqc-0.16.1/sub-01_acq-standard_T1w.html", None, None),
            ("ds004173/sub-01/anat/sub-01_acq-standard_T1w.nii.gz", set(), None),
            ("ds004173/sub-01/anat/sub-01_acq-standard_T1w.nii.gz", {"sub-01"}, "bids/sub-01/anat/sub-01_acq-standard_T1w.nii.gz"),
            ("ds004173/sub-01/anat/sub-01_acq-standard_T1w.json", None, "bids/sub-01/anat/sub-01_acq-standard_T1w.json"),
            ("ds004173/sub-01/sub-01_scans.tsv", {"sub-02"}, None),
            ("ds004173/.datalad/config", None, None),
        ],
    )
    def test_local_path(self, key, subjects, expected):
        result = download.local_path(key, subjects)
        assert (result.as_posix() if result else None) == expected

    def test_refuses_repo_folder(self, tmp_path):
        assert download.inside_repo(REPO / "data") and not download.inside_repo(tmp_path)
        assert download.main(["--data_dir", str(REPO / "mrart"), "--dry_run"]) == 2

    def test_listing_pages_and_fetch(self, tmp_path, monkeypatch):
        pages = [
            _listing([("ds004173/participants.tsv", 5)], truncated=True, token="t1"),
            _listing([("ds004173/sub-01/anat/sub-01_acq-standard_T1w.json", 2)]),
        ]
        bodies = {"participants.tsv": b"hello", "sub-01_acq-standard_T1w.json": b"{}"}
        seen = []

        def urlopen(url, timeout):
            seen.append(url)
            if "list-type" in url:
                return io.BytesIO(pages.pop(0).encode())
            return io.BytesIO(bodies[url.rsplit("/", 1)[1]])

        monkeypatch.setattr(download.urllib.request, "urlopen", urlopen)
        data = tmp_path / "data"
        assert download.main(["--data_dir", str(data), "--subjects", "all"]) == 0
        assert "continuation-token=t1" in seen[1]
        assert (data / "bids" / "participants.tsv").read_bytes() == b"hello"
        manifest = json.loads((data / "download.json").read_text())
        assert manifest["files"] == {"bids/participants.tsv": 5, "bids/sub-01/anat/sub-01_acq-standard_T1w.json": 2}
        # A file already present with the listed size is not fetched again.
        jobs = download.plan([download.Remote("ds004173/participants.tsv", 5)], data, set())
        assert jobs[0][2] is True

    def test_short_download_is_dropped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(download.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"abc"))
        target = tmp_path / "f.tsv"
        with pytest.raises(OSError, match="size"):
            download.fetch(download.Remote("ds004173/f.tsv", 10), target)
        assert not target.exists() and not list(tmp_path.iterdir())


class TestBuild:
    def test_one_export_per_acquisition(self, tmp_path, monkeypatch):
        path = tmp_path / "sample.tsv"
        rows = [
            {"bids_name": "sub-02_acq-standard_T1w", "participant_id": "sub-02"},
            {"bids_name": "sub-01_acq-standard_T1w", "participant_id": "sub-01"},
            {"bids_name": "sub-01_acq-headmotion2_T1w", "participant_id": "sub-01"},
        ]
        labels.write_tsv(path, rows, ("bids_name", "participant_id"))
        calls = []
        monkeypatch.setattr(build.export, "main", lambda argv: calls.append(argv) or 0)
        assert build.build(tmp_path / "data", path, tmp_path / "out") == 0
        tasks = [argv[argv.index("--qc_task") + 1] for argv in calls]
        assert tasks == ["anat_headmotion2", "anat_standard"]
        assert (tmp_path / "out" / "participants_anat_standard.tsv").read_text() == "participant_id\nsub-01\nsub-02\n"
        assert calls[1][calls[1].index("--out_dir") + 1] == str(tmp_path / "out" / "anat_standard")

    def test_refuses_repo_folder(self, tmp_path):
        assert build.main(["--data_dir", str(tmp_path), "--sample", str(tmp_path / "s.tsv"), "--out_dir", str(REPO / "bundles")]) == 2


class PassAdapter(ModelAdapter):
    name = "fake"

    def __init__(self):
        super().__init__("fake-1", acknowledge_data_use=True)

    def complete(self, prompt, images):
        reply = dict(decision="pass", confidence="low", summary="ok", reasons=["no flag"], flagged_metrics=[], recommended_followup=[])
        return json.dumps(reply)


def test_smoke_on_sample_data(tmp_path):
    """Export the repository's sample T1w scans, run every variant with a fake adapter, and report.

    The sample data has no raw T1w images, so the bundles are partial (IQMs only)."""
    from evidence_bundle import export

    participants = tmp_path / "participants.tsv"
    participants.write_text("participant_id\nsub-CMH0001\nsub-CMH0002\nsub-CMH0003\n")
    bundles = tmp_path / "bundles"
    argv = ["--dataset_dir", str(REPO / "sample_data"), "--participant_list", str(participants), "--session_list", "ses-01,ses-02"]
    argv += ["--qc_json", str(REPO / "pipelines/fmriprep/qc.json"), "--qc_task", "anat_wf_qc", "--qc_pipeline", "fmriprep", "--out_dir", str(bundles)]
    assert export.main(argv) == 0
    out = tmp_path / "eval"
    jobs, unreadable = run_eval.plan(bundles, out, run_eval.model_key("fake", "fake-1"), run_eval.VARIANTS)
    assert not unreadable and len(jobs) == 24
    assert run_eval.run(jobs, PassAdapter()) == {"ok": 24}
    labels_path = tmp_path / "labels.tsv"
    names = sorted({job.bundle.bids_name for job in jobs})
    labels_path.write_text("bids_name\tlabel\n" + "".join(f"{n}\t{'pass' if i % 2 else 'fail'}\n" for i, n in enumerate(names)))
    assert run_eval.main(["--collect_only", "--out_dir", str(out), "--labels", str(labels_path)]) == 0
    assert report.main([str(out / "results.tsv"), "--seed", "1"]) == 0
    text = (out / "report.md").read_text()
    assert "- **Sample:** 6 scans (6 labelled, 0 control scans)" in text
    assert "| 6 | 6 | 0 | 0 | 6/6 (100.0%) |" in text
