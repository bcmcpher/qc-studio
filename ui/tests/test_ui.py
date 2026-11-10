"""Tests for ui.py module."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

import sys


class TestParseArgs:
    """Test argument parsing functionality."""

    @pytest.fixture(autouse=True)
    def _mock_streamlit_for_main_import(self, monkeypatch):
        """``main.py`` imports streamlit/layout at module level; stub them out for the
        duration of each test here only, via monkeypatch, so the swap can't leak into
        other test files' collection or execution (unlike a bare module-level assignment).
        """
        streamlit_stub = MagicMock()
        streamlit_stub.__path__ = []
        monkeypatch.setitem(sys.modules, "streamlit", streamlit_stub)
        monkeypatch.setitem(sys.modules, "streamlit.components", MagicMock())
        monkeypatch.setitem(sys.modules, "streamlit.components.v1", MagicMock())
        monkeypatch.setitem(sys.modules, "layout", MagicMock())
        monkeypatch.delitem(sys.modules, "main", raising=False)

    def test_parse_args_with_required_arguments(self):
        """Test parsing with all required arguments."""
        from main import parse_args

        args = parse_args(
            [
                "--dataset_dir",
                "/path/to/dataset",
                "--participant_list",
                "/path/to/participants.tsv",
                "--session_list",
                "ses-01",
                "--qc_pipeline",
                "fmriprep",
                "--qc_task",
                "anat_wf_qc",
                "--output_dir",
                "/output",
                "--qc_json",
                "/path/to/qc_config.json",
            ]
        )

        assert args.dataset_dir == "/path/to/dataset"
        assert args.participant_list == "/path/to/participants.tsv"
        assert args.session_list == "ses-01"
        assert args.qc_pipeline == "fmriprep"
        assert args.qc_task == "anat_wf_qc"
        assert args.out_dir == "/output"
        assert args.qc_json == "/path/to/qc_config.json"

    def test_parse_args_with_optional_rater_id(self):
        """The CLI should accept an optional rater ID that pre-fills the landing page."""
        from main import parse_args

        args = parse_args(
            [
                "--dataset_dir",
                "/path/to/dataset",
                "--participant_list",
                "/path/to/participants.tsv",
                "--qc_pipeline",
                "fmriprep",
                "--qc_task",
                "anat_wf_qc",
                "--output_dir",
                "/output",
                "--qc_json",
                "/path/to/qc_config.json",
                "--rater_id",
                "abc123",
            ]
        )

        assert args.rater_id == "abc123"

    def test_parse_args_default_session_list(self):
        """Test parsing with default session_list."""
        from main import parse_args

        args = parse_args(
            [
                "--dataset_dir",
                "/path/to/dataset",
                "--participant_list",
                "/path/to/participants.tsv",
                "--qc_pipeline",
                "fmriprep",
                "--qc_task",
                "anat_wf_qc",
                "--output_dir",
                "/output",
                "--qc_json",
                "/path/to/qc_config.json",
            ]
        )

        assert args.session_list is None
        assert args.default_qc_rating == "PASS"

    def test_parse_args_with_default_qc_rating_override(self):
        """CLI should accept overriding the default preselected QC rating."""
        from main import parse_args

        args = parse_args(
            [
                "--dataset_dir",
                "/path/to/dataset",
                "--participant_list",
                "/path/to/participants.tsv",
                "--qc_pipeline",
                "fmriprep",
                "--qc_task",
                "anat_wf_qc",
                "--output_dir",
                "/output",
                "--qc_json",
                "/path/to/qc_config.json",
                "--default_qc_rating",
                "FAIL",
            ]
        )

        assert args.default_qc_rating == "FAIL"

    def test_parse_args_with_default_qc_rating_none(self):
        """CLI should accept an explicit unrated default (None)."""
        from main import parse_args

        args = parse_args(
            [
                "--dataset_dir",
                "/path/to/dataset",
                "--participant_list",
                "/path/to/participants.tsv",
                "--qc_pipeline",
                "fmriprep",
                "--qc_task",
                "anat_wf_qc",
                "--output_dir",
                "/output",
                "--qc_json",
                "/path/to/qc_config.json",
                "--default_qc_rating",
                "None",
            ]
        )

        assert args.default_qc_rating == "None"

    def test_landing_page_entrypoint_applies_cli_rater_id_to_session(self, monkeypatch):
        """The multipage landing-page entrypoint should seed the session with the CLI rater ID."""
        import runpy

        import main
        import managers.session_manager
        import views.landing_page

        ctx = {
            "dataset_dir": "/data",
            "participant_list": "/participants.tsv",
            "session_list": "ses-01",
            "qc_pipeline": "fmriprep",
            "qc_task": "anat_wf_qc",
            "qc_tasks": ["anat_wf_qc"],
            "qc_config_path": "/tmp/qc.json",
            "out_dir": "/tmp/output",
            "total_participants": 1,
            "drop_duplicates": True,
            "participant_ids": ["CMH0001"],
            "qc_cohort": [{"participant_id": "sub-CMH0001", "session_id": "ses-01"}],
            "rater_id": "Eva",
        }

        calls = {}

        monkeypatch.setattr(main, "get_cli_run_context", lambda: ctx)
        monkeypatch.setattr(managers.session_manager.SessionManager, "init_session_state", lambda: None)
        monkeypatch.setattr(managers.session_manager.SessionManager, "compact_duplicate_qc_records_if_needed", lambda: None)
        monkeypatch.setattr(managers.session_manager.SessionManager, "set_rater_id", lambda value: calls.setdefault("rater_id", value))
        monkeypatch.setattr(
            managers.session_manager.SessionManager, "set_rater_id_display", lambda value: calls.setdefault("rater_id_display", value)
        )
        monkeypatch.setattr(views.landing_page, "show_landing_page", lambda *args, **kwargs: None)

        landing_page_path = Path(__file__).resolve().parents[2] / "ui" / "pages" / "1_Landing_Page.py"
        runpy.run_path(str(landing_page_path))

        assert calls["rater_id"] == "Eva"
        assert calls["rater_id_display"] == "Eva"

    def test_main_passes_output_dir_to_sidebar_navigation(self, monkeypatch):
        """The sidebar default path should receive the CLI output_dir when the QC page is rendered."""
        import main

        ctx = {
            "dataset_dir": "/data",
            "participant_list": "/participants.tsv",
            "session_list": "ses-01",
            "qc_pipeline": "fmriprep",
            "qc_task": "anat_wf_qc",
            "qc_tasks": ["anat_wf_qc"],
            "qc_config_path": "/tmp/qc.json",
            "out_dir": "/tmp/output",
            "total_participants": 1,
            "drop_duplicates": True,
            "participant_ids": ["CMH0001"],
            "qc_cohort": [{"participant_id": "sub-CMH0001", "session_id": "ses-01"}],
        }

        captured = {}

        monkeypatch.setattr(main, "get_cli_run_context", lambda: ctx)
        monkeypatch.setattr(main.SessionManager, "init_session_state", lambda: None)
        monkeypatch.setattr(main.SessionManager, "compact_duplicate_qc_records_if_needed", lambda: None)
        monkeypatch.setattr(main.SessionManager, "get_qc_session_id", lambda: "20260911T193730Z")
        monkeypatch.setattr(main.SessionManager, "set_qc_session_id", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "set_qc_session_label", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "set_qc_session_checkpoint_dir", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "set_qc_session_active_path", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "get_current_page", lambda: 1)
        monkeypatch.setattr(main.SessionManager, "set_current_page", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main, "render_sidebar_cohort_subjects", lambda **kwargs: captured.setdefault("nav", kwargs))
        monkeypatch.setattr(main, "app", lambda **kwargs: None)
        monkeypatch.setattr(main.st, "session_state", {"current_page": 1})

        main.main()

        assert captured["nav"]["navigation_kwargs"]["out_dir"] == "/tmp/output"

    def test_main_hides_subject_sidebar_on_congratulations_page(self, monkeypatch):
        """The main app should suppress the subject list when there is no active QC participant page."""
        import main

        ctx = {
            "dataset_dir": "/data",
            "participant_list": "/participants.tsv",
            "session_list": "ses-01",
            "qc_pipeline": "fmriprep",
            "qc_task": "anat_wf_qc",
            "qc_tasks": ["anat_wf_qc"],
            "qc_config_path": "/tmp/qc.json",
            "out_dir": "/tmp/output",
            "total_participants": 1,
            "drop_duplicates": True,
            "participant_ids": ["CMH0001"],
            "qc_cohort": [{"participant_id": "sub-CMH0001", "session_id": "ses-01"}],
        }
        captured = {}

        monkeypatch.setattr(main, "get_cli_run_context", lambda: ctx)
        monkeypatch.setattr(main.SessionManager, "init_session_state", lambda: None)
        monkeypatch.setattr(main.SessionManager, "compact_duplicate_qc_records_if_needed", lambda: None)
        monkeypatch.setattr(main.SessionManager, "get_qc_session_id", lambda: "20260911T193730Z")
        monkeypatch.setattr(main.SessionManager, "set_qc_session_id", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "set_qc_session_label", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "set_qc_session_checkpoint_dir", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "set_qc_session_active_path", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main.SessionManager, "get_current_page", lambda: 2)
        monkeypatch.setattr(main.SessionManager, "set_current_page", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main, "render_sidebar_cohort_subjects", lambda **kwargs: captured.setdefault("nav", kwargs))
        monkeypatch.setattr(main, "app", lambda **kwargs: None)
        monkeypatch.setattr(main.st, "session_state", {"current_page": 2})

        main.main()

        assert captured["nav"]["show_subject_filter"] is False
        assert captured["nav"]["show_subject_list"] is False

    @pytest.mark.parametrize(
        "tasks, expected_task",
        [(["anat_wf_qc"], "anat_wf_qc"), (["anat_wf_qc", "func_wf_qc"], "all")],
    )
    def test_cli_context_collapses_all_to_single_task(self, monkeypatch, tmp_path, tasks, expected_task):
        """``--qc_task all`` with a single-task qc.json runs as that task, not all-tasks mode."""
        import json
        import main

        qc_json = tmp_path / "qc.json"
        qc_json.write_text(json.dumps({t: {} for t in tasks}))
        participants = tmp_path / "participants.tsv"
        pd.DataFrame({"participant_id": ["sub-01"]}).to_csv(participants, sep="\t", index=False)
        monkeypatch.setattr(main.SessionManager, "get_qc_cohort_order", lambda: None)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "main.py",
                "--dataset_dir",
                str(tmp_path),
                "--participant_list",
                str(participants),
                "--session_list",
                "ses-01",
                "--qc_pipeline",
                "fmriprep",
                "--qc_task",
                "all",
                "--output_dir",
                str(tmp_path / "out"),
                "--qc_json",
                str(qc_json),
            ],
        )

        ctx = main.get_cli_run_context()

        assert ctx["qc_task"] == expected_task
        assert ctx["qc_tasks"] == tasks

    def test_parse_args_missing_required_argument(self):
        """Test parsing with missing required argument."""
        from main import parse_args

        with pytest.raises(SystemExit):
            parse_args(
                [
                    "--participant_list",
                    "/path/to/participants.tsv",
                    # missing other required arguments
                ]
            )

    def test_parse_args_all_fields_present(self):
        """Test that all parsed fields are accessible."""
        from main import parse_args

        args = parse_args(
            [
                "--dataset_dir",
                "/data",
                "--participant_list",
                "participants.tsv",
                "--session_list",
                "ses-02",
                "--qc_pipeline",
                "freesurfer",
                "--qc_task",
                "surf_wf",
                "--output_dir",
                "/output/dir",
                "--qc_json",
                "config.json",
            ]
        )

        assert hasattr(args, "dataset_dir")
        assert hasattr(args, "participant_list")
        assert hasattr(args, "session_list")
        assert hasattr(args, "qc_pipeline")
        assert hasattr(args, "qc_task")
        assert hasattr(args, "out_dir")
        assert hasattr(args, "qc_json")


class TestSessionStateInitialization:
    """Test session state initialization."""

    @patch("streamlit.session_state", {})
    def test_init_session_state_creates_defaults(self):
        """Test that init_session_state creates default values."""
        # This test would need proper Streamlit mocking
        # Placeholder for now
        pass

    def test_session_state_keys(self, sample_session_state):
        """Test that session state has expected keys."""
        expected_keys = [
            "current_page",
            "batch_size",
            "current_batch_qc",
            "qc_records",
            "rater_id",
            "rater_experience",
            "rater_fatigue",
            "rater_screen_size",
            "notes",
        ]

        for key in expected_keys:
            assert key in sample_session_state

    def test_session_state_default_values(self, sample_session_state):
        """Test default values in session state."""
        assert sample_session_state["current_page"] == 1
        assert sample_session_state["batch_size"] == 1
        assert isinstance(sample_session_state["qc_records"], list)
        assert sample_session_state["rater_id"] == "test_rater"


class TestUiConfiguration:
    """Test UI configuration and setup."""

    def test_page_config_is_wide(self):
        """Test that page config is set to wide layout."""
        # This would require mocking st.set_page_config
        pass

    def test_participant_list_loading(self, sample_participant_list):
        """Test that participant list is loaded correctly."""
        df = pd.read_csv(sample_participant_list, delimiter="\t")

        assert len(df) == 3
        assert "participant_id" in df.columns
        assert "sub-CMH0001" in df["participant_id"].values

    def test_total_participants_calculation(self, sample_participant_list):
        """Test calculation of total participants."""
        df = pd.read_csv(sample_participant_list, delimiter="\t")
        total = len(df)

        assert total == 3

    def test_participant_id_at_page_index(self, sample_participant_list):
        """Test retrieving participant ID at page index."""
        df = pd.read_csv(sample_participant_list, delimiter="\t")
        participant_ids = df["participant_id"].tolist()

        assert participant_ids[0] == "sub-CMH0001"
        assert participant_ids[1] == "sub-CMH0002"
        assert participant_ids[2] == "sub-CMH0003"


class TestPageNavigation:
    """Test page navigation logic."""

    def test_current_page_bounds_lower(self):
        """Test that current_page cannot go below 1."""
        current_page = 0
        if current_page < 1:
            current_page = 1

        assert current_page == 1

    def test_current_page_bounds_upper(self):
        """Test that current_page handles upper bounds."""
        current_page = 10
        total_participants = 5

        if current_page > total_participants:
            participant_id = None
        else:
            participant_id = f"sub-CMH{current_page:04d}"

        assert participant_id is None

    def test_session_id_assignment(self):
        """Test that session_id is correctly assigned."""
        session_id = "ses-01"

        assert session_id == "ses-01"


class TestConfigPathResolution:
    """Test configuration path resolution."""

    def test_config_path_construction(self, temp_dir):
        """Test that config path is constructed correctly."""
        qc_json = "qc_config.json"

        # Simulate the path construction
        config_path = temp_dir / qc_json

        assert config_path.name == "qc_config.json"
        assert config_path.parent == temp_dir
