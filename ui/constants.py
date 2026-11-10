"""Constants used throughout the QC-Studio UI application."""

# Rater experience levels
EXPERIENCE_LEVELS = ["Beginner (< 1 year)", "Intermediate (1-5 years)", "Expert (>5 years)"]

# Rater fatigue levels
FATIGUE_LEVELS = ["Not at all", "A bit tired ☕", "Very tired ☕☕"]

# Rater monitor screen sizes (diagonal)
SCREEN_SIZES = [
    "14 or less",
    "15-20",
    "21-25",
    "26-30",
    "31 or above",
    "Unknown",
]

# Default panel selections
DEFAULT_PANELS = {"niivue": True, "montage": True, "iqm": False}

# Panel configuration metadata
PANEL_CONFIG = {
    "niivue": {"label": "3D MRI (Niivue)", "description": "Display interactive 3D MRI viewer", "default": True},
    "montage": {"label": "Montage", "description": "Display 2D image montage visualization", "default": True},
    "iqm": {"label": "QC Metrics", "description": "Display QC metrics panel", "default": False},
}

# QC rating options
QC_RATINGS = ["PASS", "FAIL", "UNCERTAIN"]
DEFAULT_QC_RATING = "PASS"
DEFAULT_QC_RATING_NONE = "None"
DEFAULT_QC_RATING_OPTIONS = QC_RATINGS + [DEFAULT_QC_RATING_NONE]
RATING_FACET_COLUMNS = 12

# Columns used to identify duplicate QC rows when merging/saving results
QC_DEDUP_KEYS = ["participant_id", "session_id", "pipeline", "qc_task"]

# Viewer settings
NIIVUE_HEIGHT = 600
MONTAGE_HEIGHT = 600
IQM_HEIGHT = 400
# Streamlit component messages are capped (~200 MB); keep NIfTI payloads below this.
NIIVUE_MAX_FILE_BYTES = 150 * 1024 * 1024
DEFAULT_VIEW_MODE = "multiplanar"
VIEW_MODES = ["multiplanar", "axial", "coronal", "sagittal", "3d"]
OVERLAY_COLORMAPS = ["cool", "warm"]
DEFAULT_OVERLAY_OPACITY = 0.5

# Column layout ratios
NIIVUE_SECONDARY_RATIO = [0.1, 0.3, 0.6]
# Split for viewer area when Niivue + Montage (+ optional third panel) layouts need two columns
NIIVUE_MONTAGE_RATIO = [0.55, 0.45]
EQUAL_RATIO = [0.5, 0.5]
RATING_IQM_RATIO = [0.4, 0.6]
RATER_INFO_RATIO = [1, 1, 1]

# Pagination
DEFAULT_BATCH_SIZE = 1
# Fixed height (px) for the sidebar subject list so it scrolls in place.
SIDEBAR_SUBJECT_LIST_HEIGHT = 280

# Montage grid settings
DEFAULT_MONTAGE_MAX_ROWS = 1
DEFAULT_MONTAGE_MAX_COLS = 4
MIN_MONTAGE_GRID_SIZE = 1
MAX_MONTAGE_GRID_SIZE = 10

# Session state keys
SESSION_KEYS = {
    "current_page": "current_page",
    "batch_size": "batch_size",
    "qc_records": "qc_records",
    "rater_id": "rater_id",
    "rater_id_display": "rater_id_display",
    "rater_experience": "rater_experience",
    "rater_fatigue": "rater_fatigue",
    "rater_screen_size": "rater_screen_size",
    "notes": "notes",
    "notes_version": "notes_version",
    "rating_version": "rating_version",
    "participant_order": "participant_order",
    "qc_cohort_order": "qc_cohort_order",
    "landing_page_complete": "landing_page_complete",
    "selected_qc_task": "selected_qc_task",
    "all_tasks_mode_locked": "all_tasks_mode_locked",
    "default_qc_rating": "default_qc_rating",
    "selected_panels": "selected_panels",
    "montage_max_rows": "montage_max_rows",
    "montage_max_cols": "montage_max_cols",
    # Set once per Streamlit session after reading qc.json (avoid re-applying on every rerun)
    "montage_defaults_applied_qc_task": "montage_defaults_applied_qc_task",
    # Non-widget copy of the sidebar subject filter so Confirm/Next does not clear it
    "sidebar_subject_search": "sidebar_subject_search",
    # IQM viewer widget selections, mirrored outside the widgets' own keys so
    # they survive the sidebar's mid-script st.rerun()/st.switch_page() calls.
    "iqm_view_selection": "iqm_view_selection",
    "iqm_display_mode_selection": "iqm_display_mode_selection",
    "facet_max_rows": "facet_max_rows",
}

# Widget key for the subject search box (must differ from the persist key above).
SIDEBAR_SUBJECT_SEARCH_WIDGET_KEY = "sidebar_subject_search_input"

# Set by sidebar nav buttons so the subject search widget can render before st.rerun().
PENDING_SIDEBAR_RERUN_KEY = "_pending_sidebar_rerun"
# Keep the subject filter across Next/Previous and the follow-up rerun they trigger.
SIDEBAR_SEARCH_HOLD_KEY = "_sidebar_search_hold"

# File upload settings
UPLOAD_FILE_TYPES = ["csv", "tsv"]
UPLOAD_SEPARATOR_INFERENCE = None  # Let pandas infer

# Substitution formats for participant and session IDs in qc_config
SUBSTITUTIONS_DICT = {
    "participant_id": "[[NIPOPPY_BIDS_PARTICIPANT_ID]]",
    "session_id": "[[NIPOPPY_BIDS_SESSION_ID]]",
    # QSIPrep internal workflow slugs use underscores (ses_01) not BIDS hyphens (ses-01).
    "session_slug": "[[NIPOPPY_QSIPREP_SESSION_SLUG]]",
}

# Messages and UI strings
MESSAGES = {
    "welcome_title": "Welcome to Nipoppy QC-Studio! 🚀",
    "rater_info_header": "👤 Rater Information",
    "rater_id_prompt": "Enter your Rater Name or ID:",
    "experience_prompt": "What is your QC experience level?",
    "fatigue_prompt": "How tired are you feeling?",
    "screen_size_prompt": "What is the screen size (inches) of the monitor you are using?",
    "panels_header": "🖼️ Display Panels",
    "panels_help": "Select which panels to display during QC (at least one required).",
    "panels_validation_warning": "⚠️ You must select at least one panel to proceed!",
    "panels_success": "✅ {count} panel(s) selected",
    "upload_header": "📤 Upload Existing QC File (Optional)",
    "upload_help": "Upload a previously saved <QC_status>.tsv file / checkpoint to resume QC",
    "csv_uploader_label": "Choose a QC_status.tsv file",
    "rater_form_button": "**:green[Continue to QC] 🚀**",
    "congratulations_title": "**🎉 QC Complete! Congratulations! 🎉**",
    "export_results_button": "💾 Export Final Results",
    "previous_button": "◀️ Previous",
    "nav_tooltip_previous": ("Previous: navigates to the previous subject or session without saving any rating changes."),
    "nav_tooltip_next": (
        "Next: saves the current page's QC ratings and notes, then advances to the next subject or "
        "session. When more than one QC task is shown, set PASS, FAIL, or UNCERTAIN for every "
        "task before continuing."
    ),
    "start_over_button": "🔄 Start Over (go to home page)",
    "qc_title": "Nipoppy QC-Studio: Quality Control",
    "qc_rating_header": "QC Rating",
    "qc_rating_prompt": "Rate this qc-task:",
    "qc_notes_prompt": "Notes (optional):",
    "create_checkpoint_button": "🏁 Create checkpoint",
    "create_checkpoint_help": "Create a timestamped snapshot of the current QC records.",
    "next_button": "Next ▶️",
    "play_button": "▶️ Play",
    "pause_button": "⏸️ Pause",
    "back_landing_button": "🏠 Back to Landing Page",
    "sidebar_subjects_header": "QC subject list",
    "sidebar_subjects_search": "Search subjects",
    "sidebar_subjects_search_placeholder": "Filter by subject or session",
    "sidebar_subjects_search_empty": "No subjects match this search.",
    "niivue_header": "3D MRI (Niivue)",
    "niivue_controls_header": "Niivue Controls",
    "montage_header": "Montage",
    "metrics_header": "QC Metrics",
    "iqm_distribution_header": "IQM Distributions",
    "iqm_metrics_table_experimental": "🧪 Experimental layout — subject-level metrics table, may change.",
    "iqm_generic_distribution_experimental": "🧪 Experimental layout — generic per-column view for a non-MRIQC pipeline, may change.",
    "view_mode_label": "View Mode",
    "overlay_colormap_label": "Overlay Colormap",
    "display_settings_header": "Display Settings",
    "crosshair_label": "Show Crosshair",
    "radiological_label": "Radiological Convention",
    "colorbar_label": "Show Colorbar",
    "interpolation_label": "Interpolation",
    "show_overlay_label": "Show overlay image",
    "panel_selection_header": "🎨 Select Panels to Display",
}

# Error messages
ERROR_MESSAGES = {
    "invalid_rater_id": "Please enter a valid Rater ID (no spaces).",
    "no_panel_selected": "⚠️ You must select at least one display panel to proceed!",
    "no_participants": "❌ Error: The uploaded TSV contains {count} participant(s) not in the participant list: {participants}",
    "too_many_participants": "❌ Error: The uploaded TSV has {csv_count} unique participants, but the participant list only has {list_count}.",
    "file_load_error": "❌ Error loading file: {error}",
    "csv_comparison_error": "Could not display comparison: {error}",
    "mri_load_error": "Failed to load base MRI in Niivue viewer: {error}",
    "base_mri_not_found": "Base MRI image not found or could not be loaded.",
    "base_mri_too_large": ("Volume too large for the 3D viewer ({size_mb:.0f} MB; limit {limit_mb:.0f} MB). " "Use the Montage panel for this task."),
    "base_mri_preview_reduced": "Showing first BOLD volume (full 4D file is too large for the browser).",
    "montage_not_found": "Montage not found or could not be loaded.",
    "participant_list_load_error": "Error loading participant list: {error}",
    "reference_data_load_error": "Error loading reference data: {error}",
    "iqm_no_sources_configured": "No IQM distribution sources are configured for this task.",
    "iqm_data_load_error": "Failed to load IQM data for {modality}: {error}",
    "iqm_no_valid_groups": "None of the defined IQM groups have valid columns in the data.",
    "no_qc_tasks_all": (
        "`--qc_task all` needs a readable **qc.json** whose root is a JSON object with task keys. " "Found no tasks at: `{qc_config_path}`"
    ),
    "no_qc_task_resolved": "No QC task resolved (`qc_task={qc_task!r}`). Pass a valid `--qc_task` key from **qc.json**, or `all`.",
}

# Success messages
SUCCESS_MESSAGES = {
    "csv_loaded": "✅ Loaded {count} QC records from {filename}",
    "records_exported": "✅ All QC results exported to: {path}",
    "records_loaded": "✅ Loaded {count} QC records into session!",
    "records_saved": "✅ QC results saved to output_dir: {path}",
    "checkpoint_saved": "✅ Checkpoint saved to user specified <output_dir>/checkpoints",
}

# Info messages
INFO_MESSAGES = {
    "proceed_with_form": "You can now proceed with the rater form on the left to continue QC.",
    "no_export_records": "No QC records to export.",
    "checkpoint_unchanged": "No QC changes since the last checkpoint were detected, so no new checkpoint was created.",
    # "rater_info_extracted": "📋 Rater information extracted:",
    "rater_id_prefix": "- **Rater ID:** {id}",
    "experience_prefix": "- **Experience:** {exp}",
    "fatigue_prefix": "- **Fatigue Level:** {fatigue}",
    "screen_size_prefix": "- **Screen Size:** {size}",
    "preview_header": "Preview of Loaded Records",
    "load_records_button": "📥 Load These Records",
}
