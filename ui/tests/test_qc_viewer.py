"""Tests for qc_viewer helper utilities."""

import re
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import streamlit as st

from components import qc_viewer as qc_viewer_module
from components.qc_viewer import (
    _clean_filename,
    _default_qc_save_path,
    _render_autoplay_countdown_main_banner,
    try_autoplay_advance_if_due,
    AUTOPLAY_ADVANCE_GRACE_SECONDS,
    _on_rating_change,
    _on_notes_change,
    _toggle_notes_editing_for_task,
    _save_and_toggle_notes_editing_for_task,
    _save_and_start_autoplay,
    _record_qc_for_current_participant,
    _rating_widget_key,
    _facet_rating_widget_key,
    _multifacet_bulk_widget_key,
    _multifacet_bulk_index_and_sync,
    _on_multifacet_bulk_change,
    _notes_widget_key,
    _notes_edit_mode_key,
    _record_all_qc_tasks,
)
from managers.session_manager import SessionManager
from models import QCRecord
from utils.data_loaders import _build_montage_display_data
from utils.export import save_qc_results_to_csv

pytestmark = pytest.mark.unit


@pytest.fixture
def autoplay_session_state():
    """Patch ``st.session_state`` with a real dict seeded for autoplay tests, and mock ``st.rerun``.

    Yields ``(state, mock_rerun)`` so tests can seed/inspect state directly and assert on
    whether ``st.rerun()`` (the app-refresh signal) was actually triggered.
    """
    state = {
        "current_page": 1,
        "qc_records": [],
        "rater_id": "rater1",
        "rater_experience": "Expert (>5 year experience)",
        "rater_fatigue": "Not at all",
        "rater_screen_size": "26-30",
        "notes_version": 0,
        "rating_version": 0,
        "autoplay_enabled": True,
        "autoplay_start_time": 0.0,
        "autoplay_duration": 5,
    }
    with patch.object(st, "session_state", state), patch.object(st, "rerun", MagicMock()) as mock_rerun:
        yield state, mock_rerun


class TestCleanFilename:
    """Tests for compact tab label generation."""

    def test_default_qc_save_path_uses_absolute_output_dir(self, tmp_path, monkeypatch):
        """The sidebar default should resolve relative CLI output_dir values under the requested output tree."""
        monkeypatch.chdir(tmp_path)
        path = _default_qc_save_path("results/run", qc_pipeline="fmriprep", qc_task="anat_wf_qc")
        expected = str((tmp_path / "results" / "run" / "rater_fmriprep_anat_wf_qc_qc_status.tsv").resolve())
        assert path == expected

    def test_congrats_export_path_uses_current_cli_output_dir(self, monkeypatch):
        """The final export default should follow the active CLI output_dir rather than any stale session path."""
        new_out = "/tmp/new_output"
        expected = str((Path(new_out) / "rater1_qc_all_tasks_qc_status.tsv").resolve())
        state = {"rater_id": "rater1"}
        monkeypatch.setattr(st, "session_state", state)
        assert qc_viewer_module._default_qc_save_path(new_out, qc_task="all") == expected

    def test_extracts_session_task_run_tokens(self):
        """Functional keys should prefer ses/task/run tokens."""
        filename = "figures_sub-CMH0001_ses-01_task-rest_run-01_svg"
        assert _clean_filename(filename) == "ses-01_task-rest_run-01"

    def test_strips_subject_prefix_for_anatomical_keys(self):
        """Anatomical keys should remove noisy subject-prefixed fragments."""
        filename = "figures_sub-CMH0001_figure_sub-CMH0001_dseg_svg"
        assert _clean_filename(filename) == "dseg"

    def test_removes_extension_suffix_when_no_structured_tokens(self):
        """Fallback path should remove synthetic image-type suffixes."""
        filename = "summary_plot_png"
        assert _clean_filename(filename) == "summary_plot"

    def test_display_montage_panel_uses_clean_image_tabs(self, monkeypatch):
        """Multi-image montages should render one tab per configured image labeled by the cleaned filename."""
        fake_tabs = [MagicMock(), MagicMock(), MagicMock()]
        with (
            patch.object(qc_viewer_module.st, "tabs", return_value=fake_tabs) as mock_tabs,
            patch.object(
                qc_viewer_module,
                "_load_montage_data_cached",
                return_value={
                    "figures_sub-CMH0001_ses-01_task-rest_run-01_svg": {"type": "svg", "content": "<svg></svg>"},
                    "images_sub-CMH0001_overlay_png": {"type": "png", "content": MagicMock()},
                    "summary_plot_png": {"type": "png", "content": MagicMock()},
                },
            ),
            patch.object(qc_viewer_module.st, "header"),
            patch.object(qc_viewer_module, "_render_image") as mock_render,
        ):
            qc_viewer_module._display_montage_panel("/tmp", {"montage_path": ["a", "b", "c"]})

        assert mock_tabs.call_args.args[0] == [
            "ses-01_task-rest_run-01",
            "overlay",
            "summary_plot",
        ]
        assert mock_render.call_count == 3

    def test_unique_montage_tab_names_disambiguate_collisions(self):
        """Different montage files with the same cleaned basename should still get unique visible tab names."""
        keys = [
            "screenshots_sub-CMH0001_sub-CMH0001_png",
            "skullstrip_sub-CMH0001_sub-CMH0001_png",
            "surfaces_sub-CMH0001_sub-CMH0001_png",
        ]
        assert qc_viewer_module._unique_montage_tab_names(keys) == [
            "sub-CMH0001",
            "sub-CMH0001 (2)",
            "sub-CMH0001 (3)",
        ]

    def test_build_montage_display_data_keeps_combined_and_individual_tabs(self, tmp_path):
        """The loader should add a combined montage grid first while preserving one tab per original image."""
        img_a = tmp_path / "a.png"
        img_a.write_bytes(b"fake")
        img_b = tmp_path / "b.png"
        img_b.write_bytes(b"fake")

        with (
            patch("utils.data_loaders._load_image_from_file", side_effect=lambda p, dpi=96: MagicMock()),
            patch("utils.image_processing.create_grid_montage", return_value=MagicMock()),
        ):
            result = _build_montage_display_data((str(img_a), str(img_b)))

        assert list(result.keys())[0] == "montage"
        assert len(result) == 3
        assert "montage" in result
        assert any(key.endswith("_a_png") for key in result)
        assert any(key.endswith("_b_png") for key in result)

    def test_display_montage_panel_uses_overview_first_tab_when_combined_montage_exists(self):
        """The overview grid should appear as an explicit first tab before the per-image views."""
        fake_tabs = [MagicMock(), MagicMock(), MagicMock()]
        image_data = {
            "montage": {"type": "png", "content": MagicMock()},
            "surfaces_sub-ED01_lh.pial.superior_png": {"type": "png", "content": MagicMock()},
            "surfaces_sub-ED01_lh.pial.inferior_png": {"type": "png", "content": MagicMock()},
        }
        with (
            patch.object(qc_viewer_module.st, "tabs", return_value=fake_tabs) as mock_tabs,
            patch.object(qc_viewer_module, "_load_montage_data_cached", return_value=image_data),
            patch.object(qc_viewer_module.st, "header"),
            patch.object(qc_viewer_module, "_render_image") as mock_render,
        ):
            qc_viewer_module._display_montage_panel("/tmp", {"montage_path": ["a", "b", "c"]})

        assert mock_tabs.call_args.args[0][0] == "Overview"
        assert mock_render.call_count == 3


# critical
class TestTryAutoplayAdvanceIfDue:
    """Tests for the autoplay poll's save-and-advance decision."""

    def test_does_not_advance_when_start_time_is_zero(self, autoplay_session_state):
        """``autoplay_start_time == 0`` means the countdown never started; nothing should happen."""
        state, mock_rerun = autoplay_session_state
        state["autoplay_start_time"] = 0.0

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
        )

        assert state["current_page"] == 1
        assert state["qc_records"] == []
        mock_rerun.assert_not_called()

    def test_does_not_advance_during_grace_period(self, autoplay_session_state):
        """Past ``duration`` but still inside the grace window should not advance yet."""
        state, mock_rerun = autoplay_session_state
        state["autoplay_duration"] = 5
        # elapsed ~5.1s: past duration, but inside duration + AUTOPLAY_ADVANCE_GRACE_SECONDS (5.3s)
        state["autoplay_start_time"] = time.time() - 5.1

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
        )

        assert state["current_page"] == 1
        assert state["qc_records"] == []
        mock_rerun.assert_not_called()

    def test_advances_and_records_all_task_ratings_when_due(self, autoplay_session_state):
        """Past the grace window, every task's pending rating should be saved and the page advances."""
        state, mock_rerun = autoplay_session_state
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = time.time() - (5 + AUTOPLAY_ADVANCE_GRACE_SECONDS + 1)
        state["qc_rating_anat_wf_qc_0"] = "PASS"
        state["qc_rating_func_wf_qc_0"] = "FAIL"

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc", "func_wf_qc"],
            total_participants=3,
        )

        saved = {r.qc_task: (r.participant_id, r.session_id, r.final_qc) for r in SessionManager.get_qc_records()}
        assert saved == {
            "anat_wf_qc": ("sub-CMH0001", "ses-01", "PASS"),
            "func_wf_qc": ("sub-CMH0001", "ses-01", "FAIL"),
        }
        assert state["current_page"] == 2
        assert state["autoplay_start_time"] > 0
        mock_rerun.assert_called_once()

    def test_last_page_due_records_and_stops_autoplay(self, autoplay_session_state):
        """On the last page, being due should still save ratings but stop autoplay instead of advancing."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 3
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = time.time() - (5 + AUTOPLAY_ADVANCE_GRACE_SECONDS + 1)
        state["qc_rating_anat_wf_qc_0"] = "UNCERTAIN"

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0003",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
        )

        saved = {r.qc_task: (r.participant_id, r.session_id, r.final_qc) for r in SessionManager.get_qc_records()}
        assert saved == {"anat_wf_qc": ("sub-CMH0003", "ses-01", "UNCERTAIN")}
        assert state["autoplay_enabled"] is False
        assert state["autoplay_start_time"] == 0.0
        mock_rerun.assert_called_once()

    def test_advances_to_next_visible_page_when_sidebar_filter_is_active(self, autoplay_session_state):
        """Autoplay should respect the active subject/session filter instead of jumping to hidden pages."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 2
        state["sidebar_subject_search"] = "ses-02"
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = time.time() - (5 + AUTOPLAY_ADVANCE_GRACE_SECONDS + 1)
        state["qc_rating_anat_wf_qc_0"] = "PASS"

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0004", "session_id": "ses-02"},
        ]

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0002",
            session_id="ses-02",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc"],
            total_participants=4,
            qc_cohort=cohort,
        )

        assert state["current_page"] == 4
        assert state["autoplay_enabled"] is True
        assert state["autoplay_start_time"] > 0
        mock_rerun.assert_called_once()

    def test_stops_autoplay_when_no_visible_match_remains_after_filter(self, autoplay_session_state):
        """If the sidebar filter leaves no later visible subject, autoplay should pause instead of advancing to a hidden page."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 4
        state["sidebar_subject_search"] = "ses-02"
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = time.time() - (5 + AUTOPLAY_ADVANCE_GRACE_SECONDS + 1)
        state["qc_rating_anat_wf_qc_0"] = "PASS"

        cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0004", "session_id": "ses-02"},
        ]

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0004",
            session_id="ses-02",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc"],
            total_participants=4,
            qc_cohort=cohort,
        )

        assert state["current_page"] == 4
        assert state["autoplay_enabled"] is False
        assert state["autoplay_start_time"] == 0.0
        assert "_pending_incomplete_cohort_msg" in state
        mock_rerun.assert_called_once()


class TestOnRatingChange:
    def test_saves_with_empty_notes_when_notes_widget_key_was_never_set(self, autoplay_session_state):
        """If the user rates without ever touching the notes box, on_change should still save
        the rating, defaulting notes to '' rather than crashing on a missing key."""
        state, _ = autoplay_session_state
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        # Deliberately not setting _notes_widget_key("anat_wf_qc", 0) at all.

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == ""

    def test_saves_multi_facet_ratings(self, autoplay_session_state):
        state, _ = autoplay_session_state
        state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] = "PASS"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] = "FAIL"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "temporal", 0)] = "UNCERTAIN"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "occipital", 0)] = "PASS"

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fsqc",
            qc_task="FS_volume_wf_qc",
            rver=0,
            nver=0,
            rating_config={
                "type": "multi",
                "scale": ["PASS", "FAIL", "UNCERTAIN"],
                "facets": ["frontal", "parietal", "temporal", "occipital"],
            },
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved.final_qc == "Mixed"
        assert saved.ratings == {
            "frontal": "PASS",
            "parietal": "FAIL",
            "temporal": "UNCERTAIN",
            "occipital": "PASS",
        }

    @pytest.mark.parametrize("facet", ["T1 SNR", "Skull-strip (BET)", "GM/WM_Contrast", "Ünïcode ε"])
    def test_facet_names_saved_as_specified(self, autoplay_session_state, facet):
        """Facet names keep case, spaces and punctuation in saved records and inferred configs."""
        state, _ = autoplay_session_state
        state[_facet_rating_widget_key("FS_volume_wf_qc", facet, 0)] = "PASS"

        # No saved record yet: facets are recovered from the live widget keys.
        inferred = qc_viewer_module._fallback_rating_config_for_task("sub-CMH0001", "ses-01", "FS_volume_wf_qc", 0)
        assert inferred["facets"] == [facet]

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fsqc",
            qc_task="FS_volume_wf_qc",
            rver=0,
            nver=0,
            rating_config=inferred,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved.ratings == {facet: "PASS"}
        # Saved record path: facets come from the record keys.
        inferred_from_record = qc_viewer_module._fallback_rating_config_for_task("sub-CMH0001", "ses-01", "FS_volume_wf_qc", 0)
        assert inferred_from_record["facets"] == [facet]

    def test_bulk_multifacet_selection_applies_to_all_facets_and_saves(self, autoplay_session_state):
        state, _ = autoplay_session_state
        cfg = {
            "type": "multi",
            "scale": ["PASS", "FAIL", "UNCERTAIN"],
            "facets": ["frontal", "parietal", "temporal", "occipital"],
        }
        state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] = "PASS"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] = "UNCERTAIN"
        state[_multifacet_bulk_widget_key("FS_volume_wf_qc", 0)] = "FAIL"

        _on_multifacet_bulk_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fsqc",
            qc_task="FS_volume_wf_qc",
            rver=0,
            nver=0,
            rating_config=cfg,
        )

        for facet in cfg["facets"]:
            assert state[_facet_rating_widget_key("FS_volume_wf_qc", facet, 0)] == "FAIL"

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved is not None
        assert saved.final_qc == "All-Fail"
        assert saved.ratings == {facet: "FAIL" for facet in cfg["facets"]}

    def test_bulk_multifacet_selection_ignores_invalid_value(self, autoplay_session_state):
        state, _ = autoplay_session_state
        cfg = {
            "type": "multi",
            "scale": ["PASS", "FAIL", "UNCERTAIN"],
            "facets": ["frontal", "parietal"],
        }
        state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] = "PASS"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] = "FAIL"
        state[_multifacet_bulk_widget_key("FS_volume_wf_qc", 0)] = "MAYBE"

        _on_multifacet_bulk_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fsqc",
            qc_task="FS_volume_wf_qc",
            rver=0,
            nver=0,
            rating_config=cfg,
        )

        assert state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] == "PASS"
        assert state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] == "FAIL"
        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved is None

    def test_bulk_multifacet_mixed_state_sets_bulk_selection_to_none(self, autoplay_session_state):
        state, _ = autoplay_session_state
        bulk_key = _multifacet_bulk_widget_key("FS_volume_wf_qc", 0)
        state[bulk_key] = "PASS"

        idx = _multifacet_bulk_index_and_sync(bulk_key, None, ["PASS", "FAIL", "UNCERTAIN"])

        assert idx is None
        assert state[bulk_key] is None

    def test_bulk_multifacet_uniform_state_does_not_overwrite_existing_widget_state(self, autoplay_session_state):
        state, _ = autoplay_session_state
        bulk_key = _multifacet_bulk_widget_key("FS_volume_wf_qc", 0)
        state[bulk_key] = "FAIL"

        idx = _multifacet_bulk_index_and_sync(bulk_key, "PASS", ["PASS", "FAIL", "UNCERTAIN"])

        assert idx is None
        assert state[bulk_key] == "FAIL"

    def test_bulk_multifacet_uniform_state_prefills_when_no_widget_state_exists(self, autoplay_session_state):
        state, _ = autoplay_session_state
        bulk_key = _multifacet_bulk_widget_key("FS_volume_wf_qc", 0)
        state.pop(bulk_key, None)

        idx = _multifacet_bulk_index_and_sync(bulk_key, "PASS", ["PASS", "FAIL", "UNCERTAIN"])

        assert idx == 0


class TestOnNotesChange:
    def test_saves_notes_typed_after_rating_without_waiting_for_flush(self, autoplay_session_state):
        """Notes on_change should persist text immediately, same as the rating radio."""
        state, _ = autoplay_session_state
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = ""

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )
        state[_notes_widget_key("anat_wf_qc", 0)] = "Motion artifact, borderline."
        _on_notes_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Motion artifact, borderline."

    def test_uses_latest_versioned_note_state_during_autoplay_flush(self, autoplay_session_state):
        """Autoplay should save the newest note value even if older widget-version keys are still in state."""
        state, _ = autoplay_session_state
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "older note"
        state[_rating_widget_key("anat_wf_qc", 1)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 1)] = "Motion artifact, borderline."

        _record_all_qc_tasks("sub-CMH0001", "ses-01", "fmriprep", ["anat_wf_qc"])

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Motion artifact, borderline."

    def test_notes_saved_via_on_change_survive_a_forced_page_jump(self, autoplay_session_state):
        """A search-style page jump after notes on_change must not drop the saved notes."""
        state, _ = autoplay_session_state
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "FAIL"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Ringing at the vertex."

        _on_notes_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )
        SessionManager.set_current_page(2)

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "FAIL"
        assert saved.notes == "Ringing at the vertex."
        assert SessionManager.get_current_page() == 2

    def test_notes_edit_pauses_autoplay(self, autoplay_session_state):
        """Typing in the notes box should pause autoplay immediately so the user can finish their entry."""
        state, _ = autoplay_session_state
        state["autoplay_enabled"] = True
        state["autoplay_start_time"] = time.time()
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Motion artifact, borderline."

        _on_notes_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        assert state["autoplay_enabled"] is False
        assert state["autoplay_start_time"] == 0.0

    def test_toggle_notes_editing_pauses_autoplay(self, autoplay_session_state):
        """Clicking Add notes should pause autoplay before the notes field becomes editable."""
        state, _ = autoplay_session_state
        state["autoplay_enabled"] = True
        state["autoplay_start_time"] = time.time()

        _toggle_notes_editing_for_task("anat_wf_qc")

        assert state["autoplay_enabled"] is False
        assert state["autoplay_start_time"] == 0.0
        assert state[_notes_edit_mode_key("anat_wf_qc")] is True

    def test_add_notes_path_saves_current_rating_and_notes_before_toggling(self, autoplay_session_state):
        """The Add notes flow should persist the in-progress task state before rerunning the page."""
        state, _ = autoplay_session_state
        state["autoplay_enabled"] = True
        state["autoplay_start_time"] = time.time()
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Motion artifact, borderline."

        _save_and_toggle_notes_editing_for_task(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Motion artifact, borderline."
        assert state["autoplay_enabled"] is False
        assert state["autoplay_start_time"] == 0.0
        assert state[_notes_edit_mode_key("anat_wf_qc")] is True

    def test_play_resume_saves_current_page_before_autoplay_restarts(self, autoplay_session_state):
        """Resuming autoplay should flush the edited page state before the timer restarts."""
        state, _ = autoplay_session_state
        state["autoplay_enabled"] = False
        state["autoplay_start_time"] = 0.0
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "FAIL"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Updated after reviewing notes."
        state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] = "PASS"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] = "FAIL"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "temporal", 0)] = "UNCERTAIN"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "occipital", 0)] = "PASS"
        state["_qc_rating_cfg_by_task"] = {
            "anat_wf_qc": {"type": "single", "scale": ["PASS", "FAIL", "UNCERTAIN"]},
            "FS_volume_wf_qc": {
                "type": "multi",
                "scale": ["PASS", "FAIL", "UNCERTAIN"],
                "facets": ["frontal", "parietal", "temporal", "occipital"],
            },
        }

        _save_and_start_autoplay(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc", "FS_volume_wf_qc"],
        )

        saved_single = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        saved_multi = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved_single.final_qc == "FAIL"
        assert saved_single.notes == "Updated after reviewing notes."
        assert saved_multi.final_qc == "Mixed"
        assert saved_multi.ratings == {
            "frontal": "PASS",
            "parietal": "FAIL",
            "temporal": "UNCERTAIN",
            "occipital": "PASS",
        }
        assert state["autoplay_enabled"] is True
        assert state["autoplay_start_time"] > 0

    def test_play_resume_saves_multifacet_state_even_without_seeded_rating_config(self, autoplay_session_state):
        """Sidebar-triggered flush should preserve multifacet ratings even if config seeding has not run yet."""
        state, _ = autoplay_session_state
        state["autoplay_enabled"] = False
        state["autoplay_start_time"] = 0.0
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] = "PASS"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] = "FAIL"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "temporal", 0)] = "UNCERTAIN"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "occipital", 0)] = "PASS"
        state[_notes_widget_key("FS_volume_wf_qc", 0)] = "Unsaved sidebar flush note"
        state.pop("_qc_rating_cfg_by_task", None)

        _save_and_start_autoplay(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fsqc",
            qc_tasks=["FS_volume_wf_qc"],
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved is not None
        assert saved.final_qc == "Mixed"
        assert saved.ratings == {
            "frontal": "PASS",
            "parietal": "FAIL",
            "temporal": "UNCERTAIN",
            "occipital": "PASS",
        }
        assert saved.notes == "Unsaved sidebar flush note"
        assert state["autoplay_enabled"] is True
        assert state["autoplay_start_time"] > 0

    def test_reset_for_new_participant_clears_notes_edit_mode(self, autoplay_session_state):
        """A new page should reset task note edit state so the notes box is locked again until re-enabled."""
        state, _ = autoplay_session_state
        state["_notes_edit_mode_anat_wf_qc"] = True
        state["_notes_edit_mode_func_wf_qc"] = True

        SessionManager.reset_for_new_participant()

        assert "_notes_edit_mode_anat_wf_qc" not in state
        assert "_notes_edit_mode_func_wf_qc" not in state

    def test_stale_notes_callback_does_not_pause_autoplay(self, autoplay_session_state):
        """A delayed notes callback from the previous page should not pause autoplay on the new page."""
        state, _ = autoplay_session_state
        state["autoplay_enabled"] = True
        state["autoplay_start_time"] = time.time()
        state["rating_version"] = 2
        state["notes_version"] = 2

        # Simulate a delayed callback arriving with stale widget versions from the prior page.
        _on_notes_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=1,
            nver=1,
        )

        assert state["autoplay_enabled"] is True
        assert state["autoplay_start_time"] > 0

    def test_stale_rating_callback_does_not_overwrite_saved_record(self, autoplay_session_state):
        """A delayed rating callback from a prior page must not replace an already-saved record."""
        state, _ = autoplay_session_state
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "FAIL"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Saved note"

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        # Move to a new page generation and trigger an old callback payload.
        state["rating_version"] = 1
        state["notes_version"] = 1
        state[_rating_widget_key("anat_wf_qc", 0)] = None
        state[_notes_widget_key("anat_wf_qc", 0)] = ""

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "FAIL"
        assert saved.notes == "Saved note"


class TestRecordQcForCurrentParticipant:
    def test_populates_rater_metadata_and_timestamp_from_session_manager(self, autoplay_session_state):
        """A saved record should carry the rater's id/experience/fatigue/screen size and a real timestamp,
        not just final_qc/notes (which is all prior tests in this file have checked)."""
        state, _ = autoplay_session_state

        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "Looks fine.")

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.pipeline == "fmriprep"
        assert saved.rater_id == state["rater_id"]
        assert saved.rater_experience == state["rater_experience"]
        assert saved.rater_fatigue == state["rater_fatigue"]
        assert saved.rater_screen_size == state["rater_screen_size"]
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", saved.timestamp)


class TestRecordAllQcTasks:
    def test_saves_every_task_in_one_call_when_all_are_rated(self, autoplay_session_state):
        """Called directly (not via the autoplay poll or Confirm), it should save one record
        per task, each with its own rating, in a single pass over qc_tasks."""
        state, _ = autoplay_session_state
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_rating_widget_key("func_wf_qc", 0)] = "FAIL"
        state[_rating_widget_key("dwi_wf_qc", 0)] = "UNCERTAIN"

        _record_all_qc_tasks("sub-CMH0001", "ses-01", "fmriprep", ["anat_wf_qc", "func_wf_qc", "dwi_wf_qc"])

        saved = {r.qc_task: r.final_qc for r in SessionManager.get_qc_records()}
        assert saved == {
            "anat_wf_qc": "PASS",
            "func_wf_qc": "FAIL",
            "dwi_wf_qc": "UNCERTAIN",
        }


class TestSaveQcRecord:
    def test_save_qc_record_persists_partial_progress_to_disk(self, autoplay_session_state, tmp_path):
        """Save QC should flush current ratings and write a partial export file immediately."""
        state, _ = autoplay_session_state
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        out_file = tmp_path / "rater1_fmriprep_anat_wf_qc_qc_status.tsv"
        assert out_file.exists()
        text = out_file.read_text(encoding="utf-8")
        assert "sub-CMH0001" in text
        assert "anat_wf_qc" in text
        assert "PASS" in text

    def test_save_qc_record_honors_custom_save_file_path(self, autoplay_session_state, tmp_path):
        """When users provide a custom file path, Save QC should write exactly there."""
        state, _ = autoplay_session_state
        state[_rating_widget_key("anat_wf_qc", 0)] = "FAIL"
        custom_file = tmp_path / "custom" / "QC_status.csv"

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
            out_dir=str(tmp_path),
            drop_duplicates=True,
            save_file_path=str(custom_file),
        )

        assert custom_file.exists()
        text = custom_file.read_text(encoding="utf-8")
        assert "sub-CMH0001" in text
        assert "FAIL" in text

    def test_save_qc_record_message_includes_participant_and_record_counts(self, autoplay_session_state, tmp_path):
        """Save QC success text should include unique participant and record totals."""
        state, _ = autoplay_session_state
        _record_qc_for_current_participant("sub-CMH0002", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        state[_rating_widget_key("anat_wf_qc", 0)] = "FAIL"

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        kind, msg = state[qc_viewer_module.PENDING_QC_SAVE_MSG_KEY]
        assert kind == "success"
        assert "Saved 2 record(s) across 2 unique participant(s)." in msg

    def test_save_qc_record_all_mode_writes_single_file_with_all_tasks(self, autoplay_session_state, tmp_path):
        """When CLI all-tasks mode is locked, Save QC should write one TSV containing all tasks."""
        state, _ = autoplay_session_state
        state["all_tasks_mode_locked"] = True
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_rating_widget_key("func_wf_qc", 0)] = "FAIL"

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc", "func_wf_qc"],
            total_participants=3,
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        out_file = tmp_path / "rater1_fmriprep_all_tasks_qc_status.tsv"
        assert out_file.exists()
        text = out_file.read_text(encoding="utf-8")
        assert "anat_wf_qc" in text
        assert "func_wf_qc" in text

    def test_save_qc_record_all_mode_honors_custom_file_path(self, autoplay_session_state, tmp_path):
        """In locked all-tasks mode, typed custom file names should be used exactly (not ignored)."""
        state, _ = autoplay_session_state
        state["all_tasks_mode_locked"] = True
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_rating_widget_key("func_wf_qc", 0)] = "FAIL"
        custom_file = tmp_path / "custom" / "all_tasks_export.tsv"

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc", "func_wf_qc"],
            total_participants=3,
            out_dir=str(tmp_path),
            drop_duplicates=True,
            save_file_path=str(custom_file),
        )

        assert custom_file.exists()
        text = custom_file.read_text(encoding="utf-8")
        assert "anat_wf_qc" in text
        assert "func_wf_qc" in text

    def test_save_qc_record_exports_only_active_task_after_task_switch(self, autoplay_session_state, tmp_path):
        """Saving while viewing one task should not rewrite/export rows from previously rated tasks."""
        state, _ = autoplay_session_state

        _record_qc_for_current_participant("sub-CMH9999", "ses-01", "fmriprep", "func_wf_qc", "FAIL", "from older task")
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            total_participants=3,
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        anat_file = tmp_path / "rater1_fmriprep_anat_wf_qc_qc_status.tsv"
        func_file = tmp_path / "rater1_fmriprep_func_wf_qc_qc_status.tsv"
        assert anat_file.exists()
        assert not func_file.exists()

        text = anat_file.read_text(encoding="utf-8")
        assert "anat_wf_qc" in text
        assert "func_wf_qc" not in text

    def test_checkpoint_matches_final_export_for_single_and_multi_facet_records(self, autoplay_session_state, tmp_path):
        """Checkpoint TSVs should match the final qc_status.tsv export row-for-row and column-for-column."""
        state, _ = autoplay_session_state
        state["rating_version"] = 0
        state["notes_version"] = 0

        _record_qc_for_current_participant(
            "sub-CMH0001",
            "ses-01",
            "fmriprep",
            "anat_wf_qc",
            "PASS",
            "Single-task note",
        )
        _record_qc_for_current_participant(
            "sub-CMH0002",
            "ses-01",
            "fsqc",
            "FS_volume_wf_qc",
            None,
            "Facet note",
            ratings={
                "frontal": "PASS",
                "parietal": "FAIL",
                "temporal": "UNCERTAIN",
                "occipital": "PASS",
            },
        )

        records = SessionManager.get_qc_records()
        checkpoint_path = qc_viewer_module._create_qc_checkpoint(
            records=records,
            out_dir=str(tmp_path),
            qc_pipeline="fmriprep",
            qc_task="all",
            timestamp="20240101T000000Z",
        )
        export_path = tmp_path / "final_qc_status.tsv"
        save_qc_results_to_csv(export_path, records, drop_duplicates=True)

        checkpoint_df = pd.read_csv(checkpoint_path, sep="\t", dtype=str, keep_default_na=False)
        export_df = pd.read_csv(export_path, sep="\t", dtype=str, keep_default_na=False)

        pd.testing.assert_frame_equal(checkpoint_df, export_df)

    def test_does_not_save_when_multifacet_payload_contains_only_blank_values(self, autoplay_session_state):
        """A stale multifacet callback with only blank values should not overwrite existing data."""
        _record_qc_for_current_participant(
            "sub-CMH0001",
            "ses-01",
            "fsqc",
            "FS_volume_wf_qc",
            None,
            "",
            ratings={"frontal": None, "parietal": "", "occipital": "nan"},
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "FS_volume_wf_qc")
        assert saved is None

    def test_keeps_initial_rating_null_when_all_task_data_sources_are_missing(self, tmp_path):
        """Missing MRI, montage, and IQM sources should keep the task unrated instead of defaulting to PASS."""
        missing_root = tmp_path / "missing"
        missing_root.mkdir()
        state = {
            "default_qc_rating": "PASS",
            "qc_records": [],
            "rating_version": 0,
            "notes_version": 0,
        }
        with (
            patch.object(st, "session_state", state),
            patch.object(st, "markdown"),
            patch.object(st, "radio", return_value="PASS") as mock_radio,
        ):
            qc_viewer_module._display_qc_rating_for_task(
                participant_id="sub-CMH0001",
                session_id="ses-01",
                qc_pipeline="fmriprep",
                qc_task="anat_wf_qc",
                rating_config={"type": "single", "scale": ["PASS", "FAIL", "UNCERTAIN"]},
                task_has_data_sources=False,
            )

        assert mock_radio.call_args.kwargs["index"] is None


class TestRatingPersistenceNearAutoAdvance:

    def test_saved_rating_survives_a_later_none_read(self, autoplay_session_state):
        """A saved rating should survive a later read of None (e.g. from a stale widget key)."""
        state, _ = autoplay_session_state

        state["rating_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Good quality scan"

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Good quality scan"

        state["rating_version"] = 1
        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", rating=None, notes="")
        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Good quality scan"

    def test_record_all_qc_tasks_does_not_overwrite_saved_rating_after_version_bump(self, autoplay_session_state):
        """A saved rating should survive a later version bump and a None read from _record_all_qc_tasks."""
        state, _ = autoplay_session_state

        state["rating_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Good quality scan"

        test_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
        ]

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        state["rating_version"] = 1
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = time.time() - (5 + AUTOPLAY_ADVANCE_GRACE_SECONDS + 1)

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc", "func_wf_qc"],
            total_participants=3,
            qc_cohort=test_cohort,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Good quality scan"

    def test_full_advance_does_not_lose_rating_saved_via_on_change(self, autoplay_session_state):
        """A rating saved via _on_rating_change should survive a full advance (save + next page)."""
        state, mock_rerun = autoplay_session_state

        state["rating_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Good quality scan"
        state["autoplay_duration"] = 5
        # Comfortably past duration + AUTOPLAY_ADVANCE_GRACE_SECONDS, same margin as the
        # sibling tests in TestTryAutoplayAdvanceIfDue above.
        state["autoplay_start_time"] = time.time() - (5 + AUTOPLAY_ADVANCE_GRACE_SECONDS + 1)

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        try_autoplay_advance_if_due(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            qc_tasks=["anat_wf_qc", "func_wf_qc"],
            total_participants=3,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Good quality scan"
        assert state["current_page"] == 2
        mock_rerun.assert_called_once()

    def test_unrated_task_does_not_affect_a_different_tasks_saved_rating(self, autoplay_session_state):
        """On a multi-task page, one task's saved rating survives a flush that finds another task unrated."""
        state, _ = autoplay_session_state

        state["rating_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = "Good quality scan"
        # func_wf_qc is never rated: no qc_rating_func_wf_qc_0 key is ever set in state.

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        _record_all_qc_tasks("sub-CMH0001", "ses-01", "fmriprep", ["anat_wf_qc", "func_wf_qc"])

        rated = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert rated.final_qc == "PASS"
        assert rated.notes == "Good quality scan"
        unrated = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "func_wf_qc")
        assert unrated is None

    def test_notes_typed_after_rating_saved_are_merged_on_flush(self, autoplay_session_state):
        """Notes on_change or a later Confirm flush should merge them with the already-saved rating."""
        state, _ = autoplay_session_state

        state["rating_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        state[_notes_widget_key("anat_wf_qc", 0)] = ""

        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == ""

        state[_notes_widget_key("anat_wf_qc", 0)] = "Motion artifact, borderline."
        _on_notes_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert saved.notes == "Motion artifact, borderline."

    def test_changing_rating_before_advance_keeps_only_the_latest_value(self, autoplay_session_state):
        """Picking a different rating before advance should replace, not duplicate, the saved record."""
        state, _ = autoplay_session_state

        state["rating_version"] = 0
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"
        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        state[_rating_widget_key("anat_wf_qc", 0)] = "FAIL"
        _on_rating_change(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            rver=0,
            nver=0,
        )

        matching = [
            r for r in SessionManager.get_qc_records() if r.participant_id == "sub-CMH0001" and r.session_id == "ses-01" and r.qc_task == "anat_wf_qc"
        ]
        assert len(matching) == 1
        assert matching[0].final_qc == "FAIL"


class TestDisplayQcPagination:

    @staticmethod
    def _button_returns_true_for(*keys_to_click):
        def fake_button(*args, **kwargs):
            key = kwargs.get("key")
            return key in keys_to_click  # to return True for the keys we want to simulate a click on, False otherwise

        return fake_button

    def test_pause_button_disables_autoplay(self, autoplay_session_state, monkeypatch):
        """Clicking the pause button should disable autoplay and not advance the page."""
        state, mock_rerun = autoplay_session_state
        state["autoplay_enabled"] = True
        state["autoplay_start_time"] = time.time() - 10

        # Simulate clicking the pause button by returning True for its key
        pause_button_key = "autoplay_pause"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(pause_button_key))

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=1, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["autoplay_enabled"] is False
        assert state["autoplay_start_time"] == 0.0
        mock_rerun.assert_called_once()

    def test_play_button_enables_autoplay(self, autoplay_session_state, monkeypatch):
        """Clicking the play button should enable autoplay and reset the start time."""
        state, mock_rerun = autoplay_session_state
        state["autoplay_enabled"] = False
        state["autoplay_start_time"] = 0.0

        # Simulate clicking the play button by returning True for its key
        play_button_key = "autoplay_play"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(play_button_key))

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=1, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["autoplay_enabled"] is True
        assert state["autoplay_start_time"] > 0.0
        mock_rerun.assert_called_once()

    def test_prev_button_decrements_page_and_resets_autoplay_start_time(self, autoplay_session_state, monkeypatch):
        """Clicking the previous button should decrement the current page and reset autoplay start time."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 2
        old_start_time = time.time() - 10
        state["autoplay_start_time"] = old_start_time

        # Simulate clicking the previous button by returning True for its key
        prev_button_key = "pag_prev"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(prev_button_key))

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=2, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["current_page"] == 1
        assert state["autoplay_start_time"] > old_start_time
        mock_rerun.assert_called_once()

    def test_previous_button_goes_back_a_page(self, autoplay_session_state, monkeypatch):
        """Clicking the previous button should go back one page."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 2
        state["autoplay_enabled"] = False

        # Simulate clicking the previous button by returning True for its key
        prev_button_key = "pag_prev"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(prev_button_key))

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=2, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["current_page"] == 1
        assert state["autoplay_enabled"] is False
        mock_rerun.assert_called_once()

    def test_previous_button_not_rendered_on_page_1(self, autoplay_session_state, monkeypatch):
        """Clicking the previous button on page 1 should not go below page 1."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 1
        state["autoplay_enabled"] = False

        # Simulate clicking the previous button by returning True for its key
        prev_button_key = "pag_prev"
        fake_button = MagicMock(return_value=False)  # Default to not clicked
        monkeypatch.setattr(st, "button", fake_button)

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=1, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["current_page"] == 1
        called_keys = [call.kwargs.get("key") for call in fake_button.call_args_list]
        assert prev_button_key not in called_keys

    def test_previous_button_does_not_flush_ratings(self, autoplay_session_state, monkeypatch):
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 2
        state["autoplay_enabled"] = False
        # Rating sits in raw widget state, as if selected but never explicitly flushed —
        # only on_change (fired at selection time) or a Confirm click should ever save it.
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        monkeypatch.setattr(st, "button", self._button_returns_true_for("pag_prev"))

        qc_viewer_module._display_qc_pagination_controls(
            current_page=2,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
        )

        assert SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc") is None

    def test_next_button_increments_page_and_resets_autoplay_start_time(self, autoplay_session_state, monkeypatch):
        """Clicking the next button should increment the current page and reset autoplay start time."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 1
        old_start_time = time.time() - 10
        state["autoplay_start_time"] = old_start_time

        # Simulate clicking the next button by returning True for its key
        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=1, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["current_page"] == 2
        assert state["autoplay_start_time"] > old_start_time
        mock_rerun.assert_called_once()

    def test_next_button_renders_on_last_page_for_completion_checks(self, autoplay_session_state, monkeypatch):
        """The single Next button remains available on the final page so it can save and finish the cohort."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 3
        state["autoplay_enabled"] = False

        next_button_key = "pag_next"
        fake_button = MagicMock(return_value=False)
        monkeypatch.setattr(st, "button", fake_button)

        qc_viewer_module._display_qc_pagination_controls(
            current_page=3, total_participants=3, participant_id="sub-CMH0003", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        assert state["current_page"] == 3
        called_keys = [call.kwargs.get("key") for call in fake_button.call_args_list]
        assert next_button_key in called_keys

    def test_next_button_flushes_ratings_before_advance(self, autoplay_session_state, monkeypatch):
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 1
        state["autoplay_enabled"] = False
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        monkeypatch.setattr(st, "button", self._button_returns_true_for("pag_next"))

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert state["current_page"] == 2
        mock_rerun.assert_called_once()

    def test_next_button_when_autoplay_enabled_only_saves_ratings_and_not_advance(self, autoplay_session_state, monkeypatch):
        """Clicking the next button should save ratings but not advance the page when autoplay is enabled."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 1
        state["autoplay_enabled"] = True
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1, total_participants=3, participant_id="sub-CMH0001", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0001", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert state["current_page"] == 2
        mock_rerun.assert_called_once()

    def test_next_button_when_autoplay_disabled_saves_ratings_and_advances_if_not_last_page(self, autoplay_session_state, monkeypatch):
        """Clicking the next button should save ratings and advance the page when autoplay is disabled."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 3
        state["autoplay_enabled"] = False
        # rating_version tracks how many next_page()/previous_page() calls have already
        # happened; for the 3rd participant (page 1 -> 2 -> 3) that's 2 resets, so version 2.
        state["rating_version"] = 2
        state[_rating_widget_key("anat_wf_qc", 2)] = "PASS"

        # Simulate clicking the next button by returning True for its key
        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))

        # Call the function that renders the pagination controls
        qc_viewer_module._display_qc_pagination_controls(
            current_page=3, total_participants=4, participant_id="sub-CMH0003", session_id="ses-01", qc_pipeline="fmriprep", qc_tasks=["anat_wf_qc"]
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0003", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert state["current_page"] == 4  # Page should advance
        mock_rerun.assert_called_once()

    def test_confirm_and_next_button_keeps_filtered_view_active_when_subset_is_complete(self, autoplay_session_state, monkeypatch):
        """A filtered view should remain in-place at the end of the visible list instead of jumping to the congratulations page."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 4
        state["autoplay_enabled"] = False
        state["sidebar_subject_search"] = "ses-02"
        state["rating_version"] = 2
        state[_rating_widget_key("anat_wf_qc", 2)] = "PASS"

        qc_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0004", "session_id": "ses-02"},
        ]
        _record_qc_for_current_participant("sub-CMH0002", "ses-02", "fmriprep", "anat_wf_qc", "PASS", "")

        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))
        monkeypatch.setattr(st, "info", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=4,
            total_participants=4,
            participant_id="sub-CMH0004",
            session_id="ses-02",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            qc_cohort=qc_cohort,
        )

        assert state["current_page"] == 4
        mock_rerun.assert_called_once()

    def test_save_qc_record_navigates_to_congratulations_when_filtered_view_completes_full_cohort(self, autoplay_session_state, monkeypatch):
        """If the active filter is still on and the full cohort is fully rated, saving should finish the cohort."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 4
        state["sidebar_subject_search"] = "ses-02"
        monkeypatch.setattr(st, "info", MagicMock())

        qc_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0004", "session_id": "ses-02"},
        ]
        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0002", "ses-02", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0003", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0004", "ses-02", "fmriprep", "anat_wf_qc", "PASS", "")

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0004",
            session_id="ses-02",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            total_participants=4,
            qc_cohort=qc_cohort,
        )

        assert state["current_page"] == 5
        st.info.assert_not_called()
        mock_rerun.assert_called_once()

    def test_save_qc_record_does_not_warn_when_filtered_subject_list_is_complete_but_cohort_is_not(self, autoplay_session_state, monkeypatch):
        """Save progress should not trigger the filtered-complete navigation warning."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 2
        state["sidebar_subject_search"] = "ses-02"
        monkeypatch.setattr(st, "info", MagicMock())

        qc_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-02"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0004", "session_id": "ses-02"},
        ]
        _record_qc_for_current_participant("sub-CMH0002", "ses-02", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0004", "ses-02", "fmriprep", "anat_wf_qc", "PASS", "")

        qc_viewer_module._save_qc_record(
            participant_id="sub-CMH0002",
            session_id="ses-02",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            total_participants=4,
            qc_cohort=qc_cohort,
        )

        st.info.assert_not_called()
        mock_rerun.assert_called_once()

    def test_next_button_does_not_advance_when_cohort_incomplete(self, autoplay_session_state, monkeypatch):
        """On the last page with an incomplete cohort, Next should save ratings but not advance."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 3
        state["autoplay_enabled"] = False
        state["rating_version"] = 2
        state[_rating_widget_key("anat_wf_qc", 2)] = "PASS"

        qc_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},  # never rated
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
        ]

        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))

        qc_viewer_module._display_qc_pagination_controls(
            current_page=3,
            total_participants=3,
            participant_id="sub-CMH0003",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            qc_cohort=qc_cohort,
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0003", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert state["current_page"] == 3  # still incomplete (sub-CMH0002 unrated), must not jump ahead
        assert "_pending_incomplete_cohort_msg" in state
        mock_rerun.assert_called_once()

    def test_next_button_builds_cohort_from_participant_ids_and_advances_when_complete(self, autoplay_session_state, monkeypatch):
        """With no qc_cohort but participant_ids given, Next should build a cohort on the fly and
        advance to the congratulations page once every participant in it is rated."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 3
        state["autoplay_enabled"] = False
        state["rating_version"] = 2
        state[_rating_widget_key("anat_wf_qc", 2)] = "PASS"

        # Other two cohort members already reviewed earlier; bare IDs exercise the sub- normalization.
        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0002", "ses-01", "fmriprep", "anat_wf_qc", "FAIL", "")

        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))

        qc_viewer_module._display_qc_pagination_controls(
            current_page=3,
            total_participants=3,
            participant_id="sub-CMH0003",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            participant_ids=["CMH0001", "CMH0002", "CMH0003"],
        )

        assert state["current_page"] == 4  # total_participants + 1 -> congratulations page
        mock_rerun.assert_called_once()

    def test_next_button_builds_cohort_from_participant_ids_and_does_not_advance_when_incomplete(self, autoplay_session_state, monkeypatch):
        """Same fallback cohort-building path, but must not advance while that cohort is still incomplete."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 3
        state["autoplay_enabled"] = False
        state["rating_version"] = 2
        state[_rating_widget_key("anat_wf_qc", 2)] = "PASS"

        # sub-CMH0001 rated, sub-CMH0002 never rated -> cohort incomplete.
        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")

        next_button_key = "pag_next"
        monkeypatch.setattr(st, "button", self._button_returns_true_for(next_button_key))

        qc_viewer_module._display_qc_pagination_controls(
            current_page=3,
            total_participants=3,
            participant_id="sub-CMH0003",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            participant_ids=["CMH0001", "CMH0002", "CMH0003"],
        )

        saved = SessionManager.get_qc_record_for_participant("sub-CMH0003", "ses-01", "anat_wf_qc")
        assert saved.final_qc == "PASS"
        assert state["current_page"] == 3  # still incomplete (sub-CMH0002 unrated), must not jump ahead
        mock_rerun.assert_called_once()

    def test_save_progress_button_does_not_advance_to_congratulations_when_cohort_is_complete(self, autoplay_session_state, monkeypatch, tmp_path):
        """Only the next action may advance to the congratulations page."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 1
        state["autoplay_enabled"] = False
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        qc_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
        ]
        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0002", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0003", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")

        monkeypatch.setattr(st, "button", self._button_returns_true_for("save_progress"))
        monkeypatch.setattr(st, "success", MagicMock())
        monkeypatch.setattr(st, "info", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            participant_ids=["CMH0001", "CMH0002", "CMH0003"],
            qc_cohort=qc_cohort,
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        assert state["current_page"] == 1
        mock_rerun.assert_not_called()

    def test_create_checkpoint_button_does_not_advance_to_congratulations_when_cohort_is_complete(
        self, autoplay_session_state, monkeypatch, tmp_path
    ):
        """Checkpoint creation is a side action and should not trigger congratulation-page navigation."""
        state, mock_rerun = autoplay_session_state
        state["current_page"] = 1
        state["autoplay_enabled"] = False

        qc_cohort = [
            {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
            {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
        ]
        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0002", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        _record_qc_for_current_participant("sub-CMH0003", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")

        monkeypatch.setattr(st, "button", self._button_returns_true_for("create_checkpoint"))
        success_mock = MagicMock()
        monkeypatch.setattr(st, "success", success_mock)
        monkeypatch.setattr(st, "info", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            participant_ids=["CMH0001", "CMH0002", "CMH0003"],
            qc_cohort=qc_cohort,
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        assert state["current_page"] == 1
        assert "_pending_checkpoint_msg" not in state
        success_mock.assert_not_called()
        mock_rerun.assert_not_called()

    def test_create_checkpoint_button_shows_output_dir_above_button(self, autoplay_session_state, monkeypatch, tmp_path):
        """The selected output directory should be visible directly above the checkpoint button."""
        state, mock_rerun = autoplay_session_state
        caption_mock = MagicMock()
        monkeypatch.setattr(st, "button", lambda *args, **kwargs: False)
        monkeypatch.setattr(st, "caption", caption_mock)
        monkeypatch.setattr(st, "info", MagicMock())
        monkeypatch.setattr(st, "markdown", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        caption_mock.assert_any_call(f"Output dir: {Path(tmp_path).resolve()}")
        mock_rerun.assert_not_called()

    def test_create_checkpoint_button_creates_backup_for_current_qc_records(self, autoplay_session_state, monkeypatch, tmp_path):
        """The sidebar checkpoint action should back up current QC records to the configured output_dir/checkpoints folder."""
        state, mock_rerun = autoplay_session_state
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        _record_qc_for_current_participant("sub-CMH0001", "ses-01", "fmriprep", "anat_wf_qc", "PASS", "")
        monkeypatch.setattr(st, "button", self._button_returns_true_for("create_checkpoint"))
        monkeypatch.setattr(st, "info", MagicMock())
        monkeypatch.setattr(st, "markdown", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        assert any(checkpoint_dir.glob("*.tsv"))
        mock_rerun.assert_not_called()

    def test_create_checkpoint_uses_only_active_task_records_after_task_switch(self, autoplay_session_state, monkeypatch, tmp_path):
        """Checkpoint files created from one selected task should not include rows from a previously selected task."""
        state, mock_rerun = autoplay_session_state
        state[_rating_widget_key("anat_wf_qc", 0)] = "PASS"

        _record_qc_for_current_participant("sub-CMH9999", "ses-01", "fmriprep", "func_wf_qc", "FAIL", "from older task")

        monkeypatch.setattr(st, "button", self._button_returns_true_for("create_checkpoint"))
        monkeypatch.setattr(st, "info", MagicMock())
        monkeypatch.setattr(st, "markdown", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_files = list(checkpoint_dir.glob("*.tsv"))
        assert len(checkpoint_files) == 1
        assert "_anat_wf_qc_checkpoint_" in checkpoint_files[0].name

        checkpoint_df = pd.read_csv(checkpoint_files[0], sep="\t", dtype=str, keep_default_na=False)
        assert set(checkpoint_df["qc_task"]) == {"anat_wf_qc"}
        mock_rerun.assert_not_called()

    def test_create_checkpoint_button_flushes_live_facet_ratings_before_saving(self, autoplay_session_state, monkeypatch, tmp_path):
        """Checkpoint creation should persist the current page's unsaved facet ratings before writing the TSV."""
        state, mock_rerun = autoplay_session_state
        state["rating_version"] = 0
        state["notes_version"] = 0
        state[_facet_rating_widget_key("FS_volume_wf_qc", "frontal", 0)] = "PASS"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "parietal", 0)] = "FAIL"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "temporal", 0)] = "UNCERTAIN"
        state[_facet_rating_widget_key("FS_volume_wf_qc", "occipital", 0)] = "PASS"
        state[_notes_widget_key("FS_volume_wf_qc", 0)] = "Facet note from current page"
        state["_qc_rating_cfg_by_task"] = {
            "FS_volume_wf_qc": {
                "type": "multi",
                "scale": ["PASS", "FAIL", "UNCERTAIN"],
                "facets": ["frontal", "parietal", "temporal", "occipital"],
            }
        }

        monkeypatch.setattr(st, "button", self._button_returns_true_for("create_checkpoint"))
        monkeypatch.setattr(st, "info", MagicMock())
        monkeypatch.setattr(st, "markdown", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fsqc",
            qc_tasks=["FS_volume_wf_qc"],
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_files = list(checkpoint_dir.glob("*.tsv"))
        assert len(checkpoint_files) == 1
        checkpoint_df = pd.read_csv(checkpoint_files[0], sep="\t", dtype=str, keep_default_na=False)
        assert set(checkpoint_df["facet"]) == {"frontal", "parietal", "temporal", "occipital"}
        assert set(checkpoint_df["rating_value"]) == {"PASS", "FAIL", "UNCERTAIN"}
        assert set(checkpoint_df["notes"]) == {"Facet note from current page"}
        mock_rerun.assert_not_called()

    def test_create_checkpoint_does_not_duplicate_when_records_match_last_checkpoint(self, autoplay_session_state, monkeypatch, tmp_path):
        """If the QC records are unchanged since the last checkpoint, do not create a duplicate backup."""
        state, _ = autoplay_session_state
        state["rater_id"] = "rater1"

        record = QCRecord(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_task="anat_wf_qc",
            pipeline="fmriprep",
            timestamp="2024-01-01 00:00:00",
            rater_id="rater1",
            rater_experience="novice",
            rater_fatigue="low",
            final_qc="PASS",
            notes="",
        )
        SessionManager.set_qc_records([record])

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / "rater1_fmriprep_anat_wf_qc_checkpoint_20240102T030405Z.tsv"
        pd.DataFrame(
            [
                {
                    "pipeline": "fmriprep",
                    "qc_task": "anat_wf_qc",
                    "participant_id": "sub-CMH0001",
                    "session_id": "ses-01",
                    "task_id": "",
                    "run_id": "",
                    "timestamp": "2024-01-01 00:00:00",
                    "rater_id": "rater1",
                    "rater_experience": "novice",
                    "rater_fatigue": "low",
                    "final_qc": "PASS",
                    "notes": "",
                }
            ]
        ).to_csv(checkpoint_path, sep="\t", index=False)

        monkeypatch.setattr(st, "button", self._button_returns_true_for("create_checkpoint"))
        monkeypatch.setattr(st, "success", MagicMock())
        monkeypatch.setattr(st, "info", MagicMock())

        qc_viewer_module._display_qc_pagination_controls(
            current_page=1,
            total_participants=3,
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_pipeline="fmriprep",
            qc_tasks=["anat_wf_qc"],
            participant_ids=["CMH0001", "CMH0002", "CMH0003"],
            qc_cohort=[
                {"participant_id": "sub-CMH0001", "session_id": "ses-01"},
                {"participant_id": "sub-CMH0002", "session_id": "ses-01"},
                {"participant_id": "sub-CMH0003", "session_id": "ses-01"},
            ],
            out_dir=str(tmp_path),
            drop_duplicates=True,
        )

        assert qc_viewer_module._checkpoint_contents_match_records(
            SessionManager.get_latest_qc_records_per_dedup(None),
            str(tmp_path),
        )
        assert len(list(checkpoint_dir.glob("*.tsv"))) == 1

    def test_checkpoint_guard_uses_checkpoint_label_in_all_tasks_mode_with_one_task(self, autoplay_session_state, tmp_path):
        """All-tasks lock with one task writes a task-named checkpoint; the guard must look up that same name."""
        state, _ = autoplay_session_state
        state["rater_id"] = "rater1"
        SessionManager.set_all_tasks_mode_locked(True)
        record = QCRecord(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_task="anat_wf_qc",
            pipeline="fmriprep",
            timestamp="2024-01-01 00:00:00",
            rater_id="rater1",
            rater_experience="novice",
            rater_fatigue="low",
            final_qc="PASS",
            notes="",
        )
        SessionManager.set_qc_records([record])
        records = SessionManager.get_qc_records()

        qc_viewer_module._create_qc_checkpoint(records, str(tmp_path), "fmriprep", "anat_wf_qc")

        assert qc_viewer_module._checkpoint_contents_match_records(records, str(tmp_path), qc_pipeline="fmriprep", qc_task="anat_wf_qc")

    def test_checkpoint_export_trims_whitespace_and_newlines_from_notes(self, autoplay_session_state, tmp_path):
        """Checkpoint exports should normalize notes the same way as final TSV exports."""
        state, _ = autoplay_session_state
        state["rater_id"] = "rater1"

        record = QCRecord(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_task="anat_wf_qc",
            pipeline="fmriprep",
            timestamp="2024-01-01 00:00:00",
            rater_id="rater1",
            rater_experience="novice",
            rater_fatigue="low",
            final_qc="PASS",
            notes="\n  Motion artifact\n  ",
        )
        SessionManager.set_qc_records([record])

        checkpoint_path = qc_viewer_module._create_qc_checkpoint(
            SessionManager.get_qc_records(),
            str(tmp_path),
            "fmriprep",
            "anat_wf_qc",
        )

        checkpoint_df = pd.read_csv(checkpoint_path, sep="\t", dtype=str)
        assert checkpoint_df.iloc[0]["notes"] == "Motion artifact"

    def test_checkpoint_guard_ignores_refresh_timestamps_when_qc_content_is_unchanged(self, autoplay_session_state, tmp_path):
        """Saving progress can refresh timestamps without representing new QC content; the checkpoint guard should ignore that."""
        state, _ = autoplay_session_state
        state["rater_id"] = "rater1"

        record = QCRecord(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_task="anat_wf_qc",
            pipeline="fmriprep",
            timestamp="2024-01-01 00:00:00",
            rater_id="rater1",
            rater_experience="novice",
            rater_fatigue="low",
            final_qc="PASS",
            notes="",
        )
        SessionManager.set_qc_records([record])

        checkpoint_dir = tmp_path / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / "rater1_fmriprep_anat_wf_qc_checkpoint_20240102T030405Z.tsv"
        pd.DataFrame(
            [
                {
                    "pipeline": "fmriprep",
                    "qc_task": "anat_wf_qc",
                    "participant_id": "sub-CMH0001",
                    "session_id": "ses-01",
                    "task_id": "",
                    "run_id": "",
                    "timestamp": "2024-01-01 00:00:00",
                    "rater_id": "rater1",
                    "rater_experience": "novice",
                    "rater_fatigue": "low",
                    "final_qc": "PASS",
                    "notes": "",
                }
            ]
        ).to_csv(checkpoint_path, sep="\t", index=False)

        refreshed = QCRecord(
            participant_id="sub-CMH0001",
            session_id="ses-01",
            qc_task="anat_wf_qc",
            pipeline="fmriprep",
            timestamp="2024-01-02 00:00:00",
            rater_id="rater1",
            rater_experience="novice",
            rater_fatigue="low",
            final_qc="PASS",
            notes="",
        )
        SessionManager.set_qc_records([refreshed])

        assert qc_viewer_module._checkpoint_contents_match_records(
            SessionManager.get_latest_qc_records_per_dedup(None),
            str(tmp_path),
        )

    def test_checkpoint_path_uses_session_output_dir_when_out_dir_is_not_explicit(self, autoplay_session_state, tmp_path):
        """Checkpoint snapshots should honor the active user-selected output directory even when callers omit out_dir."""
        state, _ = autoplay_session_state
        state["rater_id"] = "Rater1"

        custom_output = tmp_path / "custom_output"
        SessionManager.set_qc_session_checkpoint_dir(str((custom_output / "checkpoints").resolve()))

        path = qc_viewer_module._default_qc_checkpoint_path(
            None,
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            timestamp="20240102T030405Z",
        )

        assert Path(path).parent == custom_output / "checkpoints"
        assert Path(path).name == "rater1_fmriprep_anat_wf_qc_checkpoint_20240102T030405Z.tsv"

    def test_default_checkpoint_path_uses_single_timestamp_without_pipeline_name(self, autoplay_session_state, tmp_path):
        """Checkpoint snapshots should use a compact rater/task/timestamp naming pattern."""
        state, _ = autoplay_session_state
        state["rater_id"] = "Rater1"

        path = qc_viewer_module._default_qc_checkpoint_path(
            str(tmp_path),
            qc_pipeline="fmriprep",
            qc_task="anat_wf_qc",
            timestamp="20240102T030405Z",
        )

        expected_name = "rater1_fmriprep_anat_wf_qc_checkpoint_20240102T030405Z.tsv"
        assert Path(path).name == expected_name
        assert "fmriprep" in Path(path).name
        assert Path(path).name.count("20240102T030405Z") == 1


# pure autoplay
class TestAutoplayCountdownTiming:
    """Tests for the countdown banner's time math (``_render_autoplay_countdown_main_banner``)."""

    FIXED_NOW = 1_700_000_000.0

    @staticmethod
    def _extract_secs_now(html: str) -> int:
        match = re.search(r'id="qc_autoplay_sec"[^>]*>(\d+)</span>', html)
        assert match, "countdown span not found in rendered HTML"
        return int(match.group(1))

    @staticmethod
    def _extract_deadline_ms(html: str) -> int:
        match = re.search(r"const deadline = (\d+);", html)
        assert match, "deadline constant not found in rendered HTML"
        return int(match.group(1))

    def test_secs_now_counts_down_correctly_mid_interval(self, autoplay_session_state, monkeypatch):
        """2s into a 5s countdown, the banner should show 3s remaining."""
        state, _ = autoplay_session_state
        monkeypatch.setattr(qc_viewer_module.time, "time", lambda: self.FIXED_NOW)
        mock_html = MagicMock()
        monkeypatch.setattr(qc_viewer_module.st, "iframe", mock_html)
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = self.FIXED_NOW - 2

        _render_autoplay_countdown_main_banner()

        assert self._extract_secs_now(mock_html.call_args.args[0]) == 3

    def test_secs_now_clamped_to_zero_past_duration(self, autoplay_session_state, monkeypatch):
        """Elapsed time past the configured duration should never show negative seconds."""
        state, _ = autoplay_session_state
        monkeypatch.setattr(qc_viewer_module.time, "time", lambda: self.FIXED_NOW)
        mock_html = MagicMock()
        monkeypatch.setattr(qc_viewer_module.st, "iframe", mock_html)
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = self.FIXED_NOW - 10

        _render_autoplay_countdown_main_banner()

        assert self._extract_secs_now(mock_html.call_args.args[0]) == 0

    def test_secs_now_equals_duration_at_countdown_start(self, autoplay_session_state, monkeypatch):
        """At elapsed == 0, the banner should show the full configured duration."""
        state, _ = autoplay_session_state
        monkeypatch.setattr(qc_viewer_module.time, "time", lambda: self.FIXED_NOW)
        mock_html = MagicMock()
        monkeypatch.setattr(qc_viewer_module.st, "iframe", mock_html)
        state["autoplay_duration"] = 5
        state["autoplay_start_time"] = self.FIXED_NOW

        _render_autoplay_countdown_main_banner()

        assert self._extract_secs_now(mock_html.call_args.args[0]) == 5

    def test_deadline_ms_matches_start_time_plus_duration(self, autoplay_session_state, monkeypatch):
        """The client-side JS deadline should be (start_time + duration) in milliseconds."""
        state, _ = autoplay_session_state
        monkeypatch.setattr(qc_viewer_module.time, "time", lambda: self.FIXED_NOW)
        mock_html = MagicMock()
        monkeypatch.setattr(qc_viewer_module.st, "iframe", mock_html)
        state["autoplay_duration"] = 7
        state["autoplay_start_time"] = self.FIXED_NOW - 1

        _render_autoplay_countdown_main_banner()

        expected_deadline_ms = int((state["autoplay_start_time"] + 7) * 1000)
        assert self._extract_deadline_ms(mock_html.call_args.args[0]) == expected_deadline_ms

    def test_does_not_render_when_autoplay_disabled(self, autoplay_session_state, monkeypatch):
        """No banner should be drawn once autoplay is turned off."""
        state, _ = autoplay_session_state
        mock_html = MagicMock()
        monkeypatch.setattr(qc_viewer_module.st, "iframe", mock_html)
        state["autoplay_enabled"] = False
        state["autoplay_start_time"] = time.time()

        _render_autoplay_countdown_main_banner()

        mock_html.assert_not_called()

    def test_does_not_render_when_start_time_not_set(self, autoplay_session_state, monkeypatch):
        """Autoplay enabled but not yet started (start_time == 0) should not draw a banner."""
        state, _ = autoplay_session_state
        mock_html = MagicMock()
        monkeypatch.setattr(qc_viewer_module.st, "iframe", mock_html)
        state["autoplay_enabled"] = True
        state["autoplay_start_time"] = 0.0

        _render_autoplay_countdown_main_banner()

        mock_html.assert_not_called()


class TestPathSpecHasExistingFile:
    """Tests for resolving configured source paths, including glob patterns."""

    def test_relative_glob_matches(self, tmp_path):
        (tmp_path / "sub-01").mkdir()
        (tmp_path / "sub-01" / "img.svg").write_text("x")
        assert qc_viewer_module._path_spec_has_existing_file("sub-01/*.svg", tmp_path)

    def test_absolute_glob_matches(self, tmp_path):
        (tmp_path / "img.svg").write_text("x")
        assert qc_viewer_module._path_spec_has_existing_file(str(tmp_path / "*.svg"), "/unrelated")

    def test_absolute_glob_no_match(self, tmp_path):
        assert not qc_viewer_module._path_spec_has_existing_file(str(tmp_path / "*.svg"))

    def test_relative_glob_with_special_chars_in_base(self, tmp_path):
        base = tmp_path / "data[1]"
        base.mkdir()
        (base / "img.svg").write_text("x")
        assert qc_viewer_module._path_spec_has_existing_file("*.svg", base)
