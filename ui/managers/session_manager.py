"""Session state management for QC-Studio UI."""

import streamlit as st
from constants import (
    DEFAULT_PANELS,
    SESSION_KEYS,
    DEFAULT_MONTAGE_MAX_ROWS,
    DEFAULT_MONTAGE_MAX_COLS,
    QC_RATINGS,
    DEFAULT_QC_RATING,
    DEFAULT_QC_RATING_NONE,
    DEFAULT_QC_RATING_OPTIONS,
)
from utils.cohort import bare_bids_id as _bare_bids_id


class SessionManager:
    """Manages session state access with type safety and defaults."""

    @staticmethod
    def init_session_state():
        """Initialize all required session state variables."""
        defaults = {
            SESSION_KEYS["current_page"]: 1,
            SESSION_KEYS["batch_size"]: 1,
            SESSION_KEYS["qc_records"]: [],
            SESSION_KEYS["rater_id"]: "",
            SESSION_KEYS["rater_id_display"]: "",
            SESSION_KEYS["rater_experience"]: None,
            SESSION_KEYS["rater_fatigue"]: None,
            SESSION_KEYS["rater_screen_size"]: None,
            SESSION_KEYS["notes"]: "",
            SESSION_KEYS["notes_version"]: 0,
            SESSION_KEYS["rating_version"]: 0,
            SESSION_KEYS["participant_order"]: [],
            SESSION_KEYS["qc_cohort_order"]: [],
            SESSION_KEYS["landing_page_complete"]: False,
            SESSION_KEYS["selected_qc_task"]: "",
            SESSION_KEYS["all_tasks_mode_locked"]: False,
            SESSION_KEYS["default_qc_rating"]: DEFAULT_QC_RATING,
            SESSION_KEYS["selected_panels"]: DEFAULT_PANELS.copy(),
            SESSION_KEYS["montage_max_rows"]: DEFAULT_MONTAGE_MAX_ROWS,
            SESSION_KEYS["montage_max_cols"]: DEFAULT_MONTAGE_MAX_COLS,
            SESSION_KEYS["sidebar_subject_search"]: "",
            "autoplay_enabled": False,
            "autoplay_start_time": 0.0,
            "autoplay_duration": 10,
            SESSION_KEYS["iqm_view_selection"]: "Overview",
            SESSION_KEYS["iqm_display_mode_selection"]: "Dataset",
            "qc_session_id": "",
            "qc_session_label": "",
            "qc_session_started_at": "",
            "qc_session_active_path": "",
            "qc_session_checkpoint_dir": "",
        }

        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    # Rater Information Methods
    @staticmethod
    def get_rater_id() -> str:
        """Get current normalized rater ID for filenames and exports."""
        value = st.session_state.get(SESSION_KEYS["rater_id"], "")
        return value.strip().lower() if isinstance(value, str) else ""

    @staticmethod
    def get_rater_id_display() -> str:
        """Get the user-facing rater ID as originally entered."""
        value = st.session_state.get(SESSION_KEYS["rater_id_display"], "")
        return str(value or SessionManager.get_rater_id()).strip()

    @staticmethod
    def set_rater_id(rater_id: str):
        """Set normalized rater ID for filenames and exports."""
        clean_rater_id = str(rater_id or "").strip().lower()
        st.session_state[SESSION_KEYS["rater_id"]] = clean_rater_id
        st.session_state[SESSION_KEYS["rater_id_display"]] = str(rater_id or "").strip()

    @staticmethod
    def set_rater_id_display(rater_id: str):
        """Set the exact user-facing rater ID shown in the UI."""
        st.session_state[SESSION_KEYS["rater_id_display"]] = str(rater_id or "").strip()

    @staticmethod
    def get_qc_session_id() -> str:
        """Get the active QC rating-session identifier."""
        return str(st.session_state.get("qc_session_id", "")).strip()

    @staticmethod
    def set_qc_session_id(qc_session_id: str):
        """Set the active QC rating-session identifier."""
        st.session_state["qc_session_id"] = str(qc_session_id or "").strip()

    @staticmethod
    def get_qc_session_label() -> str:
        """Get the human-readable QC session label."""
        return str(st.session_state.get("qc_session_label", "")).strip()

    @staticmethod
    def set_qc_session_label(label: str):
        """Set the human-readable QC session label."""
        st.session_state["qc_session_label"] = str(label or "").strip()

    @staticmethod
    def get_qc_session_active_path() -> str:
        """Get the active session export path."""
        return str(st.session_state.get("qc_session_active_path", "")).strip()

    @staticmethod
    def set_qc_session_active_path(path: str):
        """Set the active session export path."""
        st.session_state["qc_session_active_path"] = str(path or "").strip()

    @staticmethod
    def get_qc_session_checkpoint_dir() -> str:
        """Get the checkpoint directory for the current QC session."""
        return str(st.session_state.get("qc_session_checkpoint_dir", "")).strip()

    @staticmethod
    def set_qc_session_checkpoint_dir(path: str):
        """Set the checkpoint directory for the current QC session."""
        st.session_state["qc_session_checkpoint_dir"] = str(path or "").strip()

    @staticmethod
    def get_rater_experience() -> str:
        """Get current rater experience level."""
        return st.session_state.get(SESSION_KEYS["rater_experience"], "")

    @staticmethod
    def set_rater_experience(experience: str):
        """Set rater experience level."""
        st.session_state[SESSION_KEYS["rater_experience"]] = experience

    @staticmethod
    def get_rater_fatigue() -> str:
        """Get current rater fatigue level."""
        return st.session_state.get(SESSION_KEYS["rater_fatigue"], "")

    @staticmethod
    def set_rater_fatigue(fatigue: str):
        """Set rater fatigue level."""
        st.session_state[SESSION_KEYS["rater_fatigue"]] = fatigue

    @staticmethod
    def get_rater_screen_size() -> str:
        """Get current rater monitor screen size."""
        return st.session_state.get(SESSION_KEYS["rater_screen_size"], "")

    @staticmethod
    def set_rater_screen_size(screen_size: str):
        """Set rater monitor screen size."""
        st.session_state[SESSION_KEYS["rater_screen_size"]] = screen_size

    # QC task selection methods
    @staticmethod
    def get_selected_qc_task() -> str:
        """Get the currently selected landing-page QC task."""
        value = st.session_state.get(SESSION_KEYS["selected_qc_task"], "")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def set_selected_qc_task(qc_task: str):
        """Persist the landing-page QC task selection for the current session."""
        st.session_state[SESSION_KEYS["selected_qc_task"]] = str(qc_task or "").strip()

    @staticmethod
    def is_all_tasks_mode_locked() -> bool:
        """Whether task selection is locked because CLI requested ``--qc_task all``."""
        return bool(st.session_state.get(SESSION_KEYS["all_tasks_mode_locked"], False))

    @staticmethod
    def set_all_tasks_mode_locked(locked: bool):
        """Set whether landing-page task switching is disabled for this run."""
        st.session_state[SESSION_KEYS["all_tasks_mode_locked"]] = bool(locked)

    @staticmethod
    def get_default_qc_rating() -> str:
        """Get the session-level default QC rating used to preselect unrated forms."""
        value = str(st.session_state.get(SESSION_KEYS["default_qc_rating"], DEFAULT_QC_RATING) or "").strip()
        if not value:
            return DEFAULT_QC_RATING
        if value.lower() == DEFAULT_QC_RATING_NONE.lower():
            return DEFAULT_QC_RATING_NONE
        value_u = value.upper()
        return value_u if value_u in QC_RATINGS else DEFAULT_QC_RATING

    @staticmethod
    def set_default_qc_rating(rating: str):
        """Set the session-level default QC rating (falls back to DEFAULT_QC_RATING)."""
        value = str(rating or "").strip()
        if value.lower() == DEFAULT_QC_RATING_NONE.lower():
            st.session_state[SESSION_KEYS["default_qc_rating"]] = DEFAULT_QC_RATING_NONE
            return
        value_u = value.upper()
        st.session_state[SESSION_KEYS["default_qc_rating"]] = value_u if value_u in DEFAULT_QC_RATING_OPTIONS else DEFAULT_QC_RATING

    # Panel Selection Methods
    @staticmethod
    def get_selected_panels() -> dict:
        """Get selected panels configuration."""
        if SESSION_KEYS["selected_panels"] not in st.session_state:
            st.session_state[SESSION_KEYS["selected_panels"]] = DEFAULT_PANELS.copy()
        return st.session_state[SESSION_KEYS["selected_panels"]]

    @staticmethod
    def set_panel_selection(panels_data):
        """Set panel selections.

        Args:
            panels_data: Either a dict of {panel_key: bool} or a single panel name (str) with next param as bool.
                        If dict, replaces all panel selections.
                        For backward compatibility with single panel updates.
        """
        if isinstance(panels_data, dict):
            # Full panel dictionary provided
            st.session_state[SESSION_KEYS["selected_panels"]] = panels_data
        else:
            # Assume it's a panel_key string; this is for single updates (backward compatibility)
            panels = SessionManager.get_selected_panels()
            panels[panels_data] = panels_data  # This shouldn't happen, but keeping for safety
            st.session_state[SESSION_KEYS["selected_panels"]] = panels

    @staticmethod
    def get_panel_count() -> int:
        """Get count of selected panels."""
        panels = SessionManager.get_selected_panels()
        return sum(panels.values())

    @staticmethod
    def is_panel_selected(panel_key: str) -> bool:
        """Check if a specific panel is selected."""
        panels = SessionManager.get_selected_panels()
        return panels.get(panel_key, False)

    # QC Records Management
    @staticmethod
    def get_qc_records() -> list:
        """Get all QC records."""
        if SESSION_KEYS["qc_records"] not in st.session_state:
            st.session_state[SESSION_KEYS["qc_records"]] = []
        return st.session_state[SESSION_KEYS["qc_records"]]

    @staticmethod
    def _qc_record_dedup_tuple(record) -> tuple:
        """Normalize QC_DEDUP_KEYS for duplicate detection (matches CSV merge semantics)."""
        pid = record.participant_id if hasattr(record, "participant_id") else record.get("participant_id", "")
        sid = record.session_id if hasattr(record, "session_id") else record.get("session_id", "")
        pipe = record.pipeline if hasattr(record, "pipeline") else record.get("pipeline", "")
        task = record.qc_task if hasattr(record, "qc_task") else record.get("qc_task", "")
        return (
            _bare_bids_id(pid, "sub-"),
            _bare_bids_id(sid, "ses-"),
            str(pipe),
            str(task),
        )

    @staticmethod
    def add_qc_record(record):
        """Append a QC record, replacing any existing row with the same deduplication key.

        Keys match ``QC_DEDUP_KEYS`` (participant, session, pipeline, task) with BIDS-style
        normalization so re-saving the same subject does not create duplicate rows.
        """
        new_key = SessionManager._qc_record_dedup_tuple(record)
        kept = [r for r in SessionManager.get_qc_records() if SessionManager._qc_record_dedup_tuple(r) != new_key]
        kept.append(record)
        st.session_state[SESSION_KEYS["qc_records"]] = kept

    @staticmethod
    def get_latest_qc_records_per_dedup(qc_task: str | None = None) -> list:
        """Return the latest record per dedup key; optionally restrict to one ``qc_task``."""
        seen = {}
        for record in reversed(SessionManager.get_qc_records()):
            if qc_task is not None:
                t = record.qc_task if hasattr(record, "qc_task") else record.get("qc_task", "")
                if str(t) != str(qc_task):
                    continue
            key = SessionManager._qc_record_dedup_tuple(record)
            if key not in seen:
                seen[key] = record
        return list(seen.values())

    @staticmethod
    def compact_duplicate_qc_records_if_needed() -> None:
        """Collapse duplicate rows in session state (same dedup key), once per browser session."""
        mkey = "__qc_dedupe_compact_done"
        if st.session_state.get(mkey):
            return
        raw = list(SessionManager.get_qc_records())
        if raw:
            compacted = SessionManager.get_latest_qc_records_per_dedup(None)
            if len(compacted) < len(raw):
                SessionManager.set_qc_records(compacted)
        st.session_state[mkey] = True

    @staticmethod
    def set_qc_records(records: list):
        """Replace all QC records."""
        st.session_state[SESSION_KEYS["qc_records"]] = records

    @staticmethod
    def get_qc_record_count() -> int:
        """Get number of QC records."""
        return len(SessionManager.get_qc_records())

    # Notes Management
    @staticmethod
    def get_notes() -> str:
        """Get current notes."""
        return st.session_state.get(SESSION_KEYS["notes"], "")

    @staticmethod
    def set_notes(notes: str):
        """Set notes."""
        st.session_state[SESSION_KEYS["notes"]] = notes

    # Landing Page Management
    @staticmethod
    def is_landing_page_complete() -> bool:
        """Check if landing page has been completed."""
        return st.session_state.get(SESSION_KEYS["landing_page_complete"], False)

    @staticmethod
    def set_landing_page_complete(complete: bool):
        """Set landing page completion status."""
        st.session_state[SESSION_KEYS["landing_page_complete"]] = complete

    # Pagination Management
    @staticmethod
    def get_current_page() -> int:
        """Get current page number."""
        return st.session_state.get(SESSION_KEYS["current_page"], 1)

    @staticmethod
    def set_current_page(page: int):
        """Set current page number."""
        st.session_state[SESSION_KEYS["current_page"]] = page
        SessionManager.reset_for_new_participant()

    @staticmethod
    def next_page():
        """Move to next page."""
        st.session_state[SESSION_KEYS["current_page"]] += 1
        SessionManager.reset_for_new_participant()

    @staticmethod
    def previous_page():
        """Move to previous page."""
        st.session_state[SESSION_KEYS["current_page"]] -= 1
        SessionManager.reset_for_new_participant()

    @staticmethod
    def get_batch_size() -> int:
        """Get batch size."""
        return st.session_state.get(SESSION_KEYS["batch_size"], 1)

    @staticmethod
    def set_batch_size(size: int):
        """Set batch size."""
        st.session_state[SESSION_KEYS["batch_size"]] = size

    # Utility Methods
    @staticmethod
    def get_rater_summary() -> dict:
        """Get all rater information as a dict."""
        return {
            "rater_id": SessionManager.get_rater_id(),
            "experience": SessionManager.get_rater_experience(),
            "fatigue": SessionManager.get_rater_fatigue(),
            "screen_size": SessionManager.get_rater_screen_size(),
        }

    @staticmethod
    def get_notes_version() -> int:
        """Get the current notes widget version counter."""
        return st.session_state.get(SESSION_KEYS["notes_version"], 0)

    @staticmethod
    def get_rating_version() -> int:
        """Get the current qc_rating widget version counter."""
        return st.session_state.get(SESSION_KEYS["rating_version"], 0)

    @staticmethod
    def get_participant_ids() -> list:
        """Get the stored (optionally sorted) participant ID list."""
        return st.session_state.get(SESSION_KEYS["participant_order"], [])

    @staticmethod
    def set_participant_ids(ids: list):
        """Store the participant ID list (used to persist sort order after CSV upload)."""
        st.session_state[SESSION_KEYS["participant_order"]] = ids

    @staticmethod
    def get_qc_cohort_order() -> list:
        """Stored (participant, session) page order after CSV upload resume."""
        return st.session_state.get(SESSION_KEYS["qc_cohort_order"], [])

    @staticmethod
    def set_qc_cohort_order(cohort: list):
        """Persist cohort page order so multi-session resume keeps session rows."""
        st.session_state[SESSION_KEYS["qc_cohort_order"]] = list(cohort)

    @staticmethod
    def get_qc_record_for_participant(participant_id: str, session_id: str, qc_task: str = None):
        """Return the most recent QCRecord for a given participant/session/task, or None.

        Normalises sub-/ses- prefixes and leading zeros so that records saved
        during a session (e.g. sub-QPNNC000421 / ses-01) match records loaded
        from a CSV (e.g. QPNNC000421 / 1).
        """
        bare_pid = _bare_bids_id(participant_id, "sub-")
        bare_sid = _bare_bids_id(session_id, "ses-")
        for record in reversed(SessionManager.get_qc_records()):
            rec_pid = record.participant_id if hasattr(record, "participant_id") else record.get("participant_id", "")
            rec_sid = record.session_id if hasattr(record, "session_id") else record.get("session_id", "")
            rec_task = record.qc_task if hasattr(record, "qc_task") else record.get("qc_task", "")
            if qc_task is not None and str(rec_task) != str(qc_task):
                continue
            if _bare_bids_id(str(rec_pid), "sub-") == bare_pid and _bare_bids_id(str(rec_sid), "ses-") == bare_sid:
                return record
        return None

    @staticmethod
    def _final_qc_is_decided(record) -> bool:
        if record is None:
            return False
        ratings = record.ratings if hasattr(record, "ratings") else record.get("ratings", None)
        if isinstance(ratings, dict):
            if not ratings:
                return False
            return all(str(v).strip().lower() not in {"", "none", "nan"} for v in ratings.values())
        fq = record.final_qc if hasattr(record, "final_qc") else record.get("final_qc", "")
        fq_str = str(fq).strip()
        return fq_str.lower() not in {"", "none", "nan"}

    @staticmethod
    def derive_multifacet_final_qc(ratings: dict[str, str | None] | None) -> str | None:
        """Subject-level label for multi-facet ratings.

        Returns:
            - ``All-Pass`` when every facet is PASS
            - ``All-Fail`` when every facet is FAIL
            - ``All-Uncertain`` when every facet is UNCERTAIN
            - ``Mixed`` for any other fully rated combination
            - ``None`` otherwise (including missing/blank facet ratings)
        """
        if not isinstance(ratings, dict) or not ratings:
            return None
        values = [str(v).strip().upper() for v in ratings.values()]
        if not values or any(v in {"", "NONE", "NAN"} for v in values):
            return None
        if all(v == "PASS" for v in values):
            return "All-Pass"
        if all(v == "FAIL" for v in values):
            return "All-Fail"
        if all(v == "UNCERTAIN" for v in values):
            return "All-Uncertain"
        return "Mixed"

    @staticmethod
    def participant_has_decided_qc(participant_id: str, session_id: str, qc_task: str) -> bool:
        """True when the latest stored record for this participant/session/task has PASS/FAIL/UNCERTAIN."""
        rec = SessionManager.get_qc_record_for_participant(participant_id, session_id, qc_task)
        return SessionManager._final_qc_is_decided(rec)

    @staticmethod
    def all_cohort_qc_complete(qc_task: str, session_id: str, participant_ids: list) -> bool:
        """True when every cohort participant has a QC record with a valid ``final_qc`` for this task/session."""
        if not participant_ids:
            return False
        for pid in participant_ids:
            if not SessionManager.participant_has_decided_qc(pid, session_id, qc_task):
                return False
        return True

    @staticmethod
    def all_qc_cohort_pages_complete(qc_task: str, qc_cohort: list) -> bool:
        """True when every (participant, session) page in ``qc_cohort`` has a decided ``final_qc``."""
        return SessionManager.all_qc_cohort_pages_complete_for_tasks([qc_task], qc_cohort)

    @staticmethod
    def all_qc_cohort_pages_complete_for_tasks(qc_tasks: list, qc_cohort: list) -> bool:
        """True when every cohort page has a decided rating for **each** task in ``qc_tasks``."""
        if not qc_cohort or not qc_tasks:
            return False
        for entry in qc_cohort:
            pid = entry.get("participant_id") if isinstance(entry, dict) else entry[0]
            sid = entry.get("session_id") if isinstance(entry, dict) else entry[1]
            for t in qc_tasks:
                if not SessionManager.participant_has_decided_qc(pid, sid, t):
                    return False
        return True

    @staticmethod
    def first_page_missing_qc(qc_task: str, session_id: str, participant_ids: list) -> int:
        """1-based page index of the first participant without a decided ``final_qc``."""
        for i, pid in enumerate(participant_ids):
            if not SessionManager.participant_has_decided_qc(pid, session_id, qc_task):
                return i + 1
        return 1

    @staticmethod
    def first_qc_cohort_page_missing(qc_task: str, qc_cohort: list) -> int:
        """1-based page index of the first (participant, session) cohort row missing a decided ``final_qc``."""
        return SessionManager.first_qc_cohort_page_missing_for_tasks([qc_task], qc_cohort)

    @staticmethod
    def first_qc_cohort_page_missing_for_tasks(qc_tasks: list, qc_cohort: list) -> int:
        """First page index where any task in ``qc_tasks`` lacks a decided ``final_qc``."""
        for i, entry in enumerate(qc_cohort or []):
            pid = entry.get("participant_id") if isinstance(entry, dict) else entry[0]
            sid = entry.get("session_id") if isinstance(entry, dict) else entry[1]
            for t in qc_tasks:
                if not SessionManager.participant_has_decided_qc(pid, sid, t):
                    return i + 1
        return 1

    @staticmethod
    def get_latest_qc_records_for_task_set(qc_tasks: list | None) -> list:
        """Like ``get_latest_qc_records_per_dedup`` but only records whose ``qc_task`` is in ``qc_tasks``."""
        if not qc_tasks:
            return SessionManager.get_latest_qc_records_per_dedup(None)
        allowed = {str(t) for t in qc_tasks}
        seen = {}
        for record in reversed(SessionManager.get_qc_records()):
            t = record.qc_task if hasattr(record, "qc_task") else record.get("qc_task", "")
            if str(t) not in allowed:
                continue
            key = SessionManager._qc_record_dedup_tuple(record)
            if key not in seen:
                seen[key] = record
        return list(seen.values())

    @staticmethod
    def reset_for_new_participant():
        """Reset session state for next participant."""
        for key in list(st.session_state.keys()):
            if key.startswith("_notes_edit_mode_"):
                del st.session_state[key]
        st.session_state[SESSION_KEYS["notes"]] = ""
        st.session_state[SESSION_KEYS["notes_version"]] = SessionManager.get_notes_version() + 1
        st.session_state[SESSION_KEYS["rating_version"]] = SessionManager.get_rating_version() + 1

    # Montage Grid Settings Methods
    @staticmethod
    def get_montage_max_rows() -> int | None:
        """Get maximum rows for montage grid (None means auto-calculate)."""
        return st.session_state.get(SESSION_KEYS["montage_max_rows"], DEFAULT_MONTAGE_MAX_ROWS)

    @staticmethod
    def set_montage_max_rows(rows: int | None):
        """Set maximum rows for montage grid."""
        st.session_state[SESSION_KEYS["montage_max_rows"]] = rows

    @staticmethod
    def get_montage_max_cols() -> int | None:
        """Get maximum columns for montage grid (None means auto-calculate)."""
        return st.session_state.get(SESSION_KEYS["montage_max_cols"], DEFAULT_MONTAGE_MAX_COLS)

    @staticmethod
    def set_montage_max_cols(cols: int | None):
        """Set maximum columns for montage grid."""
        st.session_state[SESSION_KEYS["montage_max_cols"]] = cols

    # Autoplay Methods
    @staticmethod
    def is_autoplay_enabled() -> bool:
        """Check if autoplay is enabled."""
        return st.session_state.get("autoplay_enabled", False)

    @staticmethod
    def set_autoplay_enabled(enabled: bool):
        """Set autoplay state."""
        st.session_state["autoplay_enabled"] = enabled

    @staticmethod
    def get_autoplay_start_time() -> float:
        """Get the timestamp when the autoplay countdown started (0 = not running)."""
        return st.session_state.get("autoplay_start_time", 0.0)

    @staticmethod
    def set_autoplay_start_time(t: float):
        """Set the autoplay countdown start timestamp."""
        st.session_state["autoplay_start_time"] = t

    @staticmethod
    def get_autoplay_duration() -> int:
        """Get the autoplay countdown duration in seconds (2–10)."""
        return st.session_state.get("autoplay_duration", 5)

    @staticmethod
    def set_autoplay_duration(seconds: int):
        """Set the autoplay countdown duration in seconds (2–10)."""
        st.session_state["autoplay_duration"] = max(2, min(10, seconds))

    # IQM Viewer Widget Selection Mirrors
    #
    # The IQM viewer's pipeline-tab selector and Dataset/Dataset+reference
    # widgets live downstream of the sidebar in the script. Sidebar
    # navigation calls st.rerun()/st.switch_page() mid-script, which aborts
    # the run before those widgets are created, so Streamlit garbage-collects
    # their own widget-keyed state. These mirrors are plain session_state
    # entries the widgets are re-seeded from every run, so selections survive
    # a subject/session switch instead of silently resetting.
    @staticmethod
    def get_iqm_view_selection() -> str | None:
        """Get the remembered IQM pipeline-tab selection (e.g. "mriqc", "fmriprep"), or None if never set."""
        return st.session_state.get(SESSION_KEYS["iqm_view_selection"])

    @staticmethod
    def set_iqm_view_selection(view: str):
        """Remember the IQM pipeline-tab selection."""
        st.session_state[SESSION_KEYS["iqm_view_selection"]] = view

    @staticmethod
    def get_iqm_display_mode_selection() -> str:
        """Get the remembered IQM Dataset/Dataset+reference selection."""
        return st.session_state.get(SESSION_KEYS["iqm_display_mode_selection"], "Dataset")

    @staticmethod
    def set_iqm_display_mode_selection(mode: str):
        """Remember the IQM Dataset/Dataset+reference selection."""
        st.session_state[SESSION_KEYS["iqm_display_mode_selection"]] = mode
