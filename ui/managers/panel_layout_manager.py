"""Panel layout and management utilities."""

import streamlit as st
from constants import (
    PANEL_CONFIG,
    MESSAGES,
    EQUAL_RATIO,
    RATING_IQM_RATIO,
    NIIVUE_MONTAGE_RATIO,
)
from .session_manager import SessionManager


class PanelLayoutManager:
    """Manages panel layouts and visibility in the QC interface."""

    @staticmethod
    def render_panel_header_with_controls() -> dict:
        """Render panel selection controls.

        Returns:
            Dictionary of selected panels {panel_name: bool}
        """
        st.subheader(MESSAGES["panel_selection_header"])

        selected_panels = {}

        for idx, (panel_name, panel_info) in enumerate(PANEL_CONFIG.items()):
            default = panel_info.get("default", True)
            selected = st.checkbox(panel_info["label"], value=default, help=panel_info.get("description", ""))
            selected_panels[panel_name] = selected

        SessionManager.set_panel_selection(selected_panels)
        return selected_panels

    @staticmethod
    def get_active_panel_count(selected_panels: dict) -> int:
        """Count how many panels are selected.

        Args:
            selected_panels: Dictionary of panel_name -> bool

        Returns:
            Number of selected panels
        """
        return sum(1 for v in selected_panels.values() if v)

    @staticmethod
    def get_panel_layout_ratios(selected_panels: dict) -> list:
        """Return two-element column width ratios for the active viewer layout."""
        count = PanelLayoutManager.get_active_panel_count(selected_panels)
        if count == 0:
            return list(EQUAL_RATIO)
        if count == 1:
            if PanelLayoutManager.should_show_panel("iqm", selected_panels):
                return list(RATING_IQM_RATIO)
            return list(EQUAL_RATIO)
        if count == 2:
            return list(EQUAL_RATIO)
        return list(NIIVUE_MONTAGE_RATIO)

    @staticmethod
    def should_use_side_by_side_layout(selected_panels: dict) -> bool:
        """True when exactly two panels are selected (side-by-side viewer)."""
        return PanelLayoutManager.get_active_panel_count(selected_panels) == 2

    @staticmethod
    def should_show_panel(panel_name: str, selected_panels: dict = None) -> bool:
        """Determine if a specific panel should be shown.

        Args:
            panel_name: Name of the panel
            selected_panels: Optional dict of selections; if None, retrieves from session

        Returns:
            True if panel should be displayed
        """
        if selected_panels is None:
            selected_panels = SessionManager.get_selected_panels()

        return selected_panels.get(panel_name, False)

    @staticmethod
    def render_left_panel(left_col, left_panel_name: str, selected_panels: dict, render_func):
        """Render left column panel.

        Args:
            left_col: Streamlit column object
            left_panel_name: Name of panel to render on left
            selected_panels: Dictionary of selected panels
            render_func: Callable that renders the panel content
        """
        if not PanelLayoutManager.should_show_panel(left_panel_name, selected_panels):
            return

        with left_col:
            render_func()

    @staticmethod
    def render_right_panels(right_col, right_panels: list, selected_panels: dict, render_funcs: dict):
        """Render right column with stacked panels.

        Args:
            right_col: Streamlit column object
            right_panels: List of panel names to show on right
            selected_panels: Dictionary of selected panels
            render_funcs: Dictionary mapping panel_name -> render_function
        """
        active_panels = [p for p in right_panels if PanelLayoutManager.should_show_panel(p, selected_panels)]

        if not active_panels:
            return

        with right_col:
            for panel_name in active_panels:
                if panel_name in render_funcs:
                    render_funcs[panel_name]()
                    st.divider()

    @staticmethod
    def get_panel_visibility_summary(selected_panels: dict) -> str:
        """Generate a human-readable summary of visible panels.

        Args:
            selected_panels: Dictionary of selected panels

        Returns:
            Formatted string like "Niivue + Montage + IQM"
        """
        visible = []
        for panel_name, is_visible in selected_panels.items():
            if is_visible and panel_name in PANEL_CONFIG:
                visible.append(PANEL_CONFIG[panel_name]["label"])

        if not visible:
            return "No panels selected"

        return " + ".join(visible)
