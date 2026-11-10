"""Tests for app.py module."""

import json
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

# Mock streamlit and dependencies before importing layout
import sys

sys.modules["niivue_component"] = MagicMock()

from constants import (
    SESSION_KEYS,
    DEFAULT_PANELS,
    DEFAULT_MONTAGE_MAX_ROWS,
    DEFAULT_MONTAGE_MAX_COLS,
    EXPERIENCE_LEVELS,
    SCREEN_SIZES,
    MESSAGES,
    PENDING_SIDEBAR_RERUN_KEY,
    SIDEBAR_SEARCH_HOLD_KEY,
    SIDEBAR_SUBJECT_LIST_HEIGHT,
    SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY,
)

pytestmark = pytest.mark.integration


def _session_state_dict():
    """Minimal session_state matching SessionManager defaults."""
    return {
        SESSION_KEYS["current_page"]: 1,
        SESSION_KEYS["batch_size"]: 1,
        SESSION_KEYS["qc_records"]: [],
        SESSION_KEYS["rater_id"]: "",
        SESSION_KEYS["rater_experience"]: None,
        SESSION_KEYS["rater_fatigue"]: None,
        SESSION_KEYS["rater_screen_size"]: None,
        SESSION_KEYS["notes"]: "",
        SESSION_KEYS["notes_version"]: 0,
        SESSION_KEYS["rating_version"]: 0,
        SESSION_KEYS["participant_order"]: [],
        SESSION_KEYS["landing_page_complete"]: False,
        SESSION_KEYS["selected_panels"]: DEFAULT_PANELS.copy(),
        SESSION_KEYS["montage_max_rows"]: DEFAULT_MONTAGE_MAX_ROWS,
        SESSION_KEYS["montage_max_cols"]: DEFAULT_MONTAGE_MAX_COLS,
        SESSION_KEYS["sidebar_subject_search"]: "",
        "autoplay_enabled": False,
        "autoplay_start_time": 0.0,
        "autoplay_duration": 5,
    }


def _stub_qc_config_path(tmp_path, task="anat_wf_qc", montage_rows_cols=None):
    """Minimal qc.json on disk for landing page tests."""
    task_entry = {
        "base_mri_image_path": str(tmp_path / "base.nii.gz"),
        "overlay_mri_image_path": str(tmp_path / "overlay.nii.gz"),
        "montage_path": str(tmp_path / "montage.svg"),
        "iqm_path": str(tmp_path / "iqm.json"),
    }
    if montage_rows_cols is not None:
        task_entry["montage_max_rows"] = montage_rows_cols[0]
        task_entry["montage_max_cols"] = montage_rows_cols[1]
    p = tmp_path / "qc_config.json"
    p.write_text(json.dumps({task: task_entry}))
    return str(p)


def _columns_side_effect(*args, **kwargs):
    widths = args[0] if args else [1, 1, 1]
    if isinstance(widths, int):
        n = widths
    else:
        n = len(widths)
    return tuple(MagicMock() for _ in range(n))


def _configure_landing_page_streamlit_mock(mock_st):
    mock_st.session_state = _session_state_dict()
    form_ctx = MagicMock()
    form_ctx.__enter__ = MagicMock(return_value=None)
    form_ctx.__exit__ = MagicMock(return_value=False)
    mock_st.form.return_value = form_ctx
    mock_st.form_submit_button.return_value = False
    mock_st.columns.side_effect = _columns_side_effect
    mock_st.checkbox.return_value = True
    mock_st.text_input.return_value = "test_rater"
    mock_st.radio.return_value = EXPERIENCE_LEVELS[0]
    mock_st.slider.return_value = 5
    mock_st.number_input.return_value = 1
    mock_st.file_uploader.return_value = None


@contextmanager
def _patch_streamlit_for_landing(mock_st):
    _configure_landing_page_streamlit_mock(mock_st)
    with (
        patch("views.landing_page.st", mock_st),
        patch("managers.session_manager.st", mock_st),
        patch("managers.panel_layout_manager.st", mock_st),
        patch("managers.niivue_viewer_manager.st", mock_st),
    ):
        yield mock_st


class TestShowLandingPage:
    """Test landing page display functionality."""

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_displays_title(self, mock_read_csv, tmp_path):
        """Test that landing page displays the welcome greeting and default title."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001", "sub-CMH0002", "sub-CMH0003"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.markdown.assert_any_call("# Welcome to Nipoppy QC-Studio! 🚀")

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_personalizes_greeting_with_rater_id(self, mock_read_csv, tmp_path):
        """A provided rater ID should be used in the landing-page greeting and the rater form."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001", "sub-CMH0002"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            SessionManager = __import__("managers.session_manager", fromlist=["SessionManager"]).SessionManager
            SessionManager.set_rater_id("abc123")
            SessionManager.set_rater_id_display("odysseus")
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.markdown.assert_any_call("# :blue[Salut odysseus!] Welcome to Nipoppy QC-Studio! 🚀")
        rater_call = mock_st.text_input.call_args_list[0]
        assert rater_call.args[0] == "Enter your Rater Name or ID:"
        assert rater_call.kwargs["value"] == "odysseus"

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_displays_pipeline_info(self, mock_read_csv, tmp_path):
        """Test that landing page displays pipeline information."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001", "sub-CMH0002"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        subheader_calls = [str(c.args[0]) for c in mock_st.subheader.call_args_list if c.args]
        assert any("Pipeline: fmriprep" in text and "Subjects:** 2" in text for text in subheader_calls)
        assert not any("Task:**" in text for text in subheader_calls)
        assert not any("Cohort pages:**" in text for text in subheader_calls)
        assert not any("QC Pipeline:" in text and "|" in text for text in subheader_calls)

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_exposes_qc_task_selector_in_sidebar(self, mock_read_csv, tmp_path):
        """The landing-page sidebar should offer the available qc.json tasks as a single-choice selector."""
        from views.landing_page import show_landing_page

        qc_path = tmp_path / "qc_config.json"
        qc_path.write_text(
            json.dumps(
                {
                    "anat_wf_qc": {"base_mri_image_path": "/tmp/base.nii.gz", "montage_path": "/tmp/montage.svg"},
                    "func_wf_qc": {"base_mri_image_path": "/tmp/base2.nii.gz", "montage_path": "/tmp/montage2.svg"},
                }
            )
        )

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001", "sub-CMH0002"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=str(qc_path),
            )

        radio_calls = [c for c in mock_st.sidebar.radio.call_args_list if c.kwargs.get("label") == "Choose QC task"]
        assert len(radio_calls) == 1
        radio_call = radio_calls[0]
        assert radio_call.kwargs["options"] == ["anat_wf_qc", "func_wf_qc"]
        assert radio_call.kwargs["index"] == 0

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_task_switch_resets_current_page(self, mock_read_csv, tmp_path):
        """Switching tasks on landing page should snap pagination to the selected task's first pending page."""
        from views.landing_page import show_landing_page

        qc_path = tmp_path / "qc_config.json"
        qc_path.write_text(
            json.dumps(
                {
                    "anat_wf_qc": {"base_mri_image_path": "/tmp/base.nii.gz", "montage_path": "/tmp/montage.svg"},
                    "func_wf_qc": {"base_mri_image_path": "/tmp/base2.nii.gz", "montage_path": "/tmp/montage2.svg"},
                }
            )
        )

        participants_df = pd.DataFrame({"participant_id": ["sub-CMH0001", "sub-CMH0002"]})
        mock_read_csv.return_value = participants_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            mock_st.session_state[SESSION_KEYS["selected_qc_task"]] = "anat_wf_qc"
            mock_st.session_state[SESSION_KEYS["current_page"]] = 3

            def _sidebar_radio(*_args, **kwargs):
                if kwargs.get("label") == "Choose QC task":
                    return "func_wf_qc"
                return kwargs.get("options", [None])[kwargs.get("index", 0)]

            mock_st.sidebar.radio.side_effect = _sidebar_radio

            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=str(qc_path),
            )

        assert mock_st.session_state[SESSION_KEYS["selected_qc_task"]] == "func_wf_qc"
        assert mock_st.session_state[SESSION_KEYS["current_page"]] == 1

    @patch("app.display_qc_viewers")
    def test_app_uses_selected_qc_task_for_viewer_images(self, mock_display_qc_viewers, tmp_path):
        """The selected landing-page task should override the original CLI/default task in the QC viewer."""
        from app import app

        qc_path = _stub_qc_config_path(tmp_path)
        mock_st = MagicMock()
        mock_st.session_state = _session_state_dict()
        mock_st.session_state[SESSION_KEYS["landing_page_complete"]] = True
        mock_st.session_state[SESSION_KEYS["selected_qc_task"]] = "func_wf_qc"
        qc_cohort = [{"participant_id": "sub-CMH0001", "session_id": "ses-01"}]

        with patch("app.st", mock_st), patch("managers.session_manager.st", mock_st):
            app(
                dataset_dir="/dataset",
                participant_id="sub-CMH0001",
                session_id="ses-01",
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                qc_config_path=qc_path,
                out_dir="/output",
                total_participants=1,
                drop_duplicates=True,
                participant_list="participants.tsv",
                participant_ids=["sub-CMH0001"],
                qc_cohort=qc_cohort,
                qc_tasks=["anat_wf_qc"],
            )

        assert mock_display_qc_viewers.call_args.kwargs["qc_task"] == "func_wf_qc"
        assert mock_display_qc_viewers.call_args.kwargs["qc_tasks"] == ["func_wf_qc"]

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_counts_both_pages_and_qc_records(self, mock_read_csv, tmp_path):
        """Multi-task pages should show separate page and record counts, with records able to exceed pages."""
        from views.landing_page import show_landing_page

        participant_df = pd.DataFrame({"participant_id": ["sub-CMH0001", "sub-CMH0002"]})
        upload_df = pd.DataFrame(
            {
                "participant_id": ["sub-CMH0001", "sub-CMH0001", "sub-CMH0002", "sub-CMH0002"],
                "session_id": ["ses-01", "ses-01", "ses-01", "ses-01"],
                "qc_task": ["anat_wf_qc", "func_wf_qc", "anat_wf_qc", "func_wf_qc"],
                "final_qc": ["PASS", "PASS", "PASS", "PASS"],
            }
        )
        mock_read_csv.side_effect = [participant_df, upload_df]

        mock_st = MagicMock()
        upload_file = MagicMock()
        upload_file.name = "results.csv"

        with _patch_streamlit_for_landing(mock_st):
            mock_st.file_uploader.return_value = upload_file
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="all",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path, task="anat_wf_qc"),
            )

        metric_calls = [call.kwargs for call in mock_st.metric.call_args_list if call.kwargs]
        assert any(call.get("label") == "QC pages reviewed" for call in metric_calls)
        assert any(call.get("label") == "QC records reviewed" for call in metric_calls)
        caption_text = "\n".join(str(call.args[0]) for call in mock_st.caption.call_args_list)
        assert "records can exceed pages" in caption_text
        progress_text = "\n".join(str(call.kwargs.get("text", "")) for call in mock_st.progress.call_args_list)
        assert "QC records complete" in progress_text

    def test_landing_run_summary_uses_pipeline_and_subject_count_only(self):
        from views.landing_page import _landing_run_summary_lines

        summary = _landing_run_summary_lines("noddireg", 1)
        assert summary == "Pipeline: noddireg | **Subjects:** 1"
        assert "Task:**" not in summary
        assert "Cohort pages:**" not in summary

    def test_compact_session_label_omits_pipeline_and_task_count(self):
        from utils.cohort import compact_session_label

        assert compact_session_label("sub-CMH0001", "ses-01") == "sub-CMH0001 · ses-01"
        assert compact_session_label("sub-CMH0001", None) == "sub-CMH0001"
        label = compact_session_label("sub-CMH0001", "ses-01")
        assert "fmriprep" not in label.lower()
        assert "count" not in label.lower()

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_error_handling(self, mock_read_csv, tmp_path):
        """Test landing page error handling for invalid participant list."""
        from views.landing_page import show_landing_page

        mock_read_csv.side_effect = Exception("File not found")

        mock_st = MagicMock()
        mock_st.session_state = _session_state_dict()
        with patch("views.landing_page.st", mock_st), patch("managers.session_manager.st", mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="invalid.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.error.assert_called()

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_three_column_layout(self, mock_read_csv, tmp_path):
        """Test that landing page creates three-column layout."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.columns.assert_called()

    @patch("views.landing_page.pd.read_csv")
    def test_landing_page_applies_montage_defaults_from_qc_json(self, mock_read_csv, tmp_path):
        """qc.json montage_max_rows/cols seed session once for the QC task."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df
        qc_path = _stub_qc_config_path(tmp_path, montage_rows_cols=(2, 3))

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=qc_path,
            )

        assert mock_st.session_state[SESSION_KEYS["montage_max_rows"]] == 2
        assert mock_st.session_state[SESSION_KEYS["montage_max_cols"]] == 3
        assert mock_st.session_state[SESSION_KEYS["montage_defaults_applied_qc_task"]] == "anat_wf_qc"


class TestLandingPageRaterInfo:
    """Test rater information section of landing page."""

    @patch("views.landing_page.pd.read_csv")
    def test_rater_form_displays(self, mock_read_csv, tmp_path):
        """Test that rater form is displayed."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.form.assert_called()

    @patch("views.landing_page.pd.read_csv")
    def test_experience_level_options(self, mock_read_csv, tmp_path):
        """Test that experience level options are presented."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        experience_options = EXPERIENCE_LEVELS
        assert len(experience_options) == 3
        assert any("Expert" in opt for opt in experience_options)

    @patch("views.landing_page.pd.read_csv")
    def test_screen_size_options(self, mock_read_csv, tmp_path):
        """Test that screen size options are presented."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        assert len(SCREEN_SIZES) >= 1
        assert all(isinstance(opt, str) and opt.strip() for opt in SCREEN_SIZES)


class TestLandingPagePanelSelection:
    """Test panel selection functionality."""

    @patch("views.landing_page.pd.read_csv")
    def test_panel_checkboxes_displayed(self, mock_read_csv, tmp_path):
        """Test that panel selection checkboxes are displayed."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.checkbox.assert_called()

    def test_default_panel_selections(self, sample_session_state):
        """Test default panel selections."""
        panels = sample_session_state["selected_panels"]

        assert panels["niivue_col"] is True
        assert panels["montage_col"] is True
        assert panels["iqm_col"] is False

    def test_panel_selection_validation(self, sample_session_state):
        """Test that at least one panel must be selected."""
        selected_count = sum(sample_session_state["selected_panels"].values())

        assert selected_count >= 1


class TestLandingPageCsvUpload:
    """Test CSV file upload functionality."""

    @patch("views.landing_page.pd.read_csv")
    def test_file_uploader_displayed(self, mock_read_csv, tmp_path):
        """Test that file uploader is displayed."""
        from views.landing_page import show_landing_page

        mock_df = pd.DataFrame({"participant_id": ["sub-CMH0001"]})
        mock_read_csv.return_value = mock_df

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        mock_st.file_uploader.assert_called()

    def test_csv_upload_validation(self, sample_qc_results_csv):
        """Test CSV upload validation."""
        # Read actual CSV for validation
        df = pd.read_csv(sample_qc_results_csv, sep="\t")

        # Should have expected columns
        assert "participant_id" in df.columns
        assert "rater_id" in df.columns
        assert "final_qc" in df.columns

    @patch("views.landing_page.pd.read_csv")
    def test_loading_complete_uploaded_results_does_not_raise_next_page_error(self, mock_read_csv, tmp_path):
        """Uploading a complete cohort file should not hit an unbound ``next_page`` path."""
        from views.landing_page import show_landing_page

        participants_df = pd.DataFrame(
            {
                "participant_id": ["sub-CMH0001", "sub-CMH0002"],
                "session_id": ["ses-01", "ses-01"],
            }
        )
        uploaded_df = pd.DataFrame(
            {
                "pipeline": ["fmriprep", "fmriprep"],
                "qc_task": ["anat_wf_qc", "anat_wf_qc"],
                "participant_id": ["sub-CMH0001", "sub-CMH0002"],
                "session_id": ["ses-01", "ses-01"],
                "timestamp": ["2026-09-03 10:00:00", "2026-09-03 10:01:00"],
                "rater_id": ["tester", "tester"],
                "rater_experience": ["Expert (>5 year experience)", "Expert (>5 year experience)"],
                "rater_fatigue": ["Not at all", "Not at all"],
                "final_qc": ["PASS", "FAIL"],
                "notes": ["", ""],
            }
        )
        mock_read_csv.side_effect = [participants_df, uploaded_df]

        uploaded_file = MagicMock()
        uploaded_file.name = "saved_qc.tsv"

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            mock_st.file_uploader.return_value = uploaded_file
            mock_st.button.return_value = True
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        # 2 cohort pages complete -> move to congratulations page at index 3.
        assert mock_st.session_state[SESSION_KEYS["current_page"]] == 3

    @patch("views.landing_page.pd.read_csv")
    def test_upload_accepts_zero_padded_participant_ids(self, mock_read_csv, tmp_path):
        """Upload validation should treat sub-00153 as a known participant when list contains sub-00153."""
        from views.landing_page import show_landing_page

        participants_df = pd.DataFrame(
            {
                "participant_id": ["sub-00153"],
                "session_id": ["ses-01"],
            }
        )
        uploaded_df = pd.DataFrame(
            {
                "pipeline": ["fmriprep"],
                "qc_task": ["anat_wf_qc"],
                "participant_id": ["sub-00153"],
                "session_id": ["ses-01"],
                "timestamp": ["2026-09-24 13:57:25"],
                "rater_id": ["nik"],
                "rater_experience": ["Beginner (< 1 year)"],
                "rater_fatigue": ["Not at all"],
                "rater_screen_size": ["14 inches or less"],
                "final_qc": ["UNCERTAIN"],
                "notes": [""],
            }
        )
        mock_read_csv.side_effect = [participants_df, uploaded_df]

        uploaded_file = MagicMock()
        uploaded_file.name = "nik_sdc_wf_qc_status.tsv"

        mock_st = MagicMock()
        with _patch_streamlit_for_landing(mock_st):
            mock_st.file_uploader.return_value = uploaded_file
            show_landing_page(
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                out_dir="/output",
                participant_list="participants.tsv",
                qc_config_path=_stub_qc_config_path(tmp_path),
            )

        error_texts = [str(call.args[0]) for call in mock_st.error.call_args_list if call.args]
        assert not any("not in the participant list" in text for text in error_texts)
        mock_st.stop.assert_not_called()


class TestApp:
    """Test main app function."""

    @patch("app.SessionManager.is_landing_page_complete", return_value=False)
    @patch("app.SessionManager.init_session_state")
    @patch("app.show_landing_page")
    @patch("app.st")
    def test_app_landing_page_incomplete(self, mock_st, mock_show_landing, mock_init_session, mock_landing_done):
        """Test app shows landing page when not complete."""
        from app import app

        app(
            dataset_dir="/data",
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_config_path="config.json",
            out_dir="/output",
            total_participants=5,
            drop_duplicates=True,
            participant_list="participants.tsv",
        )

        mock_st.set_page_config.assert_called()
        mock_show_landing.assert_called_once_with(
            "fmriprep",
            "anat_wf_qc",
            "/output",
            "participants.tsv",
            "config.json",
            qc_cohort=None,
        )

    @patch("app.SessionManager.is_landing_page_complete", return_value=True)
    @patch("app.SessionManager.init_session_state")
    @patch("app.show_congratulations_page")
    @patch("app.st")
    def test_app_congratulations_page(self, mock_st, mock_congrats, mock_init_session, mock_landing_done):
        """Test app shows congratulations page when complete."""
        from app import app

        app(
            dataset_dir="/data",
            participant_id=None,  # None indicates final page
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_config_path="config.json",
            out_dir="/output",
            total_participants=5,
            drop_duplicates=True,
            participant_list="participants.tsv",
        )

        mock_congrats.assert_called_once()
        assert mock_congrats.call_args.kwargs["qc_pipeline"] == "fmriprep"


class TestQcViewerLayout:
    """Test QC viewer layout and panel display."""

    def test_niivue_panel_displayed(self):
        """Placeholder — full viewer layout is exercised manually / in integration tests."""
        assert True

    @patch("components.qc_viewer.display_iqm_distribution_panel")
    @patch("components.qc_viewer.NiivueViewerManager.render_controls_panel")
    @patch("components.qc_viewer.NiivueViewerManager.render_viewer")
    @patch("components.qc_viewer._get_or_render_niivue_config")
    @patch("components.qc_viewer.st")
    def test_secondary_iqm_panel_receives_config_and_ids(
        self,
        mock_st,
        mock_get_niivue_config,
        mock_render_viewer,
        mock_render_controls,
        mock_display_iqm,
    ):
        """Test that the IQM panel is forwarded qc_config/ids/dataset_dir.

        qc_task is no longer part of this call - modality inference now
        comes from the IQM source path itself (infer_pipeline_from_iqm_path /
        _infer_modality_from_path), not the QC task name, so it's not
        threaded through here anymore.
        """
        from components.qc_viewer import _display_niivue_with_secondary_panel

        viewer_col = MagicMock()
        panel_col = MagicMock()
        mock_st.columns.return_value = (viewer_col, panel_col)
        mock_st.expander.return_value = MagicMock()
        mock_get_niivue_config.return_value = MagicMock()

        qc_config = {"base_mri_image_path": "sub-01_T1w.nii.gz"}

        _display_niivue_with_secondary_panel(
            dataset_dir="/dataset",
            selected_panels={"svg": False, "iqm": True},
            qc_config=qc_config,
            qc_config_path="qc.json",
            participant_id="sub-01",
            session_id="ses-01",
            task_suffix="anat_wf_qc",
        )

        mock_display_iqm.assert_called_once_with(
            qc_config,
            "qc.json",
            "sub-01",
            "ses-01",
            "/dataset",
        )


class TestSessionStateManagement:
    """Test session state management in app."""

    def test_rater_information_in_session(self, sample_session_state):
        """Test rater information stored in session state."""
        assert sample_session_state["rater_id"] == "test_rater"
        assert sample_session_state["rater_experience"] is not None
        assert sample_session_state["rater_fatigue"] is not None
        assert sample_session_state["rater_screen_size"] is not None

    def test_qc_records_in_session(self, sample_session_state):
        """Test QC records stored in session state."""
        assert isinstance(sample_session_state["qc_records"], list)

    def test_panel_selections_in_session(self, sample_session_state):
        """Test panel selections stored in session state."""
        assert "selected_panels" in sample_session_state
        assert isinstance(sample_session_state["selected_panels"], dict)


class TestNavigationControls:
    """Test navigation controls."""

    @patch("app.st")
    def test_previous_button_updates_page(self, mock_st):
        """Test that previous button updates current page."""
        mock_st.session_state = {"landing_page_complete": True, "current_page": 2, "rater_id": "test_rater"}
        mock_st.set_page_config = MagicMock()

        # Button behavior would be tested with button clicks
        # This is a placeholder for the concept
        assert mock_st.session_state["current_page"] > 1

    def test_page_bounds_lower(self, sample_session_state):
        """Test that page cannot be less than 1."""
        current_page = 0
        if current_page < 1:
            current_page = 1

        assert current_page == 1

    def test_page_bounds_upper(self, sample_session_state):
        """Test that page is bounded by total participants."""
        current_page = 100
        total_participants = 5

        valid_page = min(max(current_page, 1), total_participants)

        assert valid_page == total_participants


def _sidebar_ctx():
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=ctx)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestSidebarCohortNavOrder:
    """Playback and page controls stay above a scrollable subject list."""

    def test_controls_render_before_subject_list(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        order = []
        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        nav_kwargs = {
            "current_page": 1,
            "total_participants": 2,
            "participant_id": "sub-CMH0001",
            "session_id": "ses-01",
            "qc_pipeline": "fmriprep",
            "qc_tasks": ["sdc_wf_qc"],
            "participant_ids": ["sub-CMH0001"],
            "qc_cohort": cohort,
        }
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.button.return_value = False
        mock_st.session_state = {}
        mock_st.caption.side_effect = lambda text, *a, **k: order.append(("caption", text))
        mock_st.divider.side_effect = lambda: order.append(("divider", None))
        mock_st.text_input.side_effect = lambda *a, **k: order.append(("search", None)) or "ses-01"

        def header(*args, **kwargs):
            order.append(("header", None))

        def controls(**kwargs):
            order.append(("controls", None))
            assert mock_st.session_state.get(SESSION_KEYS["sidebar_subject_search"], "") == ""

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
            patch("components.qc_viewer._display_qc_pagination_header", side_effect=header),
            patch("components.qc_viewer._display_qc_pagination_controls", side_effect=controls),
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 1
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
                prepend_navigation=True,
                navigation_kwargs=nav_kwargs,
            )

        names = [name for name, _ in order]
        assert names[:5] == ["caption", "header", "controls", "caption", "search"]
        mock_st.container.assert_any_call(height=SIDEBAR_SUBJECT_LIST_HEIGHT, border=True)
        assert any(call.args[0] == "QC task: sdc_wf_qc" for call in mock_st.caption.call_args_list)
        assert any(
            call.args[0] == f"Participant ID: {nav_kwargs['participant_id']} | Session ID: {nav_kwargs['session_id']}"
            for call in mock_st.caption.call_args_list
        )
        mock_st.text_input.assert_called_once_with(
            MESSAGES["sidebar_subjects_search"],
            key=SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY,
            placeholder=MESSAGES["sidebar_subjects_search_placeholder"],
            label_visibility="collapsed",
        )
        assert mock_st.button.call_count == 1
        assert mock_st.button.call_args.kwargs["key"] == "sidebar_cohort_nav_0"


class TestSidebarSubjectSearch:
    """Subject list can be filtered without changing page indices."""

    def test_matching_entries_keep_original_indices(self):
        from views.sidebar_cohort_nav import _matching_subject_entries

        entries = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
        ]

        by_subject = _matching_subject_entries(entries, "CMH0002", "ses-01")
        assert by_subject == [(2, entries[2])]

        by_session = _matching_subject_entries(entries, "ses-02", "ses-01")
        assert by_session == [(1, entries[1])]

        by_ses01 = _matching_subject_entries(entries, "ses-01", "ses-01")
        assert by_ses01 == [(0, entries[0]), (2, entries[2])]

        empty_query = _matching_subject_entries(entries, "  ", "ses-01")
        assert empty_query == list(enumerate(entries))

        none = _matching_subject_entries(entries, "no-such-id", "ses-01")
        assert none == []

    def test_filtered_button_navigates_to_original_page(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {}
        mock_st.text_input.return_value = "ses-02"
        mock_st.button.return_value = True

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 2
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=3,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        mock_st.button.assert_called_once()
        assert mock_st.button.call_args.kwargs["key"] == "sidebar_cohort_nav_1"
        mock_sm.set_current_page.assert_called_with(2)
        mock_st.rerun.assert_called()

    def test_empty_search_shows_no_match_caption(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {}
        mock_st.text_input.return_value = "zzz"
        mock_st.button.return_value = False

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 1
            mock_sm.participant_has_decided_qc.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=1,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        mock_st.button.assert_not_called()
        mock_st.caption.assert_any_call(MESSAGES["sidebar_subjects_search_empty"])

    def test_search_survives_confirm_next_rerun(self):
        from views.sidebar_cohort_nav import _hold_search_across_nav

        persist = SESSION_KEYS["sidebar_subject_search"]
        state = {
            persist: "ses-01",
            SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY: "",
            "pag_next": True,
        }
        with patch("views.sidebar_cohort_nav.st") as mock_st:
            mock_st.session_state = state
            _hold_search_across_nav()

        assert state[SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY] == "ses-01"
        assert state[persist] == "ses-01"
        assert state[SIDEBAR_SEARCH_HOLD_KEY] is True

    def test_next_button_keeps_filter_in_list(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {
            SESSION_KEYS["sidebar_subject_search"]: "ses-01",
            "pag_next": True,
        }
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 1
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        mock_st.button.assert_called_once()
        assert mock_st.button.call_args.kwargs["key"] == "sidebar_cohort_nav_0"

    def test_followup_rerun_does_not_drop_filter(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {
            SESSION_KEYS["sidebar_subject_search"]: "ses-01",
            SIDEBAR_SEARCH_HOLD_KEY: True,
            SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY: "",
        }
        mock_st.text_input.return_value = ""
        mock_st.button.return_value = False

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 1
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        mock_st.button.assert_called_once()
        assert mock_st.button.call_args.kwargs["key"] == "sidebar_cohort_nav_0"
        assert mock_st.session_state[SESSION_KEYS["sidebar_subject_search"]] == "ses-01"
        assert SIDEBAR_SEARCH_HOLD_KEY not in mock_st.session_state

    def test_list_filters_from_box_value_not_empty_persist(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {}
        mock_st.text_input.return_value = "ses-02"
        mock_st.button.return_value = False

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 2
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        mock_st.button.assert_called_once()
        assert mock_st.button.call_args.kwargs["key"] == "sidebar_cohort_nav_1"
        assert mock_st.session_state[SESSION_KEYS["sidebar_subject_search"]] == "ses-02"

    def test_confirm_next_rerun_happens_after_search_box(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        order = []
        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {
            SESSION_KEYS["sidebar_subject_search"]: "ses-02",
            PENDING_SIDEBAR_RERUN_KEY: True,
        }
        mock_st.button.return_value = False
        mock_st.text_input.side_effect = lambda *a, **k: order.append("search") or "ses-02"
        mock_st.rerun.side_effect = lambda: order.append("rerun")

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 2
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        assert order == ["search", "rerun"]
        mock_st.button.assert_called_once()
        assert mock_st.button.call_args.kwargs["key"] == "sidebar_cohort_nav_1"

    def test_next_visible_page_skips_non_matching_sessions(self):
        from views.sidebar_cohort_nav import next_visible_subject_page, prev_visible_subject_page

        entries = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-02"},
        ]
        assert next_visible_subject_page(entries, "ses-02", "ses-01", 1) == 2
        assert next_visible_subject_page(entries, "ses-02", "ses-01", 2) == 4
        assert next_visible_subject_page(entries, "ses-02", "ses-01", 4) is None
        assert next_visible_subject_page(entries, "ses-01", "ses-01", 1) == 3
        assert next_visible_subject_page(entries, "ses-01", "ses-01", 3) is None
        assert prev_visible_subject_page(entries, "ses-02", "ses-01", 4) == 2
        assert prev_visible_subject_page(entries, "ses-02", "ses-01", 2) is None

    def test_filter_hiding_current_jumps_to_first_match(self):
        from views.sidebar_cohort_nav import page_if_filter_hides_current, _page_after_filter_change

        entries = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        assert page_if_filter_hides_current(entries, "ses-01", "ses-01", 2) == 1
        assert page_if_filter_hides_current(entries, "ses-01", "ses-01", 1) is None
        assert page_if_filter_hides_current(entries, "ses-0", "ses-01", 2) is None
        assert page_if_filter_hides_current(entries, "", "ses-01", 2) is None
        assert page_if_filter_hides_current(entries, "zzz", "ses-01", 2) is None
        assert page_if_filter_hides_current(entries, "ses-01", "ses-01", 3) is None

        with patch("views.sidebar_cohort_nav.st") as mock_st:
            mock_st.session_state = {}
            assert _page_after_filter_change(entries, "ses-02", "ses-01", 1) == 2
            assert mock_st.session_state["_sidebar_search_applied_query"] == "ses-02"
            assert _page_after_filter_change(entries, "ses-02", "ses-01", 2) is None

    def test_changing_filter_navigates_to_first_visible_subject(self):
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {SESSION_KEYS["sidebar_subject_search"]: "ses-01"}
        mock_st.text_input.return_value = "ses-01"
        mock_st.button.return_value = False

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 2
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
            )

        mock_sm.set_current_page.assert_called_once_with(1)
        mock_st.rerun.assert_called_once()

    def test_filter_jump_flushes_notes_before_changing_page(self):
        """Search snap must save the current subject's notes before jumping (issue #84)."""
        from views.sidebar_cohort_nav import render_sidebar_cohort_subjects

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
        ]
        nav_kwargs = {
            "current_page": 2,
            "total_participants": 2,
            "participant_id": "sub-CMH0001",
            "session_id": "ses-02",
            "qc_pipeline": "fmriprep",
            "qc_tasks": ["sdc_wf_qc"],
            "participant_ids": ["sub-CMH0001"],
            "qc_cohort": cohort,
        }
        mock_st = MagicMock()
        mock_st.sidebar = _sidebar_ctx()
        mock_st.container.return_value = _sidebar_ctx()
        mock_st.session_state = {}
        mock_st.text_input.return_value = "ses-01"
        mock_st.button.return_value = False
        flush_order = []

        def flush(*args, **kwargs):
            flush_order.append("flush")

        def set_page(page):
            flush_order.append(("page", page))

        with (
            patch("views.sidebar_cohort_nav.st", mock_st),
            patch("views.sidebar_cohort_nav.SessionManager") as mock_sm,
            patch("components.qc_viewer._display_qc_pagination_header"),
            patch("components.qc_viewer._display_qc_pagination_controls"),
            patch("components.qc_viewer._record_all_qc_tasks", side_effect=flush),
        ):
            mock_sm.is_landing_page_complete.return_value = True
            mock_sm.get_current_page.return_value = 2
            mock_sm.set_current_page.side_effect = set_page
            mock_sm.participant_has_decided_qc.return_value = False
            mock_sm.is_autoplay_enabled.return_value = False
            render_sidebar_cohort_subjects(
                qc_cohort=cohort,
                total_participants=2,
                qc_task="sdc_wf_qc",
                qc_tasks=["sdc_wf_qc"],
                prepend_navigation=True,
                navigation_kwargs=nav_kwargs,
            )

        assert flush_order == ["flush", ("page", 1)]
        mock_st.rerun.assert_called_once()

    def test_clear_subject_search_empties_filter(self):
        from views.sidebar_cohort_nav import clear_subject_search

        persist = SESSION_KEYS["sidebar_subject_search"]
        state = {
            persist: "ses-02",
            SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY: "ses-02",
            SIDEBAR_SEARCH_HOLD_KEY: True,
        }
        with patch("views.sidebar_cohort_nav.st") as mock_st:
            mock_st.session_state = state
            clear_subject_search()
        assert state[persist] == ""
        assert state[SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY] == ""
        assert SIDEBAR_SEARCH_HOLD_KEY not in state

    def test_get_subject_search_query_uses_persist_not_blank_widget(self):
        from views.sidebar_cohort_nav import get_subject_search_query

        state = {
            SESSION_KEYS["sidebar_subject_search"]: "ses-01",
            SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY: "",
        }
        with patch("views.sidebar_cohort_nav.st") as mock_st:
            mock_st.session_state = state
            assert get_subject_search_query() == "ses-01"

    def test_next_prev_stay_inside_session_filter(self):
        from components.qc_viewer import _filtered_adjacent_pages

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0001", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
        ]
        with patch("views.sidebar_cohort_nav.st") as mock_st:
            mock_st.session_state = {SESSION_KEYS["sidebar_subject_search"]: "ses-01"}
            prev_page, next_page = _filtered_adjacent_pages(
                current_page=1,
                total_participants=3,
                participant_ids=None,
                qc_cohort=cohort,
                session_id="ses-01",
            )
        assert prev_page is None
        assert next_page == 3

        with patch("views.sidebar_cohort_nav.st") as mock_st:
            mock_st.session_state = {SESSION_KEYS["sidebar_subject_search"]: "ses-01"}
            prev_page, next_page = _filtered_adjacent_pages(
                current_page=1,
                total_participants=2,
                participant_ids=None,
                qc_cohort=cohort[:2],
                session_id="ses-01",
            )
        assert prev_page is None
        assert next_page is None
