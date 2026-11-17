"""Tests for evidence bundle acquisition metadata and statistics, on synthetic data."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from evidence_bundle.acquisition import acquisition_deviations, extract_acquisition, nifti_geometry, protocol_signature, round_to_step
from evidence_bundle.context import load_metric_context, resolve_context
from evidence_bundle.models import (
    AcquisitionMetadata,
    EvidenceBundle,
    ProtocolSignature,
    StatsConfig,
    context_category_for,
)
from evidence_bundle import stats as stats_module
from evidence_bundle.stats import (
    ScanInput,
    empirical_percentile,
    metric_flags,
    numeric_iqms,
    outlier_score,
    ReferenceTable,
    reference_subset,
    robust_z,
    scan_statistics,
    select_stratum,
    stratum_outlier_scores,
)
from utils import reference_data
from utils.reference_data import filter_reference_frame, filter_reference_iqm

REPO = Path(__file__).resolve().parents[2]
SAMPLE_MRIQC = REPO / "sample_data/derivatives/mriqc/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.json"
SAMPLE_BIDS = REPO / "sample_data/bids/sub-ED01/ses-01/anat"

CONFIG = StatsConfig()


def _signature(suffix="T1w", **kwargs) -> ProtocolSignature:
    fields: dict[str, Any] = dict(
        suffix=suffix,
        MRAcquisitionType="3D",
        MagneticFieldStrength=3.0,
        Manufacturer="siemens",
        RepetitionTime=2.3,
        EchoTime=0.0029,
        InversionTime=0.9,
        FlipAngle=9.0,
        VoxelSize=(1.0, 1.0, 1.0),
    )
    fields.update(kwargs)
    return ProtocolSignature(**fields)


def _iqms(rng: np.random.Generator) -> dict[str, float]:
    quality = rng.normal()
    return {
        "cjv": 0.45 + 0.03 * (0.8 * quality + 0.6 * rng.normal()),
        "cnr": 3.0 - 0.2 * (0.8 * quality + 0.6 * rng.normal()),
        "snr_wm": 15.0 - 1.0 * (0.8 * quality + 0.6 * rng.normal()),
        "efc": 0.5 + 0.02 * rng.normal(),
        "wm2max": 0.7 + 0.03 * rng.normal(),
        "size_x": 176.0,
    }


def _project(n: int, seed: int = 0, suffix: str = "T1w", **signature) -> list[ScanInput]:
    rng = np.random.default_rng(seed)
    return [ScanInput(suffix=suffix, signature=_signature(suffix, **signature), iqms=_iqms(rng)) for _ in range(n)]


def _metric(stats, name):
    return next(m for m in stats.metrics if m.name == name)


def _reference(n: int = 400, seed: int = 1, **columns) -> pd.DataFrame:
    """Synthetic reference table with the columns of the MRIQC Web API export."""
    rng = np.random.default_rng(seed)
    data = pd.DataFrame([_iqms(rng) for _ in range(n)])
    data["Manufacturer"] = "Siemens"
    data["MagneticFieldStrength"] = 3
    data["ManufacturersModelName"] = "Prisma"
    for axis in ("x", "y", "z"):
        data[f"spacing_{axis}"] = 1.0
    for name, values in columns.items():
        data[name] = values
    return data


# --- acquisition metadata ----------------------------------------------------------------


class TestExtractAcquisition:
    def test_sample_mriqc_json(self):
        mriqc = json.loads(SAMPLE_MRIQC.read_text())
        acquisition = extract_acquisition(mriqc)
        assert acquisition.scanner.Manufacturer == "GE"
        assert acquisition.scanner.MagneticFieldStrength == 3.0
        assert acquisition.sequence.EchoTime == pytest.approx(0.00292)
        assert acquisition.scanner.ReceiveCoilName is not None  # from CoilString
        assert acquisition.provenance.mriqc_version == mriqc["provenance"]["version"]
        assert acquisition.geometry.voxel_size is not None  # from spacing_* without an image

    def test_identifying_fields_dropped(self):
        mriqc = json.loads(SAMPLE_MRIQC.read_text())
        dumped = extract_acquisition(mriqc).model_dump_json()
        for field in ("DeviceSerialNumber", "InstitutionName", "AcquisitionTime", "StationName", "XNATAccessionID"):
            assert field in mriqc["bids_meta"]
            assert field not in dumped
        assert mriqc["bids_meta"]["InstitutionName"] not in dumped

    def test_sidecar_wins_over_bids_meta(self):
        acquisition = extract_acquisition({"bids_meta": {"EchoTime": 0.003}}, {"EchoTime": 0.004})
        assert acquisition.sequence.EchoTime == 0.004

    def test_missing_and_malformed_fields_are_null(self):
        acquisition = extract_acquisition(sidecar={"MagneticFieldStrength": "3T", "FlipAngle": "n/a"})
        assert acquisition.scanner.MagneticFieldStrength == 3.0
        assert acquisition.sequence.FlipAngle is None
        assert acquisition.sequence.RepetitionTime is None

    def test_geometry_from_nifti(self):
        nifti = SAMPLE_BIDS / "sub-ED01_ses-01_T1w.nii.gz"
        sidecar = json.loads((SAMPLE_BIDS / "sub-ED01_ses-01_T1w.json").read_text())
        acquisition = extract_acquisition(sidecar=sidecar, nifti_path=nifti)
        geometry = nifti_geometry(nifti)
        assert acquisition.geometry.shape == geometry.shape
        assert acquisition.geometry.voxel_size == geometry.voxel_size
        assert geometry.orientation is not None and len(geometry.orientation) == 3

    def test_lps_orientation_codes(self, tmp_path):
        import nibabel as nib

        affine = np.diag([-1.0, -1.0, 3.0, 1.0])
        path = tmp_path / "lps.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((4, 5, 6), dtype=np.int16), affine), str(path))
        geometry = nifti_geometry(path)
        assert geometry.orientation == ("L", "P", "S")
        assert geometry.voxel_size == (1.0, 1.0, 3.0)
        assert geometry.field_of_view == (4.0, 5.0, 18.0)


class TestExtractAcquisitionReview:
    def test_null_sidecar_value_keeps_bids_meta(self):
        acquisition = extract_acquisition({"bids_meta": {"EchoTime": 0.003, "FlipAngle": 9}}, {"EchoTime": None, "FlipAngle": "n/a"})
        assert acquisition.sequence.EchoTime == 0.003
        assert acquisition.sequence.FlipAngle == 9.0

    def test_multi_echo_list_does_not_replace_scalar(self):
        acquisition = extract_acquisition({"bids_meta": {"EchoTime": 0.003}}, {"EchoTime": [0.002, 0.004]})
        assert acquisition.sequence.EchoTime == 0.003

    def test_voxel_size_in_ras_order(self, tmp_path):
        import nibabel as nib

        # Sagittal storage: voxel axes i, j, k run along S, R, A (zooms 1.2, 1.0, 0.9).
        affine = np.array([[0, 1.0, 0, 0], [0, 0, 0.9, 0], [1.2, 0, 0, 0], [0, 0, 0, 1]])
        path = tmp_path / "sagittal.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((10, 20, 30), dtype=np.int16), affine), str(path))
        geometry = nifti_geometry(path)
        assert geometry.shape == (10, 20, 30)
        assert geometry.orientation == ("S", "R", "A")
        assert geometry.voxel_size == pytest.approx((1.0, 0.9, 1.2))
        assert geometry.field_of_view == pytest.approx((20.0, 27.0, 12.0))


class TestProtocolSignature:
    def test_rounding(self):
        acquisition = AcquisitionMetadata.from_sidecar(
            {
                "Manufacturer": "Siemens Healthineers",
                "MagneticFieldStrength": 3,
                "MRAcquisitionType": "3D",
                "RepetitionTime": 0.006952,
                "EchoTime": 0.00292,
                "InversionTime": 1.0649,
                "FlipAngle": 8.4,
            },
            geometry={"voxel_size": (0.9999, 1.04, 1.2)},
        )
        signature = protocol_signature("T1w", acquisition)
        assert signature.RepetitionTime == 0.007
        assert signature.EchoTime == 0.0029
        assert signature.InversionTime == 1.06
        assert signature.FlipAngle == 8.0
        assert signature.VoxelSize == (1.0, 1.0, 1.2)
        assert signature.Manufacturer == "siemens"

    @pytest.mark.parametrize("value,step,expected", [(0.74, 0.25, 0.75), (0.0371, 0.025, 0.025), (2.92e-3, 1e-4, 0.0029), (8.4, 1.0, 8.0)])
    def test_round_to_step(self, value, step, expected):
        assert round_to_step(value, step) == expected

    def test_short_trs_stay_apart(self):
        assert round_to_step(0.00695, 0.001) != round_to_step(0.0082, 0.001)

    def test_missing_fields_are_null(self):
        signature = protocol_signature("T1w", AcquisitionMetadata())
        assert signature.EchoTime is None and signature.Manufacturer is None and signature.VoxelSize is None


class TestAcquisitionCheck:
    def test_different_echo_time(self):
        signatures = [_signature(EchoTime=0.0029)] * 19 + [_signature(EchoTime=0.0035)]
        deviations = acquisition_deviations(signatures)
        assert all(not d for d in deviations[:19])
        (deviation,) = deviations[19]
        assert (deviation.field, deviation.value, deviation.expected) == ("EchoTime", 0.0035, 0.0029)
        assert deviation.share == pytest.approx(0.95)
        assert deviation.n == 20

    def test_within_rounding(self):
        def sig(tr):
            return protocol_signature("T1w", AcquisitionMetadata.from_sidecar({"RepetitionTime": tr}))

        assert acquisition_deviations([sig(2.3), sig(2.3002), sig(2.2999)]) == [[], [], []]

    def test_grouped_by_suffix_and_site(self):
        signatures = [_signature("T1w")] * 3 + [_signature("T2w", EchoTime=0.1)] * 3
        assert all(not d for d in acquisition_deviations(signatures))
        sites = ["A", "A", "A", "B", "B", "B"]
        signatures = [_signature()] * 3 + [_signature(RepetitionTime=2.0)] * 3
        assert all(not d for d in acquisition_deviations(signatures, sites))

    def test_tied_mode_has_no_deviation(self):
        signatures = [_signature(RepetitionTime=2.3), _signature(RepetitionTime=2.4)]
        assert acquisition_deviations(signatures) == [[], []]
        assert acquisition_deviations(list(reversed(signatures))) == [[], []]

    def test_missing_value_is_a_deviation(self):
        signatures = [_signature()] * 4 + [_signature(InversionTime=None)]
        (deviation,) = acquisition_deviations(signatures)[4]
        assert (deviation.field, deviation.value) == ("InversionTime", None)


# --- strata ------------------------------------------------------------------------------


class TestStrata:
    def test_off_protocol_scan_excluded(self):
        scans = _project(20)
        scans[5] = ScanInput("T1w", _signature(RepetitionTime=2.0), scans[5].iqms)
        members, context = select_stratum(0, scans, CONFIG)
        assert 5 not in members and len(members) == 18
        assert "RepetitionTime" in context.signature_fields
        assert any(d.field == "RepetitionTime" for d in acquisition_deviations([s.signature for s in scans])[5])

    def test_off_protocol_scan_falls_back(self):
        scans = _project(20)
        scans[5] = ScanInput("T1w", _signature(RepetitionTime=2.0), scans[5].iqms)
        members, context = select_stratum(5, scans, CONFIG)
        assert len(members) == 19
        assert "RepetitionTime" not in context.signature_fields
        assert "VoxelSize" in context.signature_fields

    def test_fallback_order(self):
        # Every scan differs in flip angle, inversion and echo time, so those three are dropped.
        scans = [
            ScanInput("T1w", _signature(FlipAngle=float(i), InversionTime=0.8 + i / 100, EchoTime=0.002 + i / 10000), {"cjv": 0.4}) for i in range(12)
        ]
        _, context = select_stratum(0, scans, CONFIG)
        assert context.signature_fields == ["suffix", "MRAcquisitionType", "MagneticFieldStrength", "Manufacturer", "RepetitionTime", "VoxelSize"]
        assert context.n == 11 and context.note is None

    def test_no_adequate_stratum(self):
        scans = _project(5)
        members, context = select_stratum(0, scans, CONFIG)
        assert members == []
        assert context.signature_fields == ["suffix", "MRAcquisitionType", "MagneticFieldStrength"]
        assert context.note is not None and "below the minimum" in context.note
        stats = scan_statistics(0, scans, resolve_context("T1w"), CONFIG)
        assert all(m.project_percentile is None for m in stats.metrics)
        assert stats.outlier is None

    def test_fixed_and_fallback_fields_disjoint(self):
        from evidence_bundle.constants import SIGNATURE_FALLBACK_ORDER, SIGNATURE_FIXED

        assert not set(SIGNATURE_FIXED) & set(SIGNATURE_FALLBACK_ORDER)

    def test_fixed_fields_never_dropped(self):
        scans = _project(15) + _project(15, seed=2, MagneticFieldStrength=1.5)
        members, _ = select_stratum(0, scans, StatsConfig(min_stratum_size=20))
        assert members == []

    def test_contrasts_never_mixed(self):
        scans = _project(12, suffix="T1w") + _project(12, seed=3, suffix="T2w")
        members, _ = select_stratum(0, scans, CONFIG)
        assert all(scans[j].suffix == "T1w" for j in members)
        members, _ = select_stratum(12, scans, CONFIG)
        assert all(scans[j].suffix == "T2w" for j in members)

    def test_site_kept_when_known(self):
        scans = [ScanInput("T1w", _signature(), {"cjv": 0.4}, site="A" if i < 11 else "B") for i in range(22)]
        members, context = select_stratum(0, scans, CONFIG)
        assert all(scans[j].site == "A" for j in members)
        assert context.filters == {"site": "A"}


# --- statistics --------------------------------------------------------------------------


class TestRobustStatistics:
    def test_known_percentiles(self):
        sample = np.arange(10, dtype=float)
        assert empirical_percentile(4.5, sample) == 50.0
        assert empirical_percentile(4.0, sample) == 45.0
        assert empirical_percentile(-1.0, sample) == 0.0
        assert empirical_percentile(99.0, sample) == 100.0

    def test_robust_z(self):
        sample = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert robust_z(3.0, sample) == 0.0
        assert robust_z(5.0, sample) == pytest.approx(2.0 / 1.4826)

    def test_robust_z_zero_mad(self):
        sample = np.array([1.0] * 9 + [2.0])
        assert robust_z(1.0, sample) == 0.0
        assert np.isfinite(robust_z(3.0, sample)) and robust_z(3.0, sample) > 0
        assert robust_z(2.0, np.ones(5)) == np.inf


class TestFlags:
    def test_direction_aware(self):
        assert metric_flags("higher_worse", 3.5, None, CONFIG) == ["project_outlier"]
        assert metric_flags("lower_worse", 3.5, None, CONFIG) == []
        assert metric_flags("lower_worse", -3.5, None, CONFIG) == ["project_outlier"]
        assert metric_flags("higher_worse", None, 99.0, CONFIG) == ["reference_outlier"]
        assert metric_flags("lower_worse", None, 99.0, CONFIG) == []
        assert metric_flags("lower_worse", None, 1.0, CONFIG) == ["reference_outlier"]

    def test_two_sided(self):
        assert metric_flags("outside_range", -3.5, None, CONFIG) == ["project_outlier"]
        assert metric_flags("outside_range", 3.5, 1.0, CONFIG) == ["project_outlier", "reference_outlier"]
        assert metric_flags("outside_range", 1.0, 50.0, CONFIG) == []

    def test_non_directional_never_flagged(self):
        assert metric_flags("context_dependent", 10.0, 100.0, CONFIG) == []
        assert metric_flags("not_quality_metric", 10.0, 0.0, CONFIG) == []

    def test_lax_config_flags_more(self):
        lax = StatsConfig(project_z_threshold=2.0, reference_percentile_low=5.0, reference_percentile_high=95.0)
        assert metric_flags("higher_worse", 2.5, 96.0, CONFIG) == []
        assert metric_flags("higher_worse", 2.5, 96.0, lax) == ["project_outlier", "reference_outlier"]

    @pytest.mark.parametrize(
        "flags,category",
        [(["project_outlier", "reference_outlier"], "scan"), (["reference_outlier"], "protocol"), (["project_outlier"], "project"), ([], "normal")],
    )
    def test_categories(self, flags, category):
        assert context_category_for(flags) == category


class TestStatsConfig:
    def test_defaults(self):
        assert (CONFIG.min_stratum_size, CONFIG.project_z_threshold) == (10, 3.0)
        assert (CONFIG.reference_percentile_low, CONFIG.reference_percentile_high) == (2.5, 97.5)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"min_stratum_size": 1},
            {"project_z_threshold": 0},
            {"reference_percentile_low": 60, "reference_percentile_high": 40},
            {"reference_percentile_high": 101},
            {"unknown": 1},
        ],
    )
    def test_invalid(self, kwargs):
        with pytest.raises(ValidationError):
            StatsConfig(**kwargs)

    def test_partial_override_from_json(self):
        config = StatsConfig.model_validate_json('{"project_z_threshold": 2.0}')
        assert config.project_z_threshold == 2.0 and config.min_stratum_size == 10


class TestScanStatistics:
    def test_project_outlier_and_categories(self):
        scans = _project(30)
        scans[0] = ScanInput("T1w", scans[0].signature, {**scans[0].iqms, "cjv": 0.8, "cnr": 3.0})
        reference = _reference(cjv=np.linspace(0.3, 1.0, 400), cnr=np.linspace(3.5, 5.0, 400))
        stats = scan_statistics(0, scans, resolve_context("T1w"), CONFIG, reference=reference)
        cjv, cnr, efc = _metric(stats, "cjv"), _metric(stats, "cnr"), _metric(stats, "efc")
        assert cjv.flags == ["project_outlier"] and cjv.context_category == "project"
        # Normal in the project, below every reference value: a protocol effect.
        assert cnr.flags == ["reference_outlier"] and cnr.context_category == "protocol"
        assert efc.context_category in ("normal", "project", "scan", "protocol")
        assert _metric(stats, "size_x").context_category is None
        assert stats.reference.n == 400
        assert stats.reference.filters == {"MagneticFieldStrength": "3", "Manufacturer": "siemens", "VoxelSize": "1x1x1"}

    def test_scan_category(self):
        scans = _project(30)
        scans[0] = ScanInput("T1w", scans[0].signature, {**scans[0].iqms, "cjv": 2.0})
        stats = scan_statistics(0, scans, resolve_context("T1w"), CONFIG, reference=_reference())
        assert _metric(stats, "cjv").context_category == "scan"

    def test_flair_only_with_flair_and_no_reference(self):
        scans = _project(12, suffix="T2w", seed=4) + _project(12, suffix="FLAIR", seed=5)
        resolved = resolve_context("FLAIR")
        stats = scan_statistics(12, scans, resolved, CONFIG, reference=_reference())
        members, _ = select_stratum(12, scans, CONFIG)
        assert all(scans[j].suffix == "FLAIR" for j in members)
        assert all(m.reference_percentile is None for m in stats.metrics)
        assert stats.reference.n == 0 and stats.reference.note is not None and "fallback" in stats.reference.note
        assert _metric(stats, "wm2max").direction_of_concern == "context_dependent"
        assert _metric(stats, "cnr").project_percentile is not None

    def test_unsupported_percentiles_but_no_flags(self):
        scans = _project(15, suffix="PDw")
        scans[0] = ScanInput("PDw", scans[0].signature, {**scans[0].iqms, "cjv": 5.0})
        stats = scan_statistics(0, scans, resolve_context("PDw"), CONFIG, catalog=load_metric_context("T1w"))
        cjv = _metric(stats, "cjv")
        assert cjv.project_percentile == 100.0
        assert cjv.flags == [] and cjv.direction_of_concern == "context_dependent" and cjv.evidence_strength == "none"
        assert cjv.display_name == load_metric_context("T1w").metrics["cjv"].display_name
        assert stats.outlier is None

    def test_supported_without_reference_data(self):
        stats = scan_statistics(0, _project(12, suffix="T2w"), resolve_context("T2w"), CONFIG, reference_unavailable="T2w.parquet is not served")
        assert stats.reference.n == 0 and stats.reference.note == "T2w.parquet is not served"
        assert all(m.reference_percentile is None for m in stats.metrics)

    def test_non_finite_iqms_skipped(self):
        scans = _project(12)
        scans[0] = ScanInput("T1w", scans[0].signature, {**scans[0].iqms, "fber": float("inf"), "snrd_wm": float("nan")})
        stats = scan_statistics(0, scans, resolve_context("T1w"), CONFIG)
        assert stats.skipped == ["fber", "snrd_wm"]
        assert {"fber", "snrd_wm"}.isdisjoint(m.name for m in stats.metrics)

    def test_unknown_iqm_not_interpreted(self):
        scans = _project(12)
        scans[0] = ScanInput("T1w", scans[0].signature, {**scans[0].iqms, "new_iqm": 1.0})
        metric = _metric(scan_statistics(0, scans, resolve_context("T1w"), CONFIG), "new_iqm")
        assert (metric.category, metric.direction_of_concern, metric.evidence_strength) == ("uncategorized", "context_dependent", "none")

    def test_bundle_from_statistics_validates(self):
        scans = _project(20)
        resolved = resolve_context("T1w")
        stats = scan_statistics(0, scans, resolved, CONFIG, reference=_reference())
        bundle = EvidenceBundle(
            participant_id="sub-01",
            session_id="ses-01",
            pipeline="mriqc",
            qc_task="anat",
            bids_name="sub-01_ses-01_T1w",
            suffix="T1w",
            support=resolved.support,
            context_suffix=resolved.context_suffix,
            protocol_signature=scans[0].signature,
            stats_config=StatsConfig(project_z_threshold=2.5),
            project=stats.project,
            reference=stats.reference,
            metrics=stats.metrics,
            outlier=stats.outlier,
        )
        loaded = EvidenceBundle.model_validate_json(bundle.model_dump_json())
        assert loaded == bundle
        assert loaded.stats_config.project_z_threshold == 2.5


class TestReferenceSubset:
    def test_drops_voxel_size_then_manufacturer(self):
        reference = _reference(n=50)
        reference.loc[:, "spacing_z"] = 1.2
        reference.loc[:5, "Manufacturer"] = "GE"
        signature = _signature(Manufacturer="ge")
        data, context = reference_subset(resolve_context("T1w"), signature, reference, CONFIG)
        assert data is not None and len(data) == 50
        assert context.signature_fields == ["MagneticFieldStrength"]

    def test_too_few_rows(self):
        data, context = reference_subset(resolve_context("T1w"), _signature(), _reference(n=5), CONFIG)
        assert data is None and context.n == 5 and context.note is not None


class TestOutlierScore:
    def test_injected_outlier_ranked_first(self):
        scans = _project(40, seed=7)
        shifted = {**scans[0].iqms, "cjv": scans[0].iqms["cjv"] + 0.2, "cnr": scans[0].iqms["cnr"] - 1.2, "snr_wm": scans[0].iqms["snr_wm"] - 6.0}
        scans[0] = ScanInput("T1w", scans[0].signature, shifted)
        resolved = resolve_context("T1w")
        results = [scan_statistics(i, scans, resolved, CONFIG) for i in range(len(scans))]
        scores = [r.outlier.score for r in results if r.outlier is not None]
        assert len(scores) == 40
        assert int(np.argmax(scores)) == 0
        top = results[0].outlier
        assert top is not None
        assert {c.metric for c in top.top_contributors} == {"cjv", "cnr", "snr_wm"}
        assert top.percentile == 100.0
        assert "size_x" not in top.metrics_used

    def test_largest_shift_contributes_most(self):
        rng = np.random.default_rng(0)
        members = rng.normal(size=(30, 4))
        score = outlier_score(np.array([4.0, -1.5, 0.5, 0.0]), members, ["a", "b", "c", "d"])
        assert score is not None
        assert [c.metric for c in score.top_contributors][:2] == ["a", "b"]
        assert all(c.contribution > 0 for c in score.top_contributors)

    def test_ordinary_scans_have_ordinary_percentiles(self):
        # In a small stratum with no outliers, scores in-sample members would push the
        # percentiles up (median about 73 at n = 12); leave-one-out keeps them near 50.
        resolved = resolve_context("T1w")
        percentiles = []
        for seed in range(5):
            scans = _project(12, seed=seed)
            percentiles += [scan_statistics(i, scans, resolved, CONFIG).outlier.percentile for i in range(12)]  # type: ignore[union-attr]
        assert 35 <= float(np.median(percentiles)) <= 60

    def test_constant_metrics_left_out(self):
        members = np.column_stack([np.ones(20), np.random.default_rng(1).normal(size=20)])
        score = outlier_score(np.array([1.0, 0.0]), members, ["const", "x"])
        assert score is not None and score.metrics_used == ["x"]
        assert outlier_score(np.array([1.0]), np.ones((20, 1)), ["const"]) is None


def test_numeric_iqms():
    mriqc = json.loads(SAMPLE_MRIQC.read_text())
    iqms = numeric_iqms(mriqc)
    assert "cjv" in iqms and "bids_meta" not in iqms and "provenance" not in iqms
    assert numeric_iqms({"a": True, "b": 1, "c": "x"}) == {"b": 1.0}


class TestReferenceFilter:
    def test_voxel_size_filter(self):
        data = _reference(n=10)
        data.loc[:3, "spacing_z"] = 1.2
        assert len(filter_reference_frame(data, "siemens", "3", 1000, (1.0, 1.0, 1.0))) == 6
        assert len(filter_reference_frame(data, "siemens", "3", 1000, (1.0, 1.0, 1.2))) == 4
        assert len(filter_reference_frame(data.drop(columns=["spacing_z"]), "siemens", "3", 1000, (1.0, 1.0, 1.2))) == 10

    def test_filter_reference_iqm_reads_parquet(self, tmp_path, monkeypatch):
        monkeypatch.setattr(reference_data, "REFERENCE_CACHE_DIR", tmp_path)
        _reference(n=20).to_parquet(tmp_path / "T1w.parquet")
        assert len(filter_reference_iqm("T1w", "siemens", "3", 1000, voxel_size=(1.0, 1.0, 1.0))) == 20
        assert len(filter_reference_iqm("T1w", "ge", "3", 1000)) == 0


class TestReferenceTable:
    def test_scans_with_one_key_share_one_filter_pass(self, monkeypatch):
        calls = []
        real = stats_module.filter_reference_frame
        monkeypatch.setattr(stats_module, "filter_reference_frame", lambda *a, **k: calls.append(a[1:]) or real(*a, **k))
        scans = _project(12)
        table = ReferenceTable(_reference())
        first = [scan_statistics(i, scans, resolve_context("T1w"), CONFIG, reference=table) for i in range(3)]
        assert len(calls) == 1
        assert first[0].reference == scan_statistics(0, scans, resolve_context("T1w"), CONFIG, reference=_reference()).reference


class TestStratumScores:
    def test_each_stratum_scored_once(self, monkeypatch):
        scans = _project(15, seed=3)
        resolved = resolve_context("T1w")
        uncached = [scan_statistics(i, scans, resolved, CONFIG).outlier for i in range(15)]
        calls = []
        real = stats_module._distance
        monkeypatch.setattr(stats_module, "_distance", lambda *a: calls.append(1) or real(*a))
        cache: dict = {}
        cached = [scan_statistics(i, scans, resolved, CONFIG, outlier_cache=cache).outlier for i in range(15)]
        assert cached == uncached
        assert len(calls) == 15 and len(cache) == 1

    def test_percentiles_of_one_stratum_are_ranks(self):
        scores = stratum_outlier_scores(np.random.default_rng(2).normal(size=(10, 3)), ["a", "b", "c"])
        percentiles = sorted(s.percentile for s in scores if s is not None)
        assert percentiles == [100.0 * k / 9 for k in range(10)]

    def test_too_small_stratum_has_no_scores(self):
        assert stratum_outlier_scores(np.random.default_rng(2).normal(size=(3, 2)), ["a", "b"]) == [None] * 3
