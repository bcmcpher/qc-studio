"""Unit tests for PanelLayoutManager."""

from managers.panel_layout_manager import PanelLayoutManager
from constants import PANEL_CONFIG, NIIVUE_SECONDARY_RATIO, EQUAL_RATIO, RATING_IQM_RATIO


class TestPanelLayoutRatios:
    """Tests for panel layout ratio calculation."""

    def test_get_panel_layout_ratios_all_panels(self):
        """Test layout ratios when all panels are selected."""
        selected_panels = {"niivue": True, "montage": True, "iqm": True}
        ratios = PanelLayoutManager.get_panel_layout_ratios(selected_panels)

        # Should return appropriate ratios
        assert isinstance(ratios, list)
        assert len(ratios) == 2
        assert ratios[0] > 0 and ratios[1] > 0

    def test_get_panel_layout_ratios_niivue_montage(self):
        """Test layout ratios with niivue and montage - should be side-by-side (equal)."""
        selected_panels = {"niivue": True, "montage": True, "iqm": False}
        ratios = PanelLayoutManager.get_panel_layout_ratios(selected_panels)

        # 2 panels should use EQUAL_RATIO for side-by-side layout
        assert ratios == list(EQUAL_RATIO)

    def test_get_panel_layout_ratios_niivue_iqm_two_panels(self):
        """Test layout ratios for Niivue + IQM (2 panels) returns equal ratio."""
        selected_panels = {"niivue": True, "montage": False, "iqm": True}
        ratios = PanelLayoutManager.get_panel_layout_ratios(selected_panels)

        # 2 panels should use EQUAL_RATIO
        assert ratios == list(EQUAL_RATIO)

    def test_get_panel_layout_ratios_only_iqm(self):
        """Test layout ratios with only IQM panel."""
        selected_panels = {"niivue": False, "montage": False, "iqm": True}
        ratios = PanelLayoutManager.get_panel_layout_ratios(selected_panels)

        assert isinstance(ratios, list)
        assert len(ratios) == 2

    def test_get_panel_layout_ratios_niivue_only(self):
        """Test layout ratios with only niivue."""
        selected_panels = {"niivue": True, "montage": False, "iqm": False}
        ratios = PanelLayoutManager.get_panel_layout_ratios(selected_panels)

        assert isinstance(ratios, list)


class TestShouldShowPanel:
    """Tests for determining panel visibility."""

    def test_should_show_panel_selected(self):
        """Test that selected panels should be shown."""
        selected_panels = {"niivue": True, "montage": False}

        assert PanelLayoutManager.should_show_panel("niivue", selected_panels) is True
        assert PanelLayoutManager.should_show_panel("montage", selected_panels) is False

    def test_should_show_panel_default_false(self):
        """Test that missing panels default to False."""
        selected_panels = {"niivue": True}

        assert PanelLayoutManager.should_show_panel("missing_panel", selected_panels) is False


class TestGetActivePanelCount:
    """Tests for counting active panels."""

    def test_get_active_panel_count_all_selected(self):
        """Test counting when all panels are selected."""
        selected_panels = {"niivue": True, "montage": True, "iqm": True}
        count = PanelLayoutManager.get_active_panel_count(selected_panels)

        assert count == 3

    def test_get_active_panel_count_partial(self):
        """Test counting when some panels are selected."""
        selected_panels = {"niivue": True, "montage": False, "iqm": True}
        count = PanelLayoutManager.get_active_panel_count(selected_panels)

        assert count == 2

    def test_get_active_panel_count_none_selected(self):
        """Test counting when no panels are selected."""
        selected_panels = {"niivue": False, "montage": False, "iqm": False}
        count = PanelLayoutManager.get_active_panel_count(selected_panels)

        assert count == 0


class TestGetPanelVisibilitySummary:
    """Tests for panel visibility summary generation."""

    def test_get_panel_visibility_summary_all(self):
        """Test summary when all panels are visible."""
        selected_panels = {"niivue": True, "montage": True, "iqm": True}
        summary = PanelLayoutManager.get_panel_visibility_summary(selected_panels)

        assert "Niivue" in summary or "3D MRI" in summary or "niivue" in summary.lower()
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_get_panel_visibility_summary_partial(self):
        """Test summary when some panels are visible."""
        selected_panels = {"niivue": True, "montage": False, "iqm": True}
        summary = PanelLayoutManager.get_panel_visibility_summary(selected_panels)

        # Should contain plus signs indicating multiple panels
        assert isinstance(summary, str)
        assert len(summary) > 0

    def test_get_panel_visibility_summary_none(self):
        """Test summary when no panels are visible."""
        selected_panels = {"niivue": False, "montage": False, "iqm": False}
        summary = PanelLayoutManager.get_panel_visibility_summary(selected_panels)

        assert summary == "No panels selected"


class TestPanelVisibility:
    """Tests for panel visibility configuration."""

    def test_panel_config_keys_exist(self):
        """Test that PANEL_CONFIG has expected keys."""
        expected_keys = ["niivue", "montage", "iqm"]
        for key in expected_keys:
            assert key in PANEL_CONFIG

    def test_panel_config_has_required_fields(self):
        """Test that each panel has required fields."""
        for panel_name, panel_info in PANEL_CONFIG.items():
            assert "label" in panel_info
            assert "description" in panel_info
            assert "default" in panel_info

    def test_panel_config_default_values(self):
        """Test default panel visibility values."""
        assert PANEL_CONFIG["niivue"]["default"] is True
        assert PANEL_CONFIG["montage"]["default"] is True
        assert PANEL_CONFIG["iqm"]["default"] is False


class TestLayoutConstants:
    """Tests for layout ratio constants."""

    def test_niivue_montage_ratio_valid(self):
        """Test NIIVUE_SECONDARY_RATIO is valid."""
        assert len(NIIVUE_SECONDARY_RATIO) == 3
        # all values should be positive
        assert all(value > 0 for value in NIIVUE_SECONDARY_RATIO)
        # Should sum to approximately 1.0
        assert abs(sum(NIIVUE_SECONDARY_RATIO) - 1.0) < 0.01

    def test_equal_ratio_valid(self):
        """Test EQUAL_RATIO is valid."""
        assert len(EQUAL_RATIO) == 2
        assert abs(EQUAL_RATIO[0] - EQUAL_RATIO[1]) < 0.01
        # Should sum to approximately 1.0
        assert abs(sum(EQUAL_RATIO) - 1.0) < 0.01

    def test_rating_iqm_ratio_valid(self):
        """Test RATING_IQM_RATIO is valid."""
        assert len(RATING_IQM_RATIO) == 2
        assert RATING_IQM_RATIO[0] > 0
        assert RATING_IQM_RATIO[1] > 0
        # Should sum to approximately 1.0
        assert abs(sum(RATING_IQM_RATIO) - 1.0) < 0.01


class TestSideBySideLayout:
    """Tests for 2-panel side-by-side layout detection."""

    def test_should_use_side_by_side_with_two_panels(self):
        """Test that 2 panels return True for side-by-side layout."""
        selected_panels = {"niivue": True, "montage": True, "iqm": False}
        assert PanelLayoutManager.should_use_side_by_side_layout(selected_panels) is True

    def test_should_use_side_by_side_niivue_iqm(self):
        """Test Niivue + IQM = side-by-side."""
        selected_panels = {"niivue": True, "montage": False, "iqm": True}
        assert PanelLayoutManager.should_use_side_by_side_layout(selected_panels) is True

    def test_should_use_side_by_side_montage_iqm(self):
        """Test Montage + IQM = side-by-side."""
        selected_panels = {"niivue": False, "montage": True, "iqm": True}
        assert PanelLayoutManager.should_use_side_by_side_layout(selected_panels) is True

    def test_should_not_use_side_by_side_one_panel(self):
        """Test that 1 panel returns False."""
        selected_panels = {"niivue": True, "montage": False, "iqm": False}
        assert PanelLayoutManager.should_use_side_by_side_layout(selected_panels) is False

    def test_should_not_use_side_by_side_three_panels(self):
        """Test that 3 panels returns False."""
        selected_panels = {"niivue": True, "montage": True, "iqm": True}
        assert PanelLayoutManager.should_use_side_by_side_layout(selected_panels) is False

    def test_should_not_use_side_by_side_no_panels(self):
        """Test that 0 panels returns False."""
        selected_panels = {"niivue": False, "montage": False, "iqm": False}
        assert PanelLayoutManager.should_use_side_by_side_layout(selected_panels) is False


class TestPanelLayoutManagerIntegration:
    """Integration tests for PanelLayoutManager."""

    def test_panel_workflow(self):
        """Test a complete panel configuration workflow."""
        # Start with default panels
        selected_panels = {panel: config["default"] for panel, config in PANEL_CONFIG.items()}

        # Count active panels
        count = PanelLayoutManager.get_active_panel_count(selected_panels)
        assert count >= 1  # At least one panel should be active

        # Get layout ratios
        ratios = PanelLayoutManager.get_panel_layout_ratios(selected_panels)
        assert isinstance(ratios, list)

        # Get summary
        summary = PanelLayoutManager.get_panel_visibility_summary(selected_panels)
        assert isinstance(summary, str)
        assert len(summary) > 0
