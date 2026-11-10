"""Landing page component for QC-Studio UI."""

from pathlib import Path

import pandas as pd
import streamlit as st
from constants import (
    EXPERIENCE_LEVELS,
    FATIGUE_LEVELS,
    SCREEN_SIZES,
    DEFAULT_QC_RATING_OPTIONS,
    UPLOAD_FILE_TYPES,
    MESSAGES,
    ERROR_MESSAGES,
    SUCCESS_MESSAGES,
    INFO_MESSAGES,
    MIN_MONTAGE_GRID_SIZE,
    MAX_MONTAGE_GRID_SIZE,
    QC_DEDUP_KEYS,
    SESSION_KEYS,
)
from managers.session_manager import SessionManager
from models import QCRecord
from managers.panel_layout_manager import PanelLayoutManager
from utils.config import list_qc_tasks_from_json, parse_qc_config
from utils.cohort import (
    build_qc_cohort,
    count_complete_cohort_pages,
    decided_rating_keys_from_df,
    invalid_upload_cohort_pairs,
    participant_ids_in_cohort_order,
)


def _normalize_participant_id(pid: str) -> str:
    """Normalize participant IDs for CSV/list comparisons."""
    pid_str = str(pid).strip()
    return pid_str[4:] if pid_str.startswith("sub-") else pid_str


def _maybe_apply_montage_defaults_from_qc_json(
    qc_config_path: str,
    qc_task: str,
    first_participant_raw: str,
) -> None:
    """Apply optional montage_max_rows / montage_max_cols from qc.json once per session.

    Pipeline authors can recommend a default grid for multi-image montages per QC task.
    Raters can still override via the landing-page montage form afterward.
    """
    applied_key = SESSION_KEYS["montage_defaults_applied_qc_task"]
    if st.session_state.get(applied_key) == qc_task:
        return
    task_for_defaults = qc_task
    if str(qc_task).strip().lower() == "all":
        tasks = list_qc_tasks_from_json(qc_config_path)
        task_for_defaults = tasks[0] if tasks else qc_task
    pid = str(first_participant_raw).strip()
    if not pid.startswith("sub-"):
        pid = f"sub-{pid}"
    cfg = parse_qc_config(
        qc_config_path,
        task_for_defaults,
        {"participant_id": pid, "session_id": "ses-01"},
    )
    if cfg.get("montage_max_rows") is not None:
        SessionManager.set_montage_max_rows(cfg["montage_max_rows"])
    if cfg.get("montage_max_cols") is not None:
        SessionManager.set_montage_max_cols(cfg["montage_max_cols"])
    st.session_state[applied_key] = qc_task


def _upload_qc_task_filter_keys(qc_task: str, qc_config_path: str) -> list[str] | None:
    """QC task keys to keep when filtering an uploaded results file.

    For ``--qc_task all``, exports store concrete task names (``anat_wf_qc``, etc.),
    not the literal CLI value ``all``.
    """
    if str(qc_task).strip().lower() == "all":
        tasks = list_qc_tasks_from_json(qc_config_path)
        return tasks if tasks else None
    return [str(qc_task).strip()]


def _filter_uploaded_df_for_qc_task(
    df: pd.DataFrame,
    qc_task: str,
    qc_config_path: str,
) -> pd.DataFrame:
    """Return uploaded rows that belong to the current QC workflow."""
    if "qc_task" not in df.columns:
        return df.copy()
    filter_keys = _upload_qc_task_filter_keys(qc_task, qc_config_path)
    if filter_keys is None:
        return df.iloc[0:0].copy()
    return df[df["qc_task"].astype(str).isin(filter_keys)].copy()


def _upload_filter_label(qc_task: str, qc_config_path: str) -> str:
    """Human-readable label for the upload filter caption."""
    if str(qc_task).strip().lower() == "all":
        tasks = list_qc_tasks_from_json(qc_config_path)
        if tasks:
            return f"all ({', '.join(tasks)})"
        return "all (no tasks found in qc.json)"
    return str(qc_task)


def _qc_task_display_labels(qc_config_path: str, task_keys: list[str]) -> list[str]:
    """Human-readable QC task names (qc.json ``display_name``, else the task key)."""
    dummy = {"participant_id": "sub-x", "session_id": "ses-01"}
    labels: list[str] = []
    for key in task_keys:
        key_s = str(key).strip()
        if not key_s:
            continue
        cfg = parse_qc_config(qc_config_path, key_s, dummy)
        labels.append(cfg.get("display_name") or key_s)
    return labels


def _landing_qc_task_options(qc_config_path: str, fallback_qc_task: str | None = None) -> list[str]:
    """Return all QC tasks defined in qc.json, or a fallback of the current task when unavailable."""
    tasks = list_qc_tasks_from_json(qc_config_path)
    if tasks:
        return tasks
    fallback = str(fallback_qc_task or "").strip()
    return [fallback] if fallback else []


def _landing_run_summary_lines(
    qc_pipeline: str,
    n_subjects: int,
) -> str:
    """Return the landing-page summary line, showing only the pipeline and participant count."""
    return f"Pipeline: {qc_pipeline} | **Subjects:** {n_subjects}"


def _list_resume_files(out_dir: str) -> tuple[Path | None, list[Path]]:
    """Find status/checkpoint TSV files under the run output directory."""
    base_dir = Path(str(out_dir).strip()).expanduser() if out_dir and str(out_dir).strip() else None
    if base_dir is None:
        return None, []

    try:
        resolved_base = base_dir.resolve()
    except OSError:
        return None, []
    if not resolved_base.exists() or not resolved_base.is_dir():
        return resolved_base, []

    seen: set[Path] = set()
    candidates: list[Path] = []
    patterns = ["*_qc_status.tsv", "*_status.tsv"]
    for pattern in patterns:
        for path in resolved_base.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                candidates.append(path)

    checkpoint_dir = resolved_base / "checkpoints"
    if checkpoint_dir.exists() and checkpoint_dir.is_dir():
        for path in checkpoint_dir.glob("*.tsv"):
            if path.is_file() and path not in seen:
                seen.add(path)
                candidates.append(path)

    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0.0, reverse=True)
    return resolved_base, candidates


def _resume_file_label(base_dir: Path, candidate: Path) -> str:
    """Human-readable label for local resume files in the select box."""
    try:
        rel = candidate.relative_to(base_dir)
        return str(rel)
    except ValueError:
        return str(candidate)


def _records_from_df_task(df_task: pd.DataFrame) -> list[QCRecord]:
    """Convert filtered TSV rows into QCRecord entries for session import."""
    loaded_records: list[QCRecord] = []
    has_facets = "facet" in df_task.columns and "rating_value" in df_task.columns and df_task["facet"].notna().any()
    if has_facets:
        group_cols = [c for c in ["participant_id", "session_id", "pipeline", "qc_task", "task_id", "run_id"] if c in df_task.columns]
        for _, group in df_task.groupby(group_cols, dropna=False, sort=False):
            first_row = group.iloc[0]
            ratings = {}
            for _, row in group.iterrows():
                facet = row.get("facet")
                value = row.get("rating_value")
                if pd.notna(facet) and str(facet).strip():
                    ratings[str(facet).strip()] = str(value).strip() if pd.notna(value) else ""

            final_qc = SessionManager.derive_multifacet_final_qc(ratings)
            if final_qc is None:
                final_qc_raw = first_row.get("final_qc", "")
                final_qc_txt = str(final_qc_raw).strip() if pd.notna(final_qc_raw) else ""
                final_qc = final_qc_txt if final_qc_txt.lower() not in {"", "none", "nan"} else None

            record = QCRecord(
                participant_id=str(first_row.get("participant_id", "")),
                session_id=str(first_row.get("session_id", "")),
                qc_task=str(first_row.get("qc_task", "")),
                pipeline=str(first_row.get("pipeline", "")),
                timestamp=str(first_row.get("timestamp", "")),
                rater_id=str(first_row.get("rater_id", "")),
                rater_experience=str(first_row.get("rater_experience", "")),
                rater_fatigue=str(first_row.get("rater_fatigue", "")),
                rater_screen_size=str(first_row.get("rater_screen_size", "")),
                final_qc=final_qc,
                ratings=ratings,
                notes=str(first_row.get("notes", "")) if pd.notna(first_row.get("notes")) else "",
            )
            loaded_records.append(record)
    else:
        for _, row in df_task.iterrows():
            record = QCRecord(
                participant_id=str(row.get("participant_id", "")),
                session_id=str(row.get("session_id", "")),
                qc_task=str(row.get("qc_task", "")),
                pipeline=str(row.get("pipeline", "")),
                timestamp=str(row.get("timestamp", "")),
                rater_id=str(row.get("rater_id", "")),
                rater_experience=str(row.get("rater_experience", "")),
                rater_fatigue=str(row.get("rater_fatigue", "")),
                rater_screen_size=str(row.get("rater_screen_size", "")),
                final_qc=str(row.get("final_qc", "")),
                notes=str(row.get("notes", "")) if pd.notna(row.get("notes")) else "",
            )
            loaded_records.append(record)
    return loaded_records


def _show_import_confirmation_dialog(
    payload_key: str,
    feedback_key: str,
    total_cohort_pages: int,
    qc_cohort: list[dict],
    qc_tasks: list[str],
) -> None:
    """Render a popup preview of parsed TSV rows and require explicit import confirmation."""
    payload = st.session_state.get(payload_key)
    if not payload:
        return

    def _confirm_import_dialog_body() -> None:
        st.caption(f"Source file: {payload['source_name']} | Current workflow filter: **{payload['filter_label']}**")

        source_df = payload["source_df"]
        top_left, top_right = st.columns(2)
        with top_left:
            if len(source_df) > 0:
                first_record = source_df.iloc[0]
                extracted_rater_id = str(first_record.get("rater_id", ""))
                extracted_experience = str(first_record.get("rater_experience", ""))
                extracted_fatigue = str(first_record.get("rater_fatigue", ""))
                extracted_screen_size = str(first_record.get("rater_screen_size", ""))
                # st.info(INFO_MESSAGES["rater_info_extracted"])
                st.write(INFO_MESSAGES["rater_id_prefix"].format(id=extracted_rater_id))
                st.write(INFO_MESSAGES["experience_prefix"].format(exp=extracted_experience))
                st.write(INFO_MESSAGES["fatigue_prefix"].format(fatigue=extracted_fatigue))
                st.write(INFO_MESSAGES["screen_size_prefix"].format(size=extracted_screen_size))

        with top_right:
            col_comp1, col_comp2 = st.columns(2)
            with col_comp1:
                st.metric(label="QC pages reviewed", value=payload["pages_reviewed"])
            with col_comp2:
                st.metric(label="QC records reviewed", value=payload["records_reviewed"])

            if payload.get("facet_total", 0) > 0:
                st.metric(label="Facet ratings reviewed", value=f"{payload['facet_reviewed']} / {payload['facet_total']}")

            st.caption(
                f"Totals: {total_cohort_pages} cohort pages · {payload['total_qc_records']} QC records "
                "across this workflow. When a page includes multiple tasks, records can exceed pages."
            )
            progress_pct = payload["progress_pct"]
            st.progress(min(progress_pct / 100, 1.0), text=f"{progress_pct:.1f}% of QC records complete")

        if payload["preview_df"].empty:
            st.warning(
                f"No records found for workflow **{payload['filter_label']}** in the uploaded file. "
                f"All {payload['total_rows']} records are for other tasks."
            )
        else:
            st.subheader(INFO_MESSAGES["preview_header"])
            st.caption(f"Showing records for workflow: **{payload['filter_label']}**")
            st.dataframe(payload["preview_df"], width="stretch")

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("📥 Confirm Import", key="confirm_import_records", width="stretch"):
                source_df = payload["source_df"]
                if len(source_df) > 0:
                    first_record = source_df.iloc[0]
                    SessionManager.set_rater_id(str(first_record.get("rater_id", "")))
                    SessionManager.set_rater_experience(str(first_record.get("rater_experience", "")))
                    SessionManager.set_rater_fatigue(str(first_record.get("rater_fatigue", "")))
                    SessionManager.set_rater_screen_size(str(first_record.get("rater_screen_size", "")))

                loaded_records = _records_from_df_task(payload["df_task"])
                SessionManager.set_qc_records(loaded_records)
                SessionManager.set_qc_cohort_order(qc_cohort)
                SessionManager.set_participant_ids(participant_ids_in_cohort_order(qc_cohort))
                if SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks, qc_cohort):
                    target_page = total_cohort_pages + 1
                else:
                    next_page = SessionManager.first_qc_cohort_page_missing_for_tasks(qc_tasks, qc_cohort)
                    target_page = min(next_page, total_cohort_pages)
                SessionManager.set_current_page(target_page)
                st.session_state[feedback_key] = (
                    SUCCESS_MESSAGES["records_loaded"].format(count=len(loaded_records)),
                    INFO_MESSAGES["proceed_with_form"],
                )
                st.session_state.pop(payload_key, None)
                st.rerun()

        with col_btn2:
            if st.button("Cancel", key="cancel_import_records", width="stretch"):
                st.session_state.pop(payload_key, None)
                st.rerun()

    dialog_fn = getattr(st, "dialog", None)
    can_use_dialog = callable(dialog_fn) and "streamlit" in str(getattr(dialog_fn, "__module__", ""))
    if can_use_dialog:

        @st.dialog("Confirm QC Data Import", width="large")
        def _confirm_import_dialog() -> None:
            _confirm_import_dialog_body()

        _confirm_import_dialog()
    else:
        _confirm_import_dialog_body()


def show_landing_page(
    qc_pipeline,
    qc_task,
    out_dir,
    participant_list,
    qc_config_path: str,
    *,
    qc_cohort: list[dict] | None = None,
    session_ids: list[str] | None = None,
    entrypoint_rel_path: str | None = None,
) -> None:
    """Display the landing page with rater info, panel selection, and CSV upload.

    Args:
            qc_pipeline: QC pipeline name
            qc_task: QC task name
            out_dir: Output directory path
            participant_list: Path to participant list file
            qc_config_path: Absolute or cwd-relative path to qc.json (for optional montage defaults)
            qc_cohort: Optional pre-built (participant, session) page list from CLI context
            session_ids: BIDS session labels when ``qc_cohort`` is not provided
            entrypoint_rel_path: If set (for example ``"main.py"``), a successful Continue to QC
                    uses ``st.switch_page`` so the multipage sidebar hands off to the real app entrypoint.
                    Omit when the host is already ``main`` / ``app`` (normal ``st.rerun()``).
    """
    rater_id = SessionManager.get_rater_id_display()
    greeting = f"Salut {rater_id}!" if rater_id else ""
    welcome_markdown = f"# :blue[{greeting}] {MESSAGES['welcome_title']}" if greeting else f"# {MESSAGES['welcome_title']}"
    st.markdown(welcome_markdown)

    available_qc_tasks = _landing_qc_task_options(qc_config_path, qc_task)
    all_tasks_locked = SessionManager.is_all_tasks_mode_locked()
    task_changed = False
    if available_qc_tasks:
        if all_tasks_locked:
            selected_task = "all"
            SessionManager.set_selected_qc_task(selected_task)
            qc_task = selected_task
            st.sidebar.subheader("Available tasks")
            st.sidebar.caption("Task selection is locked because the run was started with `--qc_task all`.")
        else:
            previous_selection = SessionManager.get_selected_qc_task()
            current_selection = previous_selection
            if current_selection in available_qc_tasks:
                selected_task = current_selection
            elif str(qc_task).strip() in available_qc_tasks:
                selected_task = str(qc_task).strip()
            else:
                selected_task = available_qc_tasks[0]
            st.sidebar.subheader("Available tasks")
            radio_value = st.sidebar.radio(
                label="Choose QC task",
                options=available_qc_tasks,
                index=available_qc_tasks.index(selected_task),
                key="landing_page_qc_task_radio",
            )
            if isinstance(radio_value, str) and radio_value in available_qc_tasks:
                selected_task = radio_value
            else:
                selected_task = available_qc_tasks[available_qc_tasks.index(selected_task)]
            task_changed = bool(previous_selection and selected_task != previous_selection)
            SessionManager.set_selected_qc_task(selected_task)
            qc_task = selected_task

        default_rating = SessionManager.get_default_qc_rating()
        default_idx = DEFAULT_QC_RATING_OPTIONS.index(default_rating) if default_rating in DEFAULT_QC_RATING_OPTIONS else 0
        st.sidebar.subheader("Default QC rating")
        selected_default_rating = st.sidebar.radio(
            label="Choose default rating",
            options=DEFAULT_QC_RATING_OPTIONS,
            index=default_idx,
            key="landing_page_default_qc_rating_radio",
        )
        SessionManager.set_default_qc_rating(selected_default_rating)
    else:
        SessionManager.set_selected_qc_task("")

    # Load participant list to get total unique participants
    try:
        participants_df = pd.read_csv(participant_list, delimiter="\t")
        raw_ids = participants_df["participant_id"].tolist()
        normalized_ids = [_normalize_participant_id(pid) for pid in raw_ids]
        total_participants_in_ds = len(set(normalized_ids))
        participant_ids_in_ds = set(normalized_ids)
        if qc_cohort is None:
            qc_cohort = build_qc_cohort(participants_df, session_ids or ["ses-01"])
        total_cohort_pages = len(qc_cohort)

        if task_changed:
            qc_tasks_for_selection = _upload_qc_task_filter_keys(qc_task, qc_config_path) or [qc_task]
            if SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks_for_selection, qc_cohort):
                target_page = total_cohort_pages + 1
            else:
                next_page = SessionManager.first_qc_cohort_page_missing_for_tasks(qc_tasks_for_selection, qc_cohort)
                target_page = min(next_page, total_cohort_pages) if total_cohort_pages > 0 else 1
            SessionManager.set_current_page(target_page)
    except Exception as e:
        st.error(ERROR_MESSAGES["participant_list_load_error"].format(error=e))
        return

    if raw_ids:
        _maybe_apply_montage_defaults_from_qc_json(qc_config_path, qc_task, raw_ids[0])

    summary_line = _landing_run_summary_lines(qc_pipeline, total_participants_in_ds)
    st.subheader(summary_line)
    st.markdown("---")

    # Three-column layout for rater info, panel selection, and CSV upload
    col1, col2, col3 = st.columns([1, 1, 1], gap="large")

    # Left column: Rater Information
    with col1:
        _display_rater_form(entrypoint_rel_path=entrypoint_rel_path)

    # Middle column: Panel Selection and Montage Settings
    with col2:
        PanelLayoutManager.render_panel_header_with_controls()
        st.divider()
        _display_montage_settings()

    # Right column: CSV Upload
    with col3:
        _display_csv_upload(
            participant_ids_in_ds,
            total_cohort_pages,
            qc_cohort,
            qc_task,
            qc_config_path,
            out_dir,
        )

    st.markdown("---")


def _display_rater_form(entrypoint_rel_path: str | None = None) -> None:
    """Render rater information form in the landing page."""
    st.subheader(MESSAGES["rater_info_header"])
    with st.form("rater_form"):
        # Rater name/ID
        rater_id = st.text_input(MESSAGES["rater_id_prompt"], value=SessionManager.get_rater_id_display())

        # Keep the exact display value for the landing-page greeting and form, while
        # still normalizing for filename safety when the session is exported.
        rater_id_clean = "".join(rater_id.split()).lower()

        # Experience level
        default_exp_idx = 0
        if SessionManager.get_rater_experience() in EXPERIENCE_LEVELS:
            default_exp_idx = EXPERIENCE_LEVELS.index(SessionManager.get_rater_experience())
        rater_experience = st.radio(MESSAGES["experience_prompt"], EXPERIENCE_LEVELS, index=default_exp_idx)

        # Fatigue level
        default_fatigue_idx = 0
        if SessionManager.get_rater_fatigue() in FATIGUE_LEVELS:
            default_fatigue_idx = FATIGUE_LEVELS.index(SessionManager.get_rater_fatigue())
        rater_fatigue = st.radio(MESSAGES["fatigue_prompt"], FATIGUE_LEVELS, index=default_fatigue_idx)

        # Screen size
        default_screen_idx = 0
        if SessionManager.get_rater_screen_size() in SCREEN_SIZES:
            default_screen_idx = SCREEN_SIZES.index(SessionManager.get_rater_screen_size())
        rater_screen_size = st.radio(MESSAGES["screen_size_prompt"], SCREEN_SIZES, index=default_screen_idx)

        # Autoplay countdown duration
        autoplay_duration = st.slider(
            "⏱️ Autoplay duration (seconds)", min_value=5, max_value=15, value=SessionManager.get_autoplay_duration(), step=1
        )

        submit_rater = st.form_submit_button(MESSAGES["rater_form_button"], width="stretch")

        if submit_rater:
            if not rater_id_clean:
                st.error(ERROR_MESSAGES["invalid_rater_id"])
            elif SessionManager.get_panel_count() == 0:
                st.error(ERROR_MESSAGES["no_panel_selected"])
            else:
                SessionManager.set_rater_id(rater_id_clean)
                SessionManager.set_rater_id_display(rater_id)
                SessionManager.set_rater_experience(rater_experience)
                SessionManager.set_rater_fatigue(rater_fatigue)
                SessionManager.set_rater_screen_size(rater_screen_size)
                SessionManager.set_autoplay_duration(autoplay_duration)
                SessionManager.set_landing_page_complete(True)
                if entrypoint_rel_path:
                    st.switch_page(entrypoint_rel_path)
                st.rerun()


def _display_csv_upload(
    participant_ids_in_ds: set,
    total_cohort_pages: int,
    qc_cohort: list[dict],
    qc_task: str,
    qc_config_path: str,
    out_dir: str,
) -> None:
    """Render CSV upload section in the landing page.

    Args:
            participant_ids_in_ds: Set of normalized participant IDs in dataset
            total_cohort_pages: Total (participant, session) pages in this run
            qc_cohort: Ordered cohort rows for pagination
            qc_task: Current QC task name (used to filter uploaded CSV)
            qc_config_path: Path to qc.json (required when ``qc_task`` is ``all``)
            out_dir: CLI output directory that may contain saved status/checkpoint files
    """
    pending_payload_key = "landing_pending_import_payload"
    import_feedback_key = "landing_import_feedback"
    qc_tasks = _upload_qc_task_filter_keys(qc_task, qc_config_path) or []
    st.subheader(MESSAGES["upload_header"])
    st.info(MESSAGES["upload_help"])

    if import_feedback_key in st.session_state:
        loaded_msg, proceed_msg = st.session_state.pop(import_feedback_key)
        st.success(loaded_msg)
        st.info(proceed_msg)

    selected_local_path: Path | None = None
    load_selected_local_file = False
    local_output_dir, local_resume_files = _list_resume_files(out_dir)
    if local_output_dir and local_resume_files:
        st.caption(f"Found {len(local_resume_files)} resume file(s) in output directory: {local_output_dir}")
        file_labels = [_resume_file_label(local_output_dir, p) for p in local_resume_files]
        selected_label = st.selectbox(
            "Available checkpoint file (s)",
            options=["(none)"] + file_labels,
            index=0,
            key="qc_local_resume_file_select",
        )
        if selected_label != "(none)":
            selected_index = file_labels.index(selected_label)
            selected_local_path = local_resume_files[selected_index]
            load_selected_local_file = st.button("📂 Load Selected Output File", key="load_selected_output_file", width="stretch")
    elif local_output_dir:
        st.caption(f"No status/checkpoint TSV files found in output directory: {local_output_dir}")

    uploaded_file = st.file_uploader(MESSAGES["csv_uploader_label"], type=UPLOAD_FILE_TYPES, key="qc_file_upload")
    source_name: str | None = None
    source_input = None
    should_review_source = False

    if uploaded_file is not None:
        source_input = uploaded_file
        source_name = uploaded_file.name
        should_review_source = pending_payload_key not in st.session_state
    elif load_selected_local_file and selected_local_path is not None:
        source_input = selected_local_path
        source_name = selected_local_path.name
        should_review_source = True

    if should_review_source and source_input is not None and source_name is not None:
        try:
            # Read the chosen file while preserving zero-padded subject IDs.
            df = pd.read_csv(source_input, sep=None, engine="python", dtype=str)

            # Deduplicate rows by QC_DEDUP_KEYS (keeping most recent record per participant)
            dedup_cols = [k for k in QC_DEDUP_KEYS if k in df.columns]
            if "facet" in df.columns:
                dedup_cols.append("facet")
            if dedup_cols:
                df[dedup_cols] = df[dedup_cols].astype(str)
                df = df.drop_duplicates(subset=dedup_cols, keep="last").reset_index(drop=True)

            # Normalize participant IDs to support re-uploaded exports without sub- prefix.
            df["participant_id"] = df["participant_id"].astype(str)
            df["_participant_id_norm"] = df["participant_id"].map(_normalize_participant_id)

            df_task = _filter_uploaded_df_for_qc_task(df, qc_task, qc_config_path)
            filter_label = _upload_filter_label(qc_task, qc_config_path)

            # Guardrail: uploaded records must match the currently selected QC task(s).
            if "qc_task" in df.columns and df_task.empty and len(df) > 0:
                uploaded_tasks = sorted({str(t).strip() for t in df["qc_task"].dropna().tolist() if str(t).strip()})
                expected_tasks = _upload_qc_task_filter_keys(qc_task, qc_config_path) or []
                uploaded_label = ", ".join(uploaded_tasks) if uploaded_tasks else "(missing qc_task values)"
                expected_label = ", ".join(expected_tasks) if expected_tasks else str(qc_task)
                st.error(
                    "Uploaded file task(s) do not match the selected QC task in the sidebar. "
                    f"Selected task(s): {expected_label}. Uploaded task(s): {uploaded_label}. "
                    "Please upload another file or select the matching QC task in the sidebar."
                )
                st.stop()

            decided = decided_rating_keys_from_df(df_task, qc_tasks)
            pages_reviewed = count_complete_cohort_pages(qc_cohort, qc_tasks, decided)
            records_reviewed = len(decided)
            total_qc_records = len(qc_cohort) * len(qc_tasks) if qc_cohort and qc_tasks else 0
            facet_mask = (
                df_task["facet"].fillna("").astype(str).str.strip().ne("") if "facet" in df_task.columns else pd.Series(False, index=df_task.index)
            )
            facet_total = int(facet_mask.sum()) if len(df_task) > 0 else 0
            if "rating_value" in df_task.columns:
                facet_reviewed = int((facet_mask & df_task["rating_value"].fillna("").astype(str).str.strip().ne("")).sum())
            else:
                facet_reviewed = 0
            participant_ids_in_csv = {str(pid).strip() for pid in df_task["_participant_id_norm"].unique()}
            preview_df = df_task.drop(columns=["_participant_id_norm"], errors="ignore")

            # Validate: Check if CSV has participants not in the participant list
            invalid_participants = participant_ids_in_csv - participant_ids_in_ds
            if invalid_participants:
                st.error(
                    ERROR_MESSAGES["no_participants"].format(count=len(invalid_participants), participants=", ".join(sorted(invalid_participants)))
                )
                st.stop()

            invalid_pairs = invalid_upload_cohort_pairs(df_task, qc_cohort, participant_ids_in_ds)
            if invalid_pairs:
                pair_text = ", ".join(f"{pid} / {sid}" for pid, sid in sorted(invalid_pairs))
                st.error(f"❌ Error: The uploaded file contains {len(invalid_pairs)} " f"participant/session pair(s) not in this cohort: {pair_text}")
                st.stop()

            progress_pct = (records_reviewed / total_qc_records) * 100 if total_qc_records > 0 else 0
            source_df = df_task if len(df_task) > 0 else df
            st.success(SUCCESS_MESSAGES["csv_loaded"].format(count=len(df), filename=source_name))
            st.session_state[pending_payload_key] = {
                "source_name": source_name,
                "filter_label": filter_label,
                "pages_reviewed": pages_reviewed,
                "records_reviewed": records_reviewed,
                "total_qc_records": total_qc_records,
                "facet_reviewed": facet_reviewed,
                "facet_total": facet_total,
                "progress_pct": progress_pct,
                "total_rows": len(df),
                "preview_df": preview_df.head(10),
                "source_df": source_df,
                "df_task": df_task,
            }

        except Exception as e:
            st.error(ERROR_MESSAGES["file_load_error"].format(error=e))

    _show_import_confirmation_dialog(
        payload_key=pending_payload_key,
        feedback_key=import_feedback_key,
        total_cohort_pages=total_cohort_pages,
        qc_cohort=qc_cohort,
        qc_tasks=qc_tasks,
    )

    st.divider()
    st.markdown(
        """
	**ℹ️ Tips:**
	- Save your work periodically using the **Checkpoint** :floppy_disk:
	- Upload a previous **checkpoint** to resume or review work
	"""
    )


def _display_montage_settings() -> None:
    """Render montage grid configuration settings.

    Allows users to specify maximum rows and columns for the montage grid.
    When both are set to None (auto), the montage will optimize for square aspect ratio.
    """
    st.markdown("#### Montage Grid Settings")

    with st.form("montage_settings_form"):
        col1, col2 = st.columns(2)

        with col1:
            current_rows = SessionManager.get_montage_max_rows()
            montage_rows = st.number_input(
                "Max Rows",
                min_value=MIN_MONTAGE_GRID_SIZE,
                max_value=MAX_MONTAGE_GRID_SIZE,
                value=current_rows if current_rows else MIN_MONTAGE_GRID_SIZE,
                step=1,
                help="Maximum number of rows in the montage grid",
            )
            use_auto_rows = st.checkbox("Auto-calculate rows", value=(current_rows is None))

        with col2:
            current_cols = SessionManager.get_montage_max_cols()
            montage_cols = st.number_input(
                "Max Columns",
                min_value=MIN_MONTAGE_GRID_SIZE,
                max_value=MAX_MONTAGE_GRID_SIZE,
                value=current_cols if current_cols else MIN_MONTAGE_GRID_SIZE,
                step=1,
                help="Maximum number of columns in the montage grid",
            )
            use_auto_cols = st.checkbox("Auto-calculate columns", value=(current_cols is None))

        submit_montage = st.form_submit_button("Apply Montage Settings", width="stretch")

        if submit_montage:
            # Set to None if auto-calculate is checked, otherwise use the specified value
            rows_to_set = None if use_auto_rows else montage_rows
            cols_to_set = None if use_auto_cols else montage_cols

            SessionManager.set_montage_max_rows(rows_to_set)
            SessionManager.set_montage_max_cols(cols_to_set)

            # Display confirmation
            auto_text = "(auto)" if use_auto_rows else f"({montage_rows})"
            auto_text_cols = "(auto)" if use_auto_cols else f"({montage_cols})"
            st.success(f"✅ Montage settings updated: Max rows {auto_text}, Max columns {auto_text_cols}")

    # Show current settings
    current_rows = SessionManager.get_montage_max_rows()
    current_cols = SessionManager.get_montage_max_cols()
    rows_display = "Auto" if current_rows is None else str(current_rows)
    cols_display = "Auto" if current_cols is None else str(current_cols)
    st.info(f"📋 Current montage settings: Max rows = {rows_display}, Max columns = {cols_display}")
