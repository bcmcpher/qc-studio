"""IQM viewer component for QC-Studio.

Renders configured Image Quality Metric (IQM) sources alongside the QC review
view. Group-level TSV/CSV sources are shown as violin plots with the current
subject highlighted, and participant-level JSON or single-row sources are shown
as metrics tables.

IQM sources are read from the QC config's ``iqm_path`` entry. MRIQC group files
use modality-specific metric groups for T1w, BOLD, and DWI data; other
pipelines fall back to one plot per numeric metric.
"""

import re
import pandas as pd
import streamlit as st

from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Union

import plotly.graph_objects as go

from utils.data_loaders import (
    resolve_iqm_data_path,
    load_scanner_metadata,
    load_iqm_distribution_table as _load_iqm_distribution_table_uncached,
    load_iqm_metrics_subject_level,
)
from utils.reference_data import (
    normalize_manufacturer,
    normalize_field_strength,
    filter_reference_iqm,
    MAX_REFERENCE_ROWS,
    CACHE_TTL_SECONDS,
)
from constants import MESSAGES, ERROR_MESSAGES
from managers.session_manager import SessionManager
from utils.iqm_distribution_config import (
    IQM_DISTRIBUTION_GROUPS,
    infer_pipeline_from_iqm_path,
    is_mriqc_pipeline,
)

DATASET_STYLE = dict(
    marker=dict(size=4, symbol="circle", color="rgba(31, 119, 180, 0.55)"),
    line=dict(color="rgba(31, 119, 180, 0.8)", width=1),
    fillcolor="rgba(31, 119, 180, 0.25)",
)
REFERENCE_STYLE = dict(
    marker=dict(size=4, symbol="circle", color="rgba(214, 39, 40, 0.55)"),
    line=dict(color="rgba(214, 39, 40, 1.0)", width=1),
    fillcolor="rgba(214, 39, 40, 0.25)",
)
SUBJECT_MARKER_STYLE = dict(size=8, symbol="diamond", color="rgba(255, 127, 14, 0.9)", line=dict(color="rgba(255, 127, 14, 1.0)", width=2))

CONTAINER_HEIGHT = 520
NUM_OVERVIEW_COLUMNS = 2

NON_METRIC_COLUMNS = {"bids_name", "subject", "subject_id", "participant_id"}

DISPLAY_MODE_OPTIONS = ["Dataset", "Dataset + Reference"]

# Reference-data comparison is hidden until issue #82 (unfiltered downloaded
# reference data can be visually misleading) is addressed. Flip to True once
# that cleaning/filtering step lands.
REFERENCE_COMPARISON_ENABLED = False


@dataclass(frozen=True)
class DistributionSource:
    path: "Path"
    pipeline_name: str
    modality: "Optional[str]"
    iqm_data: "pd.DataFrame"
    valid_groups: dict


@dataclass(frozen=True)
class MetricsSource:
    path: "Path"
    pipeline_name: str
    modality: "Optional[str]"
    metrics: dict


def _infer_modality_from_path(path: str) -> Optional[str]:
    """Infer the modality (t1w, bold, dwi) from the IQM path string."""
    if not path:
        return None

    path_str = str(path).lower()
    name = Path(path).name.lower()

    if "/func/" in path_str or re.search(r"_(bold|sbref)\.", path_str) or "bold" in name:
        return "bold"
    if "/dwi/" in path_str or re.search(r"_dwi\.", path_str) or "dwi" in name:
        return "dwi"
    if "/anat/" in path_str or "t1w" in name:
        return "t1w"

    return None


def _path_after_pipeline(path) -> str:
    """Return source-identifying path segments after ``derivatives/<pipeline>/``."""
    parts = Path(path).parts
    if "derivatives" in parts:
        idx = parts.index("derivatives")
        remainder = parts[idx + 2 :]
        if remainder:
            return str(Path(*remainder).with_suffix(""))
    return Path(path).stem


def _disambiguate_tab_labels(sources) -> list:
    """Build unique tab labels for all configured IQM sources."""

    def make_label(source, parts) -> str:
        return f"{source.pipeline_name} ({', '.join(parts)})" if parts else source.pipeline_name

    parts_list = []
    for s in sources:
        parts = []
        modality = getattr(s, "modality", None)
        if modality:
            parts.append(modality)
        if isinstance(s, MetricsSource):
            parts.append("subject-level")
        parts_list.append(parts)

    labels = [make_label(s, parts) for s, parts in zip(sources, parts_list)]

    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    if any(count > 1 for count in counts.values()):
        for i, (s, label) in enumerate(zip(sources, labels)):
            if counts[label] > 1:
                parts_list[i] = parts_list[i] + [_path_after_pipeline(s.path)]
        labels = [make_label(s, parts) for s, parts in zip(sources, parts_list)]

    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    if any(count > 1 for count in counts.values()):
        seen = {}
        numbered = []
        for label in labels:
            if counts[label] > 1:
                seen[label] = seen.get(label, 0) + 1
                numbered.append(f"{label} #{seen[label]}")
            else:
                numbered.append(label)
        labels = numbered

    return labels


def _generic_groups_from_columns(iqm_data) -> dict:
    """Return a stable fallback grouping for non-curated IQM sources.

    Until a pipeline-specific grouping is available, each numeric metric is
    rendered as its own group so the source remains inspectable.
    """
    metric_columns = [col for col in iqm_data.columns if (pd.api.types.is_numeric_dtype(iqm_data[col]) and col.lower() not in NON_METRIC_COLUMNS)]

    return {col: [col] for col in metric_columns}


def _row_to_metrics(row) -> dict:
    """Flatten a single-row Series into a metrics dict, dropping non-metric/index columns."""
    return {col: value for col, value in row.items() if str(col).lower() not in NON_METRIC_COLUMNS and not str(col).startswith("Unnamed:")}


@st.cache_data(ttl=3600, show_spinner=False)
def _load_iqm_distribution_table_cached(resolved_path):
    """Cached wrapper around ``data_loaders.load_iqm_distribution_table``."""
    return _load_iqm_distribution_table_uncached(resolved_path)


@st.cache_data(show_spinner="Loading reference data...", ttl=CACHE_TTL_SECONDS)
def _load_reference_iqm_cached(modality, manufacturer_norm, field_strength_norm, max_rows):
    """Cached wrapper around ``reference_data.filter_reference_iqm``."""
    return filter_reference_iqm(modality, manufacturer_norm, field_strength_norm, max_rows)


def load_reference_iqm_for_subject(modality, manufacturer, field_strength=None, max_rows=MAX_REFERENCE_ROWS):
    """Normalize a subject's scanner metadata, then load the cached, filtered reference table."""
    manufacturer_norm = normalize_manufacturer(manufacturer)
    field_strength_norm = normalize_field_strength(field_strength)
    return _load_reference_iqm_cached(modality, manufacturer_norm, field_strength_norm, max_rows)


def _load_distribution_source(path, resolved, pipeline_name):
    """Load a TSV/CSV distribution source and return a DistributionSource or MetricsSource object."""
    try:
        iqm_data = _load_iqm_distribution_table_cached(resolved)
    except Exception as e:
        st.error(ERROR_MESSAGES["iqm_data_load_error"].format(modality=pipeline_name, error=e))
        return None

    if len(iqm_data) == 0:
        st.warning(
            ERROR_MESSAGES.get(
                "iqm_no_valid_groups",
                f"No rows found in {pipeline_name} ({path}).",
            )
        )
        return None

    # Infer modality for tab labels; curated metric groups remain MRIQC-only.
    modality = _infer_modality_from_path(path)

    if len(iqm_data) == 1:
        return MetricsSource(
            path=resolved,
            pipeline_name=pipeline_name,
            modality=modality,
            metrics=_row_to_metrics(iqm_data.iloc[0]),
        )

    distribution_groups = {}

    if is_mriqc_pipeline(pipeline_name) and modality is not None:
        distribution_groups = IQM_DISTRIBUTION_GROUPS.get(modality, {})
        if callable(distribution_groups):
            distribution_groups = distribution_groups(iqm_data.columns)

    if distribution_groups:
        valid_groups = _get_valid_iqm_groups(distribution_groups, iqm_data)

    else:
        valid_groups = _generic_groups_from_columns(iqm_data)

    if not valid_groups:
        st.warning(
            ERROR_MESSAGES.get(
                "iqm_no_valid_groups",
                f"No usable metric columns found in {pipeline_name} ({path}).",
            )
        )
        return None

    return DistributionSource(
        path=resolved,
        pipeline_name=pipeline_name,
        modality=modality,
        iqm_data=iqm_data,
        valid_groups=valid_groups,
    )


def _load_metrics_source(path, resolved, pipeline_name):
    """JSON branch: a single per-subject metrics dict, rendered as one tab of a plain table."""
    try:
        metrics = load_iqm_metrics_subject_level(resolved)
    except Exception as e:
        st.error(ERROR_MESSAGES["iqm_data_load_error"].format(modality=pipeline_name, error=e))
        return None

    return MetricsSource(
        path=resolved,
        pipeline_name=pipeline_name,
        modality=_infer_modality_from_path(path),
        metrics=metrics,
    )


def _load_iqm_sources(iqm_paths, qc_config_path=None, dataset_dir=None) -> list:
    """Resolve configured IQM sources, skipping failed sources with UI warnings."""
    sources = []
    for path in iqm_paths:
        resolved = resolve_iqm_data_path(path, qc_config_path, dataset_dir)
        pipeline_name = infer_pipeline_from_iqm_path(path)
        suffix = Path(path).suffix.lower()

        if suffix == ".json":
            source = _load_metrics_source(path, resolved, pipeline_name)
        else:
            source = _load_distribution_source(path, resolved, pipeline_name)

        if source is not None:
            sources.append(source)
    return sources


def _render_iqm_metrics_table(metrics: dict, participant_id: str) -> None:
    """Render participant-level metrics using the default table view.

    Group-level TSV/CSV files support distribution plots. Single-subject JSON
    files and single-row tables use this table view until richer per-subject
    metric displays are defined.
    """
    scalar_metrics = {k: v for k, v in metrics.items() if not isinstance(v, (dict, list))}
    if not scalar_metrics:
        st.warning("No metrics found in this IQM source.")
        return
    st.caption(MESSAGES["iqm_metrics_table_experimental"])
    st.write(f"QC metrics for {participant_id}.")
    st.table(pd.DataFrame(sorted(scalar_metrics.items()), columns=["Metric", "Value"]))


def _extract_run_identifier(base_mri_image_path, participant_id: str, session_id: str = None) -> Optional[str]:
    """Extract run/task BIDS entities from the current QC image path."""
    if not base_mri_image_path:
        return None

    name = Path(base_mri_image_path).name
    for suffix in (".nii.gz", ".nii", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    if participant_id:
        name = name.replace(participant_id, "")
    if session_id:
        name = name.replace(session_id, "")

    name = re.sub(r"_+", "_", name).strip("_")
    return name or None


def _extract_subject_data(data: pd.DataFrame, participant_id: str, columns: list, session_id: str = None, run_identifier: str = None) -> pd.DataFrame:
    """Extract subject-specific data for the given participant ID and columns."""
    if "bids_name" not in data.columns:
        raise ValueError("Expected 'bids_name' column not found in data.")

    participant_mask = data["bids_name"].str.startswith(participant_id)
    mask = participant_mask
    if session_id:
        if not session_id.startswith("ses-"):
            raise ValueError("session_id should start with 'ses-'.")

        session_mask = participant_mask & data["bids_name"].str.contains(session_id)

        # Some MRIQC files omit session tags; fall back to participant rows when needed.
        if session_mask.any():
            mask = session_mask

    if run_identifier:
        # Match the current run/task when possible, without hiding all subject rows.
        run_mask = mask & data["bids_name"].str.contains(run_identifier, regex=False)
        if run_mask.any():
            mask = run_mask

    select_columns = columns if "bids_name" in columns else ["bids_name"] + list(columns)
    data_subject = data.loc[mask, select_columns]
    return data_subject


def _coerce_numeric_columns(data: pd.DataFrame, columns: list) -> pd.DataFrame:
    """Convert target columns to numeric, coercing invalid values to NaN."""
    converted = data.copy()
    for col in columns:
        if col in converted.columns:
            converted[col] = pd.to_numeric(converted[col], errors="coerce")
    return converted


REFERENCE_OUTLIER_PERCENTILES = (0.01, 0.99)


def _clip_reference_outliers(
    data: pd.DataFrame, columns, low: float = REFERENCE_OUTLIER_PERCENTILES[0], high: float = REFERENCE_OUTLIER_PERCENTILES[1]
) -> pd.DataFrame:
    """Clip reference values to percentile bounds so plots keep readable axes."""
    clipped = data.copy()
    for col in columns:
        if col not in clipped.columns:
            continue
        lower = clipped[col].quantile(low)
        upper = clipped[col].quantile(high)
        clipped[col] = clipped[col].clip(lower=lower, upper=upper)
    return clipped


def _add_violin_traces(
    fig: go.Figure,
    data: pd.DataFrame,
    style: dict,
    name: str = "",
    side: str = "both",
    points: Union[bool, str] = False,
) -> None:
    """Add one violin trace per metric column."""
    first_shown = True
    cols = data.columns

    for col in cols:
        values = data[col].dropna()
        if values.empty:
            continue
        fig.add_trace(
            go.Violin(
                x=[col] * len(values),
                y=values,
                side=side,
                name=name,
                scalegroup=col,
                legendgroup=name,
                spanmode="hard",
                showlegend=first_shown,
                points=points,
                jitter=0.45,
                marker=style["marker"],
                line=style["line"],
                fillcolor=style["fillcolor"],
                hovertemplate=(f"Source: {name}<br>Metric: {col}<br>Value: %{{y}}<extra></extra>"),
            )
        )
        first_shown = False


def _add_subject_overlay(
    fig: go.Figure,
    subject_rows: pd.Series,
    participant_id: str,
    style: dict = SUBJECT_MARKER_STYLE,
    offsetgroup: str = "",
    label_suffix: str = "",
    show_legend: bool = True,
) -> None:
    """Overlay subject data on the plot.
    When a subject has multiple runs, each run is shown as a separate
    star at the same x position so the rater can see run-to-run
    variability.

    In comparison mode, call this twice with different ``offsetgroup``
    values (``"dataset"`` and ``"reference"``) so the stars align on
    top of the correct violin half.
    """

    for _, row in subject_rows.iterrows():
        run_label = row.get("bids_name") or f"{participant_id}{label_suffix}"
        participant_values = row.drop(labels=["bids_name"], errors="ignore").dropna()
        if participant_values.empty:
            continue
        for col, value in participant_values.items():
            fig.add_trace(
                go.Scatter(
                    x=[col],
                    y=[value],
                    mode="markers",
                    name=f"{participant_id}{label_suffix}",
                    marker=style,
                    showlegend=show_legend,
                    offsetgroup=offsetgroup.lower(),
                    hovertemplate=(f"Run: {run_label}<br>Value: %{{y}}<extra></extra>"),
                )
            )
            show_legend = False


def _get_valid_iqm_groups(distribution_groups: dict, iqm_data: pd.DataFrame) -> dict:
    """Return IQM groups with at least one column present in the data."""
    valid_groups = {}
    for group_name, columns in distribution_groups.items():
        valid_columns = [col for col in columns if col in iqm_data.columns]

        if valid_columns:
            valid_groups[group_name] = valid_columns
    return valid_groups


def _build_iqm_distribution_figure(
    metric_group_name: str,
    modality: str,
    iqm_data: pd.DataFrame,
    participant_id: str,
    session_id: str,
    metric_columns: list,
    display_mode: str,
    reference_data: Optional[pd.DataFrame] = None,
    run_identifier: Optional[str] = None,
) -> Optional[go.Figure]:
    """Construct the Plotly figure for the IQM distribution panel."""

    if not metric_columns:
        st.error("None of the required columns for this group are present in the data.")
        return None

    iqm_data_for_group = _coerce_numeric_columns(iqm_data, metric_columns)
    participant_columns = _extract_subject_data(
        iqm_data_for_group,
        participant_id,
        metric_columns,
        session_id=session_id,
        run_identifier=run_identifier,
    )
    dataset_plot_data = iqm_data_for_group[metric_columns]

    reference_plot_data = None
    group_display_mode = display_mode
    if display_mode == DISPLAY_MODE_OPTIONS[1]:
        if reference_data is not None:
            reference_plot_data = _coerce_numeric_columns(reference_data, metric_columns)
            reference_plot_data = reference_plot_data[metric_columns]
            reference_plot_data = _clip_reference_outliers(reference_plot_data, metric_columns)
        if reference_plot_data is None or reference_plot_data.dropna(how="all").empty:
            group_display_mode = DISPLAY_MODE_OPTIONS[0]

    fig = go.Figure()

    if group_display_mode == DISPLAY_MODE_OPTIONS[0]:
        _add_violin_traces(
            fig,
            dataset_plot_data,
            DATASET_STYLE,
            name=DISPLAY_MODE_OPTIONS[0],
            side="both",
            points=False,
        )
        _add_subject_overlay(fig, participant_columns, participant_id, offsetgroup="Dataset", label_suffix=" (dataset)")

    elif group_display_mode == DISPLAY_MODE_OPTIONS[1]:
        _add_violin_traces(
            fig,
            dataset_plot_data,
            DATASET_STYLE,
            name="Dataset",
            side="negative",
            points=False,
        )
        _add_subject_overlay(fig, participant_columns, participant_id, offsetgroup="Dataset", label_suffix=" (dataset)")
        _add_violin_traces(
            fig,
            reference_plot_data,
            REFERENCE_STYLE,
            name="Reference",
            side="positive",
            points=False,
        )

    fig.update_layout(
        title=metric_group_name,
        height=220,
        showlegend=False,
        xaxis_title=None,
        yaxis_title=None,
        violinmode="overlay",
        margin=dict(l=20, r=20, t=45, b=25),
    )

    if not fig.data:
        st.warning("No plottable numeric data found for the selected group.")
        return None

    return fig


def _render_iqm_legend(show_reference: bool) -> None:
    """Render one legend for the whole tab, above the grid of charts."""
    entries = [(DATASET_STYLE["line"]["color"], "Dataset", "circle")]
    if show_reference:
        entries.append((REFERENCE_STYLE["line"]["color"], "Reference", "circle"))
    entries.append((SUBJECT_MARKER_STYLE["color"], "Current subject", "diamond"))

    def _swatch_style(shape: str) -> str:
        if shape == "diamond":
            return "width:9px;height:9px;transform:rotate(45deg);"
        return "width:11px;height:11px;border-radius:50%;"

    swatches = "".join(
        f'<span style="display:inline-flex;align-items:center;margin-right:18px;">'
        f'<span style="{_swatch_style(shape)}background:{color};'
        f'display:inline-block;margin-right:6px;"></span>{label}</span>'
        for color, label, shape in entries
    )
    st.markdown(f'<div style="margin:0 0 8px 4px;">{swatches}</div>', unsafe_allow_html=True)


def _render_montage_of_iqm_groups(
    valid_groups,
    iqm_data,
    reference_data,
    participant_id,
    session_id,
    modality,
    display_mode,
    run_identifier=None,
):
    """Render compact plots for all available IQM groups."""
    _render_iqm_legend(show_reference=display_mode == DISPLAY_MODE_OPTIONS[1])

    overview_columns = st.columns(NUM_OVERVIEW_COLUMNS)

    for index, (group_name, metric_columns) in enumerate(valid_groups.items()):
        fig = _build_iqm_distribution_figure(
            metric_group_name=group_name,
            modality=modality,
            iqm_data=iqm_data,
            participant_id=participant_id,
            session_id=session_id,
            metric_columns=metric_columns,
            display_mode=display_mode,
            reference_data=reference_data,
            run_identifier=run_identifier,
        )

        if fig is not None:
            column = overview_columns[index % NUM_OVERVIEW_COLUMNS]
            with column:
                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    key=f"iqm_overview_{modality}_{group_name}",
                )


def _render_iqm_distributions(
    iqm_paths, scanner_metadata, participant_id, session_id, qc_config_path: str = None, dataset_dir: str = None, run_identifier: str = None
):

    if not iqm_paths:
        st.warning(ERROR_MESSAGES["iqm_no_sources_configured"])
        return

    st.subheader(MESSAGES["iqm_distribution_header"])

    manufacturer = scanner_metadata.get("Manufacturer", "Unknown") if isinstance(scanner_metadata, dict) else scanner_metadata
    field_strength = scanner_metadata.get("MagneticFieldStrength") if isinstance(scanner_metadata, dict) else None
    protocol = scanner_metadata.get("ProtocolName", "Unknown") if isinstance(scanner_metadata, dict) else "Unknown"
    field_strength_label = f"{field_strength}T" if str(field_strength).replace(".", "", 1).isdigit() else (field_strength or "Unknown")
    scanner_summary = f"Vendor: {manufacturer or 'Unknown'}  ·  Protocol: {protocol or 'Unknown'}  ·  Field strength: {field_strength_label}"

    sources = _load_iqm_sources(iqm_paths, qc_config_path, dataset_dir)
    if not sources:
        return

    tab_options = _disambiguate_tab_labels(sources)

    remembered_tab = SessionManager.get_iqm_view_selection()
    if remembered_tab not in tab_options:
        remembered_tab = tab_options[0]
        SessionManager.set_iqm_view_selection(remembered_tab)

    def _remember_iqm_view_selection():
        SessionManager.set_iqm_view_selection(st.session_state["iqm_view_mode"])

    selected_label = st.segmented_control(
        "IQM source",
        options=tab_options,
        default=remembered_tab,
        key="iqm_view_mode",
        on_change=_remember_iqm_view_selection,
        label_visibility="collapsed",
    )
    if selected_label is None:
        selected_label = remembered_tab

    source = next((s for s, label in zip(sources, tab_options) if label == selected_label), None)

    source_modality = getattr(source, "modality", None)
    caption = f"{scanner_summary}  ·  Modality: {source_modality}" if source_modality else scanner_summary
    if hasattr(st, "caption"):
        st.caption(caption)
    else:
        st.info(caption)

    if isinstance(source, MetricsSource):
        _render_iqm_metrics_table(source.metrics, participant_id)
        return

    if not is_mriqc_pipeline(source.pipeline_name):
        st.caption(MESSAGES["iqm_generic_distribution_experimental"])

    can_compare_reference = REFERENCE_COMPARISON_ENABLED and is_mriqc_pipeline(source.pipeline_name) and source.modality is not None

    mode = DISPLAY_MODE_OPTIONS[0]
    reference_data = None
    if can_compare_reference:

        def _remember_iqm_display_mode():
            SessionManager.set_iqm_display_mode_selection(st.session_state["iqm_display_mode"])

        mode = st.radio(
            "Display mode",
            options=DISPLAY_MODE_OPTIONS,
            index=DISPLAY_MODE_OPTIONS.index(SessionManager.get_iqm_display_mode_selection()),
            key="iqm_display_mode",
            on_change=_remember_iqm_display_mode,
            horizontal=True,
        )
        if mode == DISPLAY_MODE_OPTIONS[1]:
            try:
                reference_data = load_reference_iqm_for_subject(
                    modality=source.modality,
                    manufacturer=manufacturer,
                    field_strength=field_strength,
                    max_rows=MAX_REFERENCE_ROWS,
                )
            except Exception as e:
                st.error(ERROR_MESSAGES["reference_data_load_error"].format(modality=source.modality, error=e))
                reference_data = None
            else:
                if reference_data is None or reference_data.empty:
                    st.warning("No reference data available for this scanner/field strength; showing dataset-only distribution.")
                    reference_data = None

    st.write("Overview of IQM distributions across the dataset, with current subject highlighted.")
    with st.container(height=CONTAINER_HEIGHT, border=False):
        _render_montage_of_iqm_groups(
            valid_groups=source.valid_groups,
            iqm_data=source.iqm_data,
            reference_data=reference_data,
            participant_id=participant_id,
            session_id=session_id,
            modality=source.modality or source.pipeline_name,
            display_mode=mode,
            run_identifier=run_identifier,
        )


def _display_iqm_panel(
    qc_config: dict, qc_config_path: str, participant_id: str, session_id: str, dataset_dir: str = None, qc_task: str = None
) -> None:
    """Display the configured IQM panel for the current participant/session.

    Args:
        qc_config: QC configuration object
        qc_config_path: Path to the QC configuration file
        participant_id: ID of the participant whose data to display
        session_id: ID of the session whose data to display
        dataset_dir: Optional dataset root used to resolve relative paths
        qc_task: The QC task for which to display IQM distributions
    """

    iqm_config = qc_config.get("iqm_path", {})

    scanner_metadata = load_scanner_metadata(
        qc_config.get("base_mri_image_path"),
        participant_id=participant_id,
        session_id=session_id,
        dataset_dir=dataset_dir,
    )

    run_identifier = _extract_run_identifier(
        qc_config.get("base_mri_image_path"),
        participant_id,
        session_id,
    )

    _render_iqm_distributions(
        iqm_config,
        scanner_metadata,
        participant_id,
        session_id,
        qc_config_path=qc_config_path,
        dataset_dir=dataset_dir,
        run_identifier=run_identifier,
    )
