"""Pytest configuration and fixtures for UI tests."""

import gzip
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Add parent directory (ui/) to path so imports work correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import QCRecord, MetricQC


def pytest_configure(config):
    """Configure pytest with markers."""
    config.addinivalue_line("markers", "unit: unit test")
    config.addinivalue_line("markers", "integration: integration test")
    config.addinivalue_line("markers", "slow: slow running test")


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_participant_list(temp_dir):
    """Create a sample participant list TSV file."""
    data = {"participant_id": ["sub-CMH0001", "sub-CMH0002", "sub-CMH0003"], "group": ["control", "patient", "control"]}
    df = pd.DataFrame(data)
    file_path = temp_dir / "participants.tsv"
    df.to_csv(file_path, sep="\t", index=False)
    return file_path


@pytest.fixture
def sample_qc_config(temp_dir):
    """Create a sample QC configuration JSON file."""
    config = {
        "anat_wf_qc": {
            "base_mri_image_path": str(temp_dir / "base.nii.gz"),
            "overlay_mri_image_path": str(temp_dir / "overlay.nii.gz"),
            "montage_path": str(temp_dir / "montage.svg"),
            "iqm_path": str(temp_dir / "iqm.json"),
        },
        "func_wf_qc": {
            "base_mri_image_path": str(temp_dir / "func_base.nii.gz"),
            "overlay_mri_image_path": None,
            "montage_path": str(temp_dir / "func_montage.svg"),
            "iqm_path": None,
        },
    }
    file_path = temp_dir / "qc_config.json"
    with open(file_path, "w") as f:
        json.dump(config, f)
    return file_path


@pytest.fixture
def sample_qc_results_csv(temp_dir):
    """Create a sample QC results CSV file."""
    data = {
        "pipeline": ["fmriprep", "fmriprep"],
        "qc_task": ["anat_wf_qc", "anat_wf_qc"],
        "participant_id": ["sub-CMH0001", "sub-CMH0002"],
        "session_id": ["ses-01", "ses-01"],
        "timestamp": ["2024-01-01 10:00:00", "2024-01-01 11:00:00"],
        "rater_id": ["rater1", "rater1"],
        "rater_experience": ["Expert (>5 year experience)", "Expert (>5 year experience)"],
        "rater_fatigue": ["Not at all", "A bit tired ☕"],
        "rater_screen_size": ["26-30", "15-20in"],
        "final_qc": ["PASS", "FAIL"],
        "notes": ["Good quality", "Artifacts detected"],
    }
    df = pd.DataFrame(data)
    file_path = temp_dir / "qc_results.tsv"
    df.to_csv(file_path, sep="\t", index=False)
    return file_path


@pytest.fixture
def sample_montage_content():
    """Create sample Montage content."""
    return """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
        <circle cx="50" cy="50" r="40" fill="blue" />
    </svg>"""


@pytest.fixture
def sample_montage_file(temp_dir, sample_montage_content):
    """Create a sample Montage file."""
    file_path = temp_dir / "montage.svg"
    file_path.write_text(sample_montage_content)
    return file_path


@pytest.fixture
def sample_nii_gz_file(temp_dir):
    """Create a sample NIfTI gzipped file (minimal valid content)."""
    # Create minimal NIfTI header (348 bytes)
    nifti_header = bytearray(348)
    nifti_header[0:4] = b"\x08\x00\x00\x00"  # sizeof_hdr
    nifti_header[40:44] = (1, 1, 1, 1)  # shape

    file_path = temp_dir / "brain.nii.gz"
    with gzip.open(file_path, "wb") as f:
        f.write(bytes(nifti_header))
    return file_path


@pytest.fixture
def sample_mri_files(temp_dir):
    """Create sample MRI files for testing."""
    # Create base MRI file
    base_file = temp_dir / "base.nii.gz"
    overlay_file = temp_dir / "overlay.nii.gz"

    nifti_header = bytearray(348)
    nifti_header[0:4] = b"\x08\x00\x00\x00"

    for file_path in [base_file, overlay_file]:
        with gzip.open(file_path, "wb") as f:
            f.write(bytes(nifti_header))

    return {"base": base_file, "overlay": overlay_file}


@pytest.fixture
def sample_iqm_data(temp_dir):
    """Create a sample IQM JSON file."""
    iqm_data = {
        "aor": 0.95,
        "cnr": 45.2,
        "conc": 0.02,
        "efc": 0.78,
        "fber": 12.5,
        "fwhm_avg": 2.5,
        "fwhm_x": 2.4,
        "fwhm_y": 2.5,
        "fwhm_z": 2.6,
        "gsr": 65.0,
        "icvs_csf": 0.10,
        "icvs_gm": 0.45,
        "icvs_wm": 0.45,
        "inu_med": 1.0,
        "inu_range": 0.05,
        "qi1": 1.0,
        "qi2": 0.95,
        "rpve_csf": 0.05,
        "rpve_gm": 0.08,
        "rpve_wm": 0.06,
        "snr_csf": 45.0,
        "snr_gm": 40.0,
        "snr_wm": 50.0,
        "snr_total": 42.0,
        "tpm_overlap_csf": 0.8,
        "tpm_overlap_gm": 0.85,
        "tpm_overlap_wm": 0.9,
        "wm_hypointensity": 0.01,
    }
    file_path = temp_dir / "iqm.json"
    with open(file_path, "w") as f:
        json.dump(iqm_data, f)
    return file_path


@pytest.fixture
def sample_session_state():
    """Create a mock Streamlit session state."""
    state = {
        "current_page": 1,
        "batch_size": 1,
        "current_batch_qc": {},
        "qc_records": [],
        "rater_id": "test_rater",
        "rater_experience": "Expert (>5 year experience)",
        "rater_fatigue": "Not at all",
        "rater_screen_size": "26-30",
        "notes": "",
        "landing_page_complete": False,
        "selected_panels": {"niivue_col": True, "montage_col": True, "iqm_col": False},
    }
    return state


@pytest.fixture
def qc_record_sample():
    """Create a sample QCRecord object."""
    return QCRecord(
        participant_id="sub-CMH0001",
        session_id="ses-01",
        qc_task="anat_wf_qc",
        pipeline="fmriprep",
        timestamp="2024-01-01 10:00:00",
        rater_id="test_rater",
        rater_experience="Expert (>5 year experience)",
        rater_fatigue="Not at all",
        rater_screen_size="26-30",
        final_qc="PASS",
        notes="Good quality scan",
    )


@pytest.fixture
def sample_qc_config_with_files(temp_dir, sample_mri_files, sample_montage_file, sample_iqm_data):
    """Create a sample QC configuration JSON file with actual file paths."""
    config = {
        "anat_wf_qc": {
            "base_mri_image_path": str(sample_mri_files["base"]),
            "overlay_mri_image_path": str(sample_mri_files["overlay"]),
            "montage_path": str(sample_montage_file),
            "iqm_path": str(sample_iqm_data),
        },
        "func_wf_qc": {
            "base_mri_image_path": str(temp_dir / "func_base.nii.gz"),
            "overlay_mri_image_path": None,
            "montage_path": str(temp_dir / "func_montage.svg"),
            "iqm_path": None,
        },
    }
    file_path = temp_dir / "qc_config.json"
    with open(file_path, "w") as f:
        json.dump(config, f)
    return file_path


@pytest.fixture
def sample_participants_with_sessions(temp_dir):
    """Create a sample participants file with multiple sessions."""
    data = {
        "participant_id": ["sub-CMH0001", "sub-CMH0001", "sub-CMH0002", "sub-CMH0002", "sub-CMH0003"],
        "session_id": ["ses-01", "ses-02", "ses-01", "ses-02", "ses-01"],
        "group": ["control", "control", "patient", "patient", "control"],
    }
    df = pd.DataFrame(data)
    file_path = temp_dir / "participants_sessions.tsv"
    df.to_csv(file_path, sep="\t", index=False)
    return file_path


@pytest.fixture
def empty_qc_records_csv(temp_dir):
    """Create an empty QC results CSV file with proper headers."""
    data = {
        "pipeline": [],
        "qc_task": [],
        "participant_id": [],
        "session_id": [],
        "task_id": [],
        "run_id": [],
        "timestamp": [],
        "rater_id": [],
        "rater_experience": [],
        "rater_fatigue": [],
        "rater_screen_size": [],
        "final_qc": [],
        "notes": [],
    }
    df = pd.DataFrame(data)
    file_path = temp_dir / "empty_qc_results.tsv"
    df.to_csv(file_path, sep="\t", index=False)
    return file_path


@pytest.fixture
def metric_qc_sample():
    """Create a sample MetricQC object."""
    return MetricQC(metric_name="SNR", metric_value=45.2, average_metric_value=42.0, pass_fail_threshold=40.0, pass_fail_status="PASS")


@pytest.fixture
def mock_streamlit(sample_session_state):
    """Mock Streamlit module and its session_state."""
    with patch("layout.st") as mock_st:
        # Create a more realistic session state mock that behaves like a dictionary
        session_state_dict = sample_session_state.copy()

        mock_session_state = MagicMock()
        mock_session_state.__getitem__ = MagicMock(side_effect=lambda x: session_state_dict.get(x))
        mock_session_state.__setitem__ = MagicMock(side_effect=lambda k, v: session_state_dict.update({k: v}))
        mock_session_state.get = MagicMock(side_effect=lambda x, default=None: session_state_dict.get(x, default))
        mock_session_state.__contains__ = MagicMock(side_effect=lambda x: x in session_state_dict)

        mock_st.session_state = mock_session_state

        # Add common Streamlit methods as mocks
        mock_st.title = MagicMock()
        mock_st.subheader = MagicMock()
        mock_st.error = MagicMock()
        mock_st.warning = MagicMock()
        mock_st.success = MagicMock()
        mock_st.info = MagicMock()
        mock_st.write = MagicMock()
        mock_st.markdown = MagicMock()
        mock_st.columns = MagicMock(return_value=(MagicMock(), MagicMock(), MagicMock()))
        mock_st.form = MagicMock()
        mock_st.form().return_value.__enter__ = MagicMock()
        mock_st.form().return_value.__exit__ = MagicMock(return_value=False)
        mock_st.text_input = MagicMock()
        mock_st.text_area = MagicMock()
        mock_st.radio = MagicMock()
        mock_st.checkbox = MagicMock()
        mock_st.selectbox = MagicMock()
        mock_st.multiselect = MagicMock()
        mock_st.file_uploader = MagicMock()
        mock_st.set_page_config = MagicMock()
        mock_st.rerun = MagicMock()

        yield mock_st
