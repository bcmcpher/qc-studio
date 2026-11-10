import streamlit as st
from constants import ERROR_MESSAGES
from utils.config import build_substitution_values, list_qc_tasks_from_json
from managers.session_manager import SessionManager
from views.landing_page import show_landing_page
from views.congratulations_page import show_congratulations_page
from components.qc_viewer import display_qc_viewers


def _legacy_qc_cohort(participant_ids: list | None, session_id: str | None) -> list[dict]:
    """Single-session cohort rows for callers that do not pass ``qc_cohort``."""
    sid = session_id or "ses-01"
    out: list[dict] = []
    for pid_raw in participant_ids or []:
        p = str(pid_raw).strip()
        if not p.startswith("sub-"):
            p = f"sub-{p}"
        out.append({"participant_id": p, "session_id": sid})
    return out


def resolve_qc_tasks(cli_qc_task: str, qc_config_path: str) -> list[str]:
    """CLI ``--qc_task`` value to a list of task keys from ``qc.json``."""
    if str(cli_qc_task).strip().lower() == "all":
        return list_qc_tasks_from_json(qc_config_path)
    return [str(cli_qc_task).strip()]


def app(
    dataset_dir,
    participant_id,
    session_id,
    qc_pipeline,
    qc_task,
    qc_config_path,
    out_dir,
    total_participants,
    drop_duplicates,
    participant_list,
    participant_ids=None,
    qc_cohort: list | None = None,
    qc_tasks: list | None = None,
) -> None:
    """Main Streamlit layout: landing page, QC viewers, and congratulations."""
    st.set_page_config(layout="wide")

    SessionManager.init_session_state()
    SessionManager.compact_duplicate_qc_records_if_needed()

    if SessionManager.is_all_tasks_mode_locked():
        qc_task = "all"
        qc_tasks_eff = qc_tasks if qc_tasks is not None else resolve_qc_tasks("all", qc_config_path)
    else:
        selected_qc_task = SessionManager.get_selected_qc_task()
        if selected_qc_task:
            qc_task = selected_qc_task
            qc_tasks_eff = resolve_qc_tasks(selected_qc_task, qc_config_path)
        else:
            qc_tasks_eff = qc_tasks if qc_tasks is not None else resolve_qc_tasks(qc_task, qc_config_path)

    qc_cohort_eff = qc_cohort if qc_cohort is not None else _legacy_qc_cohort(participant_ids, session_id)
    if not qc_tasks_eff:
        if str(qc_task).strip().lower() == "all":
            st.error(ERROR_MESSAGES["no_qc_tasks_all"].format(qc_config_path=qc_config_path))
        else:
            st.error(ERROR_MESSAGES["no_qc_task_resolved"].format(qc_task=qc_task))
        st.stop()

    if not SessionManager.is_landing_page_complete():
        show_landing_page(
            qc_pipeline,
            qc_task,
            out_dir,
            participant_list,
            qc_config_path,
            qc_cohort=qc_cohort,
        )
        return

    if participant_id is None:
        cohort_complete = (not qc_cohort_eff) or SessionManager.all_qc_cohort_pages_complete_for_tasks(qc_tasks_eff, qc_cohort_eff)
        show_congratulations_page(
            qc_task,
            out_dir,
            total_participants,
            drop_duplicates,
            cohort_complete=cohort_complete,
            participant_ids=participant_ids,
            session_id=session_id,
            qc_cohort=qc_cohort_eff,
            qc_tasks=qc_tasks_eff,
            qc_pipeline=qc_pipeline,
        )
        return

    substitution_values = build_substitution_values(participant_id, session_id)
    display_qc_viewers(
        dataset_dir=dataset_dir,
        qc_config_path=qc_config_path,
        substitution_values=substitution_values,
        participant_id=participant_id,
        session_id=session_id,
        qc_pipeline=qc_pipeline,
        qc_task=qc_task,
        qc_tasks=qc_tasks_eff,
        total_participants=total_participants,
        participant_ids=participant_ids,
        qc_cohort=qc_cohort_eff,
    )
