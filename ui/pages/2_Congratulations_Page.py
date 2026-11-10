"""Multipage sidebar entry: QC complete / congratulations summary.

The full UI lives in ``views/congratulations_page.py``; this file only wires CLI
context so Streamlit can run the page when selected from the left navigation.
"""

import streamlit as st

from main import get_cli_run_context
from managers.session_manager import SessionManager
from views.congratulations_page import show_congratulations_page

st.set_page_config(layout="wide")
ctx = get_cli_run_context()
SessionManager.init_session_state()
SessionManager.compact_duplicate_qc_records_if_needed()
st.sidebar.empty()
qc_cohort = ctx.get("qc_cohort") or []
cohort_complete = (not qc_cohort) or SessionManager.all_qc_cohort_pages_complete_for_tasks(ctx["qc_tasks"], qc_cohort)
pids = ctx.get("participant_ids") or []
session_id = qc_cohort[0]["session_id"] if qc_cohort else "ses-01"
show_congratulations_page(
    ctx["qc_task"],
    ctx["out_dir"],
    ctx["total_participants"],
    ctx["drop_duplicates"],
    cohort_complete=cohort_complete,
    participant_ids=pids or None,
    session_id=session_id,
    qc_cohort=qc_cohort or None,
    qc_tasks=ctx["qc_tasks"],
    entrypoint_rel_path="main.py",
    qc_pipeline=ctx.get("qc_pipeline"),
)
