"""Fallback when the `niivue-streamlit` package is not installed (see README Quick Start)."""

from __future__ import annotations

import streamlit as st


def niivue_viewer(**kwargs) -> None:
    key = kwargs.get("key", "niivue")
    filename = kwargs.get("filename", "")
    has_data = bool(kwargs.get("nifti_data"))
    st.info(
        "**3D viewer:** install `niivue-streamlit` for the interactive Niivue panel. "
        "From the repo root (venv active):\n\n"
        "`pip install --index-url https://test.pypi.org/simple/ --no-deps niivue-streamlit`\n\n"
        "Then restart Streamlit."
    )
    st.caption(f"Placeholder — `{key}` / `{filename}` / " f"{'volume loaded' if has_data else 'no volume'}")
