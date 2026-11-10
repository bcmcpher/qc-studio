"""Tests for models.py module."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from models import MetricQC, QCRecord, QCTask, QCConfig, RatingConfig

pytestmark = pytest.mark.unit


class TestMetricQC:
    """Test MetricQC model."""

    def test_create_metric_qc_with_all_fields(self):
        """Test creating MetricQC with all fields."""
        metric = MetricQC(name="Euler", value=42.5, qc="PASS", notes="Good quality")

        assert metric.name == "Euler"
        assert metric.value == 42.5
        assert metric.qc == "PASS"
        assert metric.notes == "Good quality"

    def test_create_metric_qc_minimal_fields(self):
        """Test creating MetricQC with minimal fields."""
        metric = MetricQC(name="Euler")

        assert metric.name == "Euler"
        assert metric.value is None
        assert metric.qc is None
        assert metric.notes is None

    def test_create_metric_qc_with_optional_value(self):
        """Test creating MetricQC with optional numeric value."""
        metric = MetricQC(name="SNR", value=35.2, qc="PASS")

        assert metric.value == 35.2
        assert isinstance(metric.value, float)

    def test_metric_qc_serialization(self):
        """Test MetricQC model serialization."""
        metric = MetricQC(name="Euler", value=42.5, qc="PASS", notes="Test note")

        serialized = metric.model_dump()

        assert serialized["name"] == "Euler"
        assert serialized["value"] == 42.5


class TestQCRecord:
    """Test QCRecord model."""

    def test_create_qc_record_with_required_fields(self):
        """Test creating QCRecord with required fields."""
        record = QCRecord(participant_id="sub-CMH0001", session_id="ses-01", qc_task="anat_wf_qc", pipeline="fmriprep", rater_id="test_rater")

        assert record.participant_id == "sub-CMH0001"
        assert record.session_id == "ses-01"
        assert record.qc_task == "anat_wf_qc"
        assert record.pipeline == "fmriprep"
        assert record.rater_id == "test_rater"

    def test_create_qc_record_with_all_fields(self, qc_record_sample):
        """Test creating QCRecord with all fields."""
        assert qc_record_sample.participant_id == "sub-CMH0001"
        assert qc_record_sample.session_id == "ses-01"
        assert qc_record_sample.rater_experience == "Expert (>5 year experience)"
        assert qc_record_sample.rater_fatigue == "Not at all"
        assert qc_record_sample.rater_screen_size == "26-30"
        assert qc_record_sample.final_qc == "PASS"
        assert qc_record_sample.notes == "Good quality scan"

    def test_qc_record_with_optional_fields(self):
        """Test QCRecord with optional task_id and run_id."""
        record = QCRecord(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_task="func_proc",
            pipeline="fmriprep",
            rater_id="test_rater",
            task_id="task-rest",
            run_id="run-1",
        )

        assert record.task_id == "task-rest"
        assert record.run_id == "run-1"

    def test_qc_record_missing_required_field(self):
        """Test creating QCRecord without required field raises error."""
        with pytest.raises(ValidationError):
            QCRecord(
                participant_id="sub-CMH0001",
                session_id="ses-01",
                qc_task="anat_wf_qc",
                # missing pipeline and rater_id
            )

    def test_qc_record_serialization(self, qc_record_sample):
        """Test QCRecord model serialization."""
        serialized = qc_record_sample.model_dump()

        assert serialized["participant_id"] == "sub-CMH0001"
        assert serialized["rater_id"] == "test_rater"
        assert "notes" in serialized

    def test_qc_record_json_serialization(self, qc_record_sample):
        """Test QCRecord JSON serialization."""
        json_str = qc_record_sample.model_dump_json()

        assert "sub-CMH0001" in json_str
        assert "test_rater" in json_str


class TestQCTask:
    """Test QCTask model."""

    def test_create_qc_task_with_all_paths(self, temp_dir):
        """Test creating QCTask with all path fields."""
        base_path = temp_dir / "base.nii.gz"
        overlay_path = temp_dir / "overlay.nii.gz"
        montage_path = temp_dir / "montage.svg"
        iqm_path = temp_dir / "iqm.json"

        task = QCTask(base_mri_image_path=base_path, overlay_mri_image_path=overlay_path, montage_path=montage_path, iqm_path=iqm_path)

        assert task.base_mri_image_path == base_path
        assert task.overlay_mri_image_path == overlay_path
        assert task.montage_path == [montage_path]
        assert task.iqm_path == [iqm_path]

    def test_create_qc_task_with_minimal_fields(self):
        """Test creating QCTask with minimal fields."""
        task = QCTask()

        assert task.base_mri_image_path is None
        assert task.overlay_mri_image_path is None
        assert task.montage_path is None
        assert task.iqm_path is None
        assert task.montage_max_rows is None
        assert task.montage_max_cols is None

    def test_qc_task_path_conversion(self, temp_dir):
        """Test that string paths are converted to Path objects."""
        base_path_str = str(temp_dir / "base.nii.gz")

        task = QCTask(base_mri_image_path=base_path_str)

        # Should be converted to Path object
        assert isinstance(task.base_mri_image_path, Path)

    def test_qc_task_serialization(self, temp_dir):
        """Test QCTask serialization."""
        base_path = temp_dir / "base.nii.gz"
        task = QCTask(base_mri_image_path=base_path)

        serialized = task.model_dump()

        assert "base_mri_image_path" in serialized

    def test_qc_task_montage_layout_fields(self, temp_dir):
        task = QCTask(
            montage_path=str(temp_dir / "a.svg"),
            montage_max_rows=2,
            montage_max_cols=3,
        )
        assert task.montage_max_rows == 2
        assert task.montage_max_cols == 3

    def test_qc_task_montage_layout_invalid_rejected(self, temp_dir):
        with pytest.raises(ValidationError):
            QCTask(
                montage_path=str(temp_dir / "a.svg"),
                montage_max_rows=99,
            )

    def test_qc_task_rating_schema_multi_facet(self):
        task = QCTask(
            rating=RatingConfig(
                type="multi",
                scale=["PASS", "FAIL", "UNCERTAIN"],
                facets=["frontal", "parietal", "temporal", "occipital"],
            )
        )

        assert task.rating is not None
        assert task.rating.type == "multi"
        assert task.rating.scale == ["PASS", "FAIL", "UNCERTAIN"]
        assert task.rating.facets == ["frontal", "parietal", "temporal", "occipital"]


class TestQCConfig:
    """Test QCConfig model."""

    def test_create_qc_config_from_dict(self, temp_dir):
        """Test creating QCConfig from dictionary."""
        config_dict = {
            "anat_wf_qc": QCTask(base_mri_image_path=temp_dir / "base.nii.gz"),
            "func_wf_qc": QCTask(base_mri_image_path=temp_dir / "func_base.nii.gz"),
        }

        config = QCConfig(config_dict)

        assert "anat_wf_qc" in config.root
        assert "func_wf_qc" in config.root

    def test_qc_config_json_parsing(self, sample_qc_config):
        """Test parsing QCConfig from JSON file."""
        with open(sample_qc_config, "r") as f:
            json_str = f.read()

        config = QCConfig.model_validate_json(json_str)

        assert "anat_wf_qc" in config.root
        assert "func_wf_qc" in config.root
        assert config.root["anat_wf_qc"].base_mri_image_path is not None

    def test_qc_config_access_tasks(self, sample_qc_config):
        """Test accessing tasks from QCConfig."""
        with open(sample_qc_config, "r") as f:
            json_str = f.read()

        config = QCConfig.model_validate_json(json_str)

        anat_task = config.root.get("anat_wf_qc")
        assert anat_task is not None
        assert isinstance(anat_task, QCTask)

    def test_qc_config_with_none_values(self):
        """Test QCConfig with None values in tasks."""
        config_dict = {"test_task": QCTask(base_mri_image_path=None, overlay_mri_image_path=None)}

        config = QCConfig(config_dict)

        assert config.root["test_task"].base_mri_image_path is None

    def test_qc_config_invalid_json(self):
        """Test QCConfig with invalid JSON."""
        with pytest.raises(Exception):  # Will raise validation error
            QCConfig.model_validate_json("{ invalid }")

    def test_qc_config_serialization(self, sample_qc_config):
        """Test QCConfig serialization."""
        with open(sample_qc_config, "r") as f:
            json_str = f.read()

        config = QCConfig.model_validate_json(json_str)
        serialized = config.model_dump()

        assert isinstance(serialized, dict)
        assert "anat_wf_qc" in serialized
