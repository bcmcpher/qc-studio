"""Tests for the evidence bundle export CLI, on a copy of ``sample_data/``.

No sample subject has both MRIQC IQMs and an anatomical image, so the fixture adds synthetic
raw T1w images for the CMH subjects. sub-ED01's fMRIPrep files are linked, not copied, and get
an IQM row borrowed from a CMH scan.
"""

import json
import os
import shutil
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
import pytest

from evidence_bundle import export
from evidence_bundle.export import main, scan_bids_name, template_counterpart
from evidence_bundle.models import EvidenceBundle
from utils import reference_data

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "sample_data"
QC_JSON = REPO / "pipelines/fmriprep/qc.json"
ED01_ANAT = "derivatives/fmriprep/23.1.3/output/sub-ED01/ses-01/anat"
SHAPE = (40, 48, 36)

IDENTIFYING_FIELDS = ("DeviceSerialNumber", "InstitutionName", "InstitutionAddress", "StationName", "AcquisitionTime", "XNATAccessionID")


def _head(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    grid = np.indices(SHAPE).astype(float)
    centre = [(s - 1) / 2 for s in SHAPE]
    inside = sum(((g - c) / (0.4 * s)) ** 2 for g, c, s in zip(grid, centre, SHAPE)) <= 1
    return (rng.normal(5, 1, SHAPE) + inside * 100).astype(np.float32)


def _scans() -> list[tuple[str, str]]:
    names = pd.read_csv(SAMPLE / "derivatives/mriqc/group_T1w.tsv", sep="\t")["bids_name"]
    return [(n.split("_")[0], n.split("_")[1]) for n in names]


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    """A partial copy of ``sample_data/`` with synthetic CMH T1w images and a reference table."""
    ds = tmp_path / "ds"
    shutil.copytree(SAMPLE / "derivatives/mriqc", ds / "derivatives/mriqc")
    for seed, (pid, sid) in enumerate(_scans()):
        anat = ds / "bids" / pid / sid / "anat"
        anat.mkdir(parents=True)
        nib.save(nib.Nifti1Image(_head(seed), np.eye(4)), str(anat / f"{pid}_{sid}_run-1_T1w.nii.gz"))
    (ds / ED01_ANAT).mkdir(parents=True)
    for source in (SAMPLE / ED01_ANAT).glob("*.nii.gz"):
        os.symlink(source, ds / ED01_ANAT / source.name)

    cache = tmp_path / "reference_cache"
    cache.mkdir()
    rng = np.random.default_rng(0)
    group = pd.read_csv(ds / "derivatives/mriqc/group_T1w.tsv", sep="\t")
    reference = pd.DataFrame({name: rng.normal(group[name].mean(), group[name].std() + 1e-6, 200) for name in ("cjv", "cnr", "efc", "snr_wm")})
    reference["Manufacturer"] = "GE"
    reference["MagneticFieldStrength"] = 3
    reference.to_parquet(cache / "T1w.parquet")
    monkeypatch.setattr(reference_data, "REFERENCE_CACHE_DIR", cache)
    monkeypatch.delenv("REFERENCE_DATA_URL", raising=False)
    return ds


def _participants(tmp_path: Path, *pids: str) -> Path:
    path = tmp_path / "participants.tsv"
    pd.DataFrame({"participant_id": list(pids)}).to_csv(path, sep="\t", index=False)
    return path


def _run(ds: Path, tmp_path: Path, *extra: str, pids=("sub-CMH0001", "sub-CMH0002", "sub-CMH0003"), qc_json=QC_JSON, qc_task="anat_wf_qc"):
    out = tmp_path / "out"
    code = main(
        [
            "--dataset_dir",
            str(ds),
            "--participant_list",
            str(_participants(tmp_path, *pids)),
            "--session_list",
            "ses-01,ses-02",
            "--qc_json",
            str(qc_json),
            "--qc_task",
            qc_task,
            "--qc_pipeline",
            "fmriprep",
            "--out_dir",
            str(out),
            *extra,
        ]
    )
    summary = pd.read_csv(out / "acquisition_summary.tsv", sep="\t", dtype=str, keep_default_na=False)
    return code, out, summary


def _bundle(out: Path, pid: str, sid: str, task="anat_wf_qc") -> EvidenceBundle:
    return EvidenceBundle.model_validate_json((out / pid / sid / "fmriprep" / task / "bundle.json").read_text())


def _qc_json(tmp_path: Path, task: dict) -> Path:
    path = tmp_path / "qc.json"
    path.write_text(json.dumps({"task": task}))
    return path


class TestNames:
    def test_derived_entities_removed(self):
        name = "sub-01_ses-01_run-1_space-MNI152NLin2009cAsym_res-2_desc-preproc_T1w.nii.gz"
        assert scan_bids_name(Path(name)) == "sub-01_ses-01_run-1_T1w"
        assert scan_bids_name(Path("sub-01_task-rest_run-2_bold.nii")) == "sub-01_task-rest_run-2_bold"

    def test_template_counterparts(self):
        anat = SAMPLE / ED01_ANAT
        image = template_counterpart(anat / "sub-ED01_ses-01_run-1_desc-preproc_T1w.nii.gz")
        assert image is not None and image.name == "sub-ED01_ses-01_run-1_space-MNI152NLin2009cAsym_res-2_desc-preproc_T1w.nii.gz"
        mask = template_counterpart(anat / "sub-ED01_ses-01_run-1_desc-brain_mask.nii.gz", like=image)
        assert mask is not None and mask.name == "sub-ED01_ses-01_run-1_space-MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz"
        assert template_counterpart(anat / "sub-ED01_ses-01_run-1_desc-ribbon_mask.nii.gz") is None


class TestExportSampleData:
    def test_every_scan_exported(self, dataset, tmp_path):
        code, out, summary = _run(dataset, tmp_path)
        assert code == 0
        assert len(summary) == 6 and set(summary["status"]) == {"ok"}
        for _, row in summary.iterrows():
            bundle = _bundle(out, row["participant_id"], row["session_id"])
            assert bundle.bids_name == row["bids_name"] == f"{row['participant_id']}_{row['session_id']}_run-1_T1w"
            assert (bundle.support, bundle.context_suffix) == ("supported", "T1w")
            assert bundle.acquisition.geometry.shape == SHAPE  # from the NIfTI header
            assert [v.path for v in bundle.views] == [f"views/core_{p}.png" for p in ("axial", "coronal", "sagittal")]
            assert all((out / row["bundle_dir"] / v.path).is_file() for v in bundle.views)
            assert (out / row["bundle_dir"] / "PACKAGE.md").read_text().startswith("# MRI QC Evidence Package")

    def test_small_project_has_no_project_percentiles(self, dataset, tmp_path):
        _, out, _ = _run(dataset, tmp_path)
        bundle = _bundle(out, "sub-CMH0001", "ses-01")
        assert bundle.project.note and "below the minimum of 10" in bundle.project.note
        assert all(m.project_percentile is None for m in bundle.metrics)

    def test_no_identifying_field_in_any_output(self, dataset, tmp_path):
        sidecar = json.loads((SAMPLE / "bids/sub-ED01/ses-01/anat/sub-ED01_ses-01_T1w.json").read_text())
        (dataset / "bids/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.json").write_text(json.dumps(sidecar))
        values = {str(sidecar[k]) for k in IDENTIFYING_FIELDS if k in sidecar}
        for path in (dataset / "derivatives/mriqc").rglob("*_T1w.json"):
            meta = json.loads(path.read_text()).get("bids_meta", {})
            values |= {str(meta[k]) for k in IDENTIFYING_FIELDS if k in meta}
        assert values
        _, out, _ = _run(dataset, tmp_path)
        texts = [p.read_text() for p in out.rglob("*") if p.suffix in (".json", ".md", ".tsv")]
        assert len(texts) == 13
        for text in texts:
            for needle in (*IDENTIFYING_FIELDS, *values):
                assert needle not in text

    def test_reference_and_stats_config(self, dataset, tmp_path):
        _, out, _ = _run(dataset, tmp_path, "--stats_config", '{"min_stratum_size": 3}')
        bundle = _bundle(out, "sub-CMH0001", "ses-01")
        assert bundle.stats_config.min_stratum_size == 3
        assert bundle.project.n >= 3 and any(m.project_percentile is not None for m in bundle.metrics)
        assert bundle.reference is not None and bundle.reference.n == 200
        assert bundle.reference.filters == {"MagneticFieldStrength": "3", "Manufacturer": "ge"}
        assert {m.name for m in bundle.metrics if m.reference_percentile is not None} == {"cjv", "cnr", "efc", "snr_wm"}

    def test_reference_unavailable_is_noted(self, dataset, tmp_path, monkeypatch):
        monkeypatch.setattr(reference_data, "REFERENCE_CACHE_DIR", tmp_path / "empty")
        _, out, summary = _run(dataset, tmp_path)
        assert set(summary["status"]) == {"ok"}
        note = _bundle(out, "sub-CMH0001", "ses-01").reference.note
        assert note and "REFERENCE_DATA_URL is not set" in note


class TestFailures:
    def test_unreadable_image_gives_bundle_without_views(self, dataset, tmp_path):
        (dataset / "bids/sub-CMH0002/ses-01/anat/sub-CMH0002_ses-01_run-1_T1w.nii.gz").write_bytes(b"not a nifti")
        code, out, summary = _run(dataset, tmp_path)
        assert code == 0
        row = summary.set_index(["participant_id", "session_id"]).loc[("sub-CMH0002", "ses-01")]
        assert row["status"] == "partial" and row["error"].startswith("no views:") and row["n_views"] == "0"
        assert "geometry from MRIQC" in row["notes"]
        bundle = _bundle(out, "sub-CMH0002", "ses-01")
        assert bundle.views == [] and bundle.acquisition.geometry.voxel_size is not None
        assert not (out / row["bundle_dir"] / "views").exists()
        assert (summary["status"] == "ok").sum() == 5

    def test_scan_without_iqms_gets_no_bundle(self, dataset, tmp_path):
        code, out, summary = _run(dataset, tmp_path, pids=("sub-CMH0001", "sub-NOPE"))
        assert code == 0
        missing = summary[summary["participant_id"] == "sub-NOPE"]
        assert set(missing["status"]) == {"error"} and all("no IQMs" in e for e in missing["error"])
        assert not (out / "sub-NOPE").exists()

    def test_no_bundle_exits_non_zero(self, dataset, tmp_path):
        code, _, summary = _run(dataset, tmp_path, pids=("sub-NOPE",))
        assert code == 1 and set(summary["status"]) == {"error"}

    def test_glob_matching_several_images_is_an_error(self, dataset, tmp_path):
        qc_json = _qc_json(tmp_path, {"base_mri_image_path": "bids/*/ses-01/anat/*_T1w.nii.gz", "iqm_path": ["derivatives/mriqc/group_T1w.tsv"]})
        code, _, summary = _run(dataset, tmp_path, pids=("sub-CMH0001",), qc_json=qc_json, qc_task="task")
        assert code == 1 and "matches 3 files" in summary["error"].iloc[0]

    def test_unknown_task_is_a_usage_error(self, dataset, tmp_path):
        assert main(["--dataset_dir", str(dataset), "--participant_list", str(_participants(tmp_path, "sub-CMH0001")),
                     "--qc_json", str(QC_JSON), "--qc_task", "nope", "--qc_pipeline", "fmriprep", "--out_dir", str(tmp_path / "out")]) == 2  # fmt: skip


class TestRaterQC:
    def test_latest_rating_with_facets_merged(self, dataset, tmp_path):
        status = tmp_path / "rater1_fmriprep_anat_wf_qc_qc_status.tsv"
        base = {"pipeline": "fmriprep", "qc_task": "anat_wf_qc", "participant_id": "sub-CMH0001", "session_id": "ses-01", "rater_id": "rater1"}
        pd.DataFrame(
            [
                {**base, "timestamp": "2026-01-01T10:00:00", "final_qc": "FAIL", "facet": "", "rating_value": "", "notes": "old"},
                {**base, "timestamp": "2026-01-02T10:00:00", "final_qc": "PASS", "facet": "motion", "rating_value": "2", "notes": "fine"},
                {**base, "timestamp": "2026-01-02T10:00:00", "final_qc": "PASS", "facet": "contrast", "rating_value": "3", "notes": "fine"},
            ]
        ).to_csv(status, sep="\t", index=False)
        _, out, _ = _run(dataset, tmp_path, "--qc_status", str(status))
        rater = _bundle(out, "sub-CMH0001", "ses-01").rater_qc
        assert rater is not None
        assert (rater.final_qc, rater.notes, rater.rater_id) == ("PASS", "fine", "rater1")
        assert rater.facets == {"motion": "2", "contrast": "3"}
        assert _bundle(out, "sub-CMH0002", "ses-01").rater_qc is None
        assert "- Final QC: PASS" in (out / "sub-CMH0001/ses-01/fmriprep/anat_wf_qc/PACKAGE.md").read_text()


class TestSupportTiers:
    @pytest.fixture
    def flair(self, dataset, tmp_path):
        tsv = dataset / "derivatives/mriqc/group_T1w.tsv"
        group = pd.read_csv(tsv, sep="\t")
        row = group.iloc[[0]].assign(bids_name="sub-CMH0001_ses-01_run-1_FLAIR")
        pd.concat([group, row]).to_csv(tsv, sep="\t", index=False)
        anat = dataset / "bids/sub-CMH0001/ses-01/anat"
        shutil.copy(anat / "sub-CMH0001_ses-01_run-1_T1w.nii.gz", anat / "sub-CMH0001_ses-01_run-1_FLAIR.nii.gz")
        return _qc_json(
            tmp_path,
            {
                "base_mri_image_path": "bids/[[NIPOPPY_BIDS_PARTICIPANT_ID]]/[[NIPOPPY_BIDS_SESSION_ID]]/anat/"
                "[[NIPOPPY_BIDS_PARTICIPANT_ID]]_[[NIPOPPY_BIDS_SESSION_ID]]_run-1_FLAIR.nii.gz",
                "iqm_path": ["derivatives/mriqc/group_T1w.tsv"],
            },
        )

    def test_flair_falls_back_to_t2w(self, dataset, tmp_path, flair):
        _, out, summary = _run(dataset, tmp_path, pids=("sub-CMH0001",), qc_json=flair, qc_task="task")
        bundle = _bundle(out, "sub-CMH0001", "ses-01", task="task")
        assert (bundle.suffix, bundle.support, bundle.context_suffix) == ("FLAIR", "fallback", "T2w")
        assert summary["support"].iloc[0] == "fallback"
        assert "Interpreted using T2w metric context" in (out / summary["bundle_dir"].iloc[0] / "PACKAGE.md").read_text()

    def test_contrast_map_replaces_default(self, dataset, tmp_path, flair):
        _, out, _ = _run(dataset, tmp_path, "--contrast_map", "{}", pids=("sub-CMH0001",), qc_json=flair, qc_task="task")
        bundle = _bundle(out, "sub-CMH0001", "ses-01", task="task")
        assert (bundle.support, bundle.context_suffix) == ("unsupported", None)
        cjv = next(m for m in bundle.metrics if m.name == "cjv")
        assert cjv.category != "uncategorized" and cjv.evidence_strength == "none"  # named from the anat base catalog


class TestTemplateSpace:
    def test_preproc_image_drawn_in_template_space_with_mask(self, dataset, tmp_path):
        tsv = dataset / "derivatives/mriqc/group_T1w.tsv"
        group = pd.read_csv(tsv, sep="\t")
        pd.concat([group, group.iloc[[0]].assign(bids_name="sub-ED01_ses-01_run-1_T1w")]).to_csv(tsv, sep="\t", index=False)
        prefix = f"{ED01_ANAT.replace('sub-ED01', '[[NIPOPPY_BIDS_PARTICIPANT_ID]]').replace('ses-01', '[[NIPOPPY_BIDS_SESSION_ID]]')}/"
        name = "[[NIPOPPY_BIDS_PARTICIPANT_ID]]_[[NIPOPPY_BIDS_SESSION_ID]]_run-1"
        qc_json = _qc_json(
            tmp_path,
            {
                "base_mri_image_path": f"{prefix}{name}_desc-preproc_T1w.nii.gz",
                "overlay_mri_image_path": f"{prefix}{name}_desc-brain_mask.nii.gz",
                "iqm_path": ["derivatives/mriqc/group_T1w.tsv"],
            },
        )
        _, out, summary = _run(dataset, tmp_path, pids=("sub-ED01",), qc_json=qc_json, qc_task="task")
        assert summary["status"].iloc[0] == "ok", summary["error"].iloc[0]
        bundle = _bundle(out, "sub-ED01", "ses-01", task="task")
        assert {v.placement for v in bundle.views} == {"mni"}
        assert [v.rule for v in bundle.views if v.kind == "targeted"] == ["mask_overlay"] * 3


def test_script_entry_point_runs(tmp_path):
    """``python ui/evidence_bundle/export.py`` resolves ui/constants.py, not evidence_bundle/constants.py."""
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(Path(export.__file__)), "--help"], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--contrast_map" in result.stdout and "--stats_config" in result.stdout
