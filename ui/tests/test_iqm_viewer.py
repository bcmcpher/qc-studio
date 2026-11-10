"""Tests for iqm_viewer.py module."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import plotly.graph_objects as go
import pytest


class _StreamlitStub:
    def __init__(self):
        self.warning = MagicMock()
        self.error = MagicMock()
        self.info = MagicMock()
        self.caption = MagicMock()
        self.subheader = MagicMock()
        self.selectbox = MagicMock()
        self.radio = MagicMock()
        self.plotly_chart = MagicMock()
        self.segmented_control = MagicMock()
        self.write = MagicMock()
        self.table = MagicMock()
        self.columns = MagicMock()
        self.container = MagicMock()
        self.markdown = MagicMock()
        self.session_state = {}

    def cache_data(self, *args, **kwargs):
        def decorator(func):
            return func

        if args and callable(args[0]) and len(args) == 1 and not kwargs:
            return args[0]

        return decorator


@pytest.fixture
def iqm_viewer_module(monkeypatch):
    """Import iqm_viewer with lightweight module stubs."""
    streamlit_stub = _StreamlitStub()
    ui_dir = Path(__file__).resolve().parents[1]
    components_dir = ui_dir / "components"

    if str(components_dir) not in sys.path:
        sys.path.insert(0, str(components_dir))
    if str(ui_dir) not in sys.path:
        sys.path.insert(0, str(ui_dir))

    monkeypatch.setitem(sys.modules, "streamlit", streamlit_stub)
    sys.modules.pop("iqm_viewer", None)
    module = importlib.import_module("iqm_viewer")

    yield module, streamlit_stub

    sys.modules.pop("iqm_viewer", None)


def test_extract_subject_data_filters_participant_and_session(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": [
                "sub-01_ses-01_T1w",
                "sub-01_ses-02_T1w",
                "sub-02_ses-01_T1w",
            ],
            "efc": [0.1, 0.2, 0.3],
            "snr_total": [10, 20, 30],
        }
    )

    result = module._extract_subject_data(data, "sub-01", ["efc", "snr_total"], session_id="ses-02")

    assert len(result) == 1
    assert result.iloc[0]["efc"] == 0.2
    assert result.iloc[0]["snr_total"] == 20


def test_extract_subject_data_requires_bids_name(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame({"efc": [0.1]})

    with pytest.raises(ValueError, match="bids_name"):
        module._extract_subject_data(data, "sub-01", ["efc"])


def test_extract_subject_data_rejects_invalid_session_prefix(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame({"bids_name": ["sub-01_ses-01_T1w"], "efc": [0.1]})

    with pytest.raises(ValueError, match="ses-"):
        module._extract_subject_data(data, "sub-01", ["efc"], session_id="01")


def test_add_subject_overlay_draws_all_points_and_keeps_first_legend(iqm_viewer_module):
    module, _ = iqm_viewer_module

    fig = go.Figure()
    subject_rows = pd.DataFrame({"efc": [0.4], "snr_total": [15.0]})

    module._add_subject_overlay(fig, subject_rows, "sub-01", offsetgroup="Dataset", label_suffix=" (dataset)")

    assert len(fig.data) == 2
    assert fig.data[0].showlegend is True
    assert fig.data[1].showlegend is False
    assert "Run: sub-01 (dataset)" in fig.data[0].hovertemplate


def test_render_iqm_distributions_dataset_only(iqm_viewer_module, temp_dir, monkeypatch):
    module, streamlit_stub = iqm_viewer_module

    dataset_path = temp_dir / "derivatives" / "mriqc" / "group_T1w.tsv"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path, sep="\t", index=False)

    monkeypatch.setitem(module.IQM_DISTRIBUTION_GROUPS, "t1w", {"EFC": ["efc"]})

    # single source -> tab label is the pipeline name plus its inferred
    # modality ("mriqc (t1w)")
    streamlit_stub.segmented_control.return_value = "mriqc (t1w)"
    streamlit_stub.radio.return_value = "Dataset"

    module._render_iqm_distributions(
        [str(dataset_path)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    streamlit_stub.plotly_chart.assert_called_once()
    fig = streamlit_stub.plotly_chart.call_args.args[0]
    assert len(fig.data) == 2


def test_render_iqm_distributions_hides_reference_toggle_by_default(iqm_viewer_module, temp_dir, monkeypatch):
    """REFERENCE_COMPARISON_ENABLED defaults to False (hidden pending #82): the
    Display mode radio should never render, and only the dataset trace shows."""
    module, streamlit_stub = iqm_viewer_module

    dataset_path = temp_dir / "derivatives" / "mriqc" / "group_T1w.tsv"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path, sep="\t", index=False)

    monkeypatch.setitem(module.IQM_DISTRIBUTION_GROUPS, "t1w", {"EFC": ["efc"]})
    streamlit_stub.segmented_control.return_value = "mriqc (t1w)"

    module._render_iqm_distributions(
        [str(dataset_path)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    streamlit_stub.radio.assert_not_called()
    fig = streamlit_stub.plotly_chart.call_args.args[0]
    # Dataset-only mode: one violin + one subject-highlight marker trace, no reference trace.
    assert len(fig.data) == 2


def test_load_reference_iqm_for_subject_normalizes_before_caching(iqm_viewer_module, monkeypatch):
    """ "GE"/"General Electric" must reach filter_reference_iqm with the same
    normalized manufacturer, so they share one cache entry."""
    module, _ = iqm_viewer_module

    calls = []

    def fake_filter(modality, manufacturer_norm, field_strength_norm, max_rows):
        calls.append((modality, manufacturer_norm, field_strength_norm, max_rows))
        return pd.DataFrame({"efc": [0.1]})

    monkeypatch.setattr(module, "filter_reference_iqm", fake_filter)

    module.load_reference_iqm_for_subject(modality="t1w", manufacturer="GE", field_strength="3T")
    module.load_reference_iqm_for_subject(modality="t1w", manufacturer="General Electric", field_strength="3.0T")

    assert calls[0] == calls[1] == ("t1w", "ge", "3", 50_000)


def test_render_iqm_distributions_comparison_mode_uses_reference(iqm_viewer_module, temp_dir, monkeypatch):
    module, streamlit_stub = iqm_viewer_module

    dataset_path = temp_dir / "derivatives" / "mriqc" / "group_T1w.tsv"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path, sep="\t", index=False)

    monkeypatch.setitem(module.IQM_DISTRIBUTION_GROUPS, "t1w", {"EFC": ["efc"]})
    # Comparison mode is hidden behind this flag pending #82; the rendering
    # logic itself still needs to work once it's re-enabled.
    monkeypatch.setattr(module, "REFERENCE_COMPARISON_ENABLED", True)

    reference_df = pd.DataFrame(
        {
            "Manufacturer": ["Siemens", "GE"],
            "efc": [0.5, 0.9],
        }
    )
    # Reference loading goes through data_loaders.load_reference_iqm_for_subject
    # (Parquet download + filter), not a REFERENCE_DATA_PATHS TSV; mock it directly.
    monkeypatch.setattr(module, "load_reference_iqm_for_subject", MagicMock(return_value=reference_df))

    streamlit_stub.segmented_control.return_value = "mriqc (t1w)"
    streamlit_stub.radio.return_value = "Dataset + Reference"

    module._render_iqm_distributions(
        [str(dataset_path)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    streamlit_stub.plotly_chart.assert_called_once()
    fig = streamlit_stub.plotly_chart.call_args.args[0]
    assert len(fig.data) == 3
    call_kwargs = streamlit_stub.segmented_control.call_args.kwargs
    assert call_kwargs["options"] == ["mriqc (t1w)"]
    assert call_kwargs["key"] == "iqm_view_mode"


def test_display_iqm_panel_calls_loader_and_renderer(iqm_viewer_module, monkeypatch):
    module, _ = iqm_viewer_module

    qc_config = {"base_mri_image_path": "sub-01_T1w.nii.gz", "iqm_path": ["derivatives/mriqc/group_T1w.tsv"]}

    load_scanner_metadata = MagicMock(return_value={"Manufacturer": "Siemens"})
    extract_run_identifier = MagicMock(return_value="run-1_T1w")
    render = MagicMock()

    monkeypatch.setattr(module, "load_scanner_metadata", load_scanner_metadata)
    monkeypatch.setattr(module, "_extract_run_identifier", extract_run_identifier)
    monkeypatch.setattr(module, "_render_iqm_distributions", render)

    module._display_iqm_panel(qc_config, "qc_config.json", "sub-01", "ses-01")

    load_scanner_metadata.assert_called_once_with(
        "sub-01_T1w.nii.gz",
        participant_id="sub-01",
        session_id="ses-01",
        dataset_dir=None,
    )
    extract_run_identifier.assert_called_once_with(
        "sub-01_T1w.nii.gz",
        "sub-01",
        "ses-01",
    )
    render.assert_called_once_with(
        qc_config.get("iqm_path", []),
        {"Manufacturer": "Siemens"},
        "sub-01",
        "ses-01",
        qc_config_path="qc_config.json",
        dataset_dir=None,
        run_identifier="run-1_T1w",
    )


def test__render_iqm_distributions_handles_empty_dataset(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    module._render_iqm_distributions([], {"Manufacturer": "Siemens"}, "sub-01", None)

    streamlit_stub.warning.assert_called_once_with(module.ERROR_MESSAGES["iqm_no_sources_configured"])
    streamlit_stub.plotly_chart.assert_not_called()
    streamlit_stub.radio.assert_not_called()


def test__render_iqm_distributions_double_tabs_withsame_pipeline_name(iqm_viewer_module, temp_dir, monkeypatch):
    module, streamlit_stub = iqm_viewer_module

    dataset_path1 = temp_dir / "derivatives" / "mriqc" / "group_T1w.tsv"
    dataset_path1.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path1, sep="\t", index=False)

    dataset_path2 = temp_dir / "derivatives" / "mriqc" / "group_T1w_2.tsv"
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.33, 0.44],
        }
    ).to_csv(dataset_path2, sep="\t", index=False)

    monkeypatch.setitem(module.IQM_DISTRIBUTION_GROUPS, "t1w", {"EFC": ["efc"]})

    # Both sources are MRIQC with the same inferred modality ("t1w"), so
    # pipeline_name + modality alone would collide; the code must fall back
    # to the filename stem to keep the two tabs independently selectable.
    streamlit_stub.segmented_control.return_value = "mriqc (t1w, group_T1w)"
    streamlit_stub.radio.return_value = "Dataset"

    module._render_iqm_distributions(
        [str(dataset_path1), str(dataset_path2)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    call_kwargs = streamlit_stub.segmented_control.call_args.kwargs
    assert call_kwargs["options"] == ["mriqc (t1w, group_T1w)", "mriqc (t1w, group_T1w_2)"]
    assert len(set(call_kwargs["options"])) == len(call_kwargs["options"])

    streamlit_stub.plotly_chart.assert_called_once()
    fig = streamlit_stub.plotly_chart.call_args.args[0]
    # Selected "mriqc (group_T1w)" -> dataset1's values (0.11/0.22), not dataset2's (0.33/0.44)
    violin_y_values = [y for trace in fig.data if trace.type == "violin" for y in trace.y]
    assert 0.11 in violin_y_values
    assert 0.33 not in violin_y_values


def test__render_iqm_distributions_double_tabs_same_pipeline_same_modality_different_version(iqm_viewer_module, temp_dir, monkeypatch):
    """Two MRIQC pipeline-version folders emitting the identically-named
    group_T1w.tsv - pipeline_name AND modality collide, so the filename
    stem alone ("group_T1w") wouldn't disambiguate them either; the tab
    labels must fall back further, to the path segments after
    derivatives/mriqc/ (the version folder)."""
    module, streamlit_stub = iqm_viewer_module

    dataset_path1 = temp_dir / "derivatives" / "mriqc" / "23.1.0" / "group_T1w.tsv"
    dataset_path1.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path1, sep="\t", index=False)

    dataset_path2 = temp_dir / "derivatives" / "mriqc" / "24.0.0" / "group_T1w.tsv"
    dataset_path2.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.33, 0.44],
        }
    ).to_csv(dataset_path2, sep="\t", index=False)

    monkeypatch.setitem(module.IQM_DISTRIBUTION_GROUPS, "t1w", {"EFC": ["efc"]})

    streamlit_stub.segmented_control.return_value = "mriqc (t1w, 23.1.0/group_T1w)"
    streamlit_stub.radio.return_value = "Dataset"

    module._render_iqm_distributions(
        [str(dataset_path1), str(dataset_path2)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    call_kwargs = streamlit_stub.segmented_control.call_args.kwargs
    assert call_kwargs["options"] == ["mriqc (t1w, 23.1.0/group_T1w)", "mriqc (t1w, 24.0.0/group_T1w)"]
    assert len(set(call_kwargs["options"])) == len(call_kwargs["options"])

    streamlit_stub.plotly_chart.assert_called_once()
    fig = streamlit_stub.plotly_chart.call_args.args[0]
    violin_y_values = [y for trace in fig.data if trace.type == "violin" for y in trace.y]
    assert 0.11 in violin_y_values
    assert 0.33 not in violin_y_values


def test__disambiguate_tab_labels_numbers_pathological_collisions(iqm_viewer_module):
    """Absolute last resort: if two sources still collide after every path-
    based disambiguator (e.g. identical resolved paths from a duplicated
    config entry), labels must still end up unique so segmented_control
    never silently drops a tab."""
    module, _ = iqm_viewer_module

    Source = module.DistributionSource
    same_path = "derivatives/mriqc/group_T1w.tsv"
    sources = [
        Source(path=same_path, pipeline_name="mriqc", modality="t1w", iqm_data=None, valid_groups=None),
        Source(path=same_path, pipeline_name="mriqc", modality="t1w", iqm_data=None, valid_groups=None),
    ]

    labels = module._disambiguate_tab_labels(sources)

    assert len(labels) == len(set(labels)) == 2


def test__render_iqm_distributions_double_tabs_with_different_pipeline_names(iqm_viewer_module, temp_dir, monkeypatch):
    module, streamlit_stub = iqm_viewer_module

    dataset_path1 = temp_dir / "derivatives" / "mriqc" / "group_T1w.tsv"
    dataset_path1.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "Manufacturer": ["Siemens", "GE"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path1, sep="\t", index=False)

    reference_data = pd.DataFrame(
        {
            "id": ["dsfdewfewfgewf", "q3ej43jrjknfiugpfi"],
            "Manufacturer": ["Siemens", "Siemens"],
            "efc": [0.33, 0.44],
        }
    )

    dataset_path2 = temp_dir / "derivatives" / "customqc" / "group_T1w.tsv"
    dataset_path2.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "Manufacturer": ["Siemens", "Siemens"],
            "efc": [0.33, 0.44],
        }
    ).to_csv(dataset_path2, sep="\t", index=False)

    monkeypatch.setattr(module, "load_reference_iqm_for_subject", MagicMock(return_value=reference_data))

    monkeypatch.setitem(module.IQM_DISTRIBUTION_GROUPS, "t1w", {"EFC": ["efc"]})
    # Comparison mode is hidden behind this flag pending #82; the rendering
    # logic itself still needs to work once it's re-enabled.
    monkeypatch.setattr(module, "REFERENCE_COMPARISON_ENABLED", True)
    streamlit_stub.segmented_control.return_value = "mriqc (t1w)"
    streamlit_stub.radio.return_value = "Dataset + Reference"

    module._render_iqm_distributions(
        [str(dataset_path1), str(dataset_path2)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    called_arg = streamlit_stub.segmented_control.call_args.kwargs["options"]
    assert called_arg == ["mriqc (t1w)", "customqc (t1w)"]

    assert streamlit_stub.plotly_chart.call_count == 1
    fig = streamlit_stub.plotly_chart.call_args.args[0]
    assert len(fig.data) == 3


def test__render_iqm_distributions_single_row_data(iqm_viewer_module, temp_dir):
    module, streamlit_stub = iqm_viewer_module

    dataset_path = temp_dir / "derivatives" / "mriqc" / "sub-01" / "ses-01" / "anat" / "sub-01_ses-01_T1w.tsv"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w"],
            "efc": [0.11],
        }
    ).to_csv(dataset_path, sep="\t", index=False)

    # A single-row source is promoted to a MetricsSource before modality/
    # distribution-group resolution ever runs, so this monkeypatch is
    # unused here - left out on purpose, unlike the multi-row tests above.

    streamlit_stub.segmented_control.return_value = "mriqc (t1w, subject-level)"

    module._render_iqm_distributions(
        [str(dataset_path)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    # Metrics-table path: renders via st.table and returns before the
    # display-mode radio or any plotting is ever reached.
    streamlit_stub.radio.assert_not_called()
    streamlit_stub.plotly_chart.assert_not_called()
    streamlit_stub.table.assert_called_once()

    metrics_df = streamlit_stub.table.call_args.args[0]
    assert list(metrics_df.columns) == ["Metric", "Value"]
    assert dict(zip(metrics_df["Metric"], metrics_df["Value"])) == {"efc": 0.11}
    streamlit_stub.warning.assert_not_called()


def test_infer_bids_from_path(iqm_viewer_module):
    module, _ = iqm_viewer_module

    paths = [
        # T1w / anat
        ("bids/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.nii.gz", "t1w"),
        ("derivatives/mriqc/group_T1w.tsv", "t1w"),
        ("derivatives/mriqc/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.json", "t1w"),
        # BOLD / func
        ("bids/sub-CMH0001/ses-01/func/sub-CMH0001_ses-01_task-rest_run-1_bold.nii.gz", "bold"),
        ("derivatives/mriqc/group_bold.tsv", "bold"),
        ("derivatives/mriqc/sub-CMH0001/ses-01/func/sub-CMH0001_ses-01_task-emp_run-1_bold.json", "bold"),
        ("sub-CMH0001/ses-01/func/sub-CMH0001_ses-01_task-rest_run-1_timeseries.json", "bold"),
        # DWI
        ("bids/sub-CMH0001/ses-01/dwi/sub-CMH0001_ses-01_acq-multishelldir92_run-1_dwi.nii.gz", "dwi"),
        ("derivatives/mriqc/group_dwi.tsv", "dwi"),
        ("derivatives/mriqc/sub-CMH0001/ses-01/dwi/sub-CMH0001_ses-01_acq-multishelldir92_run-1_dwi.json", "dwi"),
        # no modality signal anywhere - should resolve to None, not a guess
        ("derivatives/fsqc/2.1.4/output/ses-01/metrics/sub-ED01/metrics.csv", None),
        (None, None),
        ("", None),
    ]

    for path, expected in paths:
        assert module._infer_modality_from_path(path) == expected, f"failed for {path!r}"


def test_extract_run_identifier(iqm_viewer_module):
    module, _ = iqm_viewer_module

    # (base_mri_image_path, participant_id, session_id, expected)
    cases = [
        ("bids/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.nii.gz", "sub-CMH0001", "ses-01", "run-1_T1w"),
        ("bids/sub-CMH0001/ses-01/func/sub-CMH0001_ses-01_task-rest_run-1_bold.nii.gz", "sub-CMH0001", "ses-01", "task-rest_run-1_bold"),
        ("bids/sub-CMH0001/ses-01/func/sub-CMH0001_ses-01_task-rest_run-2_bold.nii.gz", "sub-CMH0001", "ses-01", "task-rest_run-2_bold"),
        (
            "derivatives/fmriprep/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_desc-preproc_T1w.nii.gz",
            "sub-CMH0001",
            "ses-01",
            "run-1_desc-preproc_T1w",
        ),
        ("derivatives/mriqc/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.json", "sub-CMH0001", "ses-01", "run-1_T1w"),
        ("bids/sub-ED01/anat/sub-ED01_run-1_T1w.nii.gz", "sub-ED01", None, "run-1_T1w"),
        (None, "sub-CMH0001", "ses-01", None),
        ("", "sub-CMH0001", "ses-01", None),
        ("bids/sub-CMH0001/ses-01/anat/sub-CMH0001_ses-01_run-1_T1w.nii.gz", "sub-CMH9999", "ses-01", "sub-CMH0001_run-1_T1w"),
    ]

    for path, participant_id, session_id, expected in cases:
        result = module._extract_run_identifier(path, participant_id, session_id)
        assert result == expected, f"failed for path={path!r} participant_id={participant_id!r} session_id={session_id!r}: got {result!r}"


def test_extract_subject_data(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": [
                "sub-01_ses-01_T1w",
                "sub-01_ses-02_T1w",
                "sub-02_ses-01_T1w",
                "sub-01_T1w",
            ],
            "efc": [0.1, 0.2, 0.3, 0.4],
            "snr_total": [10, 20, 30, 40],
        }
    )

    result = module._extract_subject_data(data, "sub-01", ["efc", "snr_total"], session_id="ses-02")

    assert len(result) == 1
    assert result.iloc[0]["efc"] == 0.2
    assert result.iloc[0]["snr_total"] == 20


def test__coerce_numeric_columns(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "efc": ["0.1", "0.2", "not_a_number"],
            "snr_total": [10, 20, 30],
            "bids_name": ["sub-01_ses-01_T1w", "sub-01_ses-02_T1w", "sub-02_ses-01_T1w"],
        }
    )

    result = module._coerce_numeric_columns(data, ["efc", "snr_total"])

    assert result["efc"].dtype.kind in ("f", "i")  # float or int
    assert result["snr_total"].dtype.kind in ("f", "i")
    assert pd.isna(result.loc[2, "efc"])  # non-numeric value coerced to NaN


def test__generic_groups_from_columns(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "efc": [0.1, 0.2, 0.3],
            "snr_total": [10, 20, 30],
            "fber": [100, 200, 300],
            "bids_name": ["sub-01_ses-01_T1w", "sub-01_ses-02_T1w", "sub-02_ses-01_T1w"],
        }
    )
    expected_groups = {
        "efc": ["efc"],
        "snr_total": ["snr_total"],
        "fber": ["fber"],
    }

    result = module._generic_groups_from_columns(data)

    assert result == expected_groups


def test__get_valid_iqm_groups(iqm_viewer_module):
    module, _ = iqm_viewer_module

    distribution_groups = {
        "EFC": ["efc"],
        "SUMMARY_BG": [
            "summary_bg_mean",
            "summary_bg_median",
            "summary_bg_stdv",
            "summary_bg_mad",
            "summary_bg_k",
            "summary_bg_p05",
            "summary_bg_p95",
        ],
        "FBER": ["fber"],
    }

    iqm_data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w"],
            "efc": [0.45],
            "summary_bg_mean": [13.1],
            "summary_bg_median": [9.0],
            "summary_bg_stdv": [17.8],
            # summary_bg_mad, summary_bg_k, summary_bg_p05, summary_bg_p95: not in this table
            # fber: not in this table at all
        }
    )

    expected = {
        "EFC": ["efc"],
        "SUMMARY_BG": ["summary_bg_mean", "summary_bg_median", "summary_bg_stdv"],
        # no "FBER" key at all
    }

    result = module._get_valid_iqm_groups(distribution_groups, iqm_data)
    assert result == expected


def test__render_iqm_metrics_table_filters_nested_values(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    single_subject_data = {
        "bids_meta": {
            "AcquisitionMatrixPE": 256,
            "ImageType": ["ORIGINAL", "PRIMARY", "OTHER"],
            "session_id": "01",
            "subject_id": "CMH0001",
        },
        "cjv": 0.5653991124260355,
        "cnr": 1.6440422676204975,
        "provenance": {
            "md5sum": "b4620176b83b7d3e803e85534fefc53d",
            "software": "mriqc",
            "warnings": {"large_rot_frame": True, "small_air_mask": False},
        },
    }

    module._render_iqm_metrics_table(single_subject_data, "sub-CMH0001")

    streamlit_stub.warning.assert_not_called()
    streamlit_stub.caption.assert_called_once_with(module.MESSAGES["iqm_metrics_table_experimental"])
    streamlit_stub.table.assert_called_once()
    df = streamlit_stub.table.call_args.args[0]
    assert list(df.columns) == ["Metric", "Value"]
    assert dict(zip(df["Metric"], df["Value"])) == {
        "cjv": 0.5653991124260355,
        "cnr": 1.6440422676204975,
    }


def test__render_iqm_metrics_table_warns_when_only_nested_values(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    single_subject_data = {
        "bids_meta": {"session_id": "01", "subject_id": "CMH0001"},
        "provenance": {"software": "mriqc"},
    }

    module._render_iqm_metrics_table(single_subject_data, "sub-CMH0001")

    streamlit_stub.warning.assert_called_once()
    streamlit_stub.caption.assert_not_called()
    streamlit_stub.table.assert_not_called()


def test__path_after_pipeline(iqm_viewer_module):
    module, _ = iqm_viewer_module

    # version subdirectory between pipeline and filename -> kept
    assert module._path_after_pipeline("derivatives/mriqc/23.1.0/group_T1w.tsv") == "23.1.0/group_T1w"
    # filename directly under the pipeline dir -> same as the stem
    assert module._path_after_pipeline("derivatives/mriqc/group_T1w.tsv") == "group_T1w"
    # no "derivatives" segment to anchor on -> falls back to the stem
    assert module._path_after_pipeline("some/other/layout/group_T1w.tsv") == "group_T1w"


def test__disambiguate_tab_labels_modality_resolves_collision(iqm_viewer_module):
    module, _ = iqm_viewer_module
    Source = module.DistributionSource

    sources = [
        Source(path="derivatives/mriqc/group_T1w.tsv", pipeline_name="mriqc", modality="t1w", iqm_data=None, valid_groups=None),
        Source(path="derivatives/mriqc/group_bold.tsv", pipeline_name="mriqc", modality="bold", iqm_data=None, valid_groups=None),
    ]

    assert module._disambiguate_tab_labels(sources) == ["mriqc (t1w)", "mriqc (bold)"]


def test__disambiguate_tab_labels_metrics_source_gets_subject_level_tag(iqm_viewer_module):
    """A MetricsSource (per-subject JSON) is labeled with its modality plus
    a "subject-level" qualifier, so it's distinguishable from a group-level
    DistributionSource tab sharing the same pipeline/modality."""
    module, _ = iqm_viewer_module

    sources = [
        module.DistributionSource(path="derivatives/mriqc/group_dwi.tsv", pipeline_name="mriqc", modality="dwi", iqm_data=None, valid_groups=None),
        module.MetricsSource(path="derivatives/mriqc/sub-01_dwi.json", pipeline_name="mriqc", modality="dwi", metrics={}),
    ]

    assert module._disambiguate_tab_labels(sources) == ["mriqc (dwi)", "mriqc (dwi, subject-level)"]


def test__disambiguate_tab_labels_metrics_source_no_modality(iqm_viewer_module):
    module, _ = iqm_viewer_module

    sources = [module.MetricsSource(path="derivatives/customqc/sub-01_metrics.json", pipeline_name="customqc", modality=None, metrics={})]

    assert module._disambiguate_tab_labels(sources) == ["customqc (subject-level)"]


def test__disambiguate_tab_labels_no_collision_stays_plain(iqm_viewer_module):
    """Modality is always shown when known; a source with no inferable
    modality (e.g. fmriprep's confounds.tsv, no t1w/bold/dwi in the path)
    falls back to the bare pipeline name. No collision here, so the
    path-based disambiguator is never consulted."""
    module, _ = iqm_viewer_module
    Source = module.DistributionSource

    sources = [
        Source(path="derivatives/mriqc/group_T1w.tsv", pipeline_name="mriqc", modality="t1w", iqm_data=None, valid_groups=None),
        Source(path="derivatives/fmriprep/desc-confounds.tsv", pipeline_name="fmriprep", modality=None, iqm_data=None, valid_groups=None),
    ]

    assert module._disambiguate_tab_labels(sources) == ["mriqc (t1w)", "fmriprep"]


def test__add_violin_traces(iqm_viewer_module):
    module, _ = iqm_viewer_module

    fig = go.Figure()
    data = pd.DataFrame(
        {
            "efc": [0.1, 0.2, None],
            "snr_total": [10, 20, 30],
            "all_nan": [None, None, None],
        }
    )

    module._add_violin_traces(fig, data, module.DATASET_STYLE, name="Dataset", side="negative", points=False)

    # all-NaN column contributes no trace at all
    assert len(fig.data) == 2
    assert [trace.name for trace in fig.data] == ["Dataset", "Dataset"]
    assert all(trace.side == "negative" for trace in fig.data)
    assert fig.data[0].showlegend is True
    assert fig.data[1].showlegend is False  # only the first trace carries the legend entry
    assert list(fig.data[0].y) == [0.1, 0.2]  # the None dropped, real values kept
    assert "Source: Dataset" in fig.data[0].hovertemplate
    assert "Metric: efc" in fig.data[0].hovertemplate


def test__add_subject_overlay_multiple_runs(iqm_viewer_module):
    module, _ = iqm_viewer_module

    fig = go.Figure()
    subject_rows = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_run-1_T1w", "sub-01_ses-01_run-2_T1w"],
            "efc": [0.3, 0.5],
        }
    )

    module._add_subject_overlay(fig, subject_rows, "sub-01", offsetgroup="Dataset", label_suffix=" (dataset)")

    assert len(fig.data) == 2
    assert "Run: sub-01_ses-01_run-1_T1w" in fig.data[0].hovertemplate
    assert "Run: sub-01_ses-01_run-2_T1w" in fig.data[1].hovertemplate
    assert fig.data[0].showlegend is True
    assert fig.data[1].showlegend is False


def test__extract_subject_data_narrows_by_run_identifier(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": [
                "sub-01_ses-01_task-rest_run-1_bold",
                "sub-01_ses-01_task-rest_run-2_bold",
            ],
            "efc": [0.1, 0.2],
        }
    )

    result = module._extract_subject_data(data, "sub-01", ["efc"], session_id="ses-01", run_identifier="run-2_bold")

    assert len(result) == 1
    assert result.iloc[0]["efc"] == 0.2


def test__extract_subject_data_run_identifier_falls_back_when_no_match(iqm_viewer_module):
    """A run_identifier that matches nothing shouldn't drop the subject
    entirely - fall back to the broader (session-only) mask so the overlay
    still shows something rather than going empty."""
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_task-rest_run-1_bold"],
            "efc": [0.1],
        }
    )

    result = module._extract_subject_data(data, "sub-01", ["efc"], session_id="ses-01", run_identifier="run-99_bold")

    assert len(result) == 1


def test__build_iqm_distribution_figure_requires_metric_columns(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    data = pd.DataFrame({"bids_name": ["sub-01_ses-01_T1w"], "efc": [0.1]})

    fig = module._build_iqm_distribution_figure(
        metric_group_name="EFC",
        modality="t1w",
        iqm_data=data,
        participant_id="sub-01",
        session_id=None,
        metric_columns=[],
        display_mode="Dataset",
    )

    assert fig is None
    streamlit_stub.error.assert_called_once()


def test__build_iqm_distribution_figure_falls_back_when_reference_empty(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.1, 0.2],
        }
    )

    fig = module._build_iqm_distribution_figure(
        metric_group_name="EFC",
        modality="t1w",
        iqm_data=data,
        participant_id="sub-01",
        session_id=None,
        metric_columns=["efc"],
        display_mode=module.DISPLAY_MODE_OPTIONS[1],
        reference_data=None,
    )

    assert fig is not None
    assert all(trace.name != "Reference" for trace in fig.data)


def test__clip_reference_outliers_caps_without_dropping_rows(iqm_viewer_module):
    module, _ = iqm_viewer_module

    # A handful of degenerate rows (fber) shouldn't stretch the axis, but
    # every row must still survive - only the extreme values get pulled in.
    data = pd.DataFrame({"fber": [1.0, 1.1, 1.2, 1.15, 561536.06]})

    result = module._clip_reference_outliers(data, ["fber"])

    assert len(result) == 5
    assert result["fber"].max() < 561536.06
    assert result["fber"].iloc[0] == pytest.approx(1.0, abs=0.5)


def test__clip_reference_outliers_ignores_missing_columns(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame({"efc": [0.1, 0.2, 0.3]})

    result = module._clip_reference_outliers(data, ["efc", "not_a_column"])

    assert list(result.columns) == ["efc"]


def test__build_iqm_distribution_figure_clips_reference_outliers(iqm_viewer_module):
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.1, 0.2],
        }
    )
    # One corrupted reference row stretched far beyond where the real
    # population lives - the violin trace's rendered range shouldn't include it.
    reference_data = pd.DataFrame({"efc": [0.1, 0.11, 0.12, 0.13, 0.14, 0.15, 999.0]})

    fig = module._build_iqm_distribution_figure(
        metric_group_name="EFC",
        modality="t1w",
        iqm_data=data,
        participant_id="sub-01",
        session_id=None,
        metric_columns=["efc"],
        display_mode=module.DISPLAY_MODE_OPTIONS[1],
        reference_data=reference_data,
    )

    reference_trace = next(trace for trace in fig.data if trace.name == "Reference")
    assert max(reference_trace.y) < 999.0


def test__build_iqm_distribution_figure_warns_when_no_plottable_data(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    data = pd.DataFrame({"bids_name": ["sub-01_ses-01_T1w"], "efc": ["not_a_number"]})

    fig = module._build_iqm_distribution_figure(
        metric_group_name="EFC",
        modality="t1w",
        iqm_data=data,
        participant_id="sub-01",
        session_id=None,
        metric_columns=["efc"],
        display_mode="Dataset",
    )

    assert fig is None
    streamlit_stub.warning.assert_called_once()


def test__render_montage_of_iqm_groups_renders_one_chart_per_group(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module
    streamlit_stub.columns.return_value = [MagicMock(), MagicMock()]

    iqm_data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.1, 0.2],
            "fber": [100, 200],
        }
    )
    valid_groups = {"EFC": ["efc"], "FBER": ["fber"]}

    module._render_montage_of_iqm_groups(
        valid_groups=valid_groups,
        iqm_data=iqm_data,
        reference_data=None,
        participant_id="sub-01",
        session_id=None,
        modality="t1w",
        display_mode="Dataset",
    )

    assert streamlit_stub.plotly_chart.call_count == 2
    keys = [call.kwargs["key"] for call in streamlit_stub.plotly_chart.call_args_list]
    assert keys == ["iqm_overview_t1w_EFC", "iqm_overview_t1w_FBER"]


def test__build_iqm_distribution_figure_never_shows_its_own_legend(iqm_viewer_module):
    """Individual per-group charts never carry a legend - it's rendered
    once for the whole tab instead (see _render_iqm_legend)."""
    module, _ = iqm_viewer_module

    data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.1, 0.2],
        }
    )

    fig = module._build_iqm_distribution_figure(
        metric_group_name="EFC",
        modality="t1w",
        iqm_data=data,
        participant_id="sub-01",
        session_id=None,
        metric_columns=["efc"],
        display_mode="Dataset",
    )

    assert fig.layout.showlegend is not True


def test__render_iqm_legend_dataset_only(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    module._render_iqm_legend(show_reference=False)

    streamlit_stub.markdown.assert_called_once()
    html = streamlit_stub.markdown.call_args.args[0]
    assert "Dataset" in html
    assert "Current subject" in html
    assert "Reference" not in html


def test__render_iqm_legend_includes_reference_when_shown(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module

    module._render_iqm_legend(show_reference=True)

    html = streamlit_stub.markdown.call_args.args[0]
    assert "Dataset" in html
    assert "Reference" in html
    assert "Current subject" in html


def test__render_montage_of_iqm_groups_renders_legend_once_not_per_chart(iqm_viewer_module):
    module, streamlit_stub = iqm_viewer_module
    streamlit_stub.columns.return_value = [MagicMock(), MagicMock()]

    iqm_data = pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.1, 0.2],
            "fber": [100, 200],
            "cjv": [0.3, 0.4],
        }
    )
    valid_groups = {"EFC": ["efc"], "FBER": ["fber"], "CJV": ["cjv"]}

    module._render_montage_of_iqm_groups(
        valid_groups=valid_groups,
        iqm_data=iqm_data,
        reference_data=None,
        participant_id="sub-01",
        session_id=None,
        modality="t1w",
        display_mode="Dataset",
    )

    streamlit_stub.markdown.assert_called_once()
    figs = [call.args[0] for call in streamlit_stub.plotly_chart.call_args_list]
    assert len(figs) == 3
    assert all(fig.layout.showlegend is not True for fig in figs)


def test__render_iqm_distributions_non_mriqc_source_skips_reference_radio(iqm_viewer_module, temp_dir):
    module, streamlit_stub = iqm_viewer_module

    dataset_path = temp_dir / "derivatives" / "customqc" / "group_T1w.tsv"
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "bids_name": ["sub-01_ses-01_T1w", "sub-02_ses-01_T1w"],
            "efc": [0.11, 0.22],
        }
    ).to_csv(dataset_path, sep="\t", index=False)

    streamlit_stub.segmented_control.return_value = "customqc (t1w)"

    module._render_iqm_distributions(
        [str(dataset_path)],
        {"Manufacturer": "Siemens"},
        "sub-01",
        None,
    )

    streamlit_stub.radio.assert_not_called()
    streamlit_stub.plotly_chart.assert_called_once()
    assert module.MESSAGES["iqm_generic_distribution_experimental"] in [c.args[0] for c in streamlit_stub.caption.call_args_list]
