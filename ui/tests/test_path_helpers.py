"""Tests for shared path helper utilities."""

import pytest

from utils.path_helpers import sanitize_qc_task_slug

pytestmark = pytest.mark.unit


def test_sanitize_qc_task_slug_lowercases_and_normalizes_symbols():
    assert sanitize_qc_task_slug("Anat WF/QC") == "anat_wf_qc"


def test_sanitize_qc_task_slug_handles_all_and_empty_values():
    assert sanitize_qc_task_slug("ALL") == "all_tasks"
    assert sanitize_qc_task_slug("  ") == "unknown_task"
