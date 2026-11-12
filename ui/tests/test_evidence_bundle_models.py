"""Tests for the evidence bundle schema and IQM context files."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from evidence_bundle.context import MODALITY_FILES, load_metric_context, lookup_metric
from evidence_bundle.models import (
    SCHEMA_VERSION,
    DistributionContext,
    EvidenceBundle,
    MetricContextFile,
    MetricEvidence,
    OutlierContributor,
    OutlierScore,
    RaterQC,
    ViewRef,
    context_category_for,
)


def _metric(name="cjv", flags=(), category="normal", **kwargs):
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
        modality="T1w",
        project=DistributionContext(filters={"site": "A"}, n=40),
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


class TestMetricContextFiles:
    @pytest.mark.parametrize("modality", ["T1w", "bold", "dwi"])
    def test_files_validate(self, modality):
        context = load_metric_context(modality)
        assert isinstance(context, MetricContextFile)
        assert context.metrics

    def test_known_modalities(self):
        assert set(MODALITY_FILES) == {"t1w", "bold", "dwi"}

    def test_unknown_modality(self):
        with pytest.raises(ValueError, match="no IQM context"):
            load_metric_context("flair")

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
