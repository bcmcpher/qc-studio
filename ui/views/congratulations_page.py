"""Congratulations page component for QC-Studio UI."""

from pathlib import Path
import re
import pandas as pd
import streamlit as st
from constants import MESSAGES, SUCCESS_MESSAGES, INFO_MESSAGES
from managers.session_manager import SessionManager
from utils.path_helpers import sanitize_qc_task_slug
from utils.export import save_qc_results_to_csv

CONGRATS_EXPORT_PATH_KEY = "congrats_export_path"
CONGRATS_EXPORT_PATH_DEFAULT_KEY = "_congrats_export_path_default"
OVERWRITE_CONFIRMATION_PATH_KEY = "_pending_overwrite_path"


def _default_congrats_export_path(
    out_dir: str,
    rater_id: str,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
    qc_session_id: str | None = None,
) -> str:
    """Default export path shown on the congratulations page."""
    base_dir = Path(str(out_dir).strip()).expanduser() if out_dir and str(out_dir).strip() else Path(".").expanduser()
    base_dir = base_dir.resolve() if base_dir.is_absolute() else (Path.cwd() / base_dir).resolve()
    rid = str(rater_id).strip().lower() or "rater"
    pipe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(qc_pipeline or "").strip()).strip("_").lower() or "qc"
    task = sanitize_qc_task_slug(qc_task or "all")
    filename = f"{rid}_{pipe}_{task}_qc_status.tsv"
    return str((base_dir / filename).resolve())


def _require_overwrite_confirmation(file_path: str | Path, label: str) -> bool:
    """Require a second explicit click before overwriting an existing export file."""
    target = Path(str(file_path)).expanduser()
    pending = st.session_state.get(OVERWRITE_CONFIRMATION_PATH_KEY)
    if not target.exists():
        st.session_state.pop(OVERWRITE_CONFIRMATION_PATH_KEY, None)
        return True
    if pending == str(target):
        st.session_state.pop(OVERWRITE_CONFIRMATION_PATH_KEY, None)
        return True
    st.session_state[OVERWRITE_CONFIRMATION_PATH_KEY] = str(target)
    st.warning(f"⚠️ {label} will overwrite the existing file: {target}")
    return False


def _resolve_congrats_export_file_path(
    out_dir: str,
    rater_id: str,
    save_file_path: str | None,
    *,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
) -> Path:
    """Resolve export destination from optional user input.

    If a directory-like path is provided (no suffix), append the default file name.
    """
    if save_file_path and str(save_file_path).strip():
        candidate = Path(str(save_file_path).strip()).expanduser()
        if candidate.suffix:
            return candidate
        default = _default_congrats_export_path(out_dir, rater_id, qc_pipeline=qc_pipeline, qc_task=qc_task)
        return candidate / Path(default).name
    return Path(_default_congrats_export_path(out_dir, rater_id, qc_pipeline=qc_pipeline, qc_task=qc_task))


def show_congratulations_page(
    qc_task: str,
    out_dir: str,
    total_participants: int,
    drop_duplicates: bool,
    *,
    cohort_complete: bool = True,
    participant_ids: list | None = None,
    session_id: str | None = None,
    qc_cohort: list | None = None,
    qc_tasks: list | None = None,
    entrypoint_rel_path: str | None = None,
    qc_pipeline: str | None = None,
) -> None:
    """Display congratulations (full summary) or a minimal placeholder until all subjects are QC'd.

    Args:
            qc_task: QC task name
            out_dir: Output directory path
            total_participants: Total number of participants in the QC session
            drop_duplicates: Whether to drop duplicate records before saving
            cohort_complete: When False, show a minimal page (not all subjects have a decided rating).
            participant_ids: Cohort order (for Continue QC navigation when using legacy single-session mode).
            session_id: BIDS session id for legacy single-session completion checks.
            qc_tasks: Task keys for this run (defaults to ``[qc_task]``).
            entrypoint_rel_path: If set (e.g. ``"main.py"``), sidebar navigation uses ``st.switch_page``.
            qc_pipeline: Pipeline name used in export file names (matches the sidebar save).
    """
    tasks_eff = list(qc_tasks) if qc_tasks else [qc_task]

    def _fully_reviewed_cohort_pages(records: list) -> int:
        required = {str(t) for t in tasks_eff}
        by_page: dict[tuple[str, str], set[str]] = {}
        for r in records:
            if not SessionManager._final_qc_is_decided(r):
                continue
            pid = r.participant_id if hasattr(r, "participant_id") else r.get("participant_id", "")
            sid = r.session_id if hasattr(r, "session_id") else r.get("session_id", "")
            tk = r.qc_task if hasattr(r, "qc_task") else r.get("qc_task", "")
            k = (str(pid), str(sid))
            by_page.setdefault(k, set()).add(str(tk))
        return sum(1 for ts in by_page.values() if required <= ts)

    st.sidebar.empty()
    if not cohort_complete:
        st.subheader("QC not finished yet")
        st.info("Not every review page has a PASS / FAIL / UNCERTAIN rating yet. " "When you are ready, use **Continue QC** to return to the review.")
        can_continue = bool(qc_cohort) or (bool(participant_ids) and bool(session_id))
        if can_continue and st.button("Continue QC", key="congrats_continue_qc_incomplete"):
            if qc_cohort:
                miss = SessionManager.first_qc_cohort_page_missing_for_tasks(tasks_eff, qc_cohort)
            else:
                temp_cohort = []
                for pid in participant_ids or []:
                    p = str(pid).strip()
                    if not p.startswith("sub-"):
                        p = f"sub-{p}"
                    temp_cohort.append({"participant_id": p, "session_id": session_id})
                miss = SessionManager.first_qc_cohort_page_missing_for_tasks(tasks_eff, temp_cohort)
            SessionManager.set_current_page(miss)
            if entrypoint_rel_path:
                st.switch_page(entrypoint_rel_path)
            st.rerun()
        return

    st.title(MESSAGES["congratulations_title"])

    record_list = SessionManager.get_latest_qc_records_for_task_set(tasks_eff)
    num_pages_done = _fully_reviewed_cohort_pages(record_list)
    num_decided_rows = len([r for r in record_list if SessionManager._final_qc_is_decided(r)])
    if len(tasks_eff) > 1:
        headline = f"## {num_pages_done} review page(s) fully completed (all {len(tasks_eff)} tasks rated)"
    else:
        headline = f"## {num_decided_rows} participant(s) have been reviewed!"

    st.markdown(
        f"""
	{headline}

	Thank you for completing the quality control process. Your thorough review ensures the integrity of our data!

	"""
    )

    rater_id = SessionManager.get_rater_id()
    pipeline_for_export = qc_pipeline or None
    all_tasks_locked = SessionManager.is_all_tasks_mode_locked()
    single_file_mode = bool(all_tasks_locked and len(tasks_eff) > 1)
    export_task_default = "all" if single_file_mode else (tasks_eff[0] if len(tasks_eff) == 1 else "all")
    # Display session information and results summary
    task_label = ", ".join(tasks_eff) if len(tasks_eff) > 1 else tasks_eff[0]
    summary_count = num_pages_done if len(tasks_eff) > 1 else num_decided_rows
    _display_session_summary(rater_id, task_label, record_list, reviewed_count=summary_count, multi_task=len(tasks_eff) > 1)
    if pending := st.session_state.pop("_pending_export_msg", None):
        kind, msg = pending
        (st.success if kind == "success" else st.info)(msg)

    default_export_path = _default_congrats_export_path(
        out_dir,
        rater_id,
        qc_pipeline=pipeline_for_export,
        qc_task=export_task_default,
        qc_session_id=SessionManager.get_qc_session_id(),
    )
    if CONGRATS_EXPORT_PATH_KEY not in st.session_state:
        st.session_state[CONGRATS_EXPORT_PATH_KEY] = default_export_path
        st.session_state[CONGRATS_EXPORT_PATH_DEFAULT_KEY] = default_export_path
    else:
        prev_default = st.session_state.get(CONGRATS_EXPORT_PATH_DEFAULT_KEY)
        current_value = st.session_state.get(CONGRATS_EXPORT_PATH_KEY, "")
        if prev_default and current_value == prev_default and default_export_path != prev_default:
            st.session_state[CONGRATS_EXPORT_PATH_KEY] = default_export_path
        st.session_state[CONGRATS_EXPORT_PATH_DEFAULT_KEY] = default_export_path

    st.caption(f"Default path: {default_export_path}")
    st.text_input(
        "QC status file path",
        key=CONGRATS_EXPORT_PATH_KEY,
        help="Set a custom file path for exported QC results (for example, /path/to/QC_status.csv). The default uses the --output_dir CLI setting.",
    )

    # Action buttons
    col1, col2 = st.columns([1, 1])
    with col1:
        export_target = _resolve_congrats_export_file_path(
            out_dir,
            rater_id,
            st.session_state.get(CONGRATS_EXPORT_PATH_KEY),
            qc_pipeline=pipeline_for_export,
            qc_task=export_task_default,
        )
        if st.session_state.get(OVERWRITE_CONFIRMATION_PATH_KEY) == str(export_target):
            st.warning(f"⚠️ Existing export file will be overwritten: {export_target}")
            if st.button("Overwrite existing file", key="confirm_congrats_overwrite", type="primary", width="stretch"):
                st.session_state.pop(OVERWRITE_CONFIRMATION_PATH_KEY, None)
                export_rows = SessionManager.get_latest_qc_records_per_dedup(None)
                _export_qc_results(
                    rater_id,
                    out_dir,
                    export_rows,
                    drop_duplicates,
                    save_file_path=st.session_state.get(CONGRATS_EXPORT_PATH_KEY),
                    single_file_mode=single_file_mode,
                    qc_pipeline=pipeline_for_export,
                    qc_task=export_task_default,
                )
                st.rerun()
        elif st.button(MESSAGES["export_results_button"], width="stretch"):
            if _require_overwrite_confirmation(export_target, "Final QC export"):
                export_rows = SessionManager.get_latest_qc_records_per_dedup(None)
                _export_qc_results(
                    rater_id,
                    out_dir,
                    export_rows,
                    drop_duplicates,
                    save_file_path=st.session_state.get(CONGRATS_EXPORT_PATH_KEY),
                    single_file_mode=single_file_mode,
                    qc_pipeline=pipeline_for_export,
                    qc_task=export_task_default,
                )
                st.rerun()
            else:
                st.rerun()
    with col2:
        if st.button(MESSAGES["previous_button"], width="stretch"):
            SessionManager.previous_page()
            if entrypoint_rel_path:
                st.switch_page(entrypoint_rel_path)
            st.rerun()


def _display_session_summary(
    rater_id: str,
    qc_task: str,
    record_list: list,
    *,
    reviewed_count: int | None = None,
    multi_task: bool = False,
) -> None:
    """Display summary of the QC session.

    Args:
            rater_id: Rater ID
            qc_task: QC task name
            record_list: QC records for this task (deduplicated)
            reviewed_count: Participants with a decided rating; defaults to len(record_list)
            multi_task: When True, ``reviewed_count`` counts cohort pages with every task rated.
    """
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Session Information")
        st.write(f"**Rater ID:** {rater_id}")
        st.write(f"**QC Task:** {qc_task}")
        n_rev = reviewed_count if reviewed_count is not None else len(record_list)
        if multi_task:
            st.write(f"**Fully completed review pages:** {n_rev}")
        else:
            st.write(f"**Total Participants Reviewed:** {n_rev}")

    with col2:
        st.subheader("QC Results Summary")
        if not record_list:
            st.info("No QC records available yet.")
            return

        subject_counts: dict[str, int] = {}
        facet_counts_by_name: dict[str, dict[str, int]] = {}
        has_multifacet = False

        def _count_bucket(value: str) -> str:
            text = str(value or "").strip()
            return text if text else "Unrated"

        for record in record_list:
            final_qc = record.final_qc if hasattr(record, "final_qc") else record.get("final_qc", "")
            ratings_map = record.ratings if hasattr(record, "ratings") else record.get("ratings", None)

            if isinstance(ratings_map, dict) and ratings_map:
                has_multifacet = True
                for facet, value in ratings_map.items():
                    facet_name = str(facet).strip() or "(unknown facet)"
                    bucket = _count_bucket(value)
                    facet_counts_by_name.setdefault(facet_name, {})
                    facet_counts_by_name[facet_name][bucket] = facet_counts_by_name[facet_name].get(bucket, 0) + 1

            status = str(final_qc).strip()
            if status.lower() in {"", "none", "nan"} and isinstance(ratings_map, dict):
                status = SessionManager.derive_multifacet_final_qc(ratings_map) or ""
            if status.lower() in {"", "none", "nan"}:
                status = "Unrated"
            subject_counts[status] = subject_counts.get(status, 0) + 1

        st.write("**Subject-level stats:**")
        subject_preferred_cols = ["PASS", "FAIL", "UNCERTAIN", "All-Pass", "All-Fail", "All-Uncertain", "Mixed", "Unrated"]
        subject_present_cols = [c for c in subject_counts.keys() if c not in subject_preferred_cols]
        subject_cols = [c for c in subject_preferred_cols if c in subject_counts] + sorted(subject_present_cols)
        if not subject_cols:
            subject_cols = ["Unrated"]
        subject_table = pd.DataFrame(
            [{col: int(subject_counts.get(col, 0)) for col in subject_cols}],
            index=["Count"],
        )
        st.table(subject_table)

        if has_multifacet and facet_counts_by_name:
            st.write("**Facet-level stats:**")
            facet_preferred_cols = ["PASS", "FAIL", "UNCERTAIN", "Unrated"]
            facet_seen_cols: set[str] = set()
            for counts in facet_counts_by_name.values():
                facet_seen_cols.update(counts.keys())
            facet_extra_cols = sorted([c for c in facet_seen_cols if c not in facet_preferred_cols])
            facet_cols = [c for c in facet_preferred_cols if c in facet_seen_cols] + facet_extra_cols
            if not facet_cols:
                facet_cols = ["Unrated"]

            facet_rows: list[dict[str, int | str]] = []
            for facet_name in sorted(facet_counts_by_name.keys()):
                counts = facet_counts_by_name[facet_name]
                row = {"Facet": facet_name}
                for col in facet_cols:
                    row[col] = int(counts.get(col, 0))
                facet_rows.append(row)
            facet_table = pd.DataFrame(facet_rows)
            st.table(facet_table)


def _export_qc_results(
    rater_id: str,
    out_dir: str,
    record_list: list,
    drop_duplicates: bool,
    *,
    save_file_path: str | None = None,
    single_file_mode: bool = False,
    qc_pipeline: str | None = None,
    qc_task: str | None = None,
) -> None:
    """Export QC results to file.

    Args:
            rater_id: Rater ID
            out_dir: Output directory path
            record_list: List of QC records to export
            drop_duplicates: Whether to drop duplicate records
    """
    out_file = _resolve_congrats_export_file_path(
        out_dir,
        rater_id,
        save_file_path,
        qc_pipeline=qc_pipeline,
        qc_task=qc_task,
    )
    if not record_list:
        st.session_state["_pending_export_msg"] = ("info", INFO_MESSAGES["no_export_records"])
        return

    dropped_total = 0
    dropped_details_total: dict[tuple[str, str], list[str]] = {}
    saved_paths: list[str] = []
    if single_file_mode:
        out_path, dropped, dropped_details = save_qc_results_to_csv(out_file, record_list, drop_duplicates)
        saved_paths.append(str(out_path))
        dropped_total += dropped
        for key, tasks in dropped_details.items():
            merged = dropped_details_total.setdefault(key, [])
            for t in tasks:
                if t not in merged:
                    merged.append(t)
    else:
        records_by_task: dict[str, list] = {}
        pipeline_by_task: dict[str, str] = {}
        for rec in record_list:
            task_name = str((rec.qc_task if hasattr(rec, "qc_task") else rec.get("qc_task", "")) or "").strip() or "unknown_task"
            pipe_name = str((rec.pipeline if hasattr(rec, "pipeline") else rec.get("pipeline", "")) or "").strip() or "qc"
            records_by_task.setdefault(task_name, []).append(rec)
            pipeline_by_task.setdefault(task_name, pipe_name)

        for task_name in sorted(records_by_task.keys()):
            rows = records_by_task[task_name]
            pipe_name = pipeline_by_task.get(task_name, "qc")
            if len(records_by_task) == 1 and save_file_path:
                target = out_file
            else:
                base_dir = out_file.parent if out_file.suffix else out_file
                filename = Path(_default_congrats_export_path(out_dir, rater_id, qc_pipeline=pipe_name, qc_task=task_name)).name
                target = base_dir / filename

            out_path, dropped, dropped_details = save_qc_results_to_csv(target, rows, drop_duplicates)
            saved_paths.append(str(out_path))
            dropped_total += dropped
            for key, tasks in dropped_details.items():
                merged = dropped_details_total.setdefault(key, [])
                for t in tasks:
                    if t not in merged:
                        merged.append(t)

    path_label = saved_paths[0] if len(saved_paths) == 1 else ", ".join(saved_paths)
    msg = SUCCESS_MESSAGES["records_exported"].format(path=path_label)
    if dropped_total:
        lines = "\n".join(f"- {pid} × {sid}: {', '.join(tasks)}" for (pid, sid), tasks in dropped_details_total.items())
        msg += f"\n\n⚠️ {dropped_total} duplicate record(s) removed (kept latest):\n{lines}"
    st.session_state["_pending_export_msg"] = ("success", msg)
