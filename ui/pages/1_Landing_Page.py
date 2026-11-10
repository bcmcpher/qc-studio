"""Multipage sidebar entry: onboarding / landing (same UI as the main app flow).

The full UI lives in ``views/landing_page.py``; this file only wires CLI context
so Streamlit can run the page when selected from the left navigation.
"""

import streamlit as st

from constants import DEFAULT_QC_RATING
from main import get_cli_run_context
from managers.session_manager import SessionManager
from views.landing_page import show_landing_page

st.set_page_config(layout="wide")
ctx = get_cli_run_context()
SessionManager.init_session_state()
if ctx.get("rater_id"):
    SessionManager.set_rater_id(ctx["rater_id"])
    SessionManager.set_rater_id_display(ctx["rater_id"])
if not SessionManager.is_landing_page_complete():
    SessionManager.set_default_qc_rating(ctx.get("default_qc_rating", DEFAULT_QC_RATING))
SessionManager.compact_duplicate_qc_records_if_needed()
show_landing_page(
    ctx["qc_pipeline"],
    ctx["qc_task"],
    ctx["out_dir"],
    ctx["participant_list"],
    ctx["qc_config_path"],
    qc_cohort=ctx.get("qc_cohort"),
    session_ids=ctx.get("session_ids"),
    entrypoint_rel_path="main.py",
)
