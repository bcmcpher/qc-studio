"""Unit tests for constants module."""

from constants import (
    EXPERIENCE_LEVELS,
    FATIGUE_LEVELS,
    SCREEN_SIZES,
    PANEL_CONFIG,
    QC_RATINGS,
    NIIVUE_HEIGHT,
    MONTAGE_HEIGHT,
    IQM_HEIGHT,
    VIEW_MODES,
    OVERLAY_COLORMAPS,
    NIIVUE_SECONDARY_RATIO,
    EQUAL_RATIO,
    RATING_IQM_RATIO,
    RATER_INFO_RATIO,
    SESSION_KEYS,
    MESSAGES,
    ERROR_MESSAGES,
    SUCCESS_MESSAGES,
    INFO_MESSAGES,
)


class TestExperienceLevels:
    """Tests for experience level constants."""

    def test_experience_levels_not_empty(self):
        """Test that experience levels are defined."""
        assert len(EXPERIENCE_LEVELS) > 0

    def test_experience_levels_are_strings(self):
        """Test that all experience levels are strings."""
        for level in EXPERIENCE_LEVELS:
            assert isinstance(level, str)
            assert len(level) > 0


class TestFatigueLevels:
    """Tests for fatigue level constants."""

    def test_fatigue_levels_not_empty(self):
        """Test that fatigue levels are defined."""
        assert len(FATIGUE_LEVELS) > 0

    def test_fatigue_levels_are_strings(self):
        """Test that all fatigue levels are strings."""
        for level in FATIGUE_LEVELS:
            assert isinstance(level, str)
            assert len(level) > 0


class TestScreenSizes:
    """Tests for screen size constants."""

    def test_screen_sizes_not_empty(self):
        """Test that screen sizes are defined."""
        assert len(SCREEN_SIZES) > 0

    def test_screen_sizes_are_strings(self):
        """Test that all screen sizes are strings."""
        for size in SCREEN_SIZES:
            assert isinstance(size, str)
            assert len(size) > 0


class TestPanelConfiguration:
    """Tests for panel configuration constants."""

    def test_panel_config_defined(self):
        """Test that panel config is defined."""
        assert len(PANEL_CONFIG) > 0

    def test_panel_config_has_required_keys(self):
        """Test that each panel has required keys."""
        for panel_name, panel_info in PANEL_CONFIG.items():
            assert "label" in panel_info
            assert "description" in panel_info
            assert "default" in panel_info

    def test_panel_defaults_are_boolean(self):
        """Test that panel defaults are boolean."""
        for panel_name, panel_info in PANEL_CONFIG.items():
            assert isinstance(panel_info["default"], bool)


class TestQCRatings:
    """Tests for QC rating constants."""

    def test_qc_ratings_defined(self):
        """Test that QC ratings are defined."""
        assert len(QC_RATINGS) > 0

    def test_qc_ratings_are_strings(self):
        """Test that all QC ratings are strings."""
        for rating in QC_RATINGS:
            assert isinstance(rating, str)

    def test_standard_qc_ratings(self):
        """Test that standard QC ratings are present."""
        assert "PASS" in QC_RATINGS
        assert "FAIL" in QC_RATINGS


class TestHeightConstants:
    """Tests for height constants."""

    def test_heights_are_positive_integers(self):
        """Test that height constants are positive integers."""
        assert isinstance(NIIVUE_HEIGHT, int)
        assert isinstance(MONTAGE_HEIGHT, int)
        assert isinstance(IQM_HEIGHT, int)

        assert NIIVUE_HEIGHT > 0
        assert MONTAGE_HEIGHT > 0
        assert IQM_HEIGHT > 0


class TestViewerModes:
    """Tests for viewer mode constants."""

    def test_view_modes_not_empty(self):
        """Test that view modes are defined."""
        assert len(VIEW_MODES) > 0

    def test_view_modes_are_strings(self):
        """Test that all view modes are strings."""
        for mode in VIEW_MODES:
            assert isinstance(mode, str)

    def test_multiplanar_included(self):
        """Test that multiplanar mode is included."""
        assert "multiplanar" in VIEW_MODES


class TestColormaps:
    """Tests for colormap constants."""

    def test_colormaps_not_empty(self):
        """Test that colormaps are defined."""
        assert len(OVERLAY_COLORMAPS) > 0

    def test_colormaps_are_strings(self):
        """Test that all colormaps are strings."""
        for cmap in OVERLAY_COLORMAPS:
            assert isinstance(cmap, str)


class TestLayoutRatios:
    """Tests for layout ratio constants."""

    def test_ratios_are_lists(self):
        """Test that layout ratios are lists."""
        assert isinstance(NIIVUE_SECONDARY_RATIO, list)
        assert isinstance(EQUAL_RATIO, list)
        assert isinstance(RATING_IQM_RATIO, list)
        assert isinstance(RATER_INFO_RATIO, list)

    def test_ratios_sum_to_one(self):
        """Test that layout ratios sum to 1.0."""
        assert abs(sum(NIIVUE_SECONDARY_RATIO) - 1.0) < 0.01
        assert abs(sum(EQUAL_RATIO) - 1.0) < 0.01
        assert abs(sum(RATING_IQM_RATIO) - 1.0) < 0.01

    def test_ratios_are_positive(self):
        """Test that all ratio values are positive."""
        for ratio in NIIVUE_SECONDARY_RATIO + EQUAL_RATIO + RATING_IQM_RATIO + RATER_INFO_RATIO:
            assert ratio > 0


class TestSessionKeys:
    """Tests for session key constants."""

    def test_session_keys_defined(self):
        """Test that session keys are defined."""
        assert len(SESSION_KEYS) > 0

    def test_session_keys_are_strings(self):
        """Test that all session keys are strings."""
        for key_name, key_value in SESSION_KEYS.items():
            assert isinstance(key_value, str)


class TestMessages:
    """Tests for message constants."""

    def test_messages_dict_not_empty(self):
        """Test that messages dictionary is defined."""
        assert len(MESSAGES) > 0

    def test_all_messages_are_strings(self):
        """Test that all messages are strings."""
        for key, message in MESSAGES.items():
            assert isinstance(message, str)

    def test_error_messages_dict_not_empty(self):
        """Test that error messages are defined."""
        assert len(ERROR_MESSAGES) > 0

    def test_all_error_messages_are_strings(self):
        """Test that all error messages are strings."""
        for key, message in ERROR_MESSAGES.items():
            assert isinstance(message, str)

    def test_success_messages_dict_not_empty(self):
        """Test that success messages are defined."""
        assert len(SUCCESS_MESSAGES) > 0

    def test_all_success_messages_are_strings(self):
        """Test that all success messages are strings."""
        for key, message in SUCCESS_MESSAGES.items():
            assert isinstance(message, str)

    def test_info_messages_dict_not_empty(self):
        """Test that info messages are defined."""
        assert len(INFO_MESSAGES) > 0

    def test_all_info_messages_are_strings(self):
        """Test that all info messages are strings."""
        for key, message in INFO_MESSAGES.items():
            assert isinstance(message, str)


class TestConstantsConsistency:
    """Tests for consistency between related constants."""

    def test_panel_config_keys_unique(self):
        """Test that panel config keys are unique."""
        keys = list(PANEL_CONFIG.keys())
        assert len(keys) == len(set(keys))

    def test_experience_and_fatigue_not_empty(self):
        """Test that experience and fatigue levels are populated."""
        assert len(EXPERIENCE_LEVELS) >= 1
        assert len(FATIGUE_LEVELS) >= 1
        assert len(SCREEN_SIZES) >= 1

    def test_qc_ratings_include_pass_fail(self):
        """Test that QC ratings include standard options."""
        ratings_lower = [r.lower() for r in QC_RATINGS]
        assert any("pass" in r for r in ratings_lower)
        assert any("fail" in r for r in ratings_lower)
