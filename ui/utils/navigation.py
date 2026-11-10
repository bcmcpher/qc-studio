"""Shared navigation helpers used by the QC viewer and sidebar controls."""

import streamlit as st

from constants import PENDING_SIDEBAR_RERUN_KEY


def request_navigation_rerun(st_module=None) -> None:
    """Request an app refresh after navigation/playback actions.

    Streamlit's real ``st.rerun()`` raises internally to stop execution and rerun.
    In test contexts where rerun is mocked/no-op, fall back to the deferred sidebar key.
    """
    target = st_module if st_module is not None else st
    rerun = getattr(target, "rerun", None)
    if callable(rerun):
        rerun()
        return
    target.session_state[PENDING_SIDEBAR_RERUN_KEY] = True
