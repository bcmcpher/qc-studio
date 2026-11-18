"""Tests for the model feedback schema, consistency check and feedback.json I/O."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import ValidationError

from evidence_bundle.constants import MAX_REASONS
from evidence_bundle.feedback import (
    FeedbackResult,
    QCFeedback,
    check_consistency,
    error_result,
    extract_json,
    load_feedback,
    parse_reply,
    reply_result,
    skipped_result,
    write_feedback,
)
from evidence_bundle.models import DistributionContext, EvidenceBundle, MetricEvidence

UI_DIR = Path(__file__).resolve().parents[1]


def _metric(name, flags=(), category: Optional[str] = "normal", **kwargs):
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
        bids_name="sub-01_ses-01_T1w",
        suffix="T1w",
        support="supported",
        context_suffix="T1w",
        project=DistributionContext(filters={"site": "A"}, n=40),
        reference=DistributionContext(filters={"manufacturer": "Siemens"}, n=1200),
        metrics=[_metric("cjv", flags=["project_outlier", "reference_outlier"], category="scan"), _metric("snr_wm")],
    )
    fields.update(kwargs)
    return EvidenceBundle(**fields)


def _unsupported_bundle():
    return _bundle(
        suffix="PDw",
        support="unsupported",
        context_suffix=None,
        reference=None,
        metrics=[
            _metric(
                "cjv",
                direction_of_concern="context_dependent",
                evidence_strength="none",
                category=None,
                reference_percentile=None,
            )
        ],
    )


def _reply(**kwargs):
    fields: dict[str, Any] = dict(
        decision="fail",
        confidence="medium",
        summary="CJV is high for this protocol.",
        reasons=["CJV is a project and reference outlier.", "Other metrics are typical."],
        flagged_metrics=["cjv"],
        recommended_followup=["Inspect the axial view for motion."],
    )
    fields.update(kwargs)
    return fields


def _result(bundle=None, reply=None, **kwargs):
    return reply_result(bundle or _bundle(), reply if reply is not None else _reply(), adapter="fake", model_id="fake-1", **kwargs)


class TestSchema:
    def test_valid_reply(self):
        result = _result(reply=json.dumps(_reply()))
        assert result.schema_valid
        assert result.feedback == QCFeedback(**_reply())
        assert result.consistency_errors == []
        assert result.status == "ok"

    def test_image_observations_optional(self):
        assert QCFeedback(**_reply()).image_observations == []
        assert QCFeedback(**_reply(image_observations=["ringing in the axial view"])).image_observations

    @pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```", "Here is my answer:\n```json\n{}\n```\nThanks."])
    def test_fenced_reply(self, fence):
        result = _result(reply=fence.replace("{}", json.dumps(_reply())))
        assert result.schema_valid

    def test_first_object_in_free_text(self):
        result = _result(reply=f"My assessment: {json.dumps(_reply())} and a trailing {{}}")
        assert result.schema_valid

    def test_mapping_reply_from_tool_input(self):
        result = _result(reply=_reply())
        assert result.schema_valid
        assert json.loads(result.raw_reply) == _reply()

    def test_invalid_json_kept(self):
        result = _result(reply="I think the scan passes.")
        assert result.status == "ok"
        assert not result.schema_valid
        assert result.feedback is None
        assert result.raw_reply == "I think the scan passes."
        assert result.schema_errors and "not JSON" in result.schema_errors[0]

    def test_schema_mismatch_kept(self):
        result = _result(reply=json.dumps(_reply(decision="maybe")))
        assert not result.schema_valid
        assert any(err.startswith("decision") for err in result.schema_errors)

    def test_unknown_field_rejected(self):
        feedback, errors = parse_reply(_reply(verdict="pass"))
        assert feedback is None
        assert any("verdict" in err for err in errors)

    def test_backticks_inside_plain_json(self):
        reply = _reply(reasons=["CJV is high; see ```cjv``` in the table."])
        result = _result(reply=json.dumps(reply))
        assert result.schema_valid and result.feedback == QCFeedback(**reply)

    def test_extract_json_without_object(self):
        with pytest.raises(ValueError, match="no JSON object"):
            extract_json("no braces here")

    def test_stray_brace_in_prose_before_json(self):
        reply = _reply()
        assert extract_json(f"Using the {{project}} context: {json.dumps(reply)}") == reply

    def test_extract_json_bad_object_only(self):
        with pytest.raises(ValueError):
            extract_json("prefix {not json}")


class TestConsistency:
    def test_consistent(self):
        assert check_consistency(QCFeedback(**_reply()), _bundle()) == []

    def test_metric_not_flagged_in_bundle(self):
        reply = _reply(flagged_metrics=["cjv", "snr_wm"], reasons=["CJV is high.", "SNR_WM is low."])
        errors = check_consistency(QCFeedback(**reply), _bundle())
        assert errors == ["flagged metric 'snr_wm' is not flagged in the bundle"]

    def test_metric_not_named_in_reason(self):
        errors = check_consistency(QCFeedback(**_reply(reasons=["Contrast is poor."])), _bundle())
        assert errors == ["flagged metric 'cjv' is not named in any reason"]

    def test_metric_named_case_insensitively(self):
        assert check_consistency(QCFeedback(**_reply(reasons=["The Cjv value is high."])), _bundle()) == []

    @pytest.mark.parametrize("reason", ["tsnr=12 is low.", "snr_wm is typical.", "the snrish value"])
    def test_metric_not_found_inside_another_name(self, reason):
        bundle = _bundle(metrics=[_metric("snr", flags=["project_outlier"], category="project"), _metric("tsnr"), _metric("snr_wm")])
        reply = _reply(flagged_metrics=["snr"], reasons=[reason])
        assert check_consistency(QCFeedback(**reply), bundle) == ["flagged metric 'snr' is not named in any reason"]

    @pytest.mark.parametrize("reason", ["snr=4.1, project percentile 2.", "Low SNR.", "(snr) is low"])
    def test_metric_named_as_word(self, reason):
        bundle = _bundle(metrics=[_metric("snr", flags=["project_outlier"], category="project")])
        assert check_consistency(QCFeedback(**_reply(flagged_metrics=["snr"], reasons=[reason])), bundle) == []

    @pytest.mark.parametrize("reasons", [[], ["   "], [f"cjv reason {i}" for i in range(MAX_REASONS + 1)]])
    def test_reason_count(self, reasons):
        errors = check_consistency(QCFeedback(**_reply(reasons=reasons, flagged_metrics=[])), _bundle())
        assert len(errors) == 1 and "reasons; expected" in errors[0]

    @pytest.mark.parametrize("decision", ["fail", "uncertain"])
    def test_missing_followup(self, decision):
        errors = check_consistency(QCFeedback(**_reply(decision=decision, recommended_followup=[""])), _bundle())
        assert errors == [f"decision '{decision}' needs a recommended follow-up"]

    def test_pass_needs_no_followup(self):
        reply = _reply(decision="pass", recommended_followup=[])
        assert check_consistency(QCFeedback(**reply), _bundle()) == []

    def test_errors_stored_in_result(self):
        result = _result(reply=_reply(flagged_metrics=["efc"], reasons=["EFC is high."]))
        assert result.schema_valid
        assert result.consistency_errors == ["flagged metric 'efc' is not flagged in the bundle"]


class TestResult:
    def test_metadata_recorded(self):
        result = _result(settings={"temperature": 0}, prompt_hash="abc", endpoint="https://proxy.example.org")
        assert result.adapter == "fake" and result.model_id == "fake-1"
        assert result.settings == {"temperature": 0}
        assert result.prompt_hash == "abc"
        assert result.endpoint == "https://proxy.example.org"
        assert result.bundle_schema_version == _bundle().schema_version
        assert (result.support, result.context_suffix) == ("supported", "T1w")
        assert result.timestamp

    def test_fallback_support_recorded(self):
        bundle = _bundle(
            suffix="FLAIR", support="fallback", context_suffix="T2w", reference=None, metrics=[_metric("cjv", reference_percentile=None)]
        )
        result = _result(bundle=bundle, reply=_reply(flagged_metrics=[], decision="pass"))
        assert (result.support, result.context_suffix) == ("fallback", "T2w")

    def test_error_result(self):
        result = error_result(_bundle(), "timeout", adapter="fake", model_id="fake-1")
        assert result.status == "error" and result.error == "timeout"
        assert result.feedback is None and not result.schema_valid

    def test_skipped_result(self):
        result = skipped_result(_unsupported_bundle(), adapter="fake", model_id="fake-1")
        assert result.status == "skipped_unsupported"
        assert result.support == "unsupported" and result.context_suffix is None
        assert result.raw_reply is None

    def test_skip_needs_unsupported_bundle(self):
        with pytest.raises(ValidationError, match="only unsupported bundles are skipped"):
            skipped_result(_bundle(), adapter="fake", model_id="fake-1")

    def test_error_needs_message(self):
        with pytest.raises(ValidationError, match="records the error"):
            error_result(_bundle(), "", adapter="fake", model_id="fake-1")

    def test_feedback_only_when_valid(self):
        fields = _result().model_dump()
        fields["schema_valid"] = False
        with pytest.raises(ValidationError, match="schema_valid is true exactly"):
            FeedbackResult(**fields)

    def test_ok_needs_reply(self):
        fields = _result(reply="not json").model_dump()
        fields["raw_reply"] = None
        with pytest.raises(ValidationError, match="holds the raw reply"):
            FeedbackResult(**fields)


class TestFeedbackFile:
    def test_round_trip(self, tmp_path):
        result = _result()
        path = write_feedback(tmp_path, result)
        assert path == tmp_path / "feedback.json"
        assert load_feedback(tmp_path) == result
        assert load_feedback(path) == result

    def test_error_replaces_success(self, tmp_path):
        write_feedback(tmp_path, _result())
        write_feedback(tmp_path, error_result(_bundle(), "rate limited", adapter="fake", model_id="fake-1"))
        assert load_feedback(tmp_path).status == "error"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["feedback.json"]

    def test_file_mode_follows_umask(self, tmp_path):
        old = os.umask(0o022)
        try:
            path = write_feedback(tmp_path, _result())
        finally:
            os.umask(old)
        assert stat.S_IMODE(path.stat().st_mode) == 0o644

    def test_write_leaves_umask_alone(self, tmp_path):
        old = os.umask(0o027)
        try:
            path = write_feedback(tmp_path, _result())
            assert os.umask(0o027) == 0o027
        finally:
            os.umask(old)
        assert stat.S_IMODE(path.stat().st_mode) == 0o640

    def test_invalid_reply_round_trip(self, tmp_path):
        write_feedback(tmp_path, _result(reply="garbage"))
        loaded = load_feedback(tmp_path)
        assert not loaded.schema_valid and loaded.raw_reply == "garbage"


def test_core_imports_without_model_sdks():
    """feedback.py imports when anthropic, torch and transformers cannot be imported."""
    code = "import sys\n" "for name in ('anthropic', 'torch', 'transformers'):\n" "    sys.modules[name] = None\n" "import evidence_bundle.feedback\n"
    subprocess.run([sys.executable, "-c", code], cwd=UI_DIR, check=True)
