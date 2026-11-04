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
        help=("List of participants to QC. Required unless --users_config is given " "(then each user's list comes from that file)."),
        required=False,
        default=None,
    )
    parser.add_argument(
        "--session_list",
        dest="session_list",
        help=(
            "Comma-separated BIDS session labels to QC (e.g. ses-01,ses-02). "
            "Each participant is combined with each session into one review page. "
            "Pass 'none' if the dataset has no session level. May be omitted only "
            "when the participant TSV has a session_id column, which then defines "
            "the (participant, session) rows."
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
        help="Directory to save session state and QC results (ignored with --users_config: " "each user's output_dir comes from that file)",
        required=False,
        default=None,
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
    parser.add_argument(
        "--users_config",
        dest="users_config",
        help=(
            "Multi-user mode: JSON mapping authenticated emails (Cloudflare Access) to "
            "per-user rater_id / rater_dir / participant_list / session_list / output_dir. "
            "Each user writes to <rater_dir>/qc-output/ unless overridden. Validate it with "
            "check_users_setup.py before launching."
        ),
        required=False,
        default=None,
    )

    parsed = parser.parse_args(args)
    if not parsed.users_config:
        if not parsed.participant_list:
            parser.error("--participant_list is required unless --users_config is given")
        if not parsed.out_dir:
            parser.error("--output_dir is required unless --users_config is given")
    return parsed


def _apply_user_overrides(args) -> str:
    """Multi-user mode: swap CLI cohort/output args for the connected user's values.

    Returns the authenticated email. Stops the Streamlit script (after showing an
    error) when the user cannot be identified or is not in the users config.
    """
    from utils.identity import IdentityError, get_current_user
    from utils.user_config import UsersConfigError, load_users_config

    try:
        identity = get_current_user()
    except IdentityError as exc:
        st.error(f"QC-Studio identity configuration error: {exc}")
        st.stop()
    if identity is None:
        st.error(
            "Could not determine who you are. QC-Studio must be accessed through the "
            "Cloudflare Access protected URL. Please reload the page or sign in again."
        )
        st.stop()
    try:
        users_cfg = load_users_config(args.users_config)
    except UsersConfigError as exc:
        print(f"QC-Studio: {exc}", file=sys.stderr)
        st.error("QC-Studio is misconfigured (users config could not be loaded). Please contact the QC administrator.")
        st.stop()
    overrides = users_cfg.users.get(identity.email)
    if overrides is None:
        if identity.email in users_cfg.rejected:
            reasons = "; ".join(users_cfg.rejected[identity.email])
            print(f"QC-Studio: rejected users config entry for {identity.email}: {reasons}", file=sys.stderr)
            st.error(f"The QC setup for **{identity.email}** has a problem. Please contact the QC administrator.")
        else:
            st.error(f"**{identity.email}** is not assigned to a QC cohort. Please contact the QC administrator.")
        st.stop()
    if not Path(overrides["participant_list"]).is_file():
        print(f"QC-Studio: participant list for {identity.email} not found: {overrides['participant_list']}", file=sys.stderr)
        st.error(f"No participant list has been set up for **{identity.email}** yet. Please contact the QC administrator.")
        st.stop()

    args.participant_list = overrides["participant_list"]
    if overrides.get("session_list"):
        args.session_list = overrides["session_list"]
    args.out_dir = overrides["out_dir"]
    args.rater_id = overrides["rater_id"]
    return identity.email


def get_cli_run_context():
    """Paths and counts from CLI args.

    Used by ``main()`` and by multipage ``pages/*.py`` entrypoints so sidebar
    navigation matches the same run configuration.
    """
    args = parse_args()
    args.out_dir = str(Path(args.out_dir).expanduser().resolve()) if args.out_dir else str(Path(".").expanduser().resolve())
    multi_user = bool(getattr(args, "users_config", None))
    user_email = _apply_user_overrides(args) if multi_user else None
    ui_dir = os.path.dirname(os.path.abspath(__file__))
    qc_config_path = os.path.join(ui_dir, args.qc_json)
    participants_df = pd.read_csv(args.participant_list, delimiter="\t")
    if args.session_list is None and "session_id" not in participants_df.columns:
        if multi_user:
            # Never SystemExit inside a shared server; refuse just this user.
            print(f"QC-Studio: no sessions for {user_email}: set session_list or add a session_id column", file=sys.stderr)
            st.error("Your participant list does not specify sessions. Please contact the QC administrator.")
            st.stop()
        print(
            "QC-Studio: cannot tell which sessions to QC. Pass --session_list ses-01,ses-02,... "
            "or --session_list none if the dataset has no sessions "
            f"(or add a session_id column to {args.participant_list!r}).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    session_ids = parse_session_list(args.session_list)
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
        "multi_user": multi_user,
        "user_email": user_email,
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
    SessionManager.apply_user_identity(ctx)
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
    if ctx.get("multi_user") and ctx.get("user_email"):
        st.sidebar.caption(f"👤 Signed in as {ctx['user_email']}")

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
