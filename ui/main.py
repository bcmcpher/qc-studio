# %%
import os
import sys
from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# Reference-data host (REFERENCE_DATA_URL) is read from the environment or a
# .env file; load it before anything else needs it.
load_dotenv()

from app import app, resolve_qc_tasks
from components.qc_viewer import AUTOPLAY_RUN_CTX_KEY
from managers.session_manager import SessionManager
from constants import SESSION_KEYS, DEFAULT_QC_RATING, DEFAULT_QC_RATING_OPTIONS
from views.sidebar_cohort_nav import render_sidebar_cohort_subjects
from utils.path_helpers import sanitize_qc_task_slug
from utils.cohort import (
    build_qc_cohort,
    normalize_session_id_bids,
    parse_session_list,
    participant_ids_in_cohort_order,
)


def parse_args(args=None):
    parser = ArgumentParser("QC-Studio")

    parser.add_argument(
        "--dataset_dir",
        dest="dataset_dir",
        help=("Path to dataset dir"),
        required=True,
    )
    parser.add_argument(
        "--participant_list",
        dest="participant_list",
        help=("List of participants to QC"),
        required=True,
    )
    parser.add_argument(
        "--session_list",
        dest="session_list",
        help=(
            "Comma-separated BIDS session labels to QC (e.g. ses-01,ses-02). "
            "Each participant is combined with each session into one review page. "
            "If the participant TSV has a session_id column, that table defines "
            "(participant, session) rows instead. Legacy default Baseline maps to ses-01."
        ),
        default=None,
        required=False,
    )
    parser.add_argument(
        "--qc_pipeline",
        help=("Pipeline output to QC"),
        dest="qc_pipeline",
        required=True,
    )
    parser.add_argument(
        "--qc_task",
        help=("QC task key from qc.json (e.g. anat_wf_qc), or **all** to show every task " "on one scrollable page with a rating per task."),
        dest="qc_task",
        required=True,
    )
    parser.add_argument(
        "--output_dir",
        dest="out_dir",
        help="Directory to save session state and QC results",
        required=True,
    )
    parser.add_argument(
        "--qc_json",
        dest="qc_json",
        help=("Path to a JSON containing a list of image file paths to be displayed."),
        required=True,
    )
    parser.add_argument(
        "--rater_id",
        dest="rater_id",
        help=("Optional rater name or ID to pre-populate the landing-page form and greeting."),
        required=False,
        default=None,
    )
    parser.add_argument(
        "--default_qc_rating",
        dest="default_qc_rating",
        help=("Default preselected QC rating for unrated forms."),
        required=False,
        default=DEFAULT_QC_RATING,
        choices=DEFAULT_QC_RATING_OPTIONS,
    )

    return parser.parse_args(args)


def get_cli_run_context():
    """Paths and counts from CLI args.

    Used by ``main()`` and by multipage ``pages/*.py`` entrypoints so sidebar
    navigation matches the same run configuration.
    """
    args = parse_args()
    args.out_dir = str(Path(args.out_dir).expanduser().resolve()) if args.out_dir else str(Path(".").expanduser().resolve())
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    qc_config_path = os.path.join(ui_dir, args.qc_json)
    session_ids = parse_session_list(args.session_list)
    if session_ids is None:
        from bids import BIDSLayout

        layout = BIDSLayout(args.dataset_dir, validate=False)
        bids_sessions = layout.get_sessions()
        if bids_sessions:
            session_ids = [normalize_session_id_bids(s) for s in bids_sessions]
            print(
                f"No --session_list given, using sessions found in dataset: {session_ids}",
                file=sys.stderr,
            )
    participants_df = pd.read_csv(args.participant_list, delimiter="\t")
    stored_cohort = SessionManager.get_qc_cohort_order()
    if stored_cohort:
        qc_cohort = stored_cohort
    else:
        qc_cohort = build_qc_cohort(participants_df, session_ids)
    total_participants = len(qc_cohort)
    participant_ids = participant_ids_in_cohort_order(qc_cohort)
    qc_tasks = resolve_qc_tasks(args.qc_task, qc_config_path)
    if str(args.qc_task).strip().lower() == "all" and not qc_tasks:
        print(
            "QC-Studio: --qc_task all requires a readable qc.json (JSON object with task keys). " f"No tasks found at {qc_config_path!r}.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    qc_task = args.qc_task
    if str(qc_task).strip().lower() == "all" and len(qc_tasks) == 1:
        # "all" with a single task is that task; avoid all-tasks mode file naming.
        qc_task = qc_tasks[0]
    return {
        "dataset_dir": args.dataset_dir,
        "participant_list": args.participant_list,
        "session_list": args.session_list,
        "session_ids": session_ids,
        "qc_pipeline": args.qc_pipeline,
        "qc_task": qc_task,
        "qc_tasks": qc_tasks,
        "qc_config_path": qc_config_path,
        "out_dir": args.out_dir,
        "total_participants": total_participants,
        "drop_duplicates": True,
        "participant_ids": participant_ids,
        "qc_cohort": qc_cohort,
        "rater_id": getattr(args, "rater_id", None),
        "default_qc_rating": getattr(args, "default_qc_rating", DEFAULT_QC_RATING),
    }


def main():
    """Main entry point for the Streamlit app."""
    ctx = get_cli_run_context()
    dataset_dir = ctx["dataset_dir"]
    participant_list = ctx["participant_list"]
    qc_pipeline = ctx["qc_pipeline"]
    qc_task = ctx["qc_task"]
    qc_config_path = ctx["qc_config_path"]
    out_dir = ctx["out_dir"]
    total_participants = ctx["total_participants"]
    drop_duplicates = ctx["drop_duplicates"]
    qc_cohort = ctx["qc_cohort"]
    participant_ids = ctx["participant_ids"]

    # Initialize session state
    SessionManager.init_session_state()
    if ctx.get("rater_id"):
        SessionManager.set_rater_id(ctx["rater_id"])
    # Seed default rating from CLI only before landing is completed.
    # After onboarding, keep any user override selected in the landing sidebar.
    if not SessionManager.is_landing_page_complete():
        SessionManager.set_default_qc_rating(ctx.get("default_qc_rating", DEFAULT_QC_RATING))
    cli_all_tasks_mode = str(ctx.get("qc_task", "")).strip().lower() == "all"
    SessionManager.set_all_tasks_mode_locked(cli_all_tasks_mode)
    selected_qc_task = SessionManager.get_selected_qc_task()
    if cli_all_tasks_mode:
        qc_task = "all"
        qc_tasks = ctx["qc_tasks"]
        SessionManager.set_selected_qc_task("all")
    elif selected_qc_task:
        qc_task = selected_qc_task
        qc_tasks = resolve_qc_tasks(selected_qc_task, qc_config_path)
    if not SessionManager.get_qc_session_id():
        SessionManager.set_qc_session_id(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    task_slug = sanitize_qc_task_slug(qc_task)
    qc_session_label = f"{SessionManager.get_rater_id() or 'rater'}_{qc_pipeline.lower()}_{task_slug}_{SessionManager.get_qc_session_id()}"
    SessionManager.set_qc_session_label(qc_session_label)
    SessionManager.set_qc_session_checkpoint_dir(str((Path(out_dir).expanduser() / "checkpoints").resolve()))
    pipeline_slug = str(qc_pipeline or "").strip().lower() or "qc"
    SessionManager.set_qc_session_active_path(
        str((Path(out_dir).expanduser() / f"{(SessionManager.get_rater_id() or 'rater')}_{pipeline_slug}_{task_slug}_qc_status.tsv").resolve())
    )
    SessionManager.compact_duplicate_qc_records_if_needed()

    session_id_for_sidebar = qc_cohort[0]["session_id"] if qc_cohort else None
    if cli_all_tasks_mode:
        qc_tasks = ctx["qc_tasks"]
    elif selected_qc_task:
        qc_tasks = resolve_qc_tasks(selected_qc_task, qc_config_path)
    else:
        qc_tasks = ctx["qc_tasks"]

    current_page = st.session_state.get(SESSION_KEYS["current_page"], 1)
    if current_page < 1:
        st.session_state[SESSION_KEYS["current_page"]] = 1
        current_page = 1

    def _participant_for_page(page: int):
        if page > total_participants or not qc_cohort:
            return None, session_id_for_sidebar
        entry = qc_cohort[page - 1]
        return entry["participant_id"], entry["session_id"]

    participant_id, session_id = _participant_for_page(current_page)
    on_qc_viewer_page = bool(participant_id is not None and qc_cohort and current_page <= total_participants)
    if not on_qc_viewer_page:
        st.sidebar.empty()
    render_sidebar_cohort_subjects(
        qc_cohort=qc_cohort,
        total_participants=total_participants,
        qc_task=qc_task,
        qc_tasks=qc_tasks,
        entrypoint_rel_path=None,
        prepend_navigation=on_qc_viewer_page,
        navigation_kwargs=(
            {
                "current_page": current_page,
                "total_participants": total_participants,
                "participant_id": participant_id,
                "session_id": session_id,
                "qc_pipeline": qc_pipeline,
                "qc_tasks": qc_tasks,
                "participant_ids": participant_ids,
                "qc_cohort": qc_cohort,
                "out_dir": out_dir,
            }
            if on_qc_viewer_page
            else None
        ),
        show_subject_filter=on_qc_viewer_page,
        show_subject_list=on_qc_viewer_page,
    )

    # Sidebar filter may have moved the page; use that for the viewer.
    current_page = SessionManager.get_current_page()
    if current_page < 1:
        SessionManager.set_current_page(1)
        current_page = 1
    participant_id, session_id = _participant_for_page(current_page)

    if participant_id is not None and qc_cohort and current_page <= total_participants:
        st.session_state[AUTOPLAY_RUN_CTX_KEY] = {
            "participant_id": participant_id,
            "session_id": session_id,
            "qc_pipeline": qc_pipeline,
            "qc_task": qc_task,
            "qc_tasks": qc_tasks,
            "total_participants": total_participants,
            "qc_cohort": qc_cohort,
            "participant_ids": participant_ids,
        }
    else:
        st.session_state.pop(AUTOPLAY_RUN_CTX_KEY, None)

    app(
        dataset_dir=dataset_dir,
        participant_id=participant_id,
        session_id=session_id,
        qc_pipeline=qc_pipeline,
        qc_task=qc_task,
        qc_config_path=qc_config_path,
        out_dir=out_dir,
        total_participants=total_participants,
        drop_duplicates=drop_duplicates,
        participant_list=participant_list,
        participant_ids=participant_ids,
        qc_cohort=qc_cohort,
        qc_tasks=qc_tasks,
    )


if __name__ == "__main__":
    main()


# %%
