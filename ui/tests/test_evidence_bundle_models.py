"""Tests for the evidence bundle schema and IQM context files."""

import json
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from evidence_bundle.constants import CONTEXT_FILES, DEFAULT_CONTRAST_MAP
from evidence_bundle.context import load_metric_context, lookup_metric, resolve_context
from evidence_bundle.models import (
    SCHEMA_VERSION,
    AcquisitionDeviation,
    AcquisitionMetadata,
    DistributionContext,
    EvidenceBundle,
    MetricContextFile,
    MetricEvidence,
    OutlierContributor,
    OutlierScore,
    ProtocolSignature,
    ProvenanceMetadata,
    RaterQC,
    ViewRef,
    context_category_for,
)


def _metric(name="cjv", flags=(), category: Optional[str] = "normal", **kwargs):
    fields: dict[str, Any] = dict(
        name=name,
        value=0.5,
        display_name=name.upper(),
        category="noise_and_tissue_contrast",
        direction_of_concern="higher_worse",
        evidence_strength="medium",
        project_percentile=50.0,
        reference_percentile=50.0,
        flags=list(flags),
        context_category=category,
    )
    fields.update(kwargs)
    return MetricEvidence(**fields)


def _bundle(**kwargs):
    fields: dict[str, Any] = dict(
        participant_id="sub-01",
        session_id="ses-01",
        pipeline="mriqc",
        qc_task="anat",
        suffix="T1w",
        support="supported",
        context_suffix="T1w",
        acquisition=AcquisitionMetadata.from_sidecar(
            {"Manufacturer": "Siemens", "MagneticFieldStrength": 3, "RepetitionTime": 2.3, "EchoTime": 0.00298},
            site="A",
            geometry={"shape": (176, 256, 256), "voxel_size": (1.0, 1.0, 1.0), "orientation": ("R", "A", "S")},
            provenance=ProvenanceMetadata(mriqc_version="24.1.0", md5sum="abc"),
        ),
        protocol_signature=ProtocolSignature(suffix="T1w", MagneticFieldStrength=3.0, RepetitionTime=2.3, VoxelSize=(1.0, 1.0, 1.0)),
        acquisition_deviations=[AcquisitionDeviation(field="EchoTime", value=0.0035, expected=0.0029, share=0.95, n=20)],
        project=DistributionContext(filters={"site": "A"}, signature_fields=["suffix", "MagneticFieldStrength"], n=40),
        reference=DistributionContext(filters={"manufacturer": "Siemens", "magnetic_field_strength": "3"}, n=1200),
        metrics=[
            _metric("cjv", flags=["project_outlier", "reference_outlier"], category="scan"),
            _metric("cnr", direction_of_concern="lower_worse"),
            _metric("size_x", direction_of_concern="not_quality_metric", context_category=None, evidence_strength="none"),
        ],
        outlier=OutlierScore(
            score=4.2,
            percentile=99.0,
            metrics_used=["cjv", "cnr"],
            top_contributors=[OutlierContributor(metric="cjv", contribution=3.1)],
        ),
        views=[
            ViewRef(
                path="views/core_axial.png",
                kind="core",
                plane="axial",
                slice_positions=[-20.0, 0.0, 20.0],
                placement="mni",
                window_percentiles=(0.5, 99.5),
            ),
            ViewRef(
                path="views/targeted_motion.png",
                kind="targeted",
                plane="sagittal",
                slice_positions=[-40.0, 40.0],
                placement="bbox_fraction",
                window_percentiles=(0.5, 99.5),
                rule="motion",
            ),
        ],
        rater_qc=RaterQC(rater_id="rater1", final_qc="PASS", notes="ok"),
    )
    fields.update(kwargs)
    return EvidenceBundle(**fields)


class TestBundleRoundTrip:
    def test_json_round_trip(self):
        bundle = _bundle()
        loaded = EvidenceBundle.model_validate_json(bundle.model_dump_json())
        assert loaded == bundle

    def test_schema_version_default(self):
        assert _bundle().schema_version == SCHEMA_VERSION

    def test_flagged_metrics(self):
        assert _bundle().flagged_metrics() == ["cjv"]

    def test_unknown_field_rejected(self):
        data = json.loads(_bundle().model_dump_json())
        data["unexpected"] = 1
        with pytest.raises(ValidationError):
            EvidenceBundle.model_validate(data)


class TestMetricEvidence:
    def test_unknown_direction_rejected_with_metric_name(self):
        data = json.loads(_bundle().model_dump_json())
        data["metrics"][0]["direction_of_concern"] = "closer_to_1_or_lower_range_better"
        with pytest.raises(ValidationError, match="direction_of_concern"):
            EvidenceBundle.model_validate(data)

    @pytest.mark.parametrize(
        "flags,expected",
        [
            (["project_outlier", "reference_outlier"], "scan"),
            (["reference_outlier"], "protocol"),
            (["project_outlier"], "project"),
            ([], "normal"),
        ],
    )
    def test_context_category_for(self, flags, expected):
        assert context_category_for(flags) == expected

    def test_category_must_match_flags(self):
        with pytest.raises(ValidationError, match="imply category 'scan'"):
            _metric(flags=["project_outlier", "reference_outlier"], category="project")

    def test_directional_metric_needs_category(self):
        with pytest.raises(ValidationError, match="needs a context category"):
            _metric(category=None)

    @pytest.mark.parametrize("direction", ["context_dependent", "not_quality_metric"])
    def test_non_directional_metric_has_no_flags(self, direction):
        with pytest.raises(ValidationError, match="no flags or context category"):
            _metric(direction_of_concern=direction, flags=["project_outlier"], category="project")

    def test_percentile_bounds(self):
        with pytest.raises(ValidationError):
            _metric(project_percentile=101.0)


class TestBundleChecks:
    def test_duplicate_metrics_rejected(self):
        with pytest.raises(ValidationError, match="duplicate metrics"):
            _bundle(metrics=[_metric("cjv"), _metric("cjv")])

    def test_outlier_metrics_must_exist(self):
        with pytest.raises(ValidationError, match="not in the bundle"):
            _bundle(outlier=OutlierScore(score=1.0, metrics_used=["cjv", "efc"]))

    def test_reference_flag_needs_reference(self):
        with pytest.raises(ValidationError, match="need a reference distribution"):
            _bundle(reference=None)


class TestViewRef:
    def test_targeted_needs_rule(self):
        with pytest.raises(ValidationError, match="needs the rule"):
            ViewRef(path="v.png", kind="targeted", plane="axial", slice_positions=[0.0], placement="mni", window_percentiles=(1, 99))

    def test_core_is_never_control(self):
        with pytest.raises(ValidationError, match="never a control"):
            ViewRef(path="v.png", kind="core", plane="axial", slice_positions=[0.0], placement="mni", window_percentiles=(1, 99), control=True)

    def test_needs_a_slice(self):
        with pytest.raises(ValidationError):
            ViewRef(path="v.png", kind="core", plane="axial", slice_positions=[], placement="mni", window_percentiles=(1, 99))


SIDECAR = {
    "Manufacturer": "GE",
    "ManufacturersModelName": "DISCOVERY_MR750",
    "MagneticFieldStrength": 3,
    "CoilString": "Nova32ch",
    "RepetitionTime": 0.006952,
    "EchoTime": 0.00292,
    "InversionTime": 1.06,
    "FlipAngle": 8,
    "MRAcquisitionType": "3D",
    "ScanningSequence": "RM",
    "SliceThickness": 1,
    "DeviceSerialNumber": "0000000416595MR1",
    "InstitutionName": "CAMH",
    "InstitutionAddress": "Somewhere",
    "StationName": "MRMR",
    "AcquisitionTime": "13:55:50.000000",
    "XNATAccessionID": "E37193",
    "ProtocolName": "Sag_MPRAGE_T1",
}
IDENTIFYING = ["0000000416595MR1", "CAMH", "Somewhere", "MRMR", "13:55:50", "E37193"]


class TestAcquisitionMetadata:
    def test_allowlist_drops_identifying_fields(self):
        dumped = _bundle(acquisition=AcquisitionMetadata.from_sidecar(SIDECAR)).model_dump_json()
        for value in IDENTIFYING:
            assert value not in dumped
        for key in ["DeviceSerialNumber", "InstitutionName", "InstitutionAddress", "StationName", "AcquisitionTime", "XNATAccessionID"]:
            assert key not in dumped

    def test_allowlisted_fields_kept(self):
        acq = AcquisitionMetadata.from_sidecar(SIDECAR)
        assert acq.scanner.Manufacturer == "GE"
        assert acq.scanner.ReceiveCoilName == "Nova32ch"
        assert acq.sequence.EchoTime == 0.00292
        assert acq.sequence.ScanningSequence == "RM"
        assert acq.geometry.SliceThickness == 1.0
        assert acq.site is None

    def test_missing_field_is_null(self):
        acq = AcquisitionMetadata.from_sidecar({"Manufacturer": "GE"})
        assert acq.sequence.InversionTime is None
        assert acq.geometry.voxel_size is None

    def test_receive_coil_name_preferred(self):
        acq = AcquisitionMetadata.from_sidecar({"ReceiveCoilName": "HeadNeck_64", "CoilString": "Nova32ch"})
        assert acq.scanner.ReceiveCoilName == "HeadNeck_64"

    def test_header_geometry_kept_over_sidecar(self):
        acq = AcquisitionMetadata.from_sidecar({"SliceThickness": 1}, geometry={"SliceThickness": 1.2})
        assert acq.geometry.SliceThickness == 1.2

    def test_signature_suffix_must_match(self):
        with pytest.raises(ValidationError, match="signature suffix"):
            _bundle(protocol_signature=ProtocolSignature(suffix="T2w"))

    def test_deviation_share_bounds(self):
        with pytest.raises(ValidationError):
            AcquisitionDeviation(field="EchoTime", value=0.0035, expected=0.0029, share=1.5, n=20)

    def test_deviation_unknown_field(self):
        with pytest.raises(ValidationError):
            AcquisitionDeviation(field="InstitutionName", value="x", expected="y", share=0.5, n=2)  # type: ignore[arg-type]


class TestMetricContextFiles:
    @pytest.mark.parametrize("suffix", ["T1w", "T2w", "bold", "dwi"])
    def test_files_validate(self, suffix):
        context = load_metric_context(suffix)
        assert isinstance(context, MetricContextFile)
        assert context.metrics

    def test_known_suffixes(self):
        assert set(CONTEXT_FILES) == {"T1w", "T2w", "bold", "dwi"}

    def test_case_insensitive(self):
        assert load_metric_context("t1w") is load_metric_context("T1w")

    def test_unknown_suffix(self):
        with pytest.raises(ValueError, match="no IQM context"):
            load_metric_context("FLAIR")

    def test_unknown_direction_in_file_rejected(self, tmp_path):
        data = json.loads(load_metric_context("T1w").model_dump_json())
        data["metrics"]["cjv"]["direction_of_concern"] = "target_range"
        with pytest.raises(ValidationError, match="direction_of_concern"):
            MetricContextFile.model_validate(data)

    @pytest.mark.parametrize(
        "name,direction",
        [
            ("cjv", "higher_worse"),
            ("snr_wm", "lower_worse"),
            ("wm2max", "outside_range"),
            ("icvs_gm", "outside_range"),
            ("inu_med", "outside_range"),
            ("inu_range", "higher_worse"),
            ("summary_bg_mean", "context_dependent"),
            ("size_x", "not_quality_metric"),
        ],
    )
    def test_t1w_lookup(self, name, direction):
        entry = lookup_metric(load_metric_context("T1w"), name)
        assert entry is not None
        assert entry.direction_of_concern == direction

    def test_lookup_unknown_metric(self):
        assert lookup_metric(load_metric_context("T1w"), "not_an_iqm") is None

    def test_dwi_lower_bound_ported(self):
        entry = lookup_metric(load_metric_context("dwi"), "ndc")
        assert entry is not None
        assert entry.expected_range == (0.4, None)


def _direction(context, name):
    entry = lookup_metric(context, name)
    assert entry is not None
    return entry.direction_of_concern


STRUCTURAL = [
    "cjv",
    "cnr",
    "efc",
    "fber",
    "qi_1",
    "qi_2",
    "inu_med",
    "inu_range",
    "snr_wm",
    "fwhm_avg",
    "rpve_gm",
    "icvs_gm",
    "tpm_overlap_wm",
    "size_x",
]


class TestT2wOverride:
    def test_wm2max_context_dependent(self):
        entry = lookup_metric(load_metric_context("T2w"), "wm2max")
        assert entry is not None
        assert entry.direction_of_concern == "context_dependent"
        assert entry.expected_range is None
        assert any("T1w-derived" in c for c in entry.caveats)

    @pytest.mark.parametrize("name", STRUCTURAL)
    def test_other_directions_unchanged(self, name):
        assert _direction(load_metric_context("T2w"), name) == _direction(load_metric_context("T1w"), name)

    @pytest.mark.parametrize("name", ["tpm_overlap_gm", "icvs_wm", "rpve_csf"])
    def test_segmentation_caveat_added(self, name):
        t1w, t2w = lookup_metric(load_metric_context("T1w"), name), lookup_metric(load_metric_context("T2w"), name)
        assert t1w is not None and t2w is not None
        assert t2w.caveats[: len(t1w.caveats)] == t1w.caveats
        assert any("T2w" in c for c in t2w.caveats[len(t1w.caveats) :])

    def test_t1w_unchanged_by_override(self):
        assert _direction(load_metric_context("T1w"), "wm2max") == "outside_range"


class TestContrastSupport:
    @pytest.mark.parametrize("suffix", ["T1w", "T2w", "bold", "dwi"])
    def test_supported(self, suffix):
        resolved = resolve_context(suffix)
        assert resolved.support == "supported"
        assert resolved.context_suffix == suffix

    def test_default_map(self):
        assert DEFAULT_CONTRAST_MAP == {"FLAIR": "T2w", "T2starw": "T2w"}

    def test_flair_uses_t2w_context(self):
        resolved = resolve_context("FLAIR")
        assert (resolved.support, resolved.context_suffix) == ("fallback", "T2w")
        assert resolved.context is not None
        assert _direction(resolved.context, "snr_wm") == "lower_worse"
        assert _direction(resolved.context, "efc") == _direction(load_metric_context("T2w"), "efc")

    @pytest.mark.parametrize("name", ["wm2max", "cjv", "tpm_overlap_gm", "icvs_csf", "rpve_wm"])
    def test_forced_set_context_dependent(self, name):
        context = resolve_context("FLAIR").context
        assert context is not None
        assert _direction(context, name) == "context_dependent"
        entry = lookup_metric(context, name)
        assert entry is not None
        assert any("FLAIR is interpreted with T2w context" in c for c in entry.caveats)

    def test_fallback_does_not_change_cached_context(self):
        resolve_context("FLAIR")
        assert _direction(load_metric_context("T2w"), "cjv") == "higher_worse"

    @pytest.mark.parametrize("suffix", ["PDw", "UNIT1", "angio"])
    def test_unmapped_unsupported(self, suffix):
        assert resolve_context(suffix) == ("unsupported", None, None)

    def test_user_map_replaces_default(self):
        resolved = resolve_context("PDw", {"PDw": "T1w"})
        assert (resolved.support, resolved.context_suffix) == ("fallback", "T1w")
        assert resolve_context("FLAIR", {"PDw": "T1w"}).support == "unsupported"

    def test_user_map_cannot_demote_supported(self):
        assert resolve_context("T2w", {"T2w": "T1w"}).support == "supported"

    def test_user_map_target_needs_context(self):
        with pytest.raises(ValueError, match="no IQM context"):
            resolve_context("PDw", {"PDw": "FLAIR"})


def _flair_bundle(**kwargs):
    fields: dict[str, Any] = dict(
        suffix="FLAIR",
        support="fallback",
        context_suffix="T2w",
        reference=None,
        protocol_signature=None,
        acquisition_deviations=[],
        metrics=[_metric("cnr", direction_of_concern="lower_worse", reference_percentile=None)],
        outlier=None,
    )
    fields.update(kwargs)
    return _bundle(**fields)


class TestSupportValidators:
    def test_fallback_bundle_valid(self):
        assert _flair_bundle().support == "fallback"

    def test_fallback_has_no_reference_percentiles(self):
        with pytest.raises(ValidationError, match="no reference percentiles"):
            _flair_bundle(metrics=[_metric("cnr", direction_of_concern="lower_worse")])

    def test_fallback_needs_other_context(self):
        with pytest.raises(ValidationError, match="context suffix other than its own"):
            _flair_bundle(context_suffix="FLAIR")

    def test_supported_uses_own_context(self):
        with pytest.raises(ValidationError, match="uses its own context"):
            _bundle(context_suffix="T2w")

    def test_unsupported_bundle_valid(self):
        bundle = _flair_bundle(
            suffix="PDw",
            support="unsupported",
            context_suffix=None,
            metrics=[_metric("cnr", direction_of_concern="context_dependent", context_category=None)],
        )
        assert bundle.flagged_metrics() == []

    def test_unsupported_metrics_context_dependent(self):
        with pytest.raises(ValidationError, match="context_dependent"):
            _flair_bundle(suffix="PDw", support="unsupported", context_suffix=None)

    def test_unsupported_has_no_context_suffix(self):
        metrics = [_metric("cnr", direction_of_concern="context_dependent", context_category=None)]
        with pytest.raises(ValidationError, match="no context suffix"):
            _flair_bundle(suffix="PDw", support="unsupported", metrics=metrics)
